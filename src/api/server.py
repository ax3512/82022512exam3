"""FastAPI 서버 — IA 영향도검토 플랫폼 V4."""
from __future__ import annotations
import os
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
import sys
import io
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
import uuid
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import yaml
import json

# 프로젝트 루트
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.storage.pg_store import PgStore
from src.embedder.embedder import Embedder
from src.engine.summarizer import Summarizer
from src.engine.search import search as do_search
from src.engine.answer import AnswerGenerator
from src.storage.db_client import (
    load_db_config, save_db_config, get_all_db_configs, reset_db,
    get_db, get_all_tables, get_table_schema, execute_select_query,
    extract_table_names_from_text, create_connection,
)
from src.engine.db_agent import get_db_agent
from src.engine.llm_client import LLMClient, CancelledError
from src.engine.context_judge import judge_context
from src.engine.ia_agent import IAAgent
from src.engine.orchestrator import Orchestrator

# ── 세션 캐시 (연계질문용: 첫 질문의 필터링 결과 보관) ──────────
_session_cache: dict[str, dict] = {}
# { session_id: { "filtered_context": str, "dr_numbers": [...], "sources": [...] } }

# ── 요청 취소 관리 ────────────────────────────────────────────
_active_requests: dict[str, threading.Event] = {}

def _register_request(request_id: str) -> threading.Event:
    """요청 등록 — cancel_event 반환 (set되면 취소됨)."""
    cancel_event = threading.Event()
    _active_requests[request_id] = cancel_event
    return cancel_event

def _unregister_request(request_id: str):
    """요청 해제."""
    _active_requests.pop(request_id, None)

def _make_cancel_check(cancel_event: threading.Event):
    """cancel_event를 확인하는 콜백 함수 생성."""
    def check():
        return cancel_event.is_set()
    return check


# ── Config ─────────────────────────────────────────────────────

def load_config() -> dict:
    config_path = PROJECT_ROOT / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _save_config(cfg: dict):
    config_path = PROJECT_ROOT / "config.yaml"
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


config = load_config()

# ── 인프라 초기화 ───────────────────────────────────────────────

pg_cfg = config["storage"]["postgresql"]
dsn = f"host={pg_cfg['host']} port={pg_cfg['port']} dbname={pg_cfg['dbname']} user={pg_cfg['user']} password={pg_cfg['password']}"
store = PgStore(dsn)

# Embedder는 lazy 로딩
_embedder = None
def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        print("🔢 임베딩 모델 로딩 중...")
        _embedder = Embedder(
            model_name=config["embedding"]["model_name"],
            cache_dir=config["embedding"].get("model_path"),
        )
        print("✅ 임베딩 모델 로딩 완료")
    return _embedder

_summarizer = None
def get_summarizer() -> Summarizer:
    global _summarizer
    if _summarizer is None:
        _summarizer = Summarizer(
            api_key=config["llm"]["api_key"],
            base_url=config["llm"].get("base_url") or None,
        )
    return _summarizer

_answer_gen = None
def get_answer_gen() -> AnswerGenerator:
    global _answer_gen
    if _answer_gen is None:
        _answer_gen = AnswerGenerator(
            api_key=config["llm"]["api_key"],
            base_url=config["llm"].get("base_url") or None,
        )
    return _answer_gen


# ── FastAPI App ─────────────────────────────────────────────────

app = FastAPI(title="IA 영향도검토 플랫폼", version="4.0.0")

# ── IA Agent / Orchestrator (lazy) ─────────────────────────────
_ia_agent = None
def get_ia_agent() -> IAAgent:
    global _ia_agent
    if _ia_agent is None:
        llm = LLMClient(api_key=config["llm"]["api_key"], base_url=config["llm"].get("base_url") or "")
        _ia_agent = IAAgent(store=store, embedder=get_embedder(), llm=llm, top_k=config.get("search", {}).get("top_k", 50))
    return _ia_agent

_orchestrator = None
def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator(agents=[get_ia_agent()])
    return _orchestrator

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request/Response Models ─────────────────────────────────────

class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str

class AskRequest(BaseModel):
    question: str
    top_k: int = config.get("search", {}).get("top_k", 50)
    request_id: str = ""
    session_id: str = ""  # 대화 세션 ID
    chat_history: list[ChatMessage] = []  # 대화이력 누적
    prev_question: str = ""  # 하위호환용 (chat_history 없을 때)
    prev_answer: str = ""
    prev_dr_numbers: list[str] = []
    force_type: str = ""  # 사용자가 선택: "followup" | "new" | "" (자동판단)

class AskResponse(BaseModel):
    answer: str
    sources: list[dict[str, Any]]
    context_type: str = ""  # "new", "followup", "unsure"
    session_id: str = ""  # 세션 ID 반환
    question_type: str = ""  # "sr_search", "dr_detail", "business"

class FeedbackRequest(BaseModel):
    question: str
    rating: str
    reason: str = ""
    reason_detail: str = ""
    correct_answer: str = ""
    sources_used: list[dict[str, Any]] = []

class ScanRequest(BaseModel):
    folder_path: str

class LoadRequest(BaseModel):
    folder_path: str
    filter: str = "new_and_modified"
    selected_files: list[str] = []

class SectionUpdateRequest(BaseModel):
    summary: str

class FileLoadRequest(BaseModel):
    file_path: str

class DBConfigRequest(BaseModel):
    active_db_type: str = "postgres"
    db_postgres: dict = {}
    db_oracle: dict = {}

class DBQueryRequest(BaseModel):
    query: str
    limit: int = 100

class DBLookupRequest(BaseModel):
    query: str


# ── Endpoints ───────────────────────────────────────────────────

@app.get("/api/health")
def health():
    stats = store.stats()
    return {"status": "ok", "stats": stats}


# ── 영향도 검토 API ────────────────────────────────────────────

class ReviewRequest(BaseModel):
    requirement: str
    request_id: str = ""

class ReviewResponse(BaseModel):
    findings: list[dict[str, Any]] = []
    similar_drs: list[dict[str, Any]] = []
    warnings: list[str] = []
    review_text: str = ""

@app.post("/api/review", response_model=ReviewResponse)
def review(req: ReviewRequest):
    """영향도 검토 — 요구사항 기반 검토 가이드 + 유사 SR 검색."""
    request_id = req.request_id or uuid.uuid4().hex[:8]
    cancel_event = _register_request(request_id)
    cancel_check = _make_cancel_check(cancel_event)

    try:
        orchestrator = get_orchestrator()
        result = orchestrator.run(req.requirement, cancel_check=cancel_check)

        # review_text는 첫 번째 agent의 raw_data에서 추출
        review_text = ""
        for ar in result.agent_results:
            if ar.raw_data and ar.raw_data.get("review_text"):
                review_text = ar.raw_data["review_text"]
                break

        return ReviewResponse(
            findings=result.findings,
            similar_drs=result.similar_drs,
            warnings=result.warnings,
            review_text=review_text,
        )
    except CancelledError:
        raise HTTPException(499, detail="요청이 취소되었습니다.")
    finally:
        _unregister_request(request_id)


@app.post("/api/ask", response_model=AskResponse)
def ask(req: AskRequest):
    """질문 응답."""
    request_id = req.request_id or uuid.uuid4().hex[:8]
    cancel_event = _register_request(request_id)
    cancel_check = _make_cancel_check(cancel_event)
    session_id = req.session_id or ""

    try:
        answer_gen = get_answer_gen()

        # 대화이력에서 직전 Q&A 추출 (연계질문 판단용)
        prev_question = req.prev_question
        prev_answer = req.prev_answer
        prev_dr_numbers = req.prev_dr_numbers
        if req.chat_history and len(req.chat_history) >= 2:
            # chat_history가 있으면 거기서 직전 Q&A 추출
            for msg in reversed(req.chat_history):
                if msg.role == "assistant" and not prev_answer:
                    prev_answer = msg.content
                elif msg.role == "user" and not prev_question:
                    prev_question = msg.content
                if prev_question and prev_answer:
                    break

        # 세션 캐시에서 이전 DR 번호 복원
        if session_id and session_id in _session_cache and not prev_dr_numbers:
            prev_dr_numbers = _session_cache[session_id].get("dr_numbers", [])

        # force_type이 있으면 LLM 판단 건너뜀
        if req.force_type in ("followup", "new"):
            ctx = {
                "type": req.force_type,
                "reason": "사용자 선택",
                "dr_numbers": prev_dr_numbers if req.force_type == "followup" else None,
            }
        else:
            ctx = judge_context(
                question=req.question,
                prev_question=prev_question,
                prev_answer=prev_answer,
                prev_dr_numbers=prev_dr_numbers or None,
                llm_client=answer_gen.llm,
            )
        print(f"\n📌 질문 유형: {ctx['type']} — {ctx['reason']}")

        # unsure → 사용자에게 선택 요청
        if ctx["type"] == "unsure":
            return AskResponse(
                answer="",
                sources=[],
                context_type="unsure",
                session_id=session_id,
            )

        if ctx["type"] == "followup" and session_id and session_id in _session_cache:
            # ── 연계질문: 이전 DR의 전체 섹션 + 대화이력으로 답변 ──
            cached = _session_cache[session_id]
            print(f"  ⏩ 연계질문 → 이전 DR {cached['dr_numbers']} 전체 섹션 조회")

            results = []
            for dr in cached["dr_numbers"]:
                sections = store.get_sections_by_dr(dr)
                for sec in sections:
                    results.append({"section": sec, "score": 1.0})

            chat_history = [{"role": m.role, "content": m.content} for m in req.chat_history]

            response = answer_gen.generate(
                question=req.question,
                search_results=results,
                cancel_check=cancel_check,
                prev_question=prev_question,
                prev_answer=prev_answer,
            )

            return AskResponse(
                answer=response["answer"],
                sources=response.get("sources", cached["sources"]),
                context_type="followup",
                session_id=session_id,
                question_type=response.get("question_type", ""),
            )

        if ctx["type"] == "followup" and ctx.get("dr_numbers") and not (session_id and session_id in _session_cache):
            # ── 연계질문이지만 세션 캐시 없음 (하위호환): 기존 방식 ──
            print(f"  ⏩ 캐시 없음 → 이전 DR {ctx['dr_numbers']} 섹션 직접 조회")
            results = []
            for dr in ctx["dr_numbers"]:
                sections = store.get_sections_by_dr(dr)
                score = 1.0
                for sec in sections:
                    results.append({"section": sec, "score": score})

            response = answer_gen.generate(
                question=req.question,
                search_results=results,
                cancel_check=cancel_check,
                prev_question=prev_question,
                prev_answer=prev_answer,
            )

            # 세션 캐시에 저장
            if session_id and response.get("filtered_context"):
                _session_cache[session_id] = {
                    "filtered_context": response["filtered_context"],
                    "dr_numbers": ctx["dr_numbers"],
                    "sources": response["sources"],
                }

        else:
            # ── 신규검색: 벡터검색부터 ──
            embedder = get_embedder()
            search_result = do_search(
                question=req.question,
                store=store,
                embedder=embedder,
                top_k=req.top_k,
                cancel_check=cancel_check,
            )

            response = answer_gen.generate(
                question=req.question,
                search_results=search_result["results"],
                cancel_check=cancel_check,
            )

            # 신규검색 → 새 세션 캐시 저장
            if not session_id:
                session_id = uuid.uuid4().hex[:12]
            if response.get("filtered_context"):
                _session_cache[session_id] = {
                    "filtered_context": response["filtered_context"],
                    "dr_numbers": [s["dr_number"] for s in response["sources"]],
                    "sources": response["sources"],
                }
                print(f"  💾 세션 캐시 저장: {session_id} — DR: {_session_cache[session_id]['dr_numbers']}")

        return AskResponse(
            answer=response["answer"],
            sources=response["sources"],
            context_type=ctx["type"],
            session_id=session_id,
            question_type=response.get("question_type", ""),
        )
    except CancelledError:
        print(f"  🛑 요청 취소됨 (request_id={request_id})")
        raise HTTPException(499, detail="요청이 취소되었습니다.")
    finally:
        _unregister_request(request_id)


class CancelRequest(BaseModel):
    request_id: str

@app.post("/api/ask/cancel")
def cancel_ask(req: CancelRequest):
    """진행 중인 질문 요청을 취소한다."""
    event = _active_requests.get(req.request_id)
    if event:
        event.set()
        print(f"  🛑 취소 신호 전송 (request_id={req.request_id})")
        return {"status": "cancelled", "request_id": req.request_id}
    print(f"  ⚠️ 취소 대상 없음 (request_id={req.request_id})")
    return {"status": "not_found", "request_id": req.request_id}


@app.get("/api/documents")
def list_documents():
    """적재된 문서 목록."""
    docs = store.get_all_documents()
    return {"documents": docs, "total": len(docs)}


@app.get("/api/documents/{dr_number}")
def get_document(dr_number: str, ym: str = ""):
    """문서 상세 (섹션 포함). ym 파라미터로 특정 버전 조회 가능."""
    doc = store.get_document(dr_number, ym if ym else None)
    if not doc:
        raise HTTPException(404, f"문서를 찾을 수 없습니다: {dr_number}")
    target_ym = doc.get("target_year_month", "")
    sections = store.get_sections_by_dr(dr_number)
    # 해당 버전 섹션만 필터링 (target_year_month가 일치하는 것)
    if target_ym:
        filtered = [s for s in sections if s.get("target_year_month", "") == target_ym]
        # 마이그레이션 전 데이터는 target_year_month가 비어있을 수 있으므로 빈 것도 포함
        if not filtered:
            filtered = sections
        sections = filtered
    return {"document": doc, "sections": sections}


@app.get("/api/documents/{dr_number}/versions")
def get_document_versions(dr_number: str):
    """특정 DR의 모든 버전 목록 (년월 기준 내림차순)."""
    versions = store.get_document_versions(dr_number)
    return {"dr_number": dr_number, "versions": versions, "total": len(versions)}


@app.delete("/api/documents/{dr_number}")
def delete_document(dr_number: str, ym: str = ""):
    """문서 삭제. ym 지정 시 해당 버전만, 없으면 전체 삭제."""
    doc = store.get_document(dr_number, ym if ym else None)
    if not doc:
        raise HTTPException(404, f"문서를 찾을 수 없습니다: {dr_number}")
    deleted = store.delete_document(dr_number, ym if ym else None)
    return {"status": "deleted", "dr_number": dr_number, "deleted_documents": deleted}


@app.post("/api/documents/cleanup")
def cleanup_invalid_documents():
    """DR번호가 없거나 비정상적인 문서를 정리(삭제)."""
    all_docs = store.get_all_documents()
    removed = []
    for doc in all_docs:
        dr = doc.get("dr_number", "")
        title = doc.get("title", "")
        sections = store.get_sections_by_dr(dr)
        has_summary = any(s.get("summary") for s in sections) if sections else False

        # DR번호 없거나, 섹션 0개이거나, 요약이 하나도 없는 문서
        if not dr or not sections or not has_summary:
            store.delete_document(dr)
            removed.append({"dr_number": dr, "title": title, "reason": "DR번호 없음" if not dr else "섹션/요약 없음"})

    return {"status": "cleaned", "removed": removed, "removed_count": len(removed)}


@app.put("/api/sections/{section_id}")
def update_section(section_id: str, req: SectionUpdateRequest):
    """섹션 요약 수정 → DB 업데이트 + 벡터 재임베딩."""
    sec = store.get_section(section_id)
    if not sec:
        raise HTTPException(404, f"섹션을 찾을 수 없습니다: {section_id}")

    sec["summary"] = req.summary

    # 벡터 재임베딩
    if req.summary.strip():
        embedder = get_embedder()
        new_embedding = embedder.embed_query(req.summary)
        store.upsert_section(sec, embedding=new_embedding)
    else:
        store.upsert_section(sec)
        store.delete_vector_by_id(section_id)

    return {"status": "updated", "section_id": section_id, "summary_length": len(req.summary)}


@app.post("/api/load-folder/scan")
def scan_folder(req: ScanRequest):
    """폴더 스캔 — 적재 가능한 문서 목록 반환."""
    folder = Path(req.folder_path)
    if not folder.exists():
        raise HTTPException(400, f"폴더가 존재하지 않습니다: {req.folder_path}")

    files = sorted([f for f in folder.iterdir() if f.suffix.lower() in ('.docx', '.pdf')])
    existing_docs = {d["dr_number"]: d for d in store.get_all_documents()}

    import re
    result_files = []
    for f in files:
        dr_match = re.search(r"DR-\d{4}-\d{4,6}", f.name)
        dr_number = dr_match.group() if dr_match else ""
        status = "new"
        if dr_number and dr_number in existing_docs:
            status = "loaded"
        result_files.append({"filename": f.name, "status": status, "dr_number": dr_number})

    return {
        "folder_path": str(folder),
        "total_docx": len(files),
        "already_loaded": sum(1 for f in result_files if f["status"] == "loaded"),
        "new": sum(1 for f in result_files if f["status"] == "new"),
        "files": result_files,
    }


@app.post("/api/load-folder/start")
def start_load(req: LoadRequest):
    """폴더 적재 시작 (스트리밍)."""
    import json as _json
    from scripts.load_documents import load_single_document

    folder = Path(req.folder_path)
    if not folder.exists():
        raise HTTPException(400, f"폴더가 존재하지 않습니다: {req.folder_path}")

    files = sorted([f for f in folder.iterdir() if f.suffix.lower() in ('.docx', '.pdf')])

    if req.selected_files:
        files = [f for f in files if f.name in req.selected_files]
    elif req.filter == "new_only":
        import re
        existing = {d["dr_number"] for d in store.get_all_documents()}
        files = [f for f in files if not any(
            dr in existing for dr in re.findall(r"DR-\d{4}-\d{4,6}", f.name)
        )]

    def generate():
        import queue, threading
        q = queue.Queue()

        def on_progress(data):
            data["type"] = "detail"
            q.put(data)

        def _line(obj):
            return _json.dumps(obj, ensure_ascii=False) + "\n"

        yield _line({"type": "start", "total": len(files)})
        yield _line({"type": "status", "message": "임베딩 모델 로딩 중..."})
        embedder = get_embedder()
        summarizer = get_summarizer()

        for i, fpath in enumerate(files):
            yield _line({"type": "file_start", "current": i + 1, "total": len(files), "file": fpath.name})

            result_holder = [None]
            error_holder = [None]
            _fpath = fpath

            def do_load(_fp=_fpath):
                try:
                    result_holder[0] = load_single_document(
                        str(_fp), store, embedder, summarizer,
                        force=(req.filter == "all"),
                        on_progress=on_progress,
                    )
                except Exception as e:
                    error_holder[0] = e
                finally:
                    q.put(None)

            t = threading.Thread(target=do_load)
            t.start()

            while True:
                msg = q.get()
                if msg is None:
                    break
                yield _line(msg)

            t.join()

            if error_holder[0]:
                from scripts.load_documents import _classify_parse_error
                err_msg = _classify_parse_error(error_holder[0], str(fpath))
                yield _line({"type": "error", "file": fpath.name, "error": err_msg})
            elif result_holder[0]:
                r = result_holder[0]
                # error 필드가 있으면 에러로 표시 (DR번호 없음 등)
                if r.get("error"):
                    yield _line({"type": "error", "file": fpath.name, "error": r["error"],
                                 "error_type": r.get("error_type", "")})
                else:
                    r["type"] = "result"
                    yield _line(r)

        s = store.stats()
        yield _line({"type": "done", "stats": s})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@app.post("/api/load-file")
def load_file(req: FileLoadRequest):
    """개별 파일 적재 (스트리밍)."""
    import json as _json
    from scripts.load_documents import load_single_document

    fpath = Path(req.file_path)
    if not fpath.exists():
        raise HTTPException(400, f"파일이 존재하지 않습니다: {req.file_path}")
    if fpath.suffix.lower() not in ('.docx', '.pdf'):
        raise HTTPException(400, "docx 또는 pdf 파일만 지원합니다.")

    def generate():
        import queue, threading
        q = queue.Queue()

        def on_progress(data):
            data["type"] = "detail"
            q.put(data)

        def _line(obj):
            return _json.dumps(obj, ensure_ascii=False) + "\n"

        yield _line({"type": "status", "message": "임베딩 모델 로딩 중..."})
        embedder = get_embedder()
        summarizer = get_summarizer()
        yield _line({"type": "file_start", "current": 1, "total": 1, "file": fpath.name})

        result_holder = [None]
        error_holder = [None]

        def do_load():
            try:
                result_holder[0] = load_single_document(
                    str(fpath), store, embedder, summarizer, force=True,
                    on_progress=on_progress,
                )
            except Exception as e:
                error_holder[0] = e
            finally:
                q.put(None)

        t = threading.Thread(target=do_load)
        t.start()

        while True:
            msg = q.get()
            if msg is None:
                break
            yield _line(msg)

        t.join()

        if error_holder[0]:
            from scripts.load_documents import _classify_parse_error
            err_msg = _classify_parse_error(error_holder[0], str(fpath))
            yield _line({"type": "error", "file": fpath.name, "error": err_msg})
        elif result_holder[0]:
            r = result_holder[0]
            if r.get("error"):
                yield _line({"type": "error", "file": fpath.name, "error": r["error"],
                             "error_type": r.get("error_type", "")})
            else:
                r["type"] = "result"
                yield _line(r)

        s = store.stats()
        yield _line({"type": "done", "stats": s})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@app.post("/api/feedback")
def submit_feedback(req: FeedbackRequest):
    """피드백 저장."""
    feedback = {
        "feedback_id": f"fb_{uuid.uuid4().hex[:8]}",
        "timestamp": datetime.now().isoformat(),
        "question": req.question,
        "rating": req.rating,
        "reason": req.reason,
        "reason_detail": req.reason_detail,
        "correct_answer": req.correct_answer,
        "sources_used": req.sources_used,
    }
    store.save_feedback(feedback)
    return {"status": "saved", "feedback_id": feedback["feedback_id"]}


# ── DB 연결 관련 Endpoints ─────────────────────────────────────

@app.get("/api/db/config")
def get_db_config():
    return get_all_db_configs()

@app.post("/api/db/config")
def update_db_config(req: DBConfigRequest):
    cfg = {
        "active_db_type": req.active_db_type,
        "db_postgres": req.db_postgres,
        "db_oracle": req.db_oracle,
    }
    save_db_config(cfg)
    reset_db()
    return {"status": "saved"}

@app.post("/api/db/test")
def test_db_connection():
    try:
        reset_db()
        db = get_db()
        success, err = db.test_connection()
        db_type = db.get_db_type()
        if success:
            return {"success": True, "message": f"{db_type} 연결 성공", "db_type": db_type}
        else:
            return {"success": False, "error": err, "db_type": db_type}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/db/tables")
def list_db_tables():
    try:
        tables = get_all_tables()
        return {"success": True, "tables": tables}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/db/tables/{table_name}/schema")
def get_db_table_schema(table_name: str):
    try:
        schema = get_table_schema(table_name)
        return {"success": True, "schema": schema}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/db/query")
def run_db_query(req: DBQueryRequest):
    result = execute_select_query(req.query, req.limit)
    return result

@app.post("/api/db/lookup")
def db_lookup(req: DBLookupRequest):
    llm_cfg = config.get("llm", {})
    agent = get_db_agent(
        api_key=llm_cfg.get("api_key", ""),
        base_url=llm_cfg.get("base_url", ""),
    )
    result = agent.query(req.query)
    return result



# ── 적재 폴더 경로 설정 ───────────────────────────────────────

@app.get("/api/loader/folder-path")
def get_loader_folder_path():
    return {"folder_path": config.get("loader", {}).get("folder_path", "")}


class FolderPathRequest(BaseModel):
    folder_path: str


@app.post("/api/loader/folder-path")
def save_loader_folder_path(req: FolderPathRequest):
    config.setdefault("loader", {})["folder_path"] = req.folder_path
    _save_config(config)
    return {"status": "saved", "folder_path": req.folder_path}


# ── LLM 설정 ────────────────────────────────────────────────────


class LLMConfigRequest(BaseModel):
    api_key: str = ""
    base_url: str = ""


@app.get("/api/llm/config")
def get_llm_config():
    llm = config.get("llm", {})
    return {
        "api_key": llm.get("api_key", ""),
        "base_url": llm.get("base_url", ""),
    }


@app.post("/api/llm/config")
def save_llm_config(req: LLMConfigRequest):
    config.setdefault("llm", {})["api_key"] = req.api_key
    config.setdefault("llm", {})["base_url"] = req.base_url
    _save_config(config)
    # LLM 클라이언트 재초기화 (다음 호출 시 새 설정 적용)
    global _summarizer, _answer_gen
    _summarizer = None
    _answer_gen = None
    return {"status": "saved"}


# ── 문서-카테고리 태깅 API ───────────────────────────────────


@app.get("/api/documents/{dr_number}/categories")
def get_document_categories(dr_number: str):
    """문서에 태깅된 카테고리 목록."""
    cats = store.get_categories_by_dr(dr_number)
    return {"dr_number": dr_number, "categories": cats}


@app.get("/api/categories/{cat_id:path}/documents")
def get_category_documents(cat_id: str):
    """카테고리에 태깅된 문서 목록 (하위 카테고리 포함)."""
    docs = store.get_documents_by_category(cat_id)
    return {"category_id": cat_id, "documents": docs, "total": len(docs)}


@app.post("/api/categories/retag-all")
def retag_all_documents():
    """적재된 모든 문서에 대해 카테고리를 일괄 재태깅 (스트리밍)."""
    import json as _json
    from scripts.load_documents import tag_document_categories

    cat_data = _load_categories()
    categories_tree = cat_data.get("categories", [])
    if not categories_tree:
        raise HTTPException(400, "카테고리 분류체계가 없습니다. 먼저 카테고리를 등록해주세요.")

    all_docs = store.get_all_documents()
    if not all_docs:
        raise HTTPException(400, "적재된 문서가 없습니다.")

    summarizer = get_summarizer()

    def generate():
        def _line(obj):
            return _json.dumps(obj, ensure_ascii=False) + "\n"

        yield _line({"type": "start", "total": len(all_docs), "message": f"총 {len(all_docs)}건 문서 카테고리 태깅 시작"})

        success_count = 0
        fail_count = 0

        for i, doc in enumerate(all_docs):
            dr = doc.get("dr_number", "")
            title = doc.get("title", "")
            system = doc.get("system", "")

            yield _line({"type": "progress", "current": i + 1, "total": len(all_docs),
                         "dr_number": dr, "title": title, "message": f"[{i+1}/{len(all_docs)}] {dr} 태깅 중..."})

            try:
                sections = store.get_sections_by_dr(dr)
                summaries = [s.get("summary", "") for s in sections if s.get("summary")]

                if not summaries:
                    yield _line({"type": "skip", "dr_number": dr, "message": f"{dr}: 요약 데이터 없음 — 스킵"})
                    continue

                tagged_ids = tag_document_categories(
                    dr_number=dr,
                    title=title,
                    system=system,
                    section_summaries=summaries,
                    categories_tree=categories_tree,
                    llm_client=summarizer.llm,
                )

                if tagged_ids:
                    ym = doc.get("target_year_month", "")
                    store.upsert_document_categories(dr, tagged_ids, tagged_by='llm', target_year_month=ym)
                    success_count += 1
                    yield _line({"type": "tagged", "dr_number": dr, "categories": tagged_ids,
                                 "message": f"{dr}: {', '.join(tagged_ids)}"})
                else:
                    yield _line({"type": "skip", "dr_number": dr, "message": f"{dr}: 매칭되는 카테고리 없음"})

            except Exception as e:
                fail_count += 1
                yield _line({"type": "error", "dr_number": dr, "message": f"{dr}: 태깅 실패 — {e}"})

        yield _line({"type": "done", "success": success_count, "fail": fail_count,
                     "message": f"완료! 태깅 {success_count}건, 실패 {fail_count}건"})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@app.get("/api/graph/category-documents")
def get_category_document_graph():
    """Force-directed graph 시각화용 데이터 (계층형: 대분류→중분류→소분류→DR)."""
    try:
        relations = store.get_all_document_categories()
    except Exception:
        return {"nodes": [], "links": []}
    cat_data = _load_categories()
    categories = cat_data.get("categories", [])

    nodes = []
    links = []
    seen: set[str] = set()

    def _get_ancestors(cat_id: str) -> list[str]:
        """'2.3.1' -> ['2', '2.3', '2.3.1']"""
        parts = cat_id.split('.')
        ancestors = []
        for i in range(1, len(parts) + 1):
            ancestors.append('.'.join(parts[:i]))
        return ancestors

    def _add_cat_node(cid: str):
        if cid in seen:
            return
        seen.add(cid)
        name = _find_category_name(categories, cid) or cid
        level = len(cid.split('.')) - 1  # 0=대분류, 1=중, 2=소, 3=상세
        nodes.append({
            "id": "cat_" + cid,
            "name": name,
            "type": "category",
            "category_id": cid,
            "level": level,
        })

    # 각 태깅된 관계에 대해 계층 체인 구성
    for rel in relations:
        cat_id = rel["category_id"]
        dr = rel["dr_number"]

        # 문서 노드
        doc_key = "doc_" + dr
        if doc_key not in seen:
            seen.add(doc_key)
            nodes.append({
                "id": doc_key,
                "name": rel["title"] or dr,
                "type": "document",
                "system": rel.get("system", ""),
                "dr_number": dr,
            })

        # 카테고리 계층 체인: 대분류 → 중분류 → 소분류
        ancestors = _get_ancestors(cat_id)
        for anc in ancestors:
            _add_cat_node(anc)

        # 카테고리 간 링크: 2 → 2.3 → 2.3.1
        for i in range(len(ancestors) - 1):
            link_key = f"cat_{ancestors[i]}->cat_{ancestors[i+1]}"
            if link_key not in seen:
                seen.add(link_key)
                links.append({"source": "cat_" + ancestors[i], "target": "cat_" + ancestors[i+1]})

        # 말단 카테고리 → 문서 링크
        link_key = f"cat_{cat_id}->{doc_key}"
        if link_key not in seen:
            seen.add(link_key)
            links.append({"source": "cat_" + cat_id, "target": doc_key})

    return {"nodes": nodes, "links": links}


def _find_category_name(nodes: list, cat_id: str) -> str | None:
    for node in nodes:
        if node["id"] == cat_id:
            return node["name"]
        if "children" in node:
            result = _find_category_name(node["children"], cat_id)
            if result:
                return result
    return None

# ── KOS 카테고리 관리 ─────────────────────────────────────────

CATEGORIES_FILE = PROJECT_ROOT / "categories.json"


def _load_categories() -> dict:
    if CATEGORIES_FILE.exists():
        with open(CATEGORIES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"categories": []}


def _save_categories(data: dict):
    with open(CATEGORIES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _find_node(nodes: list, node_id: str):
    """트리에서 id로 노드를 찾아 (parent_list, index) 반환."""
    for i, node in enumerate(nodes):
        if node["id"] == node_id:
            return nodes, i
        children = node.get("children", [])
        result = _find_node(children, node_id)
        if result:
            return result
    return None


def _next_id(parent_id: str | None, siblings: list) -> str:
    """다음 id 생성. 예: parent='1.1' + siblings 3개 → '1.1.4'"""
    if not siblings:
        return f"{parent_id}.1" if parent_id else "1"
    last = siblings[-1]["id"]
    parts = last.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)


@app.get("/api/categories")
def get_categories():
    data = _load_categories()
    try:
        data["doc_counts"] = store.get_category_doc_counts()
    except Exception:
        data["doc_counts"] = {}
    return data


class CategoryRequest(BaseModel):
    parent_id: str | None = None
    name: str


@app.post("/api/categories")
def add_category(req: CategoryRequest):
    data = _load_categories()
    cats = data["categories"]
    if req.parent_id:
        result = _find_node(cats, req.parent_id)
        if not result:
            raise HTTPException(404, f"부모 노드를 찾을 수 없습니다: {req.parent_id}")
        parent_list, idx = result
        parent = parent_list[idx]
        if "children" not in parent:
            parent["children"] = []
        new_id = _next_id(req.parent_id, parent["children"])
        node = {"id": new_id, "name": req.name}
        parent["children"].append(node)
    else:
        new_id = _next_id(None, cats)
        node = {"id": new_id, "name": req.name}
        cats.append(node)
    _save_categories(data)
    return {"status": "added", "node": node}


class CategoryUpdateRequest(BaseModel):
    name: str


@app.put("/api/categories/{cat_id:path}")
def update_category(cat_id: str, req: CategoryUpdateRequest):
    data = _load_categories()
    result = _find_node(data["categories"], cat_id)
    if not result:
        raise HTTPException(404, f"노드를 찾을 수 없습니다: {cat_id}")
    parent_list, idx = result
    parent_list[idx]["name"] = req.name
    _save_categories(data)
    return {"status": "updated", "id": cat_id, "name": req.name}


@app.delete("/api/categories/{cat_id:path}")
def delete_category(cat_id: str):
    data = _load_categories()
    result = _find_node(data["categories"], cat_id)
    if not result:
        raise HTTPException(404, f"노드를 찾을 수 없습니다: {cat_id}")
    parent_list, idx = result
    removed = parent_list.pop(idx)
    _save_categories(data)
    return {"status": "deleted", "id": cat_id, "name": removed["name"]}


# ── Static Files ──────────────────────────────────────────────

client_dir = PROJECT_ROOT / "client"
if client_dir.exists():
    @app.get("/")
    def serve_index():
        return FileResponse(client_dir / "index.html")

    app.mount("/", StaticFiles(directory=str(client_dir)), name="static")

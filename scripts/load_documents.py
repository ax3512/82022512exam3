"""문서 적재 파이프라인 — V3: PostgreSQL + pgvector 통합.

폴더 내 .docx 파일을 파싱→요약→임베딩→PostgreSQL 저장.
"""
from __future__ import annotations
import os
import sys
import io
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
import time
import json
import re
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import yaml

from src.parser.docx_parser import parse_docx, Section
from src.parser.pdf_parser import parse_pdf
from src.storage.pg_store import PgStore
from src.engine.summarizer import Summarizer
from src.embedder.embedder import Embedder


# ── 문서 검증 / 에러 분류 ─────────────────────────────────────────

class _DocLoadError(Exception):
    """적재 실패 — 사용자에게 안내할 사유 포함."""
    def __init__(self, reason: str, error_type: str):
        self.reason = reason
        self.error_type = error_type
        super().__init__(reason)


# OLE Compound 파일(암호화 docx)의 매직 바이트
_OLE_MAGIC = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
# 정상 ZIP(docx)의 매직 바이트
_ZIP_MAGIC = b'PK\x03\x04'


def _check_encrypted(file_path: str):
    """파일이 암호화되었는지 사전 검사.

    암호화된 docx는 ZIP이 아닌 OLE Compound 포맷으로 저장된다.
    """
    try:
        with open(file_path, 'rb') as f:
            header = f.read(8)
    except PermissionError:
        raise _DocLoadError(
            "파일에 접근할 수 없습니다 (다른 프로그램에서 사용 중이거나 권한 부족)",
            "permission_error",
        )
    except FileNotFoundError:
        raise _DocLoadError("파일을 찾을 수 없습니다", "file_not_found")

    if header[:8] == _OLE_MAGIC:
        raise _DocLoadError(
            "암호화된 문서입니다 — 복호화 후 다시 시도해주세요",
            "encrypted",
        )

    if header[:4] != _ZIP_MAGIC:
        raise _DocLoadError(
            "유효한 docx 파일이 아닙니다 (손상되었거나 다른 형식)",
            "invalid_format",
        )


def _classify_parse_error(error: Exception, file_path: str) -> str:
    """파싱 예외를 사용자 친화적 메시지로 분류."""
    msg = str(error).lower()

    if "encrypted" in msg or "password" in msg:
        return "암호화된 문서입니다 — 복호화 후 다시 시도해주세요"
    if "not a valid zip" in msg or "badzip" in msg or "bad magic" in msg:
        return "유효한 docx 파일이 아닙니다 (손상되었거나 다른 형식)"
    if "permission" in msg:
        return "파일에 접근할 수 없습니다 (권한 부족)"
    if "no such file" in msg or "filenotfound" in msg:
        return "파일을 찾을 수 없습니다"
    if "memory" in msg:
        return "파일이 너무 크거나 메모리가 부족합니다"
    if "xml" in msg or "parse" in msg:
        return "문서 내부 구조가 손상되었습니다 (XML 파싱 오류)"

    return f"문서 파싱 실패: {error}"


# ── 카테고리 태깅 ─────────────────────────────────────────────────

def _flatten_categories(nodes: list[dict], lines: list[str] | None = None) -> list[str]:
    """카테고리 트리를 들여쓰기 텍스트로 변환."""
    if lines is None:
        lines = []
    for node in nodes:
        depth = node["id"].count(".")
        indent = "  " * depth
        lines.append(f"{indent}{node['id']}. {node['name']}")
        if "children" in node:
            _flatten_categories(node["children"], lines)
    return lines


def _get_all_category_ids(nodes: list[dict]) -> set[str]:
    """트리에서 모든 카테고리 ID를 set으로 수집."""
    ids: set[str] = set()
    for node in nodes:
        ids.add(node["id"])
        if "children" in node:
            ids.update(_get_all_category_ids(node["children"]))
    return ids


def tag_document_categories(
    dr_number: str,
    title: str,
    system: str,
    section_summaries: list[str],
    categories_tree: list[dict],
    llm_client,
) -> list[str]:
    """LLM으로 문서를 카테고리에 분류하고 category_id 목록을 반환."""
    def _clean(txt):
        if not txt:
            return ''
        try:
            if isinstance(txt, bytes):
                return txt.decode('utf-8', errors='replace')
            return txt.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
        except Exception:
            return str(txt).encode('ascii', errors='replace').decode('ascii')

    cat_lines = _flatten_categories(categories_tree)
    cat_text = _clean("\n".join(cat_lines))

    clean_summaries = []
    for s in section_summaries:
        if s:
            clean_summaries.append("- " + _clean(s))
    combined = "\n".join(clean_summaries)
    title = _clean(title)
    system = _clean(system)
    dr_number = _clean(dr_number)

    parts = []
    parts.append("다음 IA 설계문서를 아래 카테고리 분류체계에서 가장 적합한 카테고리로 분류해주세요.")
    parts.append("")
    parts.append("## 문서 정보")
    parts.append("- DR번호: " + dr_number)
    parts.append("- 제목: " + title)
    parts.append("- 시스템: " + system)
    parts.append("")
    parts.append("## 섹션 요약")
    parts.append(combined)
    parts.append("")
    parts.append("## 카테고리 분류체계")
    parts.append(cat_text)
    parts.append("")
    parts.append("## 지시사항")
    parts.append("1. 이 문서가 해당하는 카테고리의 ID를 모두 선택하세요.")
    parts.append('2. 가장 구체적인(하위) 카테고리를 선택하세요. (예: "1.1.1.1"이 맞으면 상위 "1.1.1"은 제외)')
    parts.append("3. 복수 카테고리에 해당하면 모두 포함하세요.")
    parts.append("4. 반드시 아래 JSON 배열 형식으로만 응답하세요. 다른 텍스트는 출력하지 마세요.")
    parts.append("")
    parts.append('["카테고리ID1", "카테고리ID2"]')

    prompt = "\n".join(parts)
    prompt = prompt.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
    raw = llm_client.chat(prompt)

    try:
        match = re.search(r'\[.*?\]', raw, re.DOTALL)
        if match:
            ids = json.loads(match.group())
            valid_ids = _get_all_category_ids(categories_tree)
            return [cid for cid in ids if cid in valid_ids]
    except (json.JSONDecodeError, Exception):
        pass

    return []

def load_config() -> dict:
    config_path = PROJECT_ROOT / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_single_document(
    file_path: str,
    store: PgStore,
    embedder: Embedder,
    summarizer: Summarizer,
    *,
    force: bool = False,
    on_progress=None,
) -> dict:
    """단일 문서를 적재한다.

    V3: nosql+vector 대신 store(PgStore) 하나만 사용.
    """
    def emit(data):
        if on_progress:
            on_progress(data)

    start = time.time()
    fname = Path(file_path).name
    print(f"\n{'='*60}")
    print(f"📄 파싱 중: {fname}")
    emit({"step": "parse", "message": f"파싱 중: {fname}"})

    # 0) 암호화 여부 사전 검사 (docx만, PDF는 건너뜀)
    if Path(file_path).suffix.lower() != '.pdf':
        try:
            _check_encrypted(file_path)
        except _DocLoadError as e:
            print(f"   ❌ {e.reason}: {fname}")
            emit({"step": "error", "message": f"{e.reason}: {fname}"})
            return {"dr_number": "", "title": fname, "sections": 0, "chunks": 0, "elapsed": 0,
                    "skipped": False, "error": e.reason, "error_type": e.error_type}

    # 1) 파싱 (DOCX / PDF 자동 분기)
    try:
        if Path(file_path).suffix.lower() == '.pdf':
            result = parse_pdf(file_path)
        else:
            result = parse_docx(file_path)
    except Exception as e:
        reason = _classify_parse_error(e, file_path)
        print(f"   ❌ {reason}: {fname}")
        emit({"step": "error", "message": f"{reason}: {fname}"})
        return {"dr_number": "", "title": fname, "sections": 0, "chunks": 0, "elapsed": 0,
                "skipped": False, "error": reason, "error_type": "parse_error"}

    meta = result.meta
    sections = result.sections
    dr = meta.get("dr_number", "") or ""
    title = meta.get("title", "") or ""

    # DR번호 추출 실패 시 적재 거부
    if not dr or dr == "UNKNOWN":
        msg = f"DR번호를 추출할 수 없습니다: {fname}"
        print(f"   ❌ {msg}")
        emit({"step": "error", "message": msg})
        return {"dr_number": "", "title": title, "sections": 0, "chunks": 0, "elapsed": 0,
                "skipped": False, "error": msg, "error_type": "no_dr_number"}

    ym = meta.get("target_year_month", "") or ""
    print(f"   DR: {dr} | 대상년월: {ym} | 제목: {title} | 섹션: {len(sections)}개")
    emit({"step": "parsed", "dr_number": dr, "title": title, "target_year_month": ym, "total_sections": len(sections)})

    # 이미 적재된 문서인지 확인 (DR+년월 복합키 기준)
    if not force:
        existing = store.get_document(dr, ym)
        if existing:
            print(f"   ⏭️  이미 적재됨 (스킵): {dr}/{ym}. --force로 재적재 가능")
            return {"dr_number": dr, "title": title, "sections": 0, "chunks": 0, "elapsed": 0, "skipped": True}

    # 동일 DR+년월 기존 데이터만 삭제 (다른 년월 버전은 유지)
    store.delete_document(dr, ym)

    # 2) LLM 요약
    print(f"   🤖 LLM 요약 생성 중...")
    emit({"step": "summarize_start", "message": "LLM 요약 생성 시작"})
    section_dicts = []
    summary_errors = 0

    for i, sec in enumerate(sections):
        print(f"      [{i+1}/{len(sections)}] {sec.heading_path}")
        emit({"step": "summarize", "current": i + 1, "total": len(sections), "heading": sec.heading_path})
        sys.stdout.flush()

        try:
            summary_result = summarizer.summarize_section(sec.content, sec.section_type)
            summary = summary_result["summary"]
        except Exception as e:
            print(f"      ❌ 요약 실패: {e}")
            emit({"step": "summarized", "current": i + 1, "total": len(sections), "heading": sec.heading_path, "summary_length": 0, "summary_preview": f"요약 실패: {e}"})
            summary_result = {"summary": "", "mentioned_tables": [], "mentioned_sources": []}
            summary = ""
            summary_errors += 1

        sec_dict = asdict(sec)
        sec_dict["target_year_month"] = ym
        sec_dict["part"] = meta.get("part", "")
        sec_dict["summary"] = summary
        sec_dict["detail"] = sec.content
        sec_dict["mentioned_tables"] = summary_result["mentioned_tables"]
        sec_dict["mentioned_sources"] = summary_result["mentioned_sources"]
        section_dicts.append(sec_dict)

        if summary:
            print(f"      ─── 요약 ({len(summary)}자) ───")
            for line in summary.split('\n'):
                print(f"      {line}")
            print()
        emit({"step": "summarized", "current": i + 1, "total": len(sections), "heading": sec.heading_path, "summary_length": len(summary), "summary_preview": summary[:200] if summary else ""})

    # ★ 카테고리 태깅 (LLM 요약 기반)
    tagged_ids = []
    try:
        categories_file = PROJECT_ROOT / "categories.json"
        if categories_file.exists():
            print("   카테고리 태깅 중...")
            emit({"step": "tagging", "message": "카테고리 태깅 중..."})

            with open(categories_file, "r", encoding="utf-8") as f:
                cat_data = json.load(f)

            all_summaries = [sd["summary"] for sd in section_dicts if sd["summary"]]
            tagged_ids = tag_document_categories(
                dr_number=dr,
                title=title,
                system=meta.get("system", ""),
                section_summaries=all_summaries,
                categories_tree=cat_data.get("categories", []),
                llm_client=summarizer.llm,
            )

            if tagged_ids:
                print(f'   태깅 결과: {tagged_ids}')
                emit({'step': 'tagged', 'message': '태깅 완료: ' + ','.join(tagged_ids), 'category_ids': tagged_ids})
            else:
                print("   매칭되는 카테고리 없음")
                emit({"step": "tagged", "message": "매칭되는 카테고리 없음", "category_ids": []})
        else:
            print("   categories.json 없음 - 태깅 스킵")
            emit({"step": "tagged", "message": "categories.json 없음", "category_ids": []})
    except Exception as e:
        print(f"   카테고리 태깅 실패: {e}")
        emit({"step": "tagged", "message": f"태깅 실패: {e}", "category_ids": []})

    # 문서 통합 요약 생성 (꼭지별 정리, LLM 1번 호출)
    all_summaries = [sd["summary"] for sd in section_dicts if sd["summary"]]
    if all_summaries:
        try:
            print("   문서 통합 요약 생성 중...")
            emit({"step": "doc_summary", "message": "문서 통합 요약 생성 중..."})
            doc_summary = summarizer.summarize_document(dr, title, all_summaries)
            meta["document_summary"] = doc_summary
            print(f"   문서 통합 요약 완료 ({len(doc_summary)}자)")
        except Exception as e:
            print(f"   문서 통합 요약 실패: {e}")
            meta["document_summary"] = ""
    else:
        meta["document_summary"] = ""

    # 3) 임베딩 생성
    print(f"   🔢 임베딩 생성 중...")
    emit({"step": "embedding", "message": f"임베딩 생성 중 ({len(section_dicts)}개 섹션)"})
    summary_texts = [sd["summary"] for sd in section_dicts if sd["summary"]]
    valid_sections = [sd for sd in section_dicts if sd["summary"]]

    embedding_failed = False
    embedding_error = ""
    if summary_texts:
        try:
            embeddings = embedder.embed_documents(summary_texts)
            if not embeddings or len(embeddings) != len(summary_texts):
                embedding_failed = True
                embedding_error = f"임베딩 결과 불일치: 요청 {len(summary_texts)}개, 결과 {len(embeddings) if embeddings else 0}개"
                embeddings = []
        except Exception as e:
            embedding_failed = True
            embedding_error = str(e)
            embeddings = []
    else:
        embeddings = []

    if embedding_failed:
        print(f"   ❌ 임베딩 실패: {embedding_error}")
        emit({"step": "embedded", "status": "error", "message": f"❌ 임베딩 실패: {embedding_error}"})
    else:
        emit({"step": "embedded", "status": "ok", "message": f"임베딩 완료 ({len(embeddings)}개)"})

    # 4) PostgreSQL 저장 (문서 메타 + 섹션 + 벡터 한번에)
    print(f"   💾 PostgreSQL 저장 중...")
    emit({"step": "saving", "message": "PostgreSQL 저장 중"})

    try:
        store.upsert_document(meta)

        # 임베딩이 있는 섹션은 embedding과 함께, 없는 섹션은 embedding 없이
        emb_idx = 0
        for sd in section_dicts:
            emb = None
            if sd["summary"] and emb_idx < len(embeddings):
                emb = embeddings[emb_idx]
                emb_idx += 1
            store.upsert_section(sd, embedding=emb)

        # ★ 카테고리 태깅 DB 저장 (문서 저장 후 FK 충족)
        if tagged_ids:
            try:
                store.upsert_document_categories(dr, tagged_ids, tagged_by='llm', target_year_month=ym)
                print(f'   🏷️ 카테고리 태깅 DB 저장 완료')
            except Exception as e:
                print(f'   ⚠️ 카테고리 태깅 DB 저장 실패: {e}')
    except Exception as e:
        # DB 저장 실패 시 반쪽 데이터 정리
        print(f"   ❌ DB 저장 실패: {e}")
        emit({"step": "done", "status": "error", "message": f"❌ DB 저장 실패: {e}"})
        try:
            store.delete_document(dr, ym)
        except Exception:
            pass
        raise

    elapsed = time.time() - start
    warnings = []
    if embedding_failed:
        warnings.append(f"임베딩 실패: {embedding_error}")
    if summary_errors > 0:
        warnings.append(f"요약 실패: {summary_errors}건")

    if warnings:
        warn_msg = ", ".join(warnings)
        print(f"   ⚠️ 완료 ({warn_msg}) — {len(sections)}섹션, {len(embeddings)}벡터, {elapsed:.1f}초")
        emit({"step": "done", "status": "warning", "message": f"⚠️ 완료 ({warn_msg}) — {len(sections)}섹션, {len(embeddings)}벡터, {elapsed:.1f}초"})
    else:
        print(f"   ✅ 완료! ({len(sections)}섹션, {len(embeddings)}벡터, {elapsed:.1f}초)")
        emit({"step": "done", "message": f"완료! {len(sections)}섹션, {len(embeddings)}벡터, {elapsed:.1f}초"})

    return {
        "dr_number": dr,
        "title": title,
        "sections": len(sections),
        "chunks": len(embeddings),
        "elapsed": elapsed,
        "skipped": False,
        "tagged_categories": tagged_ids,
        "embedding_failed": embedding_failed,
        "embedding_error": embedding_error if embedding_failed else "",
        "summary_errors": summary_errors,
    }


def load_folder(
    folder_path: str,
    config: dict,
    *,
    force: bool = False,
) -> list[dict]:
    """폴더 내 모든 .docx를 적재한다."""
    folder = Path(folder_path)
    files = sorted(folder.glob("*.docx"))

    if not files:
        print(f"❌ {folder}에 .docx 파일이 없습니다.")
        return []

    print(f"📂 폴더: {folder}")
    print(f"📋 대상 파일: {len(files)}개")

    pg_cfg = config["storage"]["postgresql"]
    dsn = f"host={pg_cfg['host']} port={pg_cfg['port']} dbname={pg_cfg['dbname']} user={pg_cfg['user']} password={pg_cfg['password']}"
    store = PgStore(dsn)

    embedder = Embedder(
        model_name=config["embedding"]["model_name"],
        cache_dir=config["embedding"].get("model_path"),
    )
    summarizer = Summarizer(
        api_key=config["llm"]["api_key"],
        base_url=config["llm"].get("base_url") or None,
    )

    results = []
    total_start = time.time()

    for i, fpath in enumerate(files):
        print(f"\n[{i+1}/{len(files)}]", end="")
        try:
            r = load_single_document(str(fpath), store, embedder, summarizer, force=force)
            results.append(r)
        except Exception as e:
            print(f"\n   ❌ 에러: {fpath.name}: {e}")
            results.append({"dr_number": "ERROR", "title": fpath.name, "error": str(e), "skipped": False})

    total_elapsed = time.time() - total_start

    loaded = [r for r in results if not r.get("skipped") and not r.get("error")]
    skipped = [r for r in results if r.get("skipped")]
    errors = [r for r in results if r.get("error")]

    print(f"\n{'='*60}")
    print(f"📊 적재 완료!")
    print(f"   총 파일: {len(files)}")
    print(f"   적재됨: {len(loaded)}")
    print(f"   스킵됨: {len(skipped)}")
    print(f"   에러: {len(errors)}")
    print(f"   총 소요: {total_elapsed:.1f}초")
    stats = store.stats()
    print(f"   DB 현황: {stats}")

    store.close()
    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="IA 설계문서 적재 (V3)")
    parser.add_argument("folder", help="docx 파일이 있는 폴더 경로")
    parser.add_argument("--force", action="store_true", help="이미 적재된 문서도 재적재")
    args = parser.parse_args()

    config = load_config()
    load_folder(args.folder, config, force=args.force)

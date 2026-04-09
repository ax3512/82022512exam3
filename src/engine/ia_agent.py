"""IA Agent — 유사 SR 검색 + IA 문서 기반 검토 가이드 생성.

사용자 요구사항 텍스트를 받아:
1) 벡터 검색으로 유사 섹션 조회
2) DR별 그룹핑 → 상위 5개 유사 DR 선정
3) 각 DR의 전체 섹션 조회
4) LLM으로 실제 IA 내용 기반 구조화된 검토 가이드 생성
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Callable

from src.engine.base_agent import BaseAgent, AgentResult
from src.embedder.embedder import Embedder
from src.storage.pg_store import PgStore
from src.engine.llm_client import LLMClient, CancelledError

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_category_names() -> dict[str, str]:
    """categories.json에서 ID → 이름 매핑 로드."""
    cat_file = PROJECT_ROOT / "categories.json"
    if not cat_file.exists():
        return {}
    with open(cat_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    names = {}
    def _walk(nodes):
        for n in nodes:
            names[n["id"]] = n["name"]
            if "children" in n:
                _walk(n["children"])
    _walk(data.get("categories", []))
    return names


# ── 검토 가이드 생성 프롬프트 ─────────────────────────────────────

REVIEW_PROMPT_TEMPLATE = """\
당신은 IA(영향도분석) 설계문서 검토 전문가입니다.
아래는 신규 요구사항과 관련된 기존 IA 문서의 필터링된 내용입니다.

★★★ 절대 규칙 ★★★
- 제공된 문서에 실제로 존재하는 정보만 참조하세요. 추측/생성 금지.
- 출처 DR번호는 표기하지 마세요.
- 핵심만 간결하게. 각 항목 3~5줄 이내.
- **주요 꼭지(테이블명, 소스명, 핵심 로직 등)는 굵게** 표기하세요.
- 요구사항과 직접 관련 없는 DR은 출처로 사용하지 마세요. 관련 있는 DR만 참조하세요.
- <최종결론:> 또는 <> 괄호 형식을 절대 사용하지 마세요. 일반 텍스트로만 작성하세요.
- 과거 과제에서 취소/철회/제외된 항목은 검토 포인트에서 "과거 취소 이력 있음" 등으로 명시하세요. 취소된 것을 필수 개발사항처럼 가이드하지 마세요.
- 특정 과제에서만 해당하는 특수사항은 공통 규칙인 것처럼 안내하지 마세요.

[신규 요구사항]
{requirement}

[관련 IA 문서 내용]
{context}

아래 형식으로 검토 가이드를 작성하세요:

★★★ 작성 기준 ★★★
- 과거 IA 문서 내용을 참고하여, 신규 요구사항 개발 시 검토해야 할 항목을 가이드하세요.
- 과거에 "무엇(WHAT)을 개발했는지" 항목과 "공통 업무 규칙/기준"을 뽑아주세요.
- 몇 종, 몇 건, 상품ID 등 세부 구현 스펙은 쓰지 마세요.
- 과거 SR의 이슈사항/진행상황은 쓰지 마세요.
- "~검토 필요", "~확인 필요" 톤으로 작성하세요.

### 1. 주요 검토 포인트
- 과거 유사 개발 기반으로 **이번 개발 시 검토해야 할 핵심 항목**을 정리
- 개발 항목(WHAT)과 해당 도메인의 **공통 업무 규칙/기준**을 함께 정리

### 2. 업무 영향도
- 개발 시 **영향받는 업무 영역** 정리 (상품, 청구, 할인, 과금, 배치 등)

### 3. DB/테이블 변경 포인트
- 변경 대상 **테이블명**만 간결하게 나열

### 4. AP소스 변경 포인트
- 변경 대상 **소스/프로그램** 목록. 없으면 "확인 불가"

### 5. 주의사항
- 영향도 분석 관점에서 **놓치기 쉬운 연계 포인트**만 간결하게

### 6. 최종 결론
- 위 1~5번 내용을 3줄 이내로 핵심만 종합 요약

### 참조 DR
- 위 1~6번 검토 가이드에서 실제로 내용을 인용한 DR번호만 나열하세요.
- 요구사항의 핵심 주제(예: 부가서비스)와 직접 관련 없는 DR은 절대 포함하지 마세요.
- 단순히 제공된 문서라는 이유로 포함하지 마세요. 검토 가이드에 실질적으로 기여한 DR만 나열하세요.
- 형식: DR-XXXX-XXXXX, DR-XXXX-XXXXX
"""


class IAAgent(BaseAgent):
    """IA 문서 기반 유사 SR 검색 및 검토 가이드 생성 Agent."""

    def __init__(
        self,
        store: PgStore,
        embedder: Embedder,
        llm: LLMClient,
        top_k: int = 10,
        max_drs: int = 5,
    ):
        self._store = store
        self._embedder = embedder
        self._llm = llm
        self._top_k = top_k
        self._max_drs = max_drs

    @property
    def name(self) -> str:
        return "IAAgent"

    def analyze(
        self,
        requirement: str,
        *,
        cancel_check: Callable[[], bool] | None = None,
        **kwargs,
    ) -> AgentResult:
        """요구사항에 대해 유사 DR 검색 → summary 기반 검토 가이드 생성.

        1) 요구사항 임베딩 → 벡터 유사도 검색 top_k
        2) DR별 최고 유사도로 그룹핑 → 상위 max_drs개 DR
        3) 각 DR의 전체 섹션 summary 조회
        4) LLM으로 summary 기반 검토 가이드 생성 (1차 필터링 없음)
        """
        if cancel_check and cancel_check():
            raise CancelledError("사용자가 요청을 취소했습니다.")

        # 1) 하이브리드 검색: 카테고리 + 키워드 + 벡터
        import re as _re
        from src.engine.search import _load_categories, _find_matching_category_ids

        dr_scores: dict[str, float] = {}

        # A) 카테고리 매칭
        categories = _load_categories()
        matched_cat_ids = _find_matching_category_ids(requirement, categories)
        if matched_cat_ids:
            for cat_id in matched_cat_ids:
                docs = self._store.get_documents_by_category(cat_id)
                for doc in docs:
                    dr = doc.get("dr_number", "")
                    if dr:
                        dr_scores[dr] = max(dr_scores.get(dr, 0), 1.0)
            print(f"  카테고리 매칭: {matched_cat_ids} → {len([d for d in dr_scores])}개 DR")

        # B) 키워드 검색 (제목)
        q_clean = _re.sub(r'[개발요청신규변경관련]', '', requirement)
        keywords = [w for w in q_clean.split() if len(w) >= 2]
        for kw in keywords:
            docs = self._store.find_documents_by_title(kw)
            for doc in docs:
                dr = doc.get("dr_number", "")
                if dr:
                    dr_scores[dr] = max(dr_scores.get(dr, 0), 0.9)

        # C) 벡터 검색
        query_embedding = self._embedder.embed_query(requirement)

        if cancel_check and cancel_check():
            raise CancelledError("사용자가 요청을 취소했습니다.")

        vector_results = self._store.vector_search(
            query_embedding=query_embedding,
            top_k=self._top_k,
        )

        for vr in vector_results:
            dr = vr.get("metadata", {}).get("dr_number", "")
            score = vr.get("score", 0.0)
            if dr and score > dr_scores.get(dr, 0):
                dr_scores[dr] = score

        # 카테고리/키워드 부스트
        for dr in dr_scores:
            if dr_scores[dr] >= 1.0:  # 카테고리 매칭
                dr_scores[dr] = min(1.0, dr_scores[dr] + 0.1)

        # 2) 상위 max_drs개 DR 선정
        sorted_drs = sorted(dr_scores.items(), key=lambda x: x[1], reverse=True)[:self._max_drs]

        if not sorted_drs:
            return AgentResult(
                agent_name=self.name,
                warnings=["유사한 DR을 찾지 못했습니다."],
            )

        print(f"\n{'='*60}")
        print(f"  IA Agent: 벡터검색 상위 {len(sorted_drs)}개 DR")

        # 3) 각 DR의 섹션 summary 조회 + 유사 SR 목록 구성
        similar_drs: list[dict[str, Any]] = []
        context_parts: list[str] = []

        for dr_number, best_score in sorted_drs:
            if cancel_check and cancel_check():
                raise CancelledError("사용자가 요청을 취소했습니다.")

            sections = self._store.get_sections_by_dr(dr_number)
            doc = self._store.get_document(dr_number)
            title = doc.get("title", "") if doc else ""

            # 카테고리 태깅된 관련업무 조회 (DB에서 가져옴, LLM 호출 없음)
            cat_names = _load_category_names()
            cat_records = self._store.get_categories_by_dr(dr_number)
            related_categories = [cat_names.get(c["category_id"], c["category_id"]) for c in cat_records]

            similar_drs.append({
                "dr_number": dr_number,
                "title": title,
                "score": round(best_score, 3),
                "categories": related_categories,
            })

            # LLM 컨텍스트: 적재 시 생성된 summary만 사용
            context_parts.append(f"\n### [{dr_number}] {title}")
            for sec in sections:
                heading = sec.get("heading_path", "")
                summary = sec.get("summary", "")
                if summary:
                    context_parts.append(f"**{heading}**\n{summary}")

            print(f"  [{dr_number}] {title} | 유사도: {round(best_score, 3)} | 관련업무: {', '.join(related_categories) if related_categories else '-'}")

        print(f"{'='*60}\n")

        # 4) LLM: summary 기반 검토 가이드 생성 (1차 필터링 없이 바로)
        if cancel_check and cancel_check():
            raise CancelledError("사용자가 요청을 취소했습니다.")

        context = "\n".join(context_parts)
        prompt = REVIEW_PROMPT_TEMPLATE.format(
            requirement=requirement,
            context=context,
        )

        print(f"  LLM: {len(similar_drs)}개 DR summary 기반 검토 가이드 생성 중...")
        review_text = self._llm.chat(prompt, cancel_check=cancel_check)
        print(f"  검토 가이드 생성 완료")

        findings = _parse_review_findings(review_text)
        warnings = _extract_warnings(review_text)

        # "### 참조 DR" 섹션에서 실제 참조된 DR만 추출하여 필터링
        import re
        ref_match = re.search(r"###?\s*참조\s*DR\s*\n(.*)", review_text, re.DOTALL)
        if ref_match:
            referenced_drs = set(re.findall(r"DR-\d{4}-\d{4,6}", ref_match.group(1)))
        else:
            referenced_drs = set(re.findall(r"DR-\d{4}-\d{4,6}", review_text))
        filtered_similar = [d for d in similar_drs if d["dr_number"] in referenced_drs]
        # 참조 DR이 없거나 벡터 상위 1위가 참조 안 됐어도 1위는 포함
        if not filtered_similar and similar_drs:
            filtered_similar = similar_drs[:1]
        print(f"  참조 DR: {referenced_drs}")
        print(f"  유사 SR 필터링: {len(similar_drs)}개 → {len(filtered_similar)}개")

        return AgentResult(
            agent_name=self.name,
            findings=findings,
            similar_drs=filtered_similar,
            warnings=warnings,
            raw_data={"review_text": review_text, "prompt_length": len(prompt)},
        )


# ── 유틸 ──────────────────────────────────────────────────────────

def _parse_review_findings(review_text: str) -> list[dict[str, Any]]:
    """LLM 검토 가이드 텍스트에서 주요 검토 포인트를 파싱."""
    import re

    # "### 참조 DR" 이후 텍스트 분리 (필터링 용도로만 사용)
    main_text = re.split(r"(?:^|\n)###?\s*참조\s*DR", review_text)[0]

    findings: list[dict[str, Any]] = []
    sections = re.split(r"(?:^|\n)(?:###?\s*)?\d+\.\s+", main_text)

    for section in sections[1:]:
        lines = section.strip().split("\n", 1)
        title = lines[0].strip()
        content = lines[1].strip() if len(lines) > 1 else ""

        # "참조 DR" 섹션은 화면에 안 보여줌 (필터링 용도로만 사용)
        if "참조" in title and "DR" in title:
            continue

        sources = re.findall(r"DR-\d{4}-\d{4,6}", content)

        if title and content:
            findings.append({
                "title": title,
                "content": content,
                "sources": list(set(sources)),
            })

    return findings


def _extract_warnings(review_text: str) -> list[str]:
    """검토 가이드에서 경고 섹션 추출."""
    import re

    warnings: list[str] = []
    # "## 경고" 섹션 이후 내용
    match = re.search(r"##\s*경고\s*\n(.*)", review_text, re.DOTALL)
    if match:
        warning_text = match.group(1).strip()
        # "- " 로 시작하는 항목 추출
        for line in warning_text.split("\n"):
            line = line.strip()
            if line.startswith("- "):
                warnings.append(line[2:].strip())

    return warnings

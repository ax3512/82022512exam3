"""답변 생성 — V3: 질문 유형 분류 → 유형별 프롬프트 → 답변."""
from __future__ import annotations
import re
from typing import Any, Callable

from src.engine.llm_client import LLMClient, CancelledError


# ── 질문 유형 분류 (코드 기반, LLM 호출 없음) ─────────────────

def classify_question(question: str) -> str:
    """질문을 유형별로 분류. LLM 호출 없이 키워드/패턴으로 판단.

    Returns: "sr_search" | "dr_detail" | "business"
    """
    q = question.strip()

    # DR번호가 명시된 경우 → DR 상세
    if re.search(r'DR-\d{4}-\d{4,6}', q, re.IGNORECASE):
        return "dr_detail"

    # SR/과제 찾기 패턴
    sr_patterns = [
        r'SR\s*찾아', r'SR\s*있[어나]', r'SR\s*알려',
        r'과제\s*찾아', r'과제\s*있[어나]', r'과제\s*알려',
        r'참조.*SR', r'참조.*과제', r'참고.*SR', r'참고.*과제',
        r'관련.*SR', r'관련.*과제',
        r'SR\s*목록', r'과제\s*목록',
        r'어떤.*개발', r'개발.*이력',
        r'SR.*뭐', r'과제.*뭐',
    ]
    for pat in sr_patterns:
        if re.search(pat, q, re.IGNORECASE):
            return "sr_search"

    # 나머지 → 업무/기술 질문
    return "business"


# ── 1차 필터링 프롬프트 ───────────────────────────────────────

FILTER_PROMPT = """당신은 통신/청구 도메인 IA 설계문서 분석 전문가입니다.

사용자 질문과 관련된 섹션을 골라서 핵심 내용을 정리해주세요.

규칙:
1. 먼저 이 문서의 핵심 주제(제목 기준)가 질문의 핵심 주제와 직접 관련이 있는지 판단하세요.
   - 예: 질문이 "부가서비스"인데 문서가 "단말보험" → 관련 없음
   - 예: 질문이 "할인"인데 문서가 "단말보험 개발"이고 할인 섹션이 있음 → 관련 있음
   - 문서의 핵심 주제가 질문과 다르면 반드시 "관련 섹션 없음"으로 답하세요.
2. 관련 있다고 판단한 경우, 질문이 과제 전반을 묻는 경우 폭넓게, 특정 항목만 묻는 경우 해당 항목만 포함하세요.
3. 질문에 테이블명·소스코드명·할인ID 등 기술적 키워드가 있으면, 해당 키워드가 직접 언급된 섹션을 포함하세요.
4. 선택한 섹션의 핵심 내용을 요약하되, 테이블명·소스코드명·할인ID·단위서비스코드 등 구체적 정보는 원문 그대로 보존하세요.
5. 각 섹션의 DR번호와 섹션 경로를 반드시 포함하세요.
6. 유사한 도메인 키워드(청구, 요금, 서비스 등)가 겹친다는 이유만으로 관련 있다고 판단하지 마세요.
{prev_context}
사용자 질문: {question}

아래는 [{dr_number}] {doc_title} 문서의 섹션들입니다:
{sections_text}"""


# ── 유형별 2차 답변 프롬프트 ──────────────────────────────────

# 공통 규칙 (모든 유형에 포함)
_COMMON_RULES = """
- 참조 섹션에 있는 내용만으로 답변하세요. 없는 내용은 추측하지 마세요.
- 테이블명, 소스코드명, 할인ID, 단위서비스ID 등 코드값은 원문 그대로 빠짐없이 인용하세요.
- 목록이나 개수를 묻는 질문에는 참조자료의 표/리스트를 빠짐없이 전부 나열하세요.
- "신규"와 "기존 재사용"을 명확히 구분하세요.
- 취소/철회/제외/보류된 항목은 반드시 그 사실을 명시하세요. 취소된 것을 필수사항처럼 안내하지 마세요.
- 특정 과제에서만 해당하는 사항은 "(DR-XXXX 한정)"으로 한정하세요.
- 답변은 리스트(-) 형식을 기본으로 하세요. 마크다운 표는 3개 이상 항목을 비교할 때만 사용하세요.
- 꼭지(주제)별로 구분할 때는 ### 제목을 쓰고, 하위 항목은 들여쓰기로 계층을 표현하세요.
- 한국어로 답변하세요."""


PROMPT_SR_SEARCH = """당신은 통신/청구 도메인 IA 설계문서 Q&A 전문가입니다.
사용자가 관련 SR/과제를 찾고 있습니다. DR별로 핵심 개발내용을 요약해주세요.

규칙:
1. 각 DR을 "📎 [DR번호] 문서제목" 형식으로 구분하세요.
2. 각 DR별로 핵심 개발내용을 간결하게 요약하세요 (상품, 할인, 배치, 테이블 등).
3. 각 DR의 주요 개발 항목을 빠짐없이 포함하세요 (상품신설, 할인, 권리실행, 배치 등).
4. 질문의 핵심 주제와 직접 관련 없는 DR은 답변에 포함하지 마세요.
""" + _COMMON_RULES + """

{context}

사용자 질문: {question}

★ 답변 마지막에 아래 형식으로 실제 답변에 인용한 DR만 나열하세요:
### 참조 DR
- 질문의 핵심 주제와 직접 관련 있고, 답변에서 실제로 내용을 인용한 DR만 나열하세요.
- 단순히 제공된 문서라는 이유로 포함하지 마세요.
- 형식: DR-XXXX-XXXXX, DR-YYYY-YYYYY"""


PROMPT_DR_DETAIL = """당신은 통신/청구 도메인 IA 설계문서 Q&A 전문가입니다.
사용자가 특정 DR/과제에 대해 질문하고 있습니다. 해당 DR의 내용을 상세하게 답변하세요.

규칙:
1. 해당 DR의 개발 내용을 항목별로 상세하게 정리하세요.
2. 상품, 단위서비스, 할인, 과금/청구, 배치, 권리실행 등 모든 개발 영역을 빠짐없이 포함하세요.
3. 각 항목의 구체적인 코드값(단위서비스ID, 할인ID, 테이블명 등)을 원문 그대로 포함하세요.
4. 본문 중간에 DR번호를 반복하지 마세요. 어떤 DR인지는 앞에 한 번만 언급하세요.
""" + _COMMON_RULES + """

{context}

사용자 질문: {question}

★ 답변 마지막에 아래 형식으로 실제 답변에 인용한 DR만 나열하세요:
### 참조 DR
- 질문의 핵심 주제와 직접 관련 있고, 답변에서 실제로 내용을 인용한 DR만 나열하세요.
- 형식: DR-XXXX-XXXXX, DR-YYYY-YYYYY"""


PROMPT_BUSINESS = """당신은 통신/청구 도메인 IA 설계문서 Q&A 전문가입니다.
사용자가 업무/기술 관련 질문을 하고 있습니다. 주제 중심으로 통합 정리하여 답변하세요.

규칙:
1. 주제 중심으로 통합 정리하세요. DR별로 나누지 마세요.
2. 본문 중간에 DR번호를 넣지 마세요. 가독성이 떨어집니다.
3. 질문이 묻는 내용에 직접 해당하는 정보만 포함하세요.
4. 질문의 핵심 주제와 직접 관련 없는 DR의 내용은 포함하지 마세요.
""" + _COMMON_RULES + """

{context}

사용자 질문: {question}

★ 답변 마지막에 아래 형식으로 실제 답변에 인용한 DR만 나열하세요:
### 참조 DR
- 질문의 핵심 주제와 직접 관련 있고, 답변에서 실제로 내용을 인용한 DR만 나열하세요.
- 단순히 제공된 문서라는 이유로 포함하지 마세요.
- 형식: DR-XXXX-XXXXX, DR-YYYY-YYYYY"""


# ── 연계질문 프롬프트 ─────────────────────────────────────────

FOLLOWUP_PROMPT = """당신은 통신/청구 도메인 IA 설계문서 Q&A 전문가입니다.
아래 참조자료와 대화이력을 기반으로 사용자의 후속 질문에 답변하세요.

규칙:
1. 대화이력의 흐름을 이해하고, 후속 질문이 묻는 내용에만 집중하세요.
2. 이전 답변에서 다루던 주제와 다른 영역의 정보는 포함하지 마세요.
3. 이전 답변과 일관성을 유지하세요.
""" + _COMMON_RULES + """

[참조자료]
{context}

[대화이력]
{chat_history}

후속 질문: {question}"""


# ── 유형별 프롬프트 매핑 ──────────────────────────────────────

_PROMPT_MAP = {
    "sr_search": PROMPT_SR_SEARCH,
    "dr_detail": PROMPT_DR_DETAIL,
    "business": PROMPT_BUSINESS,
}


class AnswerGenerator:
    """V3: 질문 유형 분류 → 유형별 프롬프트 → 답변."""

    def __init__(self, api_key: str, base_url: str, **kwargs):
        self.llm = LLMClient(api_key=api_key, base_url=base_url)

    def filter_sections_by_dr(self, question: str, dr_number: str, doc_title: str, sections: list[dict], cancel_check: Callable[[], bool] | None = None, prev_context: str = "") -> str:
        """1차 LLM — DR 1개의 섹션에서 질문에 관련된 내용만 필터링."""
        parts = []
        for i, sec in enumerate(sections):
            path = sec.get("heading_path", "")
            summary = sec.get("summary", "") or sec.get("content", "")
            parts.append(
                f"[섹션 {i+1}] 경로: {path}\n"
                f"내용:\n{summary}"
            )

        sections_text = "\n---\n".join(parts)
        prev_ctx_text = ""
        if prev_context:
            prev_ctx_text = (
                f"\n[이전 대화 맥락]\n{prev_context}\n"
                f"★ 후속질문 필터링 규칙:\n"
                f"- 이전 대화에서 다루던 구체적 주제에 해당하는 섹션만 포함하세요.\n"
                f"- 이전 대화 주제와 다른 영역은 제외하세요.\n"
            )
        prompt = FILTER_PROMPT.format(
            question=question,
            dr_number=dr_number,
            doc_title=doc_title,
            sections_text=sections_text,
            prev_context=prev_ctx_text,
        )

        print(f"  📋 1차 LLM [{dr_number}]: {len(sections)}개 섹션 필터링 중...")
        filtered = self.llm.chat(prompt, cancel_check=cancel_check).strip()
        print(f"  ✅ 1차 LLM [{dr_number}] 완료 ({len(filtered)}자)")
        return filtered

    def generate(self, question: str, search_results: list[dict[str, Any]], cancel_check: Callable[[], bool] | None = None, prev_question: str = "", prev_answer: str = "") -> dict[str, Any]:
        """V3: 질문 유형 분류 → 1차 필터링 → 유형별 프롬프트로 답변."""
        if not search_results:
            return {
                "answer": "해당 정보를 찾을 수 없습니다. 질문을 다시 확인해주세요.",
                "sources": [],
            }

        # 질문 유형 분류
        q_type = classify_question(question)
        print(f"  📌 질문 유형: {q_type}")

        # DR별로 섹션 그룹핑
        dr_sections: dict[str, list[dict]] = {}
        dr_titles: dict[str, str] = {}
        dr_scores: dict[str, float] = {}

        for r in search_results:
            sec = r["section"]
            dr = sec.get("dr_number", "")
            if not dr:
                continue
            if dr not in dr_sections:
                dr_sections[dr] = []
                dr_titles[dr] = sec.get("title", "")
                dr_scores[dr] = r.get("score", 0)
            dr_sections[dr].append(sec)

        # sources
        sources = [
            {
                "dr_number": dr,
                "title": dr_titles[dr],
                "heading_path": dr_sections[dr][0].get("heading_path", ""),
                "score": round(dr_scores[dr], 3),
            }
            for dr in dr_sections
        ]

        # ── 1차 LLM: DR별 개별 호출 ──
        filter_prev_ctx = ""
        if prev_question and prev_answer:
            filter_prev_ctx = f"이전 질문: {prev_question}\n이전 답변:\n{prev_answer[:800]}"

        filtered_parts = []
        for dr, sections in dr_sections.items():
            if cancel_check and cancel_check():
                raise CancelledError("사용자가 요청을 취소했습니다.")
            title = dr_titles[dr]
            filtered = self.filter_sections_by_dr(question, dr, title, sections, cancel_check=cancel_check, prev_context=filter_prev_ctx)
            if "관련 섹션 없음" not in filtered:
                filtered_parts.append(f"[{dr}] {title}:\n{filtered}")
                print(f"    → ✅ [{dr}] 관련 내용 있음")
            else:
                print(f"    → ❌ [{dr}] 관련 섹션 없음 → 제외")

        if not filtered_parts:
            return {
                "answer": "해당 정보를 찾을 수 없습니다. 질문을 다시 확인해주세요.",
                "sources": [],
            }

        # ── 2차 LLM: 유형별 프롬프트로 답변 ──
        dr_titles_text = '\n'.join(f'  {dr}: {t}' for dr, t in dr_titles.items())
        all_filtered = '\n\n'.join(filtered_parts)
        context_with_titles = f"DR번호별 문서 제목:\n{dr_titles_text}\n\n필터링된 참조 내용:\n{all_filtered}"

        # 유형별 프롬프트 선택
        prompt_template = _PROMPT_MAP.get(q_type, PROMPT_BUSINESS)
        prompt = prompt_template.format(context=context_with_titles, question=question)

        if cancel_check and cancel_check():
            raise CancelledError("사용자가 요청을 취소했습니다.")

        print(f"  💬 2차 LLM ({q_type}): {len(filtered_parts)}개 DR 기반 답변 생성 중...")
        answer = self.llm.chat(prompt, cancel_check=cancel_check).strip()
        print("  ✅ 2차 LLM 답변 완료")

        # ── 후처리: "참조 DR" 섹션 제거 + 답변에서 실제 인용된 DR만 유지 ──
        # 1) "참조 DR" / "최종결론" 섹션 제거
        answer = re.split(r"\n*###?\s*참조\s*DR", answer)[0].strip()
        answer = re.sub(r"<최종결론:.*?>", "", answer, flags=re.DOTALL).strip()

        # 2) 답변에서 실제 언급된 DR 추출
        referenced_drs = set(re.findall(r"DR-\d{4}-\d{4,6}", answer))

        # 3) SR검색 유형: 📎 [DR번호] 형태로 명시적으로 인용된 DR만
        if q_type == "sr_search":
            explicit_drs = set(re.findall(r"📎\s*\[?(DR-\d{4}-\d{4,6})\]?", answer))
            if explicit_drs:
                referenced_drs = explicit_drs

        filtered_sources = [s for s in sources if s["dr_number"] in referenced_drs]
        if not filtered_sources and sources:
            filtered_sources = sources[:1]

        print(f"  참조 DR 필터링: {[s['dr_number'] for s in sources]} → {[s['dr_number'] for s in filtered_sources]}")

        return {
            "answer": answer,
            "sources": filtered_sources,
            "filtered_context": all_filtered,
            "question_type": q_type,
        }

    # ── 연계질문 전용 ─────────────────────────────────────────

    def generate_followup(
        self,
        question: str,
        filtered_context: str,
        chat_history: list[dict],
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """연계질문: 캐시된 필터링 결과 + 대화이력 전체로 LLM 1회 호출."""

        history_parts = []
        for msg in chat_history:
            role_label = "사용자" if msg["role"] == "user" else "AI"
            history_parts.append(f"{role_label}: {msg['content']}")
        history_text = "\n\n".join(history_parts)

        prompt = FOLLOWUP_PROMPT.format(
            context=filtered_context,
            chat_history=history_text,
            question=question,
        )

        if cancel_check and cancel_check():
            raise CancelledError("사용자가 요청을 취소했습니다.")

        print(f"  💬 연계질문 LLM: 대화이력 {len(chat_history)}턴 + 캐시 필터링 결과 기반 답변 생성 중...")
        answer = self.llm.chat(prompt, cancel_check=cancel_check).strip()
        print("  ✅ 연계질문 답변 완료")

        return {"answer": answer}

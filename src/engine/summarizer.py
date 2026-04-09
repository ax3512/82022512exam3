"""Summarizer — LLM으로 섹션별 요약 + 엔티티 추출."""
from __future__ import annotations
import json
import re
from typing import Any



# ── 섹션 유형별 요약 프롬프트 ──────────────────────────────────

SUMMARY_PROMPTS = {
    "과제분석": """이 IA 설계문서의 '과제분석' 섹션입니다.
다음 내용을 최대한 상세하게(500~2000자) 요약하세요:
1) AS-IS (현재 상태) — 있으면 구체적으로
2) TO-BE (변경 사항) — 변경 내용을 빠짐없이
3) 핵심 업무 룰 — 조건, 분기, 예외 등 상세히
4) 관련 테이블/소스 — 모두 나열

⭐ 추가 지시:
- 원문의 구체적인 데이터(테이블명, 컨럼명, 할인ID, 서비스ID, JO명, 조건값 등)를 절대 생략하지 마세요.
  - 테이블명(XX_YYY_ZZZ 패턴)과 소스코드명(XxxYyySO/JO/BO 패턴)은 원문 그대로 포함하세요.
- 상품명, 할인ID, 서비스ID 등 고유 식별자도 반드시 포함하세요.
- 요약 끝에 아래 JSON 형식으로 엔티티를 별도 추출하세요:
  {{"mentioned_tables": [...], "mentioned_sources": [...]}}

원문:
{content}""",

    "구현방안": """이 IA 설계문서의 '구현방안' 섹션입니다.
다음 내용을 최대한 상세하게(500~2000자) 요약하세요:
1) 변경 대상 테이블과 필드 — 모두 나열
2) 데이터 변경 내용 (INSERT/UPDATE/DELETE) — 건수, 조건값 포함
3) 할인/과금/배치 등 핵심 로직 — 상세히
4) 레퍼런스 데이터 변경사항 — 구체적 값 포함

⭐ 추가 지시:
- 원문의 구체적인 데이터(테이블명, 컨럼명, 할인ID, 서비스ID, JO명, 조건값 등)를 절대 생략하지 마세요.
- 테이블명과 소스코드명은 원문 그대로 포함하세요.
- 할인ID, 서비스ID, 조건값 등 구체적 값을 가능한 포함하세요.
  - 요약 끝에: {{"mentioned_tables": [...], "mentioned_sources": [...]}}

원문:
{content}""",

    "검증방안": """이 IA 설계문서의 '검증방안' 섹션입니다.
다음 내용을 최대한 상세하게(300~1000자) 요약하세요:
1) 테스트 대상 (테이블, JO, 시나리오) — 모두 나열
2) 검증 방법 — SQL, 시나리오 상세히
3) 예상 결과

⭐ 추가 지시:
- 테이블명과 소스코드명은 원문 그대로 포함하세요.
- 요약 끝에: {{"mentioned_tables": [...], "mentioned_sources": [...]}}

원문:
{content}""",

    "이슈사항": """이 IA 설계문서의 '이슈사항' 섹션입니다.
다음 내용을 상세하게(200~800자) 요약하세요:
1) 주요 이슈/리스크 — 구체적으로
2) 조치 방안 (있으면)

⭐ 추가 지시:
- 테이블명/소스코드명이 있으면 원문 그대로 포함하세요.
- 요약 끝에: {{"mentioned_tables": [...], "mentioned_sources": [...]}}

원문:
{content}""",

    "DB참조": """이 IA 설계문서의 'DB Object/참조 레퍼런스' 섹션입니다.
다음 내용을 최대한 상세하게(500~2000자) 요약하세요:
1) 변경/신규 대상 테이블 목록 — 빠짐없이 모두
2) 각 테이블의 변경 내용 (컨럼 추가/수정, 데이터 INSERT 등) — 건수 포함
3) 핵심 조건값, 레퍼런스 코드

⭐ 추가 지시:
- **테이블명**을 요약에 반드시 원문 그대로 빠짐없이 포함하세요.
- 레퍼런스 코드, 조건값, ID 등 핵심 데이터를 포함하세요.
- 요약 끝에: {{"mentioned_tables": [...], "mentioned_sources": [...]}}

원문:
{content}""",

    "default": """이 IA 설계문서 섹션을 최대한 상세하게(500~2000자) 요약하세요.
핵심 내용, 관련 시스템/테이블/소스, 조건값, ID 등 구체적 데이터를 빠짐없이 포함하세요.

⭐ 추가 지시:
- 원문의 구체적인 데이터(테이블명, 컨럼명, 할인ID, 서비스ID, JO명, 조건값 등)를 절대 생략하지 마세요.
  - 테이블명(XX_YYY_ZZZ 패턴)과 소스코드명(XxxYyySO/JO/BO 패턴)은 원문 그대로 포함하세요.
- 요약 끝에: {{"mentioned_tables": [...], "mentioned_sources": [...]}}

원문:
{content}""",
}

DOC_SUMMARY_PROMPT = """다음은 IA 설계문서 '{title}' (DR번호: {dr_number})의 주요 섹션 요약들입니다.
아래 꼭지별로 정리하세요. 원문에 있는 내용만 포함하세요.

★ 작성 규칙:
- 서두/인사/설명 문구 없이 바로 📌부터 시작하세요
- 각 꼭지에 해당 내용이 없으면 "해당 없음"으로 표기
- 테이블명, 소스코드명, 건수 등 구체적 데이터는 원문 그대로 포함
- 불필요한 서술 없이 리스트 형태로 간결하게
- <최종결론:> 또는 <> 괄호 형식을 절대 사용하지 마세요

📌 개발 목적
- 이 과제가 무엇을 개발하는지 1~2줄로

📌 주요 개발 내용
- 신규 개발한 항목 (상품, 서비스, 기능 등)
- 각 항목의 종수/건수 포함

📌 변경 테이블
- 테이블명: 변경유형(INSERT/UPDATE/DELETE) 건수

📌 변경 소스
- 소스/프로그램명 목록. 없으면 "해당 없음"

📌 검증 방법
- 검증 시나리오 및 확인 대상

📌 이슈/유의사항
- 이슈사항, 리스크, 주의점

🎯 최종 요약
- 위 내용을 2~3줄로 핵심만 종합 요약

섹션 요약들:
{section_summaries}"""


def parse_summary_response(response: str) -> tuple[str, dict[str, list[str]]]:
    """LLM 응답에서 요약 텍스트와 엔티티 JSON을 분리."""
    json_match = re.search(r'\{\s*"mentioned_tables".*?\}', response, re.DOTALL)
    if json_match:
        try:
            entities = json.loads(json_match.group())
            summary = response[:json_match.start()].strip()
            return summary, entities
        except json.JSONDecodeError:
            pass
    return response.strip(), {"mentioned_tables": [], "mentioned_sources": []}


class Summarizer:
    """Dify API로 섹션 요약 + 엔티티 추출."""

    def __init__(self, api_key: str, base_url: str, **kwargs):
        from src.engine.llm_client import LLMClient
        self.llm = LLMClient(api_key=api_key, base_url=base_url)

    def summarize_section(self, content: str, section_type: str = "default") -> dict[str, Any]:
        """섹션 하나를 요약하고 엔티티를 추출한다."""
        stripped = content.strip() if content else ""
        # 빈 컨텐츠 → 빈 summary 반환 (LLM 호출 안 함)
        if not stripped or len(stripped) < 20:
            return {"summary": "", "mentioned_tables": [], "mentioned_sources": []}

        # 빈 표 패턴 감지: 마크다운 테이블인데 값이 전부 비어있는 경우
        lines = [l.strip() for l in stripped.split('\n') if l.strip() and not l.strip().startswith('| ---')]
        non_empty_cells = [l for l in lines if l.replace('|', '').replace('-', '').strip()]
        if len(non_empty_cells) < 2:
            return {"summary": "", "mentioned_tables": [], "mentioned_sources": []}

        # 표 헤더만 있고 값이 비어있는 경우 (항목명만 존재)
        table_lines = [l for l in lines if '|' in l]
        if table_lines:
            cell_values = []
            for tl in table_lines:
                cells = [c.strip() for c in tl.split('|') if c.strip()]
                cell_values.extend(cells)
            # 셀 값이 모두 짧은 헤더성 텍스트만 있으면 빈 표로 판단
            meaningful = [c for c in cell_values if len(c) > 10]
            if len(meaningful) < 2 and len(table_lines) == len(lines):
                return {"summary": "", "mentioned_tables": [], "mentioned_sources": []}

        prompt_template = SUMMARY_PROMPTS.get(section_type, SUMMARY_PROMPTS["default"])
        prompt = prompt_template.format(content=content)
        system = (
            "당신은 통신/청구 도메인 IA 설계문서 전문 분석가입니다. 정확하고 구체적인 요약을 생성합니다.\n\n"
            "★★★ 절대 금지 ★★★:\n"
            "- 원문에 없는 내용을 절대 만들어내지 마세요.\n"
            "- 원문이 비어있거나 빈 표만 있으면, 원문 그대로만 출력하세요. 가상 내용을 채우지 마세요.\n"
            "- 가상 사례, 샘플 예시, 참고용 예시를 절대 생성하지 마세요.\n"
            "- '만약 ~라면', '예를 들어', '가상 사례' 같은 가정이나 예시를 만들지 마세요.\n"
            "- 원문에 실제로 있는 데이터만 요약하세요.\n"
            "- <최종결론:> 또는 <> 괄호 형식을 사용하지 마세요.\n\n"
            "★★★ 상태 구분 필수 ★★★:\n"
            "- 취소/철회/제외/보류된 항목은 반드시 [취소됨], [제외됨], [보류] 등으로 상태를 명시하세요.\n"
            "- '사업부서 요청으로 취소', '개발 제외', '미적용' 등의 맥락이 있으면 반드시 요약에 포함하세요.\n"
            "- 개발 예정이었으나 취소된 항목을 확정된 개발 사항처럼 요약하지 마세요.\n"
            "- 이 과제에서만 해당하는 특수사항은 '이 과제에서는~' 또는 '본 SR에서는~'으로 한정하세요."
        )
        full_prompt = f"{system}\n\n{prompt}"

        raw = self.llm.chat(full_prompt)
        summary, entities = parse_summary_response(raw)

        return {
            "summary": summary,
            "mentioned_tables": entities.get("mentioned_tables", []),
            "mentioned_sources": entities.get("mentioned_sources", []),
        }

    def summarize_document(self, dr_number: str, title: str, section_summaries: list[str]) -> str:
        """문서 전체 종합 요약 생성."""
        combined = "\n\n".join(f"- {s}" for s in section_summaries if s)
        prompt = DOC_SUMMARY_PROMPT.format(
            title=title,
            dr_number=dr_number,
            section_summaries=combined,
        )

        return self.llm.chat(prompt)

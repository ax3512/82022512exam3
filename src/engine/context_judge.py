"""연계질문 판단 — LLM이 이전 대화 맥락을 보고 신규검색 vs 연계질문 분류."""
from __future__ import annotations
import json
import re
from typing import Any

from src.engine.llm_client import LLMClient

_JUDGE_PROMPT = """당신은 대화 맥락 분석기입니다.
새 질문이 "이전에 답변한 동일 문서(DR)에 대한 후속질문"인지, "새로운 문서를 검색해야 하는 질문"인지 판단하세요.

## 이전 질문
{prev_question}

## 이전 답변에 포함된 DR번호
{prev_drs}

## 새 질문
{question}

## 판단 기준
- "followup": 이전에 답변한 문서(DR)의 다른 부분을 묻는 경우 (자세히, 요약, 비교, 다른 섹션 등)
- "new": 이전 답변에 없는 새로운 과제/문서/주제를 찾으려는 경우. 비슷한 도메인이라도 다른 문서를 찾는 거면 "new"

★ 핵심: "~과제 찾아줘", "~SR 있어?", "~관련 과제" 같이 새 문서를 탐색하는 표현이면 "new"입니다.
★ 판단이 애매하면(두 가지 모두 가능해 보이면) "unsure"로 응답하세요.

반드시 아래 JSON 형식으로만 응답하세요:
{{"type": "followup"}} 또는 {{"type": "new"}} 또는 {{"type": "unsure"}}"""


def judge_context(
    question: str,
    prev_question: str = "",
    prev_answer: str = "",
    prev_dr_numbers: list[str] | None = None,
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    """질문이 연계질문인지 신규검색인지 LLM으로 판단."""

    # 이전 맥락이 없으면 무조건 신규
    if not prev_question or not prev_dr_numbers:
        return {"type": "new", "reason": "이전 대화 없음", "dr_numbers": None}

    # DR번호가 명시되어 있으면 빠르게 판단
    new_drs = re.findall(r"DR-\d{4}-\d{4,6}", question, re.IGNORECASE)
    if new_drs:
        new_drs_upper = [d.upper() for d in new_drs]
        if set(new_drs_upper) <= set(prev_dr_numbers):
            return {"type": "followup", "reason": f"이전 DR 재질문", "dr_numbers": new_drs_upper}
        return {"type": "new", "reason": f"새 DR번호", "dr_numbers": None}

    # LLM 판단
    if llm_client:
        try:
            prompt = _JUDGE_PROMPT.format(
                prev_question=prev_question,
                prev_answer=prev_answer[:300],
                prev_drs=", ".join(prev_dr_numbers),
                question=question,
            )
            raw = llm_client.chat(prompt)
            match = re.search(r'\{.*?"type"\s*:\s*"(followup|new|unsure)".*?\}', raw, re.DOTALL)
            if match:
                qtype = match.group(1)
                return {
                    "type": qtype,
                    "reason": "LLM 판단",
                    "dr_numbers": prev_dr_numbers if qtype in ("followup", "unsure") else None,
                }
        except Exception as e:
            print(f"  ⚠️ LLM 판단 실패, 신규로 처리: {e}")

    # LLM 없거나 실패 시 기본: 신규
    return {"type": "new", "reason": "기본값 (신규)", "dr_numbers": None}

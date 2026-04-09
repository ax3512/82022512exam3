"""질문 분석 — DR번호 감지, 제목 매칭, 질문 유형 분류.

V3: PgStore 사용.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Any

from src.storage.pg_store import PgStore


@dataclass
class QueryAnalysis:
    """분석된 질문 정보."""
    original: str = ""
    dr_numbers: list[str] | None = None
    title_matches: list[dict[str, str]] | None = None
    query_type: str = "general"


def analyze_query(question: str, store: PgStore) -> QueryAnalysis:
    """질문을 분석하여 DR번호, 제목 매칭 등을 수행."""
    analysis = QueryAnalysis(original=question)

    # 1) DR번호 추출
    dr_pattern = re.findall(r"DR-\d{4}-\d{4,6}", question, re.IGNORECASE)
    if dr_pattern:
        analysis.dr_numbers = [d.upper() for d in dr_pattern]
        analysis.query_type = "specific_dr"
        return analysis

    # 2) 제목 키워드 매칭
    keywords = re.findall(r"[가-힣]{2,}", question)
    if keywords:
        matches = []
        for kw in keywords:
            docs = store.find_documents_by_title(kw)
            for doc in docs:
                matches.append({"dr_number": doc["dr_number"], "title": doc["title"], "matched_keyword": kw})
        if matches:
            seen = set()
            unique = []
            for m in matches:
                if m["dr_number"] not in seen:
                    seen.add(m["dr_number"])
                    unique.append(m)
            analysis.title_matches = unique

    return analysis

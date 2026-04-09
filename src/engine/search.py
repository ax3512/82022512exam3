"""검색엔진 — 하이브리드 검색 (카테고리 + 키워드 + 벡터).

V4: 카테고리 매칭 + 키워드 검색 + 벡터 유사도 검색을 합쳐서
    더 정확한 DR 후보를 선정.
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any, Callable

from src.storage.pg_store import PgStore
from src.embedder.embedder import Embedder
from src.engine.query_analyzer import analyze_query, QueryAnalysis
from src.engine.llm_client import CancelledError

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_categories() -> list[dict]:
    """categories.json 로드."""
    cat_file = PROJECT_ROOT / "categories.json"
    if not cat_file.exists():
        return []
    with open(cat_file, "r", encoding="utf-8") as f:
        return json.load(f).get("categories", [])


def _find_matching_category_ids(question: str, categories: list[dict]) -> list[str]:
    """질문에서 카테고리명과 매칭되는 카테고리 ID 찾기 (하위 포함)."""
    matched_ids = []

    def _walk(nodes):
        for node in nodes:
            name = node.get("name", "")
            cat_id = node.get("id", "")
            # 카테고리명이 질문에 포함되어 있으면 매칭
            if name and len(name) >= 2 and name in question:
                # 해당 카테고리 + 하위 카테고리 ID 모두 수집
                _collect_ids(node, matched_ids)
            elif "children" in node:
                _walk(node["children"])

    def _collect_ids(node, ids):
        ids.append(node["id"])
        for child in node.get("children", []):
            _collect_ids(child, ids)

    _walk(categories)
    return matched_ids


def search(
    question: str,
    store: PgStore,
    embedder: Embedder,
    top_k: int = 10,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """하이브리드 검색: 카테고리 + 키워드 + 벡터 → DR 후보 합치기 → 전체 섹션 조회."""

    # 1) 질문 분석
    analysis = analyze_query(question, store)

    if cancel_check and cancel_check():
        raise CancelledError("사용자가 요청을 취소했습니다.")

    # ── 하이브리드 검색: 3가지 소스에서 DR 후보 수집 ──
    dr_scores: dict[str, float] = {}  # DR → 최고 점수
    dr_source: dict[str, list[str]] = {}  # DR → 검색 소스 (디버깅용)

    def _add_dr(dr: str, score: float, source: str):
        if not dr:
            return
        if dr not in dr_scores or score > dr_scores[dr]:
            dr_scores[dr] = score
        if dr not in dr_source:
            dr_source[dr] = []
        if source not in dr_source[dr]:
            dr_source[dr].append(source)

    # ── A) 카테고리 매칭 ──
    categories = _load_categories()
    matched_cat_ids = _find_matching_category_ids(question, categories)
    cat_drs = []
    if matched_cat_ids:
        for cat_id in matched_cat_ids:
            docs = store.get_documents_by_category(cat_id)
            for doc in docs:
                dr = doc.get("dr_number", "")
                _add_dr(dr, 1.0, "category")
                cat_drs.append(dr)
        print(f"  카테고리 매칭: {matched_cat_ids} → {len(set(cat_drs))}개 DR")

    # ── B) 키워드 검색 (제목) ──
    # 질문에서 핵심 키워드 추출 (DR번호 제외, 2글자 이상)
    q_clean = re.sub(r'DR-\d{4}-\d{4,6}', '', question)
    q_clean = re.sub(r'[SR과제찾아줘있어알려줘개발관련목록내용뭐야어떻게]', '', q_clean)
    keywords = [w for w in q_clean.split() if len(w) >= 2]
    kw_drs = []
    for kw in keywords:
        docs = store.find_documents_by_title(kw)
        for doc in docs:
            dr = doc.get("dr_number", "")
            _add_dr(dr, 0.9, "keyword")
            kw_drs.append(dr)
    if kw_drs:
        print(f"  키워드 검색: {keywords} → {len(set(kw_drs))}개 DR")

    # ── C) 벡터 검색 ──
    query_embedding = embedder.embed_query(question)

    if cancel_check and cancel_check():
        raise CancelledError("사용자가 요청을 취소했습니다.")

    where_filter = None
    if analysis.dr_numbers:
        if len(analysis.dr_numbers) == 1:
            where_filter = {"dr_number": analysis.dr_numbers[0]}
        else:
            where_filter = {"dr_number": {"$in": analysis.dr_numbers}}

    vector_results = store.vector_search(
        query_embedding=query_embedding,
        top_k=top_k,
        where=where_filter,
    )

    # 같은 DR+heading_path 중복 제거 (최신 년월만 유지)
    dedup_key_map: dict[str, dict] = {}
    for vr in vector_results:
        meta = vr.get("metadata", {})
        dr = meta.get("dr_number", "")
        hp = meta.get("heading_path", "")
        ym = meta.get("target_year_month", "")
        key = f"{dr}::{hp}"
        if key not in dedup_key_map or ym > dedup_key_map[key]["ym"]:
            dedup_key_map[key] = {"vr": vr, "ym": ym}

    for v in dedup_key_map.values():
        vr = v["vr"]
        dr = vr.get("metadata", {}).get("dr_number", "")
        score = vr.get("score", 0)
        _add_dr(dr, score, "vector")

    # ── DR 순위 결정 ──
    # 카테고리/키워드에서 나온 DR은 우선순위 부스트
    for dr in dr_scores:
        sources = dr_source.get(dr, [])
        boost = 0
        if "category" in sources:
            boost += 0.1
        if "keyword" in sources:
            boost += 0.05
        dr_scores[dr] = min(1.0, dr_scores[dr] + boost)

    sorted_drs = sorted(dr_scores.items(), key=lambda x: x[1], reverse=True)[:5]

    # ── 터미널 로그 ──
    print(f"\n{'='*60}")
    print(f"  하이브리드 검색: 카테고리 {len(set(cat_drs))}건 + 키워드 {len(set(kw_drs))}건 + 벡터 {len(dedup_key_map)}건")
    print(f"  통합 DR 후보: {len(dr_scores)}개 → 상위 {len(sorted_drs)}개 선정")

    # 4) 해당 DR의 전체 섹션 조회
    results = []
    matched_drs = []
    for dr_number, best_score in sorted_drs:
        sections = store.get_sections_by_dr(dr_number)
        if not sections:
            continue

        doc = store.get_document(dr_number)
        title = doc.get("title", "") if doc else ""
        sources_str = ",".join(dr_source.get(dr_number, []))

        matched_drs.append({
            "dr_number": dr_number,
            "title": title,
            "best_score": round(best_score, 3),
            "section_count": len(sections),
        })
        print(f"  {len(matched_drs)}. [{dr_number}] {title}  |  점수: {round(best_score, 3)}  |  소스: {sources_str}  |  섹션: {len(sections)}개")

        for sec in sections:
            results.append({
                "section": sec,
                "score": best_score,
            })

    print(f"  총 {len(results)}개 섹션 → LLM 전달")
    print(f"{'='*60}\n")

    return {
        "analysis": analysis,
        "matched_drs": matched_drs,
        "results": results,
    }

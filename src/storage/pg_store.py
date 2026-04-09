"""PgStore — PostgreSQL + pgvector 통합 저장소.

documents, sections(+embedding), feedback을 하나의 PostgreSQL DB에서 관리.
v2의 NoSQLStore + VectorStore를 통합 대체.
"""
from __future__ import annotations
import json
from typing import Any

import psycopg2
import psycopg2.extras
from psycopg2.pool import SimpleConnectionPool


class PgStore:
    """PostgreSQL + pgvector 통합 저장소."""

    def __init__(self, dsn: str, min_conn: int = 1, max_conn: int = 5):
        self.pool = SimpleConnectionPool(min_conn, max_conn, dsn)

    def _conn(self):
        return self.pool.getconn()

    def _put(self, conn):
        self.pool.putconn(conn)

    # ── Documents ──────────────────────────────────────────────

    def upsert_document(self, meta: dict[str, Any]) -> None:
        """문서 메타 UPSERT (DR번호 + 대상년월 복합키)."""
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                known_keys = {"dr_number", "title", "system", "target_year_month",
                              "doc_version", "file_name", "document_summary"}
                extra = {k: v for k, v in meta.items() if k not in known_keys}

                cur.execute("""
                    INSERT INTO documents (dr_number, target_year_month, title, system,
                                          doc_version, file_name, document_summary, meta, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (dr_number, target_year_month) DO UPDATE SET
                        title = EXCLUDED.title,
                        system = EXCLUDED.system,
                        doc_version = EXCLUDED.doc_version,
                        file_name = EXCLUDED.file_name,
                        document_summary = EXCLUDED.document_summary,
                        meta = EXCLUDED.meta,
                        updated_at = now()
                """, (
                    meta.get("dr_number", ""),
                    meta.get("target_year_month", ""),
                    meta.get("title", ""),
                    meta.get("system", ""),
                    meta.get("doc_version", ""),
                    meta.get("file_name", ""),
                    meta.get("document_summary", ""),
                    json.dumps(extra, ensure_ascii=False),
                ))
            conn.commit()
        finally:
            self._put(conn)

    def get_document(self, dr_number: str, target_year_month: str = None) -> dict[str, Any] | None:
        """문서 조회. target_year_month 없으면 해당 DR의 최신(가장 큰 년월) 반환."""
        conn = self._conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if target_year_month:
                    cur.execute("SELECT * FROM documents WHERE dr_number = %s AND target_year_month = %s",
                                (dr_number, target_year_month))
                else:
                    cur.execute("SELECT * FROM documents WHERE dr_number = %s ORDER BY target_year_month DESC LIMIT 1",
                                (dr_number,))
                row = cur.fetchone()
                return self._doc_row_to_dict(row) if row else None
        finally:
            self._put(conn)

    def get_document_versions(self, dr_number: str) -> list[dict[str, Any]]:
        """특정 DR의 모든 버전(년월) 조회."""
        conn = self._conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM documents WHERE dr_number = %s ORDER BY target_year_month DESC",
                            (dr_number,))
                return [self._doc_row_to_dict(r) for r in cur.fetchall()]
        finally:
            self._put(conn)

    def get_all_documents(self) -> list[dict[str, Any]]:
        """DR당 최신 버전만 반환 + version_count 포함."""
        conn = self._conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT d.*, cnt.version_count
                    FROM documents d
                    JOIN (
                        SELECT dr_number, MAX(target_year_month) AS max_ym, COUNT(*) AS version_count
                        FROM documents GROUP BY dr_number
                    ) cnt ON d.dr_number = cnt.dr_number AND d.target_year_month = cnt.max_ym
                    ORDER BY d.created_at DESC
                """)
                results = []
                for r in cur.fetchall():
                    vc = r.pop("version_count", 1)
                    doc = self._doc_row_to_dict(r)
                    doc["version_count"] = vc
                    results.append(doc)
                return results
        finally:
            self._put(conn)

    def find_documents_by_title(self, keyword: str) -> list[dict[str, Any]]:
        """DR당 최신 버전만 검색 + version_count 포함."""
        conn = self._conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT d.*, cnt.version_count
                    FROM documents d
                    JOIN (
                        SELECT dr_number, MAX(target_year_month) AS max_ym, COUNT(*) AS version_count
                        FROM documents GROUP BY dr_number
                    ) cnt ON d.dr_number = cnt.dr_number AND d.target_year_month = cnt.max_ym
                    WHERE d.title ILIKE %s
                    ORDER BY d.created_at DESC
                """, (f"%{keyword}%",))
                results = []
                for r in cur.fetchall():
                    vc = r.pop("version_count", 1)
                    doc = self._doc_row_to_dict(r)
                    doc["version_count"] = vc
                    results.append(doc)
                return results
        finally:
            self._put(conn)

    def find_sections_by_keyword(self, keyword: str) -> list[dict[str, Any]]:
        """섹션 summary/content에서 키워드 검색 → 해당 DR 목록 반환."""
        conn = self._conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT DISTINCT s.dr_number, d.title, d.target_year_month
                    FROM sections s
                    JOIN documents d ON d.dr_number = s.dr_number AND d.target_year_month = s.target_year_month
                    WHERE s.summary ILIKE %s OR s.content ILIKE %s
                    ORDER BY s.dr_number
                """, (f"%{keyword}%", f"%{keyword}%"))
                return [dict(r) for r in cur.fetchall()]
        finally:
            self._put(conn)

    def delete_document(self, dr_number: str, target_year_month: str = None) -> int:
        """문서 삭제 (CASCADE로 sections도 자동 삭제).
        target_year_month 지정 시 해당 버전만, 없으면 해당 DR 전체 삭제."""
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                if target_year_month:
                    cur.execute("DELETE FROM documents WHERE dr_number = %s AND target_year_month = %s",
                                (dr_number, target_year_month))
                else:
                    cur.execute("DELETE FROM documents WHERE dr_number = %s", (dr_number,))
                count = cur.rowcount
            conn.commit()
            return count
        finally:
            self._put(conn)

    @staticmethod
    def _doc_row_to_dict(row: dict) -> dict[str, Any]:
        """DB row → dict 변환. meta JSONB를 최상위로 병합."""
        d = dict(row)
        # timestamp → 제거 (프론트에서 불필요)
        d.pop("created_at", None)
        d.pop("updated_at", None)
        # meta JSONB 병합
        extra = d.pop("meta", {})
        if isinstance(extra, str):
            extra = json.loads(extra)
        d.update(extra)
        return d

    # ── Sections ───────────────────────────────────────────────

    def upsert_section(self, section: dict[str, Any], embedding: list[float] | None = None) -> None:
        """섹션 UPSERT. embedding이 있으면 벡터도 같이 저장."""
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                emb_val = None
                if embedding:
                    emb_val = _vec_literal(embedding)

                cur.execute("""
                    INSERT INTO sections (section_id, dr_number, target_year_month, part, title, heading_number,
                                         heading_path, section_type, content, summary, detail,
                                         mentioned_tables, mentioned_sources, embedding, updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                    ON CONFLICT (section_id) DO UPDATE SET
                        dr_number = EXCLUDED.dr_number,
                        target_year_month = EXCLUDED.target_year_month,
                        part = EXCLUDED.part,
                        title = EXCLUDED.title,
                        heading_number = EXCLUDED.heading_number,
                        heading_path = EXCLUDED.heading_path,
                        section_type = EXCLUDED.section_type,
                        content = EXCLUDED.content,
                        summary = EXCLUDED.summary,
                        detail = EXCLUDED.detail,
                        mentioned_tables = EXCLUDED.mentioned_tables,
                        mentioned_sources = EXCLUDED.mentioned_sources,
                        embedding = EXCLUDED.embedding,
                        updated_at = now()
                """, (
                    section.get("section_id", ""),
                    section.get("dr_number", ""),
                    section.get("target_year_month", ""),
                    section.get("part", ""),
                    section.get("title", ""),
                    section.get("heading_number", ""),
                    section.get("heading_path", ""),
                    section.get("section_type", ""),
                    section.get("content", ""),
                    section.get("summary", ""),
                    section.get("detail", ""),
                    json.dumps(section.get("mentioned_tables", []), ensure_ascii=False),
                    json.dumps(section.get("mentioned_sources", []), ensure_ascii=False),
                    emb_val,
                ))
            conn.commit()
        finally:
            self._put(conn)

    def get_section(self, section_id: str) -> dict[str, Any] | None:
        conn = self._conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT section_id, dr_number, title, heading_number, heading_path,
                           section_type, content, summary, detail,
                           mentioned_tables, mentioned_sources
                    FROM sections WHERE section_id = %s
                """, (section_id,))
                row = cur.fetchone()
                return self._sec_row_to_dict(row) if row else None
        finally:
            self._put(conn)

    def get_sections_by_dr(self, dr_number: str) -> list[dict[str, Any]]:
        conn = self._conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT section_id, dr_number, title, heading_number, heading_path,
                           section_type, content, summary, detail,
                           mentioned_tables, mentioned_sources
                    FROM sections WHERE dr_number = %s
                    ORDER BY heading_number
                """, (dr_number,))
                return [self._sec_row_to_dict(r) for r in cur.fetchall()]
        finally:
            self._put(conn)

    def get_sections_by_ids(self, section_ids: list[str]) -> list[dict[str, Any]]:
        conn = self._conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT section_id, dr_number, title, heading_number, heading_path,
                           section_type, content, summary, detail,
                           mentioned_tables, mentioned_sources
                    FROM sections WHERE section_id = ANY(%s)
                """, (section_ids,))
                return [self._sec_row_to_dict(r) for r in cur.fetchall()]
        finally:
            self._put(conn)

    def delete_sections_by_dr(self, dr_number: str) -> int:
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM sections WHERE dr_number = %s", (dr_number,))
                count = cur.rowcount
            conn.commit()
            return count
        finally:
            self._put(conn)

    @staticmethod
    def _sec_row_to_dict(row: dict) -> dict[str, Any]:
        d = dict(row)
        # JSONB → list
        for key in ("mentioned_tables", "mentioned_sources"):
            val = d.get(key)
            if isinstance(val, str):
                d[key] = json.loads(val)
        return d

    # ── Vector Search ──────────────────────────────────────────

    def upsert_vectors(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        """벡터 임베딩 일괄 UPSERT (sections 테이블의 embedding 컬럼 업데이트)."""
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                for sid, emb, doc, meta in zip(ids, embeddings, documents, metadatas):
                    cur.execute("""
                        UPDATE sections
                        SET embedding = %s, summary = COALESCE(NULLIF(summary, ''), %s), updated_at = now()
                        WHERE section_id = %s
                    """, (_vec_literal(emb), doc, sid))
            conn.commit()
        finally:
            self._put(conn)

    def vector_search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        where: dict | None = None,
    ) -> list[dict[str, Any]]:
        """벡터 유사도 검색 (cosine distance). v2 VectorStore.search() 호환."""
        conn = self._conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                vec_str = _vec_literal(query_embedding)

                # WHERE 절 구성
                conditions = ["embedding IS NOT NULL"]
                params: list[Any] = []

                if where:
                    if "dr_number" in where:
                        val = where["dr_number"]
                        if isinstance(val, dict) and "$in" in val:
                            conditions.append("dr_number = ANY(%s)")
                            params.append(val["$in"])
                        else:
                            conditions.append("dr_number = %s")
                            params.append(val)

                where_clause = " AND ".join(conditions)
                params.append(top_k)

                cur.execute(f"""
                    SELECT section_id, dr_number, target_year_month, part, title, heading_number, heading_path,
                           section_type, summary,
                           1 - (embedding <=> '{vec_str}'::vector) AS score
                    FROM sections
                    WHERE {where_clause}
                    ORDER BY embedding <=> '{vec_str}'::vector
                    LIMIT %s
                """, params)

                results = []
                for row in cur.fetchall():
                    results.append({
                        "section_id": row["section_id"],
                        "document": row["summary"] or "",
                        "metadata": {
                            "dr_number": row["dr_number"],
                            "target_year_month": row["target_year_month"],
                            "part": row.get("part", ""),
                            "title": row["title"],
                            "heading_number": row["heading_number"],
                            "heading_path": row["heading_path"],
                            "section_type": row["section_type"],
                        },
                        "distance": 1 - float(row["score"]),
                        "score": float(row["score"]),
                    })
                return results
        finally:
            self._put(conn)

    def delete_vectors_by_dr(self, dr_number: str) -> None:
        """DR번호의 벡터만 NULL로 (섹션은 유지). delete_sections_by_dr과 별도."""
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE sections SET embedding = NULL WHERE dr_number = %s", (dr_number,))
            conn.commit()
        finally:
            self._put(conn)

    def delete_vector_by_id(self, section_id: str) -> None:
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE sections SET embedding = NULL WHERE section_id = %s", (section_id,))
            conn.commit()
        finally:
            self._put(conn)

    def vector_count(self) -> int:
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM sections WHERE embedding IS NOT NULL")
                return cur.fetchone()[0]
        finally:
            self._put(conn)

    # ── Feedback ───────────────────────────────────────────────

    def save_feedback(self, feedback: dict[str, Any]) -> None:
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO feedback (feedback_id, question, rating, reason,
                                         reason_detail, correct_answer, sources_used)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    feedback.get("feedback_id", ""),
                    feedback.get("question", ""),
                    feedback.get("rating", ""),
                    feedback.get("reason", ""),
                    feedback.get("reason_detail", ""),
                    feedback.get("correct_answer", ""),
                    json.dumps(feedback.get("sources_used", []), ensure_ascii=False),
                ))
            conn.commit()
        finally:
            self._put(conn)

    def get_feedbacks_by_section(self, section_id: str) -> list[dict[str, Any]]:
        conn = self._conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM feedback
                    WHERE sources_used @> %s::jsonb
                """, (json.dumps([{"section_id": section_id}]),))
                return [dict(r) for r in cur.fetchall()]
        finally:
            self._put(conn)

    def get_negative_feedbacks(self) -> list[dict[str, Any]]:
        conn = self._conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM feedback WHERE rating = 'negative'")
                return [dict(r) for r in cur.fetchall()]
        finally:
            self._put(conn)

    # ── Stats ──────────────────────────────────────────────────

    def stats(self) -> dict[str, int]:
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM documents")
                docs = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM sections")
                secs = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM feedback")
                fbs = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM sections WHERE embedding IS NOT NULL")
                vecs = cur.fetchone()[0]
            return {"documents": docs, "sections": secs, "feedbacks": fbs, "vectors": vecs}
        finally:
            self._put(conn)

    # ── Document Categories (문서-카테고리 태깅) ─────────────────

    def upsert_document_categories(self, dr_number: str, category_ids: list[str], tagged_by: str = "llm", target_year_month: str = "") -> None:
        """문서-카테고리 태깅 저장. 같은 DR의 모든 버전 태깅 삭제 후 재삽입."""
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM document_categories WHERE dr_number = %s",
                            (dr_number,))
                for cat_id in category_ids:
                    cur.execute("""
                        INSERT INTO document_categories (dr_number, target_year_month, category_id, tagged_by)
                        VALUES (%s, %s, %s, %s)
                    """, (dr_number, target_year_month, cat_id, tagged_by))
            conn.commit()
        finally:
            self._put(conn)

    def get_categories_by_dr(self, dr_number: str) -> list[dict[str, Any]]:
        conn = self._conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM document_categories WHERE dr_number = %s", (dr_number,))
                return [dict(r) for r in cur.fetchall()]
        finally:
            self._put(conn)

    def get_documents_by_category(self, category_id: str) -> list[dict[str, Any]]:
        """특정 카테고리에 태깅된 문서 목록 (prefix 매칭으로 하위 포함, DR당 최신 버전만)."""
        conn = self._conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT DISTINCT ON (d.dr_number)
                           d.dr_number, d.title, d.system, d.target_year_month,
                           d.doc_version, d.file_name, dc.category_id, dc.tagged_by
                    FROM document_categories dc
                    JOIN documents d ON d.dr_number = dc.dr_number
                         AND d.target_year_month = dc.target_year_month
                    WHERE dc.category_id = %s OR dc.category_id LIKE %s
                    ORDER BY d.dr_number, d.target_year_month DESC
                """, (category_id, category_id + '.%'))
                return [dict(r) for r in cur.fetchall()]
        finally:
            self._put(conn)

    def get_all_document_categories(self) -> list[dict[str, Any]]:
        """모든 문서-카테고리 관계 (그래프 시각화용, DR당 최신 버전만)."""
        conn = self._conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT DISTINCT ON (dc.dr_number, dc.category_id)
                           dc.dr_number, dc.category_id, dc.tagged_by,
                           d.title, d.system
                    FROM document_categories dc
                    JOIN documents d ON d.dr_number = dc.dr_number
                         AND d.target_year_month = dc.target_year_month
                    ORDER BY dc.dr_number, dc.category_id, d.target_year_month DESC
                """)
                return [dict(r) for r in cur.fetchall()]
        finally:
            self._put(conn)
    def get_category_doc_counts(self) -> dict[str, int]:
        """카테고리별 태깅된 DR 수 반환 (버전 중복 제외). {'1.1.1': 3, '2.1': 5, ...}"""
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT category_id, count(DISTINCT dr_number) FROM document_categories GROUP BY category_id")
                return {row[0]: row[1] for row in cur.fetchall()}
        finally:
            self._put(conn)

    # ── Cleanup ────────────────────────────────────────────────

    def close(self):
        self.pool.closeall()


def _vec_literal(embedding: list[float]) -> str:
    """list[float] → pgvector 리터럴 문자열 '[0.1,0.2,...]'."""
    return "[" + ",".join(str(x) for x in embedding) + "]"

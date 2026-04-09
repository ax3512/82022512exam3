-- IA Chatbot V3 — PostgreSQL + pgvector 초기화
-- 실행: psql -U postgres -h 127.0.0.1 -p <PORT> -f init_db.sql

-- 1) DB 생성
SELECT 'CREATE DATABASE ia_chatbot'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'ia_chatbot')\gexec

\c ia_chatbot

-- 2) pgvector 확장
CREATE EXTENSION IF NOT EXISTS vector;

-- 3) documents 테이블 (복합 PK: dr_number + target_year_month)
CREATE TABLE IF NOT EXISTS documents (
    dr_number       TEXT NOT NULL,
    target_year_month TEXT NOT NULL DEFAULT '',
    title           TEXT DEFAULT '',
    system          TEXT DEFAULT '',
    doc_version     TEXT DEFAULT '',
    file_name       TEXT DEFAULT '',
    document_summary TEXT DEFAULT '',
    meta            JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMP DEFAULT now(),
    updated_at      TIMESTAMP DEFAULT now(),
    PRIMARY KEY (dr_number, target_year_month)
);

-- 4) sections 테이블 (content + summary + embedding 통합)
CREATE TABLE IF NOT EXISTS sections (
    section_id      TEXT PRIMARY KEY,
    dr_number       TEXT NOT NULL,
    target_year_month TEXT NOT NULL DEFAULT '',
    part            TEXT DEFAULT '',
    title           TEXT DEFAULT '',
    heading_number  TEXT DEFAULT '',
    heading_path    TEXT DEFAULT '',
    section_type    TEXT DEFAULT '',
    content         TEXT DEFAULT '',
    summary         TEXT DEFAULT '',
    detail          TEXT DEFAULT '',
    mentioned_tables  JSONB DEFAULT '[]'::jsonb,
    mentioned_sources JSONB DEFAULT '[]'::jsonb,
    embedding       vector(1024),
    created_at      TIMESTAMP DEFAULT now(),
    updated_at      TIMESTAMP DEFAULT now(),
    FOREIGN KEY (dr_number, target_year_month) REFERENCES documents(dr_number, target_year_month) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sections_dr ON sections(dr_number);
CREATE INDEX IF NOT EXISTS idx_sections_dr_ym ON sections(dr_number, target_year_month);

-- HNSW 벡터 인덱스 (데이터 없어도 생성 가능, IVFFlat과 달리 사전 학습 불필요)
CREATE INDEX IF NOT EXISTS idx_sections_embedding ON sections
    USING hnsw (embedding vector_cosine_ops);

-- 5) feedback 테이블
CREATE TABLE IF NOT EXISTS feedback (
    feedback_id     TEXT PRIMARY KEY,
    question        TEXT DEFAULT '',
    rating          TEXT DEFAULT '',
    reason          TEXT DEFAULT '',
    reason_detail   TEXT DEFAULT '',
    correct_answer  TEXT DEFAULT '',
    sources_used    JSONB DEFAULT '[]'::jsonb,
    created_at      TIMESTAMP DEFAULT now()
);

-- 6) document_categories 테이블 (문서-카테고리 태깅)
CREATE TABLE IF NOT EXISTS document_categories (
    dr_number       TEXT NOT NULL,
    target_year_month TEXT NOT NULL DEFAULT '',
    category_id     TEXT NOT NULL,
    tagged_by       TEXT DEFAULT 'llm',
    created_at      TIMESTAMP DEFAULT now(),
    PRIMARY KEY (dr_number, target_year_month, category_id),
    FOREIGN KEY (dr_number, target_year_month) REFERENCES documents(dr_number, target_year_month) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_doc_categories_cat ON document_categories(category_id);

-- 완료
SELECT 'DB 초기화 완료' AS status;
SELECT 'documents' AS table_name, count(*) AS rows FROM documents
UNION ALL
SELECT 'sections', count(*) FROM sections
UNION ALL
SELECT 'feedback', count(*) FROM feedback
UNION ALL
SELECT 'document_categories', count(*) FROM document_categories;

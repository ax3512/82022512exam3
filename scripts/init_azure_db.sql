CREATE SCHEMA IF NOT EXISTS ia_chatbot;
SET search_path TO ia_chatbot;

-- 기존 테이블 삭제 (순서 중요: FK 의존성)
DROP TABLE IF EXISTS ia_chatbot.document_categories CASCADE;
DROP TABLE IF EXISTS ia_chatbot.feedback CASCADE;
DROP TABLE IF EXISTS ia_chatbot.sections CASCADE;
DROP TABLE IF EXISTS ia_chatbot.documents CASCADE;

-- 1) documents 테이블 (복합 PK: dr_number + target_year_month)
CREATE TABLE ia_chatbot.documents (
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

-- 2) sections 테이블
CREATE TABLE ia_chatbot.sections (
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
    FOREIGN KEY (dr_number, target_year_month) REFERENCES ia_chatbot.documents(dr_number, target_year_month) ON DELETE CASCADE
);

CREATE INDEX idx_sections_dr ON ia_chatbot.sections(dr_number);
CREATE INDEX idx_sections_dr_ym ON ia_chatbot.sections(dr_number, target_year_month);
CREATE INDEX idx_sections_embedding ON ia_chatbot.sections USING hnsw (embedding vector_cosine_ops);

-- 3) feedback 테이블
CREATE TABLE ia_chatbot.feedback (
    feedback_id     TEXT PRIMARY KEY,
    question        TEXT DEFAULT '',
    rating          TEXT DEFAULT '',
    reason          TEXT DEFAULT '',
    reason_detail   TEXT DEFAULT '',
    correct_answer  TEXT DEFAULT '',
    sources_used    JSONB DEFAULT '[]'::jsonb,
    created_at      TIMESTAMP DEFAULT now()
);

-- 4) document_categories 테이블
CREATE TABLE ia_chatbot.document_categories (
    dr_number       TEXT NOT NULL,
    target_year_month TEXT NOT NULL DEFAULT '',
    category_id     TEXT NOT NULL,
    tagged_by       TEXT DEFAULT 'llm',
    created_at      TIMESTAMP DEFAULT now(),
    PRIMARY KEY (dr_number, target_year_month, category_id),
    FOREIGN KEY (dr_number, target_year_month) REFERENCES ia_chatbot.documents(dr_number, target_year_month) ON DELETE CASCADE
);

CREATE INDEX idx_doc_categories_cat ON ia_chatbot.document_categories(category_id);

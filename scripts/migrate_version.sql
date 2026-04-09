-- 버전 관리 마이그레이션: dr_number 단일 PK → (dr_number, target_year_month) 복합 PK
-- ※ 기존 데이터 보존. 실행 전 백업 권장.

-- 1) 기존 FK 제거
ALTER TABLE sections DROP CONSTRAINT IF EXISTS sections_dr_number_fkey;
ALTER TABLE document_categories DROP CONSTRAINT IF EXISTS document_categories_dr_number_fkey;

-- 2) documents PK 변경
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_pkey;
ALTER TABLE documents ADD PRIMARY KEY (dr_number, target_year_month);

-- 3) sections에 target_year_month 컬럼 추가 + 기존 데이터 채우기
ALTER TABLE sections ADD COLUMN IF NOT EXISTS target_year_month TEXT DEFAULT '';
UPDATE sections s SET target_year_month = d.target_year_month
FROM documents d WHERE s.dr_number = d.dr_number AND s.target_year_month = '';

-- 4) sections FK 재설정 (복합키)
ALTER TABLE sections ADD CONSTRAINT sections_doc_fk
    FOREIGN KEY (dr_number, target_year_month) REFERENCES documents(dr_number, target_year_month) ON DELETE CASCADE;

-- 5) document_categories에 target_year_month 컬럼 추가 + 기존 데이터 채우기
ALTER TABLE document_categories ADD COLUMN IF NOT EXISTS target_year_month TEXT DEFAULT '';
UPDATE document_categories dc SET target_year_month = d.target_year_month
FROM documents d WHERE dc.dr_number = d.dr_number AND dc.target_year_month = '';

-- 6) document_categories PK/FK 변경
ALTER TABLE document_categories DROP CONSTRAINT IF EXISTS document_categories_pkey;
ALTER TABLE document_categories ADD PRIMARY KEY (dr_number, target_year_month, category_id);
ALTER TABLE document_categories ADD CONSTRAINT doc_categories_doc_fk
    FOREIGN KEY (dr_number, target_year_month) REFERENCES documents(dr_number, target_year_month) ON DELETE CASCADE;

-- 7) 인덱스
CREATE INDEX IF NOT EXISTS idx_sections_dr_ym ON sections(dr_number, target_year_month);

-- 완료 확인
SELECT 'Migration complete' AS status;
SELECT dr_number, target_year_month, title FROM documents ORDER BY dr_number, target_year_month;

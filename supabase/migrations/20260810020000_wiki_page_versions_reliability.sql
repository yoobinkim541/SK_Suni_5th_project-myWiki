-- 위키 페이지 신뢰도 자율 판정 + 발행 게이트: wiki_page_versions에 판정 결과 컬럼 추가.
-- "낮음"으로 판정된 페이지는 create_wiki_version() 자체가 호출되지 않으므로, 저장되는
-- page_reliability_level 값은 실질적으로 '보통'/'높음'/NULL 중 하나만 나온다.
ALTER TABLE wiki_page_versions ADD COLUMN page_reliability_score INTEGER
  CHECK (page_reliability_score IS NULL OR (page_reliability_score >= 0 AND page_reliability_score <= 100));
ALTER TABLE wiki_page_versions ADD COLUMN page_reliability_level VARCHAR
  CHECK (page_reliability_level IS NULL OR page_reliability_level IN ('낮음', '보통', '높음'));
ALTER TABLE wiki_page_versions ADD COLUMN page_reliability_detail JSONB;

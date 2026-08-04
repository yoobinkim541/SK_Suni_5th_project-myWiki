-- wiki_pages.page_type을 리포트 6종 카테고리에 맞춰 8종으로 확장한다.
-- 기존: industry, company, technology, issue, term
-- 추가: supply_chain(공급망·생산), policy(정책·규제), market(시장·경영)
--
-- 배경: wiki-refresh-gate가 "시장·경영" 카테고리 이슈를 topic 페이지로 만들려 할 때
-- 대응하는 page_type이 없어서 LLM이 스키마에 없는 값을 지어내 검증에 계속 실패했다.

ALTER TABLE wiki_pages DROP CONSTRAINT ck_wp_page_type;

ALTER TABLE wiki_pages ADD CONSTRAINT ck_wp_page_type
  CHECK (page_type IN (
    'industry', 'company', 'technology',
    'supply_chain', 'policy', 'market',
    'issue', 'term'
  ));

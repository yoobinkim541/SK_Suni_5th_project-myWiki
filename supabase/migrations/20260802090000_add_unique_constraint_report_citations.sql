-- report_citations에 unique 제약이 없어 앱 레벨 dedup에만 의존하고 있었다.
-- save_report_citations()가 (section_id, document_version_id, citation_order)로
-- dedup/재저장을 하도록 고쳐졌으므로, DB에도 동일한 제약을 걸어 방어한다.

ALTER TABLE report_citations
DROP CONSTRAINT IF EXISTS uq_report_citations_section_doc_order;

ALTER TABLE report_citations
ADD CONSTRAINT uq_report_citations_section_doc_order
UNIQUE (section_id, document_version_id, citation_order);

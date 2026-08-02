-- document_analysis_results / report_wiki_references RLS
-- 기존 정책 패턴을 그대로 따른다: 워크스페이스 멤버는 SELECT만, 쓰기는 service_role 백엔드가 담당.
-- (RLS를 켜면 정책이 없는 동작은 전부 거부되므로 INSERT/UPDATE/DELETE 정책은 의도적으로 만들지 않는다.)

ALTER TABLE public.document_analysis_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.report_wiki_references    ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS document_analysis_results_select ON public.document_analysis_results;
CREATE POLICY document_analysis_results_select ON public.document_analysis_results FOR SELECT
  USING (is_workspace_member(workspace_id));

DROP POLICY IF EXISTS report_wiki_references_select ON public.report_wiki_references;
CREATE POLICY report_wiki_references_select ON public.report_wiki_references FOR SELECT
  USING (EXISTS (
    SELECT 1 FROM report_sections rs JOIN reports r ON r.id = rs.report_id
    WHERE rs.id = report_wiki_references.section_id AND is_workspace_member(r.workspace_id)
  ));

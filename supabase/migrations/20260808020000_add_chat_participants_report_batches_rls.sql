-- chat_session_participants / daily_report_analysis_batches: RLS는 켜져 있었으나
-- (ENABLE ROW LEVEL SECURITY만 적용되고) SELECT 정책이 하나도 없어 서비스 롤을
-- 거치지 않는 접근은 전부 거부되던 상태였다. 나머지 신규 테이블(document_analysis_results,
-- workspace_settings, push_subscriptions, wiki_page_keywords, report_wiki_references)과
-- 같은 workspace_id 기준 패턴으로 맞춘다.

CREATE POLICY daily_report_analysis_batches_select ON public.daily_report_analysis_batches
FOR SELECT
USING (is_workspace_member(workspace_id));

CREATE POLICY chat_session_participants_select ON public.chat_session_participants
FOR SELECT
USING (EXISTS (
  SELECT 1 FROM public.chat_sessions cs
  WHERE cs.id = chat_session_participants.session_id AND is_workspace_member(cs.workspace_id)
));

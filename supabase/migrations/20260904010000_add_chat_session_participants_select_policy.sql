-- Allow workspace members to read participants for sessions in their workspace.
-- The API uses the service role, while browser-side access remains scoped by RLS.
DROP POLICY IF EXISTS chat_session_participants_select ON public.chat_session_participants;

CREATE POLICY chat_session_participants_select
ON public.chat_session_participants
FOR SELECT
USING (EXISTS (
  SELECT 1
  FROM public.chat_sessions cs
  WHERE cs.id = chat_session_participants.session_id
    AND is_workspace_member(cs.workspace_id)
));

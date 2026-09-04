-- chat_session_participants is exposed through the public Data API. Enable RLS
-- so its workspace-membership policy (added in the following migration) is enforced.
-- Backend queries use the service role and are unaffected by this change.
ALTER TABLE public.chat_session_participants ENABLE ROW LEVEL SECURITY;

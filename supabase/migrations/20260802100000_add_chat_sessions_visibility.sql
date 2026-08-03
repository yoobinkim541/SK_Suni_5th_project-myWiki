ALTER TABLE public.chat_sessions
ADD COLUMN IF NOT EXISTS visibility VARCHAR(10) NOT NULL DEFAULT 'private';

ALTER TABLE public.chat_sessions
DROP CONSTRAINT IF EXISTS chat_sessions_visibility_check;

ALTER TABLE public.chat_sessions
ADD CONSTRAINT chat_sessions_visibility_check
CHECK (visibility IN ('private', 'team'));

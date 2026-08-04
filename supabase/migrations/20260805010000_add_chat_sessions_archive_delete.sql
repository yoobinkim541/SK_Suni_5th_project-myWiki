ALTER TABLE public.chat_sessions
ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;

ALTER TABLE public.chat_sessions
ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

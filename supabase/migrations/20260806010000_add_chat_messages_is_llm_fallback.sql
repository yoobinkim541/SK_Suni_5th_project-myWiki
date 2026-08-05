ALTER TABLE public.chat_messages
ADD COLUMN IF NOT EXISTS is_llm_fallback BOOLEAN NOT NULL DEFAULT false;

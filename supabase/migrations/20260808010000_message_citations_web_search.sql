ALTER TABLE public.message_citations ALTER COLUMN document_version_id DROP NOT NULL;

ALTER TABLE public.message_citations ADD COLUMN IF NOT EXISTS source_url TEXT;
ALTER TABLE public.message_citations ADD COLUMN IF NOT EXISTS source_title TEXT;
ALTER TABLE public.message_citations ADD COLUMN IF NOT EXISTS published_at TEXT;

ALTER TABLE public.message_citations
ADD CONSTRAINT ck_mc_has_identifier CHECK (document_version_id IS NOT NULL OR source_url IS NOT NULL);

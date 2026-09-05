-- The application records the reliability judgment for generated wiki pages.
-- Older production snapshots did not include these columns, so keep the
-- migration idempotent when repairing an already partially-upgraded database.
ALTER TABLE public.wiki_page_versions
  ADD COLUMN IF NOT EXISTS page_reliability_score INTEGER
    CHECK (page_reliability_score IS NULL OR (page_reliability_score >= 0 AND page_reliability_score <= 100));

ALTER TABLE public.wiki_page_versions
  ADD COLUMN IF NOT EXISTS page_reliability_level VARCHAR
    CHECK (page_reliability_level IS NULL OR page_reliability_level IN ('낮음', '보통', '높음'));

ALTER TABLE public.wiki_page_versions
  ADD COLUMN IF NOT EXISTS page_reliability_detail JSONB;

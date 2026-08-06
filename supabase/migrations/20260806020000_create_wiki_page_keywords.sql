CREATE TABLE IF NOT EXISTS public.wiki_page_keywords (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  page_id uuid NOT NULL REFERENCES public.wiki_pages(id) ON DELETE CASCADE,
  keyword varchar(50) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (page_id, keyword)
);

CREATE INDEX IF NOT EXISTS idx_wiki_page_keywords_keyword ON public.wiki_page_keywords(keyword);

ALTER TABLE public.wiki_page_keywords ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS wiki_page_keywords_select ON public.wiki_page_keywords;

CREATE POLICY wiki_page_keywords_select ON public.wiki_page_keywords
FOR SELECT
USING (EXISTS (
  SELECT 1 FROM public.wiki_pages p
  WHERE p.id = wiki_page_keywords.page_id AND is_workspace_member(p.workspace_id)
));

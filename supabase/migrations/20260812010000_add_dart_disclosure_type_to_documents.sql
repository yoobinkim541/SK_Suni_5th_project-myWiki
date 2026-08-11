ALTER TABLE public.documents
ADD COLUMN IF NOT EXISTS disclosure_type_code varchar(1);

ALTER TABLE public.documents
ADD COLUMN IF NOT EXISTS disclosure_type_name text;

CREATE INDEX IF NOT EXISTS idx_documents_disclosure_type
ON public.documents(workspace_id, disclosure_type_code)
WHERE disclosure_type_code IS NOT NULL;

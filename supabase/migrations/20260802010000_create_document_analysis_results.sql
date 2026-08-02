CREATE TABLE IF NOT EXISTS public.document_analysis_results (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL,
    document_version_id uuid NOT NULL,
    primary_category character varying,
    secondary_categories text[] NOT NULL DEFAULT '{}'::text[],
    classification_confidence numeric,
    classification_reason text,
    status character varying NOT NULL DEFAULT 'completed',
    error_message text,
    model_name character varying NOT NULL,
    prompt_version character varying NOT NULL,
    classified_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),

    CONSTRAINT document_analysis_results_pkey PRIMARY KEY (id),
    CONSTRAINT fk_dar_workspace FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE,
    CONSTRAINT fk_dar_document_version FOREIGN KEY (document_version_id) REFERENCES public.document_versions(id) ON DELETE CASCADE,
    CONSTRAINT document_analysis_results_status_check CHECK (
        status::text = ANY (
            ARRAY[
                'pending'::character varying,
                'completed'::character varying,
                'failed'::character varying
            ]::text[]
        )
    ),
    CONSTRAINT document_analysis_results_primary_category_check CHECK (
        primary_category IS NULL
        OR primary_category::text = ANY (
            ARRAY[
                '제품·기술'::character varying,
                '경쟁사'::character varying,
                '고객·수요산업'::character varying,
                '공급망·생산'::character varying,
                '정책·규제'::character varying,
                '시장·경영'::character varying
            ]::text[]
        )
    ),
    CONSTRAINT document_analysis_results_secondary_categories_check CHECK (
        secondary_categories <@ ARRAY[
            '제품·기술',
            '경쟁사',
            '고객·수요산업',
            '공급망·생산',
            '정책·규제',
            '시장·경영'
        ]::text[]
    ),
    CONSTRAINT document_analysis_results_secondary_count_check CHECK (cardinality(secondary_categories) <= 2),
    CONSTRAINT document_analysis_results_primary_secondary_check CHECK (
        primary_category IS NULL OR NOT primary_category = ANY(secondary_categories)
    ),
    CONSTRAINT document_analysis_results_confidence_check CHECK (
        classification_confidence IS NULL OR (classification_confidence >= 0 AND classification_confidence <= 1)
    ),
    CONSTRAINT document_analysis_results_completed_check CHECK (
        (
            status = 'completed'
            AND primary_category IS NOT NULL
            AND classification_confidence IS NOT NULL
            AND classification_reason IS NOT NULL
            AND classified_at IS NOT NULL
        )
        OR (
            status = 'failed'
            AND error_message IS NOT NULL
        )
        OR status = 'pending'
    ),
    CONSTRAINT document_analysis_results_unique_run UNIQUE (
        workspace_id,
        document_version_id,
        model_name,
        prompt_version
    )
);

CREATE INDEX IF NOT EXISTS idx_document_analysis_results_workspace
ON public.document_analysis_results(workspace_id);

CREATE INDEX IF NOT EXISTS idx_document_analysis_results_document_version
ON public.document_analysis_results(document_version_id);

CREATE INDEX IF NOT EXISTS idx_document_analysis_results_category
ON public.document_analysis_results(primary_category);

CREATE INDEX IF NOT EXISTS idx_document_analysis_results_completed
ON public.document_analysis_results(workspace_id, status, classified_at DESC)
WHERE status = 'completed';

DROP TRIGGER IF EXISTS trg_document_analysis_results_updated_at ON public.document_analysis_results;
CREATE TRIGGER trg_document_analysis_results_updated_at
BEFORE UPDATE ON public.document_analysis_results
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- RLS는 20260802070000_enable_rls_analysis_report_tables.sql 에서 적용한다.

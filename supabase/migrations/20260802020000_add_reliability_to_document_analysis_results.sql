ALTER TABLE public.document_analysis_results
ADD COLUMN IF NOT EXISTS reliability_status character varying NOT NULL DEFAULT 'pending',
ADD COLUMN IF NOT EXISTS reliability_score integer,
ADD COLUMN IF NOT EXISTS reliability_level character varying,
ADD COLUMN IF NOT EXISTS traceability_score smallint,
ADD COLUMN IF NOT EXISTS source_authority_score smallint,
ADD COLUMN IF NOT EXISTS current_validity_score smallint,
ADD COLUMN IF NOT EXISTS independent_evidence_score smallint,
ADD COLUMN IF NOT EXISTS factual_consistency_score smallint,
ADD COLUMN IF NOT EXISTS reliability_summary_reason text,
ADD COLUMN IF NOT EXISTS reliability_detail jsonb NOT NULL DEFAULT '{}'::jsonb,
ADD COLUMN IF NOT EXISTS reliability_model_name character varying,
ADD COLUMN IF NOT EXISTS reliability_prompt_version character varying,
ADD COLUMN IF NOT EXISTS reliability_evaluated_at timestamp with time zone,
ADD COLUMN IF NOT EXISTS reliability_error_message text;


DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_reliability_status_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_reliability_status_check
        CHECK (
            reliability_status::text = ANY (
                ARRAY['pending'::character varying, 'completed'::character varying, 'failed'::character varying]::text[]
            )
        );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_reliability_score_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_reliability_score_check
        CHECK (
            reliability_score IS NULL OR (reliability_score >= 0 AND reliability_score <= 100)
        );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_reliability_level_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_reliability_level_check
        CHECK (
            reliability_level IS NULL
            OR reliability_level::text = ANY (
                ARRAY['낮음'::character varying, '보통'::character varying, '높음'::character varying]::text[]
            )
        );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_traceability_score_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_traceability_score_check
        CHECK (traceability_score IS NULL OR traceability_score BETWEEN 0 AND 20);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_source_authority_score_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_source_authority_score_check
        CHECK (source_authority_score IS NULL OR source_authority_score BETWEEN 0 AND 20);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_current_validity_score_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_current_validity_score_check
        CHECK (current_validity_score IS NULL OR current_validity_score BETWEEN 0 AND 20);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_independent_evidence_score_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_independent_evidence_score_check
        CHECK (independent_evidence_score IS NULL OR independent_evidence_score BETWEEN 0 AND 20);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_factual_consistency_score_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_factual_consistency_score_check
        CHECK (factual_consistency_score IS NULL OR factual_consistency_score BETWEEN 0 AND 20);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_reliability_sum_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_reliability_sum_check
        CHECK (
            reliability_status <> 'completed'
            OR reliability_score = (
                traceability_score
                + source_authority_score
                + current_validity_score
                + independent_evidence_score
                + factual_consistency_score
            )
        );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_reliability_level_score_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_reliability_level_score_check
        CHECK (
            reliability_score IS NULL
            OR reliability_level IS NULL
            OR (reliability_score BETWEEN 0 AND 39 AND reliability_level = '낮음')
            OR (reliability_score BETWEEN 40 AND 69 AND reliability_level = '보통')
            OR (reliability_score BETWEEN 70 AND 100 AND reliability_level = '높음')
        );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_reliability_completed_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_reliability_completed_check
        CHECK (
            (
                reliability_status = 'completed'
                AND reliability_score IS NOT NULL
                AND reliability_level IS NOT NULL
                AND traceability_score IS NOT NULL
                AND source_authority_score IS NOT NULL
                AND current_validity_score IS NOT NULL
                AND independent_evidence_score IS NOT NULL
                AND factual_consistency_score IS NOT NULL
                AND reliability_summary_reason IS NOT NULL
                AND length(trim(reliability_summary_reason)) > 0
                AND reliability_model_name IS NOT NULL
                AND reliability_prompt_version IS NOT NULL
                AND reliability_evaluated_at IS NOT NULL
                AND reliability_error_message IS NULL
            )
            OR (
                reliability_status = 'failed'
                AND reliability_error_message IS NOT NULL
                AND length(trim(reliability_error_message)) > 0
            )
            OR reliability_status = 'pending'
        );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_reliability_detail_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_reliability_detail_check
        CHECK (jsonb_typeof(reliability_detail) = 'object');
    END IF;
END $$;

-- RLS는 기존 workspace 기반 정책 확인 후 별도 적용 권장

CREATE INDEX IF NOT EXISTS idx_document_analysis_results_reliability_status
ON public.document_analysis_results(
    workspace_id,
    reliability_status
);

CREATE INDEX IF NOT EXISTS idx_document_analysis_results_reliability_score
ON public.document_analysis_results(
    workspace_id,
    reliability_score DESC
)
WHERE reliability_status = 'completed';

CREATE INDEX IF NOT EXISTS idx_document_analysis_results_reliability_level
ON public.document_analysis_results(
    workspace_id,
    reliability_level
)
WHERE reliability_status = 'completed';

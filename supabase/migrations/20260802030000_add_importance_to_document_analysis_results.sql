ALTER TABLE public.document_analysis_results
ADD COLUMN IF NOT EXISTS importance_status character varying NOT NULL DEFAULT 'pending',
ADD COLUMN IF NOT EXISTS importance_score integer,
ADD COLUMN IF NOT EXISTS importance_level character varying,
ADD COLUMN IF NOT EXISTS direct_relevance_score smallint,
ADD COLUMN IF NOT EXISTS business_impact_score smallint,
ADD COLUMN IF NOT EXISTS urgency_score smallint,
ADD COLUMN IF NOT EXISTS industry_impact_score smallint,
ADD COLUMN IF NOT EXISTS duration_score smallint,
ADD COLUMN IF NOT EXISTS external_attention_score smallint,
ADD COLUMN IF NOT EXISTS impact_direction character varying,
ADD COLUMN IF NOT EXISTS time_horizon character varying,
ADD COLUMN IF NOT EXISTS importance_summary_reason text,
ADD COLUMN IF NOT EXISTS core_summary text,
ADD COLUMN IF NOT EXISTS key_points text[] NOT NULL DEFAULT '{}'::text[],
ADD COLUMN IF NOT EXISTS key_numbers jsonb NOT NULL DEFAULT '[]'::jsonb,
ADD COLUMN IF NOT EXISTS sk_hynix_implication text,
ADD COLUMN IF NOT EXISTS summary_evidence_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
ADD COLUMN IF NOT EXISTS affected_areas text[] NOT NULL DEFAULT '{}'::text[],
ADD COLUMN IF NOT EXISTS opportunities text[] NOT NULL DEFAULT '{}'::text[],
ADD COLUMN IF NOT EXISTS risks text[] NOT NULL DEFAULT '{}'::text[],
ADD COLUMN IF NOT EXISTS watch_points text[] NOT NULL DEFAULT '{}'::text[],
ADD COLUMN IF NOT EXISTS importance_missing_information text[] NOT NULL DEFAULT '{}'::text[],
ADD COLUMN IF NOT EXISTS importance_detail jsonb NOT NULL DEFAULT '{}'::jsonb,
ADD COLUMN IF NOT EXISTS importance_model_name character varying,
ADD COLUMN IF NOT EXISTS importance_prompt_version character varying,
ADD COLUMN IF NOT EXISTS importance_evaluated_at timestamp with time zone,
ADD COLUMN IF NOT EXISTS importance_error_message text;


DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_importance_status_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_importance_status_check
        CHECK (importance_status IN ('pending', 'completed', 'failed'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_importance_score_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_importance_score_check
        CHECK (importance_score IS NULL OR importance_score BETWEEN 0 AND 100);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_importance_level_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_importance_level_check
        CHECK (importance_level IS NULL OR importance_level IN ('낮음', '보통', '높음'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_direct_relevance_score_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_direct_relevance_score_check
        CHECK (direct_relevance_score IS NULL OR direct_relevance_score BETWEEN 0 AND 25);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_business_impact_score_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_business_impact_score_check
        CHECK (business_impact_score IS NULL OR business_impact_score BETWEEN 0 AND 25);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_urgency_score_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_urgency_score_check
        CHECK (urgency_score IS NULL OR urgency_score BETWEEN 0 AND 15);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_industry_impact_score_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_industry_impact_score_check
        CHECK (industry_impact_score IS NULL OR industry_impact_score BETWEEN 0 AND 15);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_duration_score_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_duration_score_check
        CHECK (duration_score IS NULL OR duration_score BETWEEN 0 AND 10);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_external_attention_score_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_external_attention_score_check
        CHECK (external_attention_score IS NULL OR external_attention_score BETWEEN 0 AND 10);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_impact_direction_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_impact_direction_check
        CHECK (impact_direction IS NULL OR impact_direction IN ('기회', '위험', '혼합', '중립'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_time_horizon_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_time_horizon_check
        CHECK (time_horizon IS NULL OR time_horizon IN ('즉시', '단기', '중기', '장기'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_key_points_limit_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_key_points_limit_check
        CHECK (cardinality(key_points) <= 5);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_key_numbers_array_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_key_numbers_array_check
        CHECK (jsonb_typeof(key_numbers) = 'array');
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_summary_evidence_refs_array_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_summary_evidence_refs_array_check
        CHECK (jsonb_typeof(summary_evidence_refs) = 'array');
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_importance_detail_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_importance_detail_check
        CHECK (jsonb_typeof(importance_detail) = 'object');
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_importance_sum_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_importance_sum_check
        CHECK (
            importance_status <> 'completed'
            OR importance_score = (
                direct_relevance_score
                + business_impact_score
                + urgency_score
                + industry_impact_score
                + duration_score
                + external_attention_score
            )
        );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_importance_level_score_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_importance_level_score_check
        CHECK (
            importance_score IS NULL
            OR importance_level IS NULL
            OR (importance_score BETWEEN 0 AND 39 AND importance_level = '낮음')
            OR (importance_score BETWEEN 40 AND 69 AND importance_level = '보통')
            OR (importance_score BETWEEN 70 AND 100 AND importance_level = '높음')
        );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_importance_completed_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_importance_completed_check
        CHECK (
            (
                importance_status = 'completed'
                AND importance_score IS NOT NULL
                AND importance_level IS NOT NULL
                AND direct_relevance_score IS NOT NULL
                AND business_impact_score IS NOT NULL
                AND urgency_score IS NOT NULL
                AND industry_impact_score IS NOT NULL
                AND duration_score IS NOT NULL
                AND external_attention_score IS NOT NULL
                AND impact_direction IS NOT NULL
                AND time_horizon IS NOT NULL
                AND importance_summary_reason IS NOT NULL
                AND length(trim(importance_summary_reason)) > 0
                AND importance_model_name IS NOT NULL
                AND importance_prompt_version IS NOT NULL
                AND importance_evaluated_at IS NOT NULL
                AND importance_error_message IS NULL
            )
            OR (
                importance_status = 'failed'
                AND importance_error_message IS NOT NULL
                AND length(trim(importance_error_message)) > 0
            )
            OR importance_status = 'pending'
        );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_importance_v2_summary_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_importance_v2_summary_check
        CHECK (
            importance_status <> 'completed'
            OR importance_prompt_version <> 'importance-v2'
            OR (
                core_summary IS NOT NULL
                AND length(trim(core_summary)) > 0
                AND cardinality(key_points) BETWEEN 3 AND 5
                AND sk_hynix_implication IS NOT NULL
                AND length(trim(sk_hynix_implication)) > 0
                AND jsonb_array_length(summary_evidence_refs) >= 1
            )
        );
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_document_analysis_results_importance_status
ON public.document_analysis_results(
    workspace_id,
    importance_status
);

CREATE INDEX IF NOT EXISTS idx_document_analysis_results_importance_score
ON public.document_analysis_results(
    workspace_id,
    importance_score DESC
)
WHERE importance_status = 'completed';

CREATE INDEX IF NOT EXISTS idx_document_analysis_results_importance_level
ON public.document_analysis_results(
    workspace_id,
    importance_level
)
WHERE importance_status = 'completed';

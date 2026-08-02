CREATE INDEX IF NOT EXISTS idx_document_analysis_results_ranking_status
ON public.document_analysis_results(
    workspace_id,
    ranking_status
);

CREATE INDEX IF NOT EXISTS idx_document_analysis_results_ranking_position
ON public.document_analysis_results(
    workspace_id,
    ranking_batch_date,
    ranking_position
)
WHERE ranking_status = 'completed';

CREATE INDEX IF NOT EXISTS idx_document_analysis_results_report_selection
ON public.document_analysis_results(
    workspace_id,
    ranking_batch_date,
    report_selection_position
)
WHERE selected_for_report = true;

CREATE INDEX IF NOT EXISTS idx_document_analysis_results_ranking_score
ON public.document_analysis_results(
    workspace_id,
    ranking_score DESC
)
WHERE ranking_status = 'completed';

ALTER TABLE public.document_analysis_results
ADD COLUMN IF NOT EXISTS ranking_status character varying NOT NULL DEFAULT 'pending',
ADD COLUMN IF NOT EXISTS ranking_score numeric(5, 2),
ADD COLUMN IF NOT EXISTS recency_score smallint,
ADD COLUMN IF NOT EXISTS ranking_position integer,
ADD COLUMN IF NOT EXISTS selected_for_report boolean NOT NULL DEFAULT false,
ADD COLUMN IF NOT EXISTS report_selection_position integer,
ADD COLUMN IF NOT EXISTS selection_reason character varying,
ADD COLUMN IF NOT EXISTS ranking_exclusion_reason character varying,
ADD COLUMN IF NOT EXISTS ranking_formula_version character varying,
ADD COLUMN IF NOT EXISTS ranking_reference_time timestamp with time zone,
ADD COLUMN IF NOT EXISTS ranking_batch_date date,
ADD COLUMN IF NOT EXISTS ranked_at timestamp with time zone,
ADD COLUMN IF NOT EXISTS ranking_detail jsonb NOT NULL DEFAULT '{}'::jsonb,
ADD COLUMN IF NOT EXISTS ranking_error_message text;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_ranking_status_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_ranking_status_check
        CHECK (ranking_status IN ('pending', 'completed', 'excluded', 'failed'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_ranking_score_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_ranking_score_check
        CHECK (ranking_score IS NULL OR ranking_score BETWEEN 0 AND 100);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_recency_score_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_recency_score_check
        CHECK (recency_score IS NULL OR recency_score BETWEEN 0 AND 100);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_ranking_position_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_ranking_position_check
        CHECK (ranking_position IS NULL OR ranking_position >= 1);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_report_selection_position_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_report_selection_position_check
        CHECK (report_selection_position IS NULL OR report_selection_position >= 1);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_ranking_exclusion_reason_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_ranking_exclusion_reason_check
        CHECK (
            ranking_exclusion_reason IS NULL
            OR ranking_exclusion_reason IN ('LOW_RELIABILITY', 'CATEGORY_LIMIT', 'OUTSIDE_REPORT_LIMIT')
        );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_selection_reason_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_selection_reason_check
        CHECK (
            selection_reason IS NULL
            OR selection_reason IN ('SELECTED', 'LOW_RELIABILITY', 'CATEGORY_LIMIT', 'OUTSIDE_REPORT_LIMIT')
        );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_ranking_detail_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_ranking_detail_check
        CHECK (jsonb_typeof(ranking_detail) = 'object');
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_report_selection_state_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_report_selection_state_check
        CHECK (
            (
                selected_for_report = true
                AND ranking_status = 'completed'
                AND report_selection_position IS NOT NULL
                AND selection_reason = 'SELECTED'
            )
            OR (
                selected_for_report = false
                AND report_selection_position IS NULL
            )
        );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_ranking_completed_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_ranking_completed_check
        CHECK (
            ranking_status <> 'completed'
            OR (
                ranking_score IS NOT NULL
                AND recency_score IS NOT NULL
                AND ranking_position IS NOT NULL
                AND ranking_formula_version IS NOT NULL
                AND ranking_reference_time IS NOT NULL
                AND ranking_batch_date IS NOT NULL
                AND ranked_at IS NOT NULL
                AND ranking_error_message IS NULL
            )
        );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'document_analysis_results_ranking_excluded_check'
    ) THEN
        ALTER TABLE public.document_analysis_results
        ADD CONSTRAINT document_analysis_results_ranking_excluded_check
        CHECK (
            ranking_status <> 'excluded'
            OR (
                ranking_score IS NOT NULL
                AND recency_score IS NOT NULL
                AND ranking_position IS NULL
                AND ranking_exclusion_reason IS NOT NULL
                AND ranked_at IS NOT NULL
            )
        );
    END IF;
END $$;

-- myWiki incremental migration
-- 2026-08-02
-- ??:
--   1) document_analysis_results ? importance ??? ??
--   2) document_analysis_results RLS ??
--   3) report artifact ?? Storage bucket(reports) ??

BEGIN;

ALTER TABLE IF EXISTS public.document_analysis_results
    ADD COLUMN IF NOT EXISTS importance_status VARCHAR(30) NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS importance_score INTEGER,
    ADD COLUMN IF NOT EXISTS importance_level VARCHAR(20),
    ADD COLUMN IF NOT EXISTS direct_relevance_score INTEGER,
    ADD COLUMN IF NOT EXISTS business_impact_score INTEGER,
    ADD COLUMN IF NOT EXISTS urgency_score INTEGER,
    ADD COLUMN IF NOT EXISTS industry_impact_score INTEGER,
    ADD COLUMN IF NOT EXISTS duration_score INTEGER,
    ADD COLUMN IF NOT EXISTS external_attention_score INTEGER,
    ADD COLUMN IF NOT EXISTS impact_direction VARCHAR(20),
    ADD COLUMN IF NOT EXISTS time_horizon VARCHAR(20),
    ADD COLUMN IF NOT EXISTS importance_summary_reason TEXT,
    ADD COLUMN IF NOT EXISTS core_summary TEXT,
    ADD COLUMN IF NOT EXISTS key_points JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS key_numbers JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS sk_hynix_implication TEXT,
    ADD COLUMN IF NOT EXISTS summary_evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS affected_areas JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS opportunities JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS risks JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS watch_points JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS importance_missing_information JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS importance_detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS importance_model_name VARCHAR(100),
    ADD COLUMN IF NOT EXISTS importance_prompt_version VARCHAR(50),
    ADD COLUMN IF NOT EXISTS importance_evaluated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS importance_error_message TEXT;

ALTER TABLE IF EXISTS public.document_analysis_results ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS document_analysis_results_select ON public.document_analysis_results;
CREATE POLICY document_analysis_results_select ON public.document_analysis_results FOR SELECT
  USING (is_workspace_member(workspace_id));

INSERT INTO storage.buckets (id, name, public)
VALUES ('reports', 'reports', false)
ON CONFLICT (id) DO NOTHING;

COMMIT;

-- ============================================================
-- Supabase SQL Editor용 (PostgreSQL 문법, backtick 사용 안 함)
-- 실행 순서: 1) CREATE TABLE -> 2) PK -> 3) FK -> 4) UNIQUE -> 5) CHECK
--          -> 6) RLS 정책 -> 7) 트리거/함수 -> 8) Storage 버킷
-- 전체를 그대로 New Query에 붙여넣고 Run 하면 됩니다.
--
-- [중요] 이 파일은 라이브 Supabase 프로젝트(uhzjshqmnlahhvqzygkp)의
-- 실제 스키마를 information_schema / pg_catalog에서 직접 조회하여
-- 그대로 재구성한 파일입니다. (2026-08-07 기준 정본)
--
-- [2026-08-07 동기화 관련 메모]
--   - CREATE TABLE / PK / FK / UNIQUE / CHECK 섹션은 2026-08-07에 팀이 제공한
--     "-- WARNING: This schema is for context only..." 라이브 덤프를 그대로
--     반영했다(실행용이 아니라 문맥 참고용 덤프였지만, information_schema 기준
--     CREATE TABLE 형태라 구조 동기화에는 신뢰 가능한 소스로 판단했다).
--   - 그 덤프에는 RLS 정책 / 트리거 / 함수 / Storage 버킷 정의가 없다. 이 파일의
--     해당 섹션은 2026-07-29 시점 내용을 그대로 유지한다. 신규 테이블
--     (document_analysis_results, workspace_settings, push_subscriptions,
--     chat_session_participants, daily_report_analysis_batches,
--     wiki_page_keywords, report_wiki_references)의 RLS 정책은 2026-08-08
--     라이브 DB 직접 조회로 전부 확인·반영했다 — "6-A" 참고. 그중
--     chat_session_participants / daily_report_analysis_batches는 정책이
--     아예 없어(전체 차단 상태) 그 자리에서 새로 추가했다(마이그레이션
--     20260808020000).
--   - VARCHAR 길이: 덤프가 대부분 길이 없는 `character varying`으로 나와서,
--     실제 컬럼에 길이 제한이 없는 것으로 보고 길이를 붙이지 않았다. 예전
--     버전의 VARCHAR(n) 값은 검증되지 않은 추정치였을 수 있다.
--   - CHECK 제약 이름(ck_*, fk_*, uq_*)은 덤프에 실제 이름이 없는 테이블은
--     이 파일의 기존 네이밍 관례를 따라 새로 지었다 — 라이브 DB의 실제
--     제약 이름과 문자 그대로 일치한다는 보장은 없다(SELECT/INSERT 동작은
--     길이/CHECK 값 자체로 결정되므로 무방하지만, `DROP CONSTRAINT` 등을
--     이름으로 실행할 땐 실제 DB에서 이름을 먼저 확인할 것).
-- ============================================================

-- ============================================================
-- myWiki 스키마 v2 (멘토링 피드백 반영본)
-- 변경 이력:
--   1) workspaces / workspace_members 추가 + RLS로 데이터 격리
--   2) reports를 재생성 시마다 새 row(버전)를 쌓는 구조로 변경
--   3) artifacts 테이블 신설 + 리포트 산출물(md/pdf/pptx/docx)을 버전별로 관리
--   4) 문자열 필드 UNIQUE 제약 추가
--   5) 각 상태 필드 CHECK 제약 추가
--   6) object_key 버킷 정책 및 경로 규칙은 UNIQUE 제약 + 코드 레벨 가이드로 관리
--   7) [7/27 멘토링 반영] profiles.role 제거 (역할은 workspace_members.role 로 일원화)
--   8) profiles -> auth.users FK 추가 (auth.users(id) ON DELETE CASCADE)
--   9) documents/wiki_page_versions/reports/artifacts/pipeline_jobs 의
--      "행위자(actor)" 컬럼(uploaded_by/created_by/reviewed_by/requested_by)에
--      profiles(id) FK 추가 (ON DELETE SET NULL)
--  10) workspaces.slug UNIQUE 제약 추가
--  11) workspace_members.role / wiki_page_versions.generated_by CHECK 제약 추가
--  12) RLS 정책 전체 적용 (workspace_members 기반 데이터 격리)
--  13) 회원가입 시 profiles 자동 생성 트리거 적용
--  14) updated_at 자동 갱신 트리거 적용
--  15) Storage 버킷(raw/processed/wiki) 생성
--  16) [7/29] id/created_at/updated_at 등 컬럼 DEFAULT 전체 추가
--      (gen_random_uuid()/now()/'{}'::jsonb/true/0) - profiles.id 제외
--  17) [7/29] workspace_members.role CHECK 버그 수정 (owner 누락 -> 추가)
--  18) [7/29] chat_messages.role / sources.source_type /
--      wiki_pages.page_type / wiki_pages.review_policy CHECK 제약 신규 추가
--  19) [8/07] 회원 탈퇴(소프트 삭제): workspaces.deleted_at / profiles.deleted_at /
--      chat_sessions.deleted_at·archived_at 추가
--  20) [8/07] chat_messages.is_llm_fallback 추가(위키 근거 없이 LLM 일반 지식으로
--      답했는지 구분 — 프론트가 별도 배지로 표시)
--  21) [8/07] chat_sessions.visibility(private/team) + chat_session_participants
--      테이블 신설 (팀 공유 대화)
--  22) [8/07] push_subscriptions 테이블 신설 (웹 푸시 알림 구독)
--  23) [8/07] workspace_settings 테이블 신설 (워크스페이스별 수집/위키 갱신 주기,
--      채팅 보존 기간)
--  24) [8/07] document_analysis_results 테이블 신설 (분류/신뢰도/중요도/랭킹
--      파이프라인 결과 — 대형 테이블, CHECK 제약 다수)
--  25) [8/07] reports.report_type/status CHECK 제약 신규(문서 유형·생성 파이프라인
--      단계가 늘어남), report_sections.issue_key 추가, report_wiki_references
--      테이블 신설(리포트 섹션 <-> 위키 페이지 연결)
--  26) [8/07] pipeline_jobs.job_type/target_type CHECK 제약 신규
--      (index_qmd/generate_wiki/generate_report, document_version/wiki_page/report)
--  27) [8/07] daily_report_analysis_batches 테이블 신설 (일일 리포트용 분석
--      배치 — 특정 report_date에 어떤 document_version이 묶였는지 기록)
--  28) [8/07] wiki_page_keywords 테이블 신설 (위키 페이지 키워드 검색/필터)
--  29) [8/10] wiki_page_versions.page_reliability_score/level/detail 추가
--      (야간 배치 위키 페이지 생성 LLM의 자율 신뢰도 판정 + 발행 게이트)
-- ============================================================


-- ------------------------------------------------------------
-- 0. workspace 관련
-- ------------------------------------------------------------

CREATE TABLE workspaces (
    id          UUID          NOT NULL DEFAULT gen_random_uuid(),
    name        VARCHAR       NOT NULL,
    slug        VARCHAR       NOT NULL,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    deleted_at  TIMESTAMPTZ
);

CREATE TABLE workspace_members (
    id           UUID          NOT NULL DEFAULT gen_random_uuid(),
    workspace_id UUID          NOT NULL,
    user_id      UUID          NOT NULL,
    role         VARCHAR       NOT NULL,
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE TABLE workspace_settings (
    workspace_id                UUID          NOT NULL,
    wiki_update_cycle_minutes   INTEGER       NOT NULL DEFAULT 360,
    chat_retention_days         INTEGER,
    last_wiki_refresh_at        TIMESTAMPTZ,
    updated_by                  UUID,
    updated_at                  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    data_refresh_cycle_minutes  INTEGER       NOT NULL DEFAULT 120,
    last_data_refresh_at        TIMESTAMPTZ
);


-- ------------------------------------------------------------
-- 1. profiles (auth.users 확장)
-- ------------------------------------------------------------

CREATE TABLE profiles (
    id            UUID          NOT NULL,  -- DEFAULT 없음: auth.users.id 값을 그대로 사용
    display_name  VARCHAR       NOT NULL,
    department    VARCHAR,
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    deleted_at    TIMESTAMPTZ
);


-- ------------------------------------------------------------
-- 2. sources / documents / document_versions / document_analysis_results
-- ------------------------------------------------------------

CREATE TABLE sources (
    id                 UUID           NOT NULL DEFAULT gen_random_uuid(),
    workspace_id       UUID           NOT NULL,
    name               VARCHAR        NOT NULL,
    source_type        VARCHAR        NOT NULL,
    base_url           TEXT,
    reliability_score  NUMERIC,
    config             JSONB          NOT NULL DEFAULT '{}'::jsonb,
    enabled            BOOLEAN        NOT NULL DEFAULT true,
    created_at         TIMESTAMPTZ    NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ    NOT NULL DEFAULT now()
);

CREATE TABLE documents (
    id             UUID          NOT NULL DEFAULT gen_random_uuid(),
    workspace_id   UUID          NOT NULL,
    source_id      UUID,
    title          VARCHAR       NOT NULL,
    canonical_url  TEXT,
    published_at   TIMESTAMPTZ,
    status         VARCHAR       NOT NULL,
    uploaded_by    UUID,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE TABLE document_versions (
    id                   UUID          NOT NULL DEFAULT gen_random_uuid(),
    document_id          UUID          NOT NULL,
    version_no           INTEGER       NOT NULL,
    content_hash         VARCHAR       NOT NULL,
    raw_object_key       TEXT,
    markdown_object_key  TEXT          NOT NULL,
    parser_version       VARCHAR,
    language             VARCHAR,
    created_at           TIMESTAMPTZ   NOT NULL DEFAULT now()
);

-- 분류(classification) / 신뢰도(reliability) / 중요도(importance) / 랭킹(ranking)
-- 4단계 분석 파이프라인 결과를 document_version 1건당 1행으로 누적한다.
-- 각 단계는 독립적으로 진행되므로 단계별 status/error_message/평가 시각을 따로 둔다.
CREATE TABLE document_analysis_results (
    id                              UUID          NOT NULL DEFAULT gen_random_uuid(),
    workspace_id                    UUID          NOT NULL,
    document_version_id             UUID          NOT NULL,

    -- 분류
    primary_category                VARCHAR,
    secondary_categories            TEXT[]        NOT NULL DEFAULT '{}'::text[],
    classification_confidence       NUMERIC,
    classification_reason           TEXT,
    status                          VARCHAR       NOT NULL DEFAULT 'completed',
    error_message                   TEXT,
    model_name                      VARCHAR       NOT NULL,
    prompt_version                  VARCHAR       NOT NULL,
    classified_at                   TIMESTAMPTZ,
    created_at                      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at                      TIMESTAMPTZ   NOT NULL DEFAULT now(),

    -- 신뢰도(교차검증)
    reliability_status              VARCHAR       NOT NULL DEFAULT 'pending',
    reliability_score               INTEGER,
    reliability_level               VARCHAR,
    traceability_score              SMALLINT,
    source_authority_score          SMALLINT,
    current_validity_score          SMALLINT,
    independent_evidence_score      SMALLINT,
    factual_consistency_score       SMALLINT,
    reliability_summary_reason      TEXT,
    reliability_detail              JSONB         NOT NULL DEFAULT '{}'::jsonb,
    reliability_model_name          VARCHAR,
    reliability_prompt_version      VARCHAR,
    reliability_evaluated_at        TIMESTAMPTZ,
    reliability_error_message       TEXT,

    -- 중요도
    importance_status               VARCHAR       NOT NULL DEFAULT 'pending',
    importance_score                INTEGER,
    importance_level                VARCHAR,
    direct_relevance_score          SMALLINT,
    business_impact_score           SMALLINT,
    urgency_score                   SMALLINT,
    industry_impact_score           SMALLINT,
    duration_score                  SMALLINT,
    external_attention_score        SMALLINT,
    impact_direction                VARCHAR,
    time_horizon                    VARCHAR,
    importance_summary_reason       TEXT,
    core_summary                    TEXT,
    key_points                      TEXT[]        NOT NULL DEFAULT '{}'::text[],
    key_numbers                     JSONB         NOT NULL DEFAULT '[]'::jsonb,
    sk_hynix_implication            TEXT,
    summary_evidence_refs           JSONB         NOT NULL DEFAULT '[]'::jsonb,
    affected_areas                  TEXT[]        NOT NULL DEFAULT '{}'::text[],
    opportunities                   TEXT[]        NOT NULL DEFAULT '{}'::text[],
    risks                           TEXT[]        NOT NULL DEFAULT '{}'::text[],
    watch_points                    TEXT[]        NOT NULL DEFAULT '{}'::text[],
    importance_missing_information  TEXT[]        NOT NULL DEFAULT '{}'::text[],
    importance_detail               JSONB         NOT NULL DEFAULT '{}'::jsonb,
    importance_model_name           VARCHAR,
    importance_prompt_version       VARCHAR,
    importance_evaluated_at         TIMESTAMPTZ,
    importance_error_message        TEXT,

    -- 랭킹 / 리포트·위키 채택 여부
    ranking_status                  VARCHAR       NOT NULL DEFAULT 'pending',
    ranking_score                   NUMERIC,
    recency_score                   SMALLINT,
    ranking_position                INTEGER,
    selected_for_report             BOOLEAN       NOT NULL DEFAULT false,
    report_selection_position       INTEGER,
    selection_reason                VARCHAR,
    ranking_exclusion_reason        VARCHAR,
    ranking_formula_version         VARCHAR,
    ranking_reference_time          TIMESTAMPTZ,
    ranking_batch_date              DATE,
    ranked_at                       TIMESTAMPTZ,
    ranking_detail                  JSONB         NOT NULL DEFAULT '{}'::jsonb,
    ranking_error_message            TEXT
);


-- ------------------------------------------------------------
-- 3. wiki_pages / wiki_page_versions / wiki_page_sources / wiki_page_keywords
-- ------------------------------------------------------------

CREATE TABLE wiki_pages (
    id                  UUID          NOT NULL DEFAULT gen_random_uuid(),
    workspace_id        UUID          NOT NULL,
    parent_page_id      UUID,
    slug                VARCHAR       NOT NULL,
    title               VARCHAR       NOT NULL,
    page_type           VARCHAR       NOT NULL,
    status              VARCHAR       NOT NULL,
    review_policy       VARCHAR       NOT NULL,
    current_version_id  UUID,
    published_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE TABLE wiki_page_versions (
    id                         UUID          NOT NULL DEFAULT gen_random_uuid(),
    page_id                    UUID          NOT NULL,
    version_no                 INTEGER       NOT NULL,
    markdown_object_key        TEXT          NOT NULL,
    content_hash               VARCHAR       NOT NULL,
    change_summary             TEXT,
    created_by                 UUID,
    review_status              VARCHAR       NOT NULL,
    reviewed_by                UUID,
    reviewed_at                TIMESTAMPTZ,
    generated_by               VARCHAR       NOT NULL,
    generator_model            VARCHAR,
    generator_prompt_version   VARCHAR,
    generation_run_id          UUID,
    validation_status          VARCHAR       NOT NULL,
    confidence_score           NUMERIC,
    page_reliability_score      INTEGER,
    page_reliability_level      VARCHAR,
    page_reliability_detail     JSONB,
    created_at                 TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE TABLE wiki_page_sources (
    id                    UUID         NOT NULL DEFAULT gen_random_uuid(),
    wiki_version_id       UUID         NOT NULL,
    document_version_id   UUID         NOT NULL,
    claim_text            TEXT,
    source_start_line     INTEGER,
    source_end_line       INTEGER,
    support_type          VARCHAR,
    citation_order        INTEGER,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- 위키 페이지 본문 키워드(검색/필터용) — 페이지당 여러 행.
CREATE TABLE wiki_page_keywords (
    id          UUID          NOT NULL DEFAULT gen_random_uuid(),
    page_id     UUID          NOT NULL,
    keyword     VARCHAR       NOT NULL,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now()
);


-- ------------------------------------------------------------
-- 4. reports / report_sections / report_citations / report_wiki_references / artifacts
-- ------------------------------------------------------------

CREATE TABLE reports (
    id              UUID          NOT NULL DEFAULT gen_random_uuid(),
    workspace_id    UUID          NOT NULL,
    report_key      VARCHAR       NOT NULL,
    version         INTEGER       NOT NULL,
    requested_by    UUID,
    title           VARCHAR       NOT NULL,
    report_type     VARCHAR       NOT NULL,
    status          VARCHAR       NOT NULL,
    request_config  JSONB         NOT NULL,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

CREATE TABLE report_sections (
    id                  UUID          NOT NULL DEFAULT gen_random_uuid(),
    report_id           UUID          NOT NULL,
    section_order       INTEGER       NOT NULL,
    title               VARCHAR       NOT NULL,
    content             TEXT,
    status              VARCHAR       NOT NULL,
    model_name          VARCHAR,
    prompt_version      VARCHAR,
    generation_run_id   UUID,
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    issue_key           TEXT
);

CREATE TABLE report_citations (
    id                    UUID          NOT NULL DEFAULT gen_random_uuid(),
    section_id            UUID          NOT NULL,
    document_version_id   UUID          NOT NULL,
    source_start_line     INTEGER,
    source_end_line       INTEGER,
    quoted_text           TEXT,
    relevance_score       NUMERIC,
    citation_order        INTEGER,
    created_at            TIMESTAMPTZ   NOT NULL DEFAULT now()
);

-- 리포트 섹션이 근거로 참조한 위키 페이지(원문 document_version 인용과 별개 트랙).
CREATE TABLE report_wiki_references (
    id               UUID          NOT NULL DEFAULT gen_random_uuid(),
    section_id       UUID          NOT NULL,
    wiki_page_id     UUID          NOT NULL,
    wiki_version_id  UUID          NOT NULL,
    reference_order  INTEGER       NOT NULL,
    relevance_score  NUMERIC,
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE TABLE artifacts (
    id             UUID          NOT NULL DEFAULT gen_random_uuid(),
    report_id      UUID          NOT NULL,
    artifact_type  VARCHAR       NOT NULL,
    object_key     TEXT          NOT NULL,
    version        INTEGER       NOT NULL,
    file_size      INTEGER,
    mime_type      VARCHAR,
    created_by     UUID,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT now()
);

-- 일일 리포트 생성에 실제로 묶인 document_version 집합을 기록한다 — 배치가
-- 도는 동안(running) 새로 분석 완료된 문서가 다음 배치로 밀리지 않도록,
-- 이 report_date에 확정된 버전 목록을 완료(completed) 시점에 남긴다.
CREATE TABLE daily_report_analysis_batches (
    id                    UUID          NOT NULL DEFAULT gen_random_uuid(),
    workspace_id          UUID          NOT NULL,
    report_date           DATE          NOT NULL,
    document_version_ids  JSONB         NOT NULL DEFAULT '[]'::jsonb,
    status                TEXT          NOT NULL,
    started_at            TIMESTAMPTZ   NOT NULL,
    completed_at          TIMESTAMPTZ,
    created_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ   NOT NULL DEFAULT now()
);


-- ------------------------------------------------------------
-- 5. chat_sessions / chat_messages / chat_session_participants /
--    message_citations / push_subscriptions
-- ------------------------------------------------------------

CREATE TABLE chat_sessions (
    id            UUID          NOT NULL DEFAULT gen_random_uuid(),
    workspace_id  UUID          NOT NULL,
    user_id       UUID          NOT NULL,
    title         VARCHAR,
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    visibility    VARCHAR       NOT NULL DEFAULT 'private',
    archived_at   TIMESTAMPTZ,
    deleted_at    TIMESTAMPTZ
);

CREATE TABLE chat_messages (
    id                UUID          NOT NULL DEFAULT gen_random_uuid(),
    session_id        UUID          NOT NULL,
    role              VARCHAR       NOT NULL,
    content           TEXT          NOT NULL,
    model_name        VARCHAR,
    prompt_version    VARCHAR,
    created_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),
    user_id           UUID,
    is_llm_fallback   BOOLEAN       NOT NULL DEFAULT false
);

-- 팀 공유(visibility='team') 대화방의 참여자 목록. 세션 생성자는 자동 참여로
-- 간주하고(코드 레벨), 이 테이블엔 그 외 초대된 참여자를 기록한다.
CREATE TABLE chat_session_participants (
    id          UUID          NOT NULL DEFAULT gen_random_uuid(),
    session_id  UUID          NOT NULL,
    user_id     UUID          NOT NULL,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE TABLE message_citations (
    id                    UUID          NOT NULL DEFAULT gen_random_uuid(),
    message_id            UUID          NOT NULL,
    document_version_id   UUID,
    qmd_uri               TEXT,
    source_start_line     INTEGER,
    source_end_line       INTEGER,
    source_url            TEXT,
    source_title          TEXT,
    published_at          TEXT,
    quoted_text           TEXT,
    relevance_score       NUMERIC,
    citation_order        INTEGER,
    created_at            TIMESTAMPTZ   NOT NULL DEFAULT now()
);

-- 웹 푸시 알림 구독 정보(VAPID). 사용자당 여러 브라우저/기기에서 구독 가능.
CREATE TABLE push_subscriptions (
    id            UUID          NOT NULL DEFAULT gen_random_uuid(),
    user_id       UUID          NOT NULL,
    workspace_id  UUID          NOT NULL,
    endpoint      TEXT          NOT NULL,
    p256dh        TEXT          NOT NULL,
    auth          TEXT          NOT NULL,
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT now()
);


-- ------------------------------------------------------------
-- 6. pipeline_jobs / qmd_index_entries
-- ------------------------------------------------------------

CREATE TABLE pipeline_jobs (
    id                UUID           NOT NULL DEFAULT gen_random_uuid(),
    workspace_id      UUID           NOT NULL,
    job_type          VARCHAR        NOT NULL,
    target_type       VARCHAR,
    target_id         UUID,
    status            VARCHAR        NOT NULL,
    progress          INTEGER        NOT NULL DEFAULT 0,
    error_message     TEXT,
    requested_by      UUID,
    payload           JSONB          NOT NULL DEFAULT '{}'::jsonb,
    result            JSONB,
    retry_count       INTEGER        NOT NULL DEFAULT 0,
    idempotency_key   VARCHAR,
    started_at        TIMESTAMPTZ,
    completed_at      TIMESTAMPTZ,
    created_at        TIMESTAMPTZ    NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ    NOT NULL DEFAULT now()
);

CREATE TABLE qmd_index_entries (
    id                    UUID          NOT NULL DEFAULT gen_random_uuid(),
    document_version_id   UUID,
    wiki_version_id       UUID,
    report_id             UUID,
    collection_name       VARCHAR       NOT NULL,
    status                VARCHAR       NOT NULL,
    qmd_uri               TEXT,
    qmd_docid             VARCHAR,
    index_generation      INTEGER       NOT NULL,
    indexed_at            TIMESTAMPTZ,
    last_error            TEXT,
    created_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ   NOT NULL DEFAULT now()
);


-- ============================================================
-- PRIMARY KEYS
-- ============================================================

ALTER TABLE workspaces                     ADD CONSTRAINT pk_workspaces                     PRIMARY KEY (id);
ALTER TABLE workspace_members              ADD CONSTRAINT pk_workspace_members              PRIMARY KEY (id);
ALTER TABLE workspace_settings             ADD CONSTRAINT pk_workspace_settings             PRIMARY KEY (workspace_id);
ALTER TABLE profiles                       ADD CONSTRAINT pk_profiles                       PRIMARY KEY (id);
ALTER TABLE sources                        ADD CONSTRAINT pk_sources                        PRIMARY KEY (id);
ALTER TABLE documents                      ADD CONSTRAINT pk_documents                      PRIMARY KEY (id);
ALTER TABLE document_versions              ADD CONSTRAINT pk_document_versions              PRIMARY KEY (id);
ALTER TABLE document_analysis_results      ADD CONSTRAINT pk_document_analysis_results      PRIMARY KEY (id);
ALTER TABLE wiki_pages                     ADD CONSTRAINT pk_wiki_pages                     PRIMARY KEY (id);
ALTER TABLE wiki_page_versions             ADD CONSTRAINT pk_wiki_page_versions             PRIMARY KEY (id);
ALTER TABLE wiki_page_sources              ADD CONSTRAINT pk_wiki_page_sources              PRIMARY KEY (id);
ALTER TABLE wiki_page_keywords             ADD CONSTRAINT pk_wiki_page_keywords             PRIMARY KEY (id);
ALTER TABLE reports                        ADD CONSTRAINT pk_reports                        PRIMARY KEY (id);
ALTER TABLE report_sections                ADD CONSTRAINT pk_report_sections                PRIMARY KEY (id);
ALTER TABLE report_citations               ADD CONSTRAINT pk_report_citations               PRIMARY KEY (id);
ALTER TABLE report_wiki_references         ADD CONSTRAINT pk_report_wiki_references         PRIMARY KEY (id);
ALTER TABLE artifacts                      ADD CONSTRAINT pk_artifacts                      PRIMARY KEY (id);
ALTER TABLE daily_report_analysis_batches  ADD CONSTRAINT pk_daily_report_analysis_batches  PRIMARY KEY (id);
ALTER TABLE chat_sessions                  ADD CONSTRAINT pk_chat_sessions                  PRIMARY KEY (id);
ALTER TABLE chat_messages                  ADD CONSTRAINT pk_chat_messages                  PRIMARY KEY (id);
ALTER TABLE chat_session_participants      ADD CONSTRAINT pk_chat_session_participants      PRIMARY KEY (id);
ALTER TABLE message_citations              ADD CONSTRAINT pk_message_citations              PRIMARY KEY (id);
ALTER TABLE push_subscriptions             ADD CONSTRAINT pk_push_subscriptions             PRIMARY KEY (id);
ALTER TABLE pipeline_jobs                  ADD CONSTRAINT pk_pipeline_jobs                  PRIMARY KEY (id);
ALTER TABLE qmd_index_entries              ADD CONSTRAINT pk_qmd_index_entries              PRIMARY KEY (id);


-- ============================================================
-- FOREIGN KEYS
-- ============================================================

ALTER TABLE profiles           ADD CONSTRAINT fk_profiles_auth_user   FOREIGN KEY (id) REFERENCES auth.users(id) ON DELETE CASCADE;

ALTER TABLE workspace_members  ADD CONSTRAINT fk_wm_workspace         FOREIGN KEY (workspace_id) REFERENCES workspaces(id);
ALTER TABLE workspace_members  ADD CONSTRAINT fk_wm_user              FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE workspace_settings  ADD CONSTRAINT fk_ws_workspace                FOREIGN KEY (workspace_id) REFERENCES workspaces(id);
ALTER TABLE workspace_settings  ADD CONSTRAINT fk_ws_updated_by               FOREIGN KEY (updated_by) REFERENCES profiles(id) ON DELETE SET NULL;

ALTER TABLE sources             ADD CONSTRAINT fk_sources_workspace           FOREIGN KEY (workspace_id) REFERENCES workspaces(id);

ALTER TABLE documents           ADD CONSTRAINT fk_documents_workspace         FOREIGN KEY (workspace_id) REFERENCES workspaces(id);
ALTER TABLE documents           ADD CONSTRAINT fk_documents_source            FOREIGN KEY (source_id) REFERENCES sources(id);
ALTER TABLE documents           ADD CONSTRAINT fk_documents_uploaded_by       FOREIGN KEY (uploaded_by) REFERENCES profiles(id) ON DELETE SET NULL;

ALTER TABLE document_versions   ADD CONSTRAINT fk_dv_document                 FOREIGN KEY (document_id) REFERENCES documents(id);

ALTER TABLE document_analysis_results ADD CONSTRAINT fk_dar_workspace         FOREIGN KEY (workspace_id) REFERENCES workspaces(id);
ALTER TABLE document_analysis_results ADD CONSTRAINT fk_dar_document_version  FOREIGN KEY (document_version_id) REFERENCES document_versions(id);

ALTER TABLE wiki_pages          ADD CONSTRAINT fk_wiki_pages_workspace        FOREIGN KEY (workspace_id) REFERENCES workspaces(id);
ALTER TABLE wiki_pages          ADD CONSTRAINT fk_wiki_pages_parent           FOREIGN KEY (parent_page_id) REFERENCES wiki_pages(id);
ALTER TABLE wiki_pages          ADD CONSTRAINT fk_wiki_pages_current_version  FOREIGN KEY (current_version_id) REFERENCES wiki_page_versions(id);

ALTER TABLE wiki_page_versions  ADD CONSTRAINT fk_wpv_page                    FOREIGN KEY (page_id) REFERENCES wiki_pages(id);
ALTER TABLE wiki_page_versions  ADD CONSTRAINT fk_wpv_created_by              FOREIGN KEY (created_by) REFERENCES profiles(id) ON DELETE SET NULL;
ALTER TABLE wiki_page_versions  ADD CONSTRAINT fk_wpv_reviewed_by             FOREIGN KEY (reviewed_by) REFERENCES profiles(id) ON DELETE SET NULL;

ALTER TABLE wiki_page_sources   ADD CONSTRAINT fk_wps_wiki_version            FOREIGN KEY (wiki_version_id) REFERENCES wiki_page_versions(id);
ALTER TABLE wiki_page_sources   ADD CONSTRAINT fk_wps_document_version        FOREIGN KEY (document_version_id) REFERENCES document_versions(id);

ALTER TABLE wiki_page_keywords  ADD CONSTRAINT fk_wpk_page                    FOREIGN KEY (page_id) REFERENCES wiki_pages(id);

ALTER TABLE reports              ADD CONSTRAINT fk_reports_workspace          FOREIGN KEY (workspace_id) REFERENCES workspaces(id);
ALTER TABLE reports              ADD CONSTRAINT fk_reports_requested_by       FOREIGN KEY (requested_by) REFERENCES profiles(id) ON DELETE SET NULL;

ALTER TABLE report_sections      ADD CONSTRAINT fk_rs_report                  FOREIGN KEY (report_id) REFERENCES reports(id);

ALTER TABLE report_citations     ADD CONSTRAINT fk_rc_section                 FOREIGN KEY (section_id) REFERENCES report_sections(id);
ALTER TABLE report_citations     ADD CONSTRAINT fk_rc_document_version        FOREIGN KEY (document_version_id) REFERENCES document_versions(id);

ALTER TABLE report_wiki_references ADD CONSTRAINT fk_rwr_section              FOREIGN KEY (section_id) REFERENCES report_sections(id);
ALTER TABLE report_wiki_references ADD CONSTRAINT fk_rwr_wiki_page            FOREIGN KEY (wiki_page_id) REFERENCES wiki_pages(id);
ALTER TABLE report_wiki_references ADD CONSTRAINT fk_rwr_wiki_version         FOREIGN KEY (wiki_version_id) REFERENCES wiki_page_versions(id);

ALTER TABLE artifacts            ADD CONSTRAINT fk_artifacts_report           FOREIGN KEY (report_id) REFERENCES reports(id);
ALTER TABLE artifacts            ADD CONSTRAINT fk_artifacts_created_by       FOREIGN KEY (created_by) REFERENCES profiles(id) ON DELETE SET NULL;

ALTER TABLE daily_report_analysis_batches ADD CONSTRAINT fk_drab_workspace    FOREIGN KEY (workspace_id) REFERENCES workspaces(id);

ALTER TABLE chat_sessions        ADD CONSTRAINT fk_cs_workspace               FOREIGN KEY (workspace_id) REFERENCES workspaces(id);
ALTER TABLE chat_sessions        ADD CONSTRAINT fk_cs_user                    FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE chat_messages        ADD CONSTRAINT fk_cm_session                 FOREIGN KEY (session_id) REFERENCES chat_sessions(id);
ALTER TABLE chat_messages        ADD CONSTRAINT fk_cm_user                    FOREIGN KEY (user_id) REFERENCES profiles(id);

ALTER TABLE chat_session_participants ADD CONSTRAINT fk_csp_session           FOREIGN KEY (session_id) REFERENCES chat_sessions(id);
ALTER TABLE chat_session_participants ADD CONSTRAINT fk_csp_user              FOREIGN KEY (user_id) REFERENCES profiles(id);

ALTER TABLE message_citations    ADD CONSTRAINT fk_mc_message                 FOREIGN KEY (message_id) REFERENCES chat_messages(id);
ALTER TABLE message_citations    ADD CONSTRAINT fk_mc_document_version        FOREIGN KEY (document_version_id) REFERENCES document_versions(id);

ALTER TABLE push_subscriptions   ADD CONSTRAINT fk_ps_user                    FOREIGN KEY (user_id) REFERENCES profiles(id);
ALTER TABLE push_subscriptions   ADD CONSTRAINT fk_ps_workspace               FOREIGN KEY (workspace_id) REFERENCES workspaces(id);

ALTER TABLE pipeline_jobs        ADD CONSTRAINT fk_pj_workspace               FOREIGN KEY (workspace_id) REFERENCES workspaces(id);
ALTER TABLE pipeline_jobs        ADD CONSTRAINT fk_pj_requested_by            FOREIGN KEY (requested_by) REFERENCES profiles(id) ON DELETE SET NULL;

ALTER TABLE qmd_index_entries    ADD CONSTRAINT fk_qmd_document_version       FOREIGN KEY (document_version_id) REFERENCES document_versions(id);
ALTER TABLE qmd_index_entries    ADD CONSTRAINT fk_qmd_wiki_version           FOREIGN KEY (wiki_version_id) REFERENCES wiki_page_versions(id);
ALTER TABLE qmd_index_entries    ADD CONSTRAINT fk_qmd_report                 FOREIGN KEY (report_id) REFERENCES reports(id);


-- ============================================================
-- UNIQUE 제약
-- ============================================================

ALTER TABLE workspaces           ADD CONSTRAINT uq_workspaces_slug           UNIQUE (slug);
ALTER TABLE workspace_members    ADD CONSTRAINT uq_wm_workspace_user         UNIQUE (workspace_id, user_id);
ALTER TABLE sources              ADD CONSTRAINT uq_sources_workspace_name    UNIQUE (workspace_id, name);
ALTER TABLE documents            ADD CONSTRAINT uq_documents_workspace_url   UNIQUE (workspace_id, canonical_url);
ALTER TABLE document_versions    ADD CONSTRAINT uq_dv_document_versionno     UNIQUE (document_id, version_no);
ALTER TABLE document_versions    ADD CONSTRAINT uq_dv_document_hash          UNIQUE (document_id, content_hash);
ALTER TABLE document_versions    ADD CONSTRAINT uq_dv_markdown_object_key    UNIQUE (markdown_object_key);
ALTER TABLE wiki_pages           ADD CONSTRAINT uq_wiki_pages_workspace_slug UNIQUE (workspace_id, slug);
ALTER TABLE wiki_page_versions   ADD CONSTRAINT uq_wpv_page_versionno        UNIQUE (page_id, version_no);
ALTER TABLE wiki_page_versions   ADD CONSTRAINT uq_wpv_markdown_object_key   UNIQUE (markdown_object_key);
ALTER TABLE reports              ADD CONSTRAINT uq_reports_workspace_key_version UNIQUE (workspace_id, report_key, version);
ALTER TABLE artifacts            ADD CONSTRAINT uq_artifacts_report_type_version UNIQUE (report_id, artifact_type, version);
ALTER TABLE artifacts            ADD CONSTRAINT uq_artifacts_object_key      UNIQUE (object_key);
ALTER TABLE pipeline_jobs        ADD CONSTRAINT uq_pj_idempotency_key        UNIQUE (idempotency_key);


-- ============================================================
-- CHECK 제약
-- ============================================================

-- [7/29] owner 누락 버그 수정: 기존엔 admin/editor/viewer만 허용되어 있었음
ALTER TABLE workspace_members    ADD CONSTRAINT ck_wm_role         CHECK (role IN ('owner','admin','editor','viewer'));

ALTER TABLE chat_messages        ADD CONSTRAINT ck_cm_role           CHECK (role IN ('user','assistant','system'));
ALTER TABLE chat_sessions        ADD CONSTRAINT ck_cs_visibility     CHECK (visibility IN ('private','team'));
ALTER TABLE sources              ADD CONSTRAINT ck_sources_type      CHECK (source_type IN ('news','rss','disclosure','report','website','manual_upload'));

ALTER TABLE documents            ADD CONSTRAINT ck_documents_status  CHECK (status IN ('active','deleted','blocked','failed'));
ALTER TABLE document_versions    ADD CONSTRAINT ck_dv_versionno      CHECK (version_no >= 1);

-- [7/29] page_type: [8/07] supply_chain / policy / market 추가(실사용 카테고리 확장)
-- review_policy: 기존 메모는 manual/auto/hybrid였으나, LLM 자율 진행 방식으로
-- 설계 변경하여 draft/review/confirmed 로 교체함 (2026-07-29 팀 확인)
ALTER TABLE wiki_pages           ADD CONSTRAINT ck_wp_page_type      CHECK (page_type IN ('industry','company','technology','supply_chain','policy','market','issue','term'));
ALTER TABLE wiki_pages           ADD CONSTRAINT ck_wp_review_policy  CHECK (review_policy IN ('draft','review','confirmed'));
ALTER TABLE wiki_pages           ADD CONSTRAINT ck_wiki_pages_status CHECK (status IN ('draft','published','archived'));
ALTER TABLE wiki_page_versions   ADD CONSTRAINT ck_wpv_versionno     CHECK (version_no >= 1);
ALTER TABLE wiki_page_versions   ADD CONSTRAINT ck_wpv_review_status CHECK (review_status IN ('pending','approved','rejected'));
ALTER TABLE wiki_page_versions   ADD CONSTRAINT ck_wpv_generated_by  CHECK (generated_by IN ('human','llm'));
ALTER TABLE wiki_page_versions   ADD CONSTRAINT ck_wpv_validation_status CHECK (validation_status IN ('pending','passed','failed'));
ALTER TABLE wiki_page_versions   ADD CONSTRAINT ck_wpv_confidence    CHECK (confidence_score >= 0 AND confidence_score <= 1);
ALTER TABLE wiki_page_versions ADD CONSTRAINT ck_wpv_page_reliability_score
  CHECK (page_reliability_score IS NULL OR (page_reliability_score >= 0 AND page_reliability_score <= 100));
ALTER TABLE wiki_page_versions ADD CONSTRAINT ck_wpv_page_reliability_level
  CHECK (page_reliability_level IS NULL OR page_reliability_level IN ('낮음', '보통', '높음'));

-- [8/07] report_type/status: 리포트 유형이 daily 외로 확장되고, 생성 파이프라인이
-- planning/researching/drafting/verifying/rendering 세부 단계를 거치도록 바뀜
ALTER TABLE reports              ADD CONSTRAINT ck_reports_type      CHECK (report_type IN ('daily','weekly','company','technology','issue_briefing'));
ALTER TABLE reports              ADD CONSTRAINT ck_reports_status    CHECK (status IN ('pending','planning','researching','drafting','verifying','rendering','completed','failed','cancelled'));
ALTER TABLE reports              ADD CONSTRAINT ck_reports_version   CHECK (version >= 1);

ALTER TABLE report_sections      ADD CONSTRAINT ck_rs_status         CHECK (status IN ('pending','researching','drafting','verifying','completed','failed'));

ALTER TABLE report_citations     ADD CONSTRAINT ck_rc_relevance      CHECK (relevance_score >= 0 AND relevance_score <= 1);
ALTER TABLE report_wiki_references ADD CONSTRAINT ck_rwr_relevance   CHECK (relevance_score >= 0 AND relevance_score <= 1);

ALTER TABLE artifacts            ADD CONSTRAINT ck_artifacts_type    CHECK (artifact_type IN ('markdown','pdf','pptx','docx'));
ALTER TABLE artifacts            ADD CONSTRAINT ck_artifacts_version CHECK (version >= 1);

ALTER TABLE daily_report_analysis_batches ADD CONSTRAINT ck_drab_status CHECK (status IN ('running','completed'));

ALTER TABLE message_citations    ADD CONSTRAINT ck_mc_relevance      CHECK (relevance_score >= 0 AND relevance_score <= 1);
ALTER TABLE message_citations ADD CONSTRAINT ck_mc_has_identifier CHECK (document_version_id IS NOT NULL OR source_url IS NOT NULL);

-- [8/07] job_type/target_type: index_qmd/generate_wiki/generate_report,
-- document_version/wiki_page/report 추가 — 코드 상수는 src/pipeline_common/constants.py
ALTER TABLE pipeline_jobs        ADD CONSTRAINT ck_pj_job_type       CHECK (job_type IN ('collect','parse_document','index_qmd','generate_wiki','generate_report'));
ALTER TABLE pipeline_jobs        ADD CONSTRAINT ck_pj_target_type    CHECK (target_type IN ('document','document_version','wiki_page','report'));
ALTER TABLE pipeline_jobs        ADD CONSTRAINT ck_pj_status         CHECK (status IN ('pending','running','completed','failed','cancelled'));
ALTER TABLE pipeline_jobs        ADD CONSTRAINT ck_pj_progress       CHECK (progress >= 0 AND progress <= 100);
ALTER TABLE pipeline_jobs        ADD CONSTRAINT ck_pj_retry_count    CHECK (retry_count >= 0);

ALTER TABLE qmd_index_entries    ADD CONSTRAINT ck_qmd_status        CHECK (status IN ('pending','indexing','indexed','failed','stale'));

ALTER TABLE sources              ADD CONSTRAINT ck_sources_reliability CHECK (reliability_score >= 0 AND reliability_score <= 1);

-- [8/07] workspace_settings: 프론트 드롭다운 선택지와 1:1
ALTER TABLE workspace_settings   ADD CONSTRAINT ck_ws_wiki_cycle      CHECK (wiki_update_cycle_minutes IN (30,60,180,360,720,1440));
ALTER TABLE workspace_settings   ADD CONSTRAINT ck_ws_data_cycle      CHECK (data_refresh_cycle_minutes IN (30,60,120,180,360,720,1440));
ALTER TABLE workspace_settings   ADD CONSTRAINT ck_ws_chat_retention  CHECK (chat_retention_days IS NULL OR chat_retention_days IN (7,30,90));

-- [8/07] document_analysis_results: 4단계(분류/신뢰도/중요도/랭킹) 상태값 + 세부 점수 범위.
-- 세부 점수 배점은 analysis/README.md 채점 기준과 1:1로 맞춰져 있다.
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_category
  CHECK (primary_category IS NULL OR primary_category IN ('제품·기술','경쟁사','고객·수요산업','공급망·생산','정책·규제','시장·경영'));
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_secondary_categories
  CHECK (secondary_categories <@ ARRAY['제품·기술','경쟁사','고객·수요산업','공급망·생산','정책·규제','시장·경영']::text[]);
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_classification_confidence
  CHECK (classification_confidence IS NULL OR (classification_confidence >= 0 AND classification_confidence <= 1));
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_status
  CHECK (status IN ('pending','completed','failed'));

ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_reliability_status
  CHECK (reliability_status IN ('pending','completed','failed'));
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_reliability_score
  CHECK (reliability_score IS NULL OR (reliability_score >= 0 AND reliability_score <= 100));
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_reliability_level
  CHECK (reliability_level IS NULL OR reliability_level IN ('낮음','보통','높음'));
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_traceability_score
  CHECK (traceability_score IS NULL OR (traceability_score >= 0 AND traceability_score <= 20));
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_source_authority_score
  CHECK (source_authority_score IS NULL OR (source_authority_score >= 0 AND source_authority_score <= 20));
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_current_validity_score
  CHECK (current_validity_score IS NULL OR (current_validity_score >= 0 AND current_validity_score <= 20));
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_independent_evidence_score
  CHECK (independent_evidence_score IS NULL OR (independent_evidence_score >= 0 AND independent_evidence_score <= 20));
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_factual_consistency_score
  CHECK (factual_consistency_score IS NULL OR (factual_consistency_score >= 0 AND factual_consistency_score <= 20));
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_reliability_detail_is_object
  CHECK (jsonb_typeof(reliability_detail) = 'object');

ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_importance_status
  CHECK (importance_status IN ('pending','completed','failed'));
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_importance_score
  CHECK (importance_score IS NULL OR (importance_score >= 0 AND importance_score <= 100));
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_importance_level
  CHECK (importance_level IS NULL OR importance_level IN ('낮음','보통','높음'));
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_direct_relevance_score
  CHECK (direct_relevance_score IS NULL OR (direct_relevance_score >= 0 AND direct_relevance_score <= 25));
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_business_impact_score
  CHECK (business_impact_score IS NULL OR (business_impact_score >= 0 AND business_impact_score <= 25));
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_urgency_score
  CHECK (urgency_score IS NULL OR (urgency_score >= 0 AND urgency_score <= 15));
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_industry_impact_score
  CHECK (industry_impact_score IS NULL OR (industry_impact_score >= 0 AND industry_impact_score <= 15));
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_duration_score
  CHECK (duration_score IS NULL OR (duration_score >= 0 AND duration_score <= 10));
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_external_attention_score
  CHECK (external_attention_score IS NULL OR (external_attention_score >= 0 AND external_attention_score <= 10));
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_impact_direction
  CHECK (impact_direction IS NULL OR impact_direction IN ('기회','위험','혼합','중립'));
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_time_horizon
  CHECK (time_horizon IS NULL OR time_horizon IN ('즉시','단기','중기','장기'));
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_key_points_max5
  CHECK (cardinality(key_points) <= 5);
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_key_numbers_is_array
  CHECK (jsonb_typeof(key_numbers) = 'array');
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_summary_evidence_refs_is_array
  CHECK (jsonb_typeof(summary_evidence_refs) = 'array');
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_importance_detail_is_object
  CHECK (jsonb_typeof(importance_detail) = 'object');

ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_ranking_status
  CHECK (ranking_status IN ('pending','completed','excluded','failed'));
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_ranking_score
  CHECK (ranking_score IS NULL OR (ranking_score >= 0 AND ranking_score <= 100));
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_recency_score
  CHECK (recency_score IS NULL OR (recency_score >= 0 AND recency_score <= 100));
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_ranking_position
  CHECK (ranking_position IS NULL OR ranking_position >= 1);
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_report_selection_position
  CHECK (report_selection_position IS NULL OR report_selection_position >= 1);
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_selection_reason
  CHECK (selection_reason IS NULL OR selection_reason IN ('SELECTED','LOW_RELIABILITY','CATEGORY_LIMIT','OUTSIDE_REPORT_LIMIT'));
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_ranking_exclusion_reason
  CHECK (ranking_exclusion_reason IS NULL OR ranking_exclusion_reason IN ('LOW_RELIABILITY','CATEGORY_LIMIT','OUTSIDE_REPORT_LIMIT'));
ALTER TABLE document_analysis_results ADD CONSTRAINT ck_dar_ranking_detail_is_object
  CHECK (jsonb_typeof(ranking_detail) = 'object');


-- ============================================================
-- object_key 경로 설계 가이드 (애플리케이션 레벨 규칙, DB 제약 아님)
--   raw/{workspace_id}/{document_id}/{version_no}.{ext}
--   processed/{workspace_id}/{document_id}/{version_no}.md
--   wiki/{workspace_id}/{page_id}/{version_no}.md
--   reports/{workspace_id}/reports/{report_id}/{artifact_type}/v{version}.{ext}
-- ============================================================


-- ============================================================
-- ROW LEVEL SECURITY (2026-07 적용)
--
-- 설계 원칙: workspace_members 가 모든 권한 판정의 단일 출처.
-- 모든 콘텐츠 테이블은 workspace_id (직접 보유) 또는 상위 테이블과의
-- JOIN 체인을 통해 workspace_id에 도달한 뒤, 그 워크스페이스의
-- workspace_members 여부로 접근을 판정한다.
--
-- workspace_members 자신을 조회하는 정책이 workspace_members를
-- 다시 셀렉트하면 "infinite recursion detected in policy" 에러가
-- 발생하므로, SECURITY DEFINER 헬퍼 함수(is_workspace_member,
-- has_workspace_role)를 통해 우회한다. (Supabase 공식 권장 패턴)
--
-- 헬퍼 함수는 anon/PUBLIC 에서는 실행 불가하도록 REVOKE 하고
-- authenticated 에게만 GRANT 한다 (RLS 정책 평가 시 필요).
--
-- [주의] 아래 정책은 2026-07-29 시점 내용이다. 이후 추가된 배치(백엔드
-- SERVICE_ROLE_KEY 경유, RLS 우회) 위주 테이블은 이 섹션 갱신이 밀렸을 수
-- 있다 — 6-A 참고.
-- ============================================================

CREATE OR REPLACE FUNCTION is_workspace_member(p_workspace_id uuid, p_user_id uuid DEFAULT auth.uid())
RETURNS boolean
LANGUAGE sql
STABLE SECURITY DEFINER
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1 FROM workspace_members
    WHERE workspace_id = p_workspace_id AND user_id = p_user_id
  );
$$;

CREATE OR REPLACE FUNCTION has_workspace_role(p_workspace_id uuid, p_roles text[], p_user_id uuid DEFAULT auth.uid())
RETURNS boolean
LANGUAGE sql
STABLE SECURITY DEFINER
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1 FROM workspace_members
    WHERE workspace_id = p_workspace_id AND user_id = p_user_id AND role = ANY(p_roles)
  );
$$;

REVOKE EXECUTE ON FUNCTION is_workspace_member(uuid, uuid) FROM PUBLIC;
GRANT  EXECUTE ON FUNCTION is_workspace_member(uuid, uuid) TO authenticated;

REVOKE EXECUTE ON FUNCTION has_workspace_role(uuid, text[], uuid) FROM PUBLIC;
GRANT  EXECUTE ON FUNCTION has_workspace_role(uuid, text[], uuid) TO authenticated;

ALTER TABLE workspaces          ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace_members   ENABLE ROW LEVEL SECURITY;
ALTER TABLE profiles            ENABLE ROW LEVEL SECURITY;
ALTER TABLE sources             ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents           ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_versions   ENABLE ROW LEVEL SECURITY;
ALTER TABLE wiki_pages          ENABLE ROW LEVEL SECURITY;
ALTER TABLE wiki_page_versions  ENABLE ROW LEVEL SECURITY;
ALTER TABLE wiki_page_sources   ENABLE ROW LEVEL SECURITY;
ALTER TABLE reports             ENABLE ROW LEVEL SECURITY;
ALTER TABLE report_sections     ENABLE ROW LEVEL SECURITY;
ALTER TABLE report_citations    ENABLE ROW LEVEL SECURITY;
ALTER TABLE artifacts           ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_sessions       ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_messages       ENABLE ROW LEVEL SECURITY;
ALTER TABLE message_citations   ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_jobs       ENABLE ROW LEVEL SECURITY;
ALTER TABLE qmd_index_entries   ENABLE ROW LEVEL SECURITY;

-- profiles: 본인 행만 조회/수정
CREATE POLICY profiles_select_own ON profiles FOR SELECT
  USING (id = auth.uid());
CREATE POLICY profiles_update_own ON profiles FOR UPDATE
  USING (id = auth.uid()) WITH CHECK (id = auth.uid());

-- workspaces: 멤버만 조회, admin만 수정
CREATE POLICY workspaces_select_member ON workspaces FOR SELECT
  USING (is_workspace_member(id));
CREATE POLICY workspaces_update_admin ON workspaces FOR UPDATE
  USING (has_workspace_role(id, ARRAY['admin'])) WITH CHECK (has_workspace_role(id, ARRAY['admin']));

-- workspace_members: 같은 워크스페이스 멤버는 조회 가능, admin만 추가/수정/삭제
CREATE POLICY wm_select_same_workspace ON workspace_members FOR SELECT
  USING (is_workspace_member(workspace_id));
CREATE POLICY wm_insert_admin ON workspace_members FOR INSERT
  WITH CHECK (has_workspace_role(workspace_id, ARRAY['admin']));
CREATE POLICY wm_update_admin ON workspace_members FOR UPDATE
  USING (has_workspace_role(workspace_id, ARRAY['admin'])) WITH CHECK (has_workspace_role(workspace_id, ARRAY['admin']));
CREATE POLICY wm_delete_admin ON workspace_members FOR DELETE
  USING (has_workspace_role(workspace_id, ARRAY['admin']));

-- workspace_id를 직접 보유한 콘텐츠 테이블: 멤버는 SELECT 가능 (쓰기는 서비스 롤/백엔드에서 처리)
CREATE POLICY sources_select ON sources FOR SELECT
  USING (is_workspace_member(workspace_id));
CREATE POLICY documents_select ON documents FOR SELECT
  USING (is_workspace_member(workspace_id));
CREATE POLICY wiki_pages_select ON wiki_pages FOR SELECT
  USING (is_workspace_member(workspace_id));
CREATE POLICY reports_select ON reports FOR SELECT
  USING (is_workspace_member(workspace_id));
CREATE POLICY chat_sessions_select ON chat_sessions FOR SELECT
  USING (is_workspace_member(workspace_id));
CREATE POLICY pipeline_jobs_select ON pipeline_jobs FOR SELECT
  USING (is_workspace_member(workspace_id));

-- 자식 테이블: 상위 테이블 JOIN으로 workspace_id에 도달
CREATE POLICY document_versions_select ON document_versions FOR SELECT
  USING (EXISTS (SELECT 1 FROM documents d WHERE d.id = document_versions.document_id AND is_workspace_member(d.workspace_id)));

CREATE POLICY wiki_page_versions_select ON wiki_page_versions FOR SELECT
  USING (EXISTS (SELECT 1 FROM wiki_pages p WHERE p.id = wiki_page_versions.page_id AND is_workspace_member(p.workspace_id)));

CREATE POLICY wiki_page_sources_select ON wiki_page_sources FOR SELECT
  USING (EXISTS (
    SELECT 1 FROM wiki_page_versions wpv JOIN wiki_pages p ON p.id = wpv.page_id
    WHERE wpv.id = wiki_page_sources.wiki_version_id AND is_workspace_member(p.workspace_id)
  ));

CREATE POLICY report_sections_select ON report_sections FOR SELECT
  USING (EXISTS (SELECT 1 FROM reports r WHERE r.id = report_sections.report_id AND is_workspace_member(r.workspace_id)));

CREATE POLICY report_citations_select ON report_citations FOR SELECT
  USING (EXISTS (
    SELECT 1 FROM report_sections rs JOIN reports r ON r.id = rs.report_id
    WHERE rs.id = report_citations.section_id AND is_workspace_member(r.workspace_id)
  ));

CREATE POLICY artifacts_select ON artifacts FOR SELECT
  USING (EXISTS (SELECT 1 FROM reports r WHERE r.id = artifacts.report_id AND is_workspace_member(r.workspace_id)));

CREATE POLICY chat_messages_select ON chat_messages FOR SELECT
  USING (EXISTS (SELECT 1 FROM chat_sessions cs WHERE cs.id = chat_messages.session_id AND is_workspace_member(cs.workspace_id)));

CREATE POLICY message_citations_select ON message_citations FOR SELECT
  USING (EXISTS (
    SELECT 1 FROM chat_messages cm JOIN chat_sessions cs ON cs.id = cm.session_id
    WHERE cm.id = message_citations.message_id AND is_workspace_member(cs.workspace_id)
  ));

-- qmd_index_entries: document_version_id / wiki_version_id / report_id 중
-- 채워진 것을 통해 workspace_id에 도달 (셋 다 nullable, 3-way OR)
CREATE POLICY qmd_index_entries_select ON qmd_index_entries FOR SELECT
  USING (
    (document_version_id IS NOT NULL AND EXISTS (
      SELECT 1 FROM document_versions dv JOIN documents d ON d.id = dv.document_id
      WHERE dv.id = qmd_index_entries.document_version_id AND is_workspace_member(d.workspace_id)
    ))
    OR (wiki_version_id IS NOT NULL AND EXISTS (
      SELECT 1 FROM wiki_page_versions wpv JOIN wiki_pages p ON p.id = wpv.page_id
      WHERE wpv.id = qmd_index_entries.wiki_version_id AND is_workspace_member(p.workspace_id)
    ))
    OR (report_id IS NOT NULL AND EXISTS (
      SELECT 1 FROM reports r WHERE r.id = qmd_index_entries.report_id AND is_workspace_member(r.workspace_id)
    ))
  );


-- ------------------------------------------------------------
-- 6-A. 2026-07-29 이후 신설 테이블 RLS 정책 (2026-08-08 라이브 DB 직접 조회로 확인)
--
-- chat_session_participants / daily_report_analysis_batches는 RLS만 켜져 있고
-- 정책이 하나도 없어(서비스 롤 우회 없이는 전부 거부) 이번에 새로 추가했다
-- (마이그레이션 20260808020000). 나머지 5개는 이미 정책이 있었음을 확인했다.
-- ------------------------------------------------------------

CREATE POLICY document_analysis_results_select ON document_analysis_results FOR SELECT
  USING (is_workspace_member(workspace_id));

CREATE POLICY workspace_settings_select ON workspace_settings FOR SELECT
  USING (EXISTS (
    SELECT 1 FROM workspace_members
    WHERE workspace_members.workspace_id = workspace_settings.workspace_id
      AND workspace_members.user_id = auth.uid()
  ));

-- push_subscriptions: 워크스페이스 공용 조회가 아니라 본인 구독만(SELECT/INSERT/UPDATE/DELETE 전부)
CREATE POLICY push_subscriptions_own ON push_subscriptions FOR ALL
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

CREATE POLICY wiki_page_keywords_select ON wiki_page_keywords FOR SELECT
  USING (EXISTS (
    SELECT 1 FROM wiki_pages p WHERE p.id = wiki_page_keywords.page_id AND is_workspace_member(p.workspace_id)
  ));

CREATE POLICY report_wiki_references_select ON report_wiki_references FOR SELECT
  USING (EXISTS (
    SELECT 1 FROM report_sections rs JOIN reports r ON r.id = rs.report_id
    WHERE rs.id = report_wiki_references.section_id AND is_workspace_member(r.workspace_id)
  ));

-- 아래 2개는 RLS는 켜져 있었으나 정책이 없어(전체 차단 상태) 2026-08-08에 추가.
CREATE POLICY daily_report_analysis_batches_select ON daily_report_analysis_batches FOR SELECT
  USING (is_workspace_member(workspace_id));

CREATE POLICY chat_session_participants_select ON chat_session_participants FOR SELECT
  USING (EXISTS (
    SELECT 1 FROM chat_sessions cs WHERE cs.id = chat_session_participants.session_id AND is_workspace_member(cs.workspace_id)
  ));


-- ============================================================
-- 회원가입 시 profiles 자동 생성 + MVP workspace 자동 합류 트리거
-- (2026-07-31 변경: workspace_members 자동 합류 추가 — 마이그레이션
--  handle_new_user_auto_join_mvp_workspace)
-- ============================================================

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  mvp_workspace_id uuid;
BEGIN
  INSERT INTO public.profiles (id, display_name, created_at, updated_at)
  VALUES (
    NEW.id,
    COALESCE(NEW.raw_user_meta_data->>'full_name', NEW.raw_user_meta_data->>'name', split_part(NEW.email, '@', 1), 'unnamed'),
    now(),
    now()
  )
  ON CONFLICT (id) DO NOTHING;

  -- MVP 단계: workspace가 'mywiki' 하나뿐이므로 신규 가입자를 자동으로 editor로 합류시킨다.
  -- workspace가 여러 개로 늘어나면 이 자동 합류 로직은 제거하고 초대 흐름으로 교체해야 한다.
  SELECT id INTO mvp_workspace_id FROM public.workspaces WHERE slug = 'mywiki' LIMIT 1;
  IF mvp_workspace_id IS NOT NULL THEN
    INSERT INTO public.workspace_members (workspace_id, user_id, role)
    VALUES (mvp_workspace_id, NEW.id, 'editor')
    ON CONFLICT (workspace_id, user_id) DO NOTHING;
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();


-- ============================================================
-- updated_at 자동 갱신 트리거
-- ============================================================

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

CREATE TRIGGER trg_workspaces_updated_at        BEFORE UPDATE ON workspaces        FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER trg_profiles_updated_at          BEFORE UPDATE ON profiles          FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER trg_sources_updated_at           BEFORE UPDATE ON sources           FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER trg_documents_updated_at         BEFORE UPDATE ON documents         FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER trg_wiki_pages_updated_at        BEFORE UPDATE ON wiki_pages        FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER trg_reports_updated_at           BEFORE UPDATE ON reports           FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER trg_report_sections_updated_at   BEFORE UPDATE ON report_sections   FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER trg_chat_sessions_updated_at     BEFORE UPDATE ON chat_sessions     FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER trg_pipeline_jobs_updated_at     BEFORE UPDATE ON pipeline_jobs     FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER trg_qmd_index_entries_updated_at BEFORE UPDATE ON qmd_index_entries FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- [TODO] 아래 신규 테이블들도 updated_at 컬럼을 갖고 있어 트리거 대상 후보다 —
-- 실제 DB에 트리거가 있는지 확인 후 추가할 것 (6-A와 같은 이유로 추측 기입 안 함):
--   document_analysis_results, workspace_settings, daily_report_analysis_batches


-- ============================================================
-- Storage 버킷
-- ============================================================

INSERT INTO storage.buckets (id, name, public)
VALUES ('raw', 'raw', false), ('processed', 'processed', false), ('wiki', 'wiki', false), ('reports', 'reports', false)
ON CONFLICT (id) DO NOTHING;


-- ============================================================
-- [참고] 이 파일 밖에서 처리해야 하는 것
--   1) Google 소셜 로그인: Google Cloud Console에서 OAuth 클라이언트 생성 후
--      Supabase Dashboard > Authentication > Providers > Google 에 Client ID/Secret 등록.
--      승인된 리디렉션 URI: https://uhzjshqmnlahhvqzygkp.supabase.co/auth/v1/callback
--   2) 이메일/비밀번호 로그인: Supabase 기본값으로 이미 활성화되어 있음 (추가 작업 불필요)
--   3) 소셜 로그인과 이메일/비밀번호의 이메일이 같으면 같은 계정으로 연결되는 것:
--      Supabase 기본 동작 (동일 이메일이면 auth.identities 로 자동 연결됨, 추가 코드 불필요)
--   4) exposed schemas: public 스키마만 사용하므로 별도 설정 불필요
-- ============================================================

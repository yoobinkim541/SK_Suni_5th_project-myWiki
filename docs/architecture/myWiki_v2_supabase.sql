-- ============================================================
-- Supabase SQL Editor용 (PostgreSQL 문법, backtick 사용 안 함)
-- 실행 순서: 1) CREATE TABLE -> 2) PK -> 3) FK -> 4) UNIQUE -> 5) CHECK
--          -> 6) RLS 정책 -> 7) 트리거/함수 -> 8) Storage 버킷
-- 전체를 그대로 New Query에 붙여넣고 Run 하면 됩니다.
--
-- [중요] 이 파일은 라이브 Supabase 프로젝트(uhzjshqmnlahhvqzygkp)의
-- 실제 스키마를 information_schema / pg_catalog에서 직접 조회하여
-- 그대로 재구성한 파일입니다. (2026-07-29 기준 정본)
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
-- ============================================================


-- ------------------------------------------------------------
-- 0. workspace 관련 (신규)
-- ------------------------------------------------------------

CREATE TABLE workspaces (
    id          UUID          NOT NULL DEFAULT gen_random_uuid(),
    name        VARCHAR(200)  NOT NULL,
    slug        VARCHAR(100)  NOT NULL,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE TABLE workspace_members (
    id           UUID          NOT NULL DEFAULT gen_random_uuid(),
    workspace_id UUID          NOT NULL,
    user_id      UUID          NOT NULL,
    role         VARCHAR(20)   NOT NULL,
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT now()
);


-- ------------------------------------------------------------
-- 1. profiles (auth.users 확장)
-- ------------------------------------------------------------

CREATE TABLE profiles (
    id            UUID          NOT NULL,  -- DEFAULT 없음: auth.users.id 값을 그대로 사용
    display_name  VARCHAR(100)  NOT NULL,
    department    VARCHAR(100),
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT now()
);


-- ------------------------------------------------------------
-- 2. sources / documents / document_versions
-- ------------------------------------------------------------

CREATE TABLE sources (
    id                 UUID           NOT NULL DEFAULT gen_random_uuid(),
    workspace_id       UUID           NOT NULL,
    name               VARCHAR(200)   NOT NULL,
    source_type        VARCHAR(30)    NOT NULL,
    base_url           TEXT,
    reliability_score  NUMERIC(5,4),
    config             JSONB          NOT NULL DEFAULT '{}'::jsonb,
    enabled            BOOLEAN        NOT NULL DEFAULT true,
    created_at         TIMESTAMPTZ    NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ    NOT NULL DEFAULT now()
);

CREATE TABLE documents (
    id             UUID          NOT NULL DEFAULT gen_random_uuid(),
    workspace_id   UUID          NOT NULL,
    source_id      UUID,
    title          VARCHAR(500)  NOT NULL,
    canonical_url  TEXT,
    published_at   TIMESTAMPTZ,
    status         VARCHAR(30)   NOT NULL,
    uploaded_by    UUID,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE TABLE document_versions (
    id                   UUID          NOT NULL DEFAULT gen_random_uuid(),
    document_id          UUID          NOT NULL,
    version_no           INTEGER       NOT NULL,
    content_hash         VARCHAR(64)   NOT NULL,
    raw_object_key       TEXT,
    markdown_object_key  TEXT          NOT NULL,
    parser_version       VARCHAR(50),
    language             VARCHAR(10),
    created_at           TIMESTAMPTZ   NOT NULL DEFAULT now()
);


-- ------------------------------------------------------------
-- 3. wiki_pages / wiki_page_versions / wiki_page_sources
-- ------------------------------------------------------------

CREATE TABLE wiki_pages (
    id                  UUID          NOT NULL DEFAULT gen_random_uuid(),
    workspace_id        UUID          NOT NULL,
    parent_page_id      UUID,
    slug                VARCHAR(300)  NOT NULL,
    title               VARCHAR(500)  NOT NULL,
    page_type           VARCHAR(30)   NOT NULL,
    status              VARCHAR(30)   NOT NULL,
    review_policy       VARCHAR(20)   NOT NULL,
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
    content_hash               VARCHAR(64)   NOT NULL,
    change_summary             TEXT,
    created_by                 UUID,
    review_status              VARCHAR(30)   NOT NULL,
    reviewed_by                UUID,
    reviewed_at                TIMESTAMPTZ,
    generated_by               VARCHAR(20)   NOT NULL,
    generator_model            VARCHAR(100),
    generator_prompt_version   VARCHAR(50),
    generation_run_id          UUID,
    validation_status          VARCHAR(30)   NOT NULL,
    confidence_score           NUMERIC(5,4),
    created_at                 TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE TABLE wiki_page_sources (
    id                    UUID         NOT NULL DEFAULT gen_random_uuid(),
    wiki_version_id       UUID         NOT NULL,
    document_version_id   UUID         NOT NULL,
    claim_text            TEXT,
    source_start_line     INTEGER,
    source_end_line       INTEGER,
    support_type          VARCHAR(20),
    citation_order        INTEGER,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now()
);


-- ------------------------------------------------------------
-- 4. reports / report_sections / report_citations / artifacts
-- ------------------------------------------------------------

CREATE TABLE reports (
    id              UUID          NOT NULL DEFAULT gen_random_uuid(),
    workspace_id    UUID          NOT NULL,
    report_key      VARCHAR(200)  NOT NULL,
    version         INTEGER       NOT NULL,
    requested_by    UUID,
    title           VARCHAR(500)  NOT NULL,
    report_type     VARCHAR(50)   NOT NULL,
    status          VARCHAR(30)   NOT NULL,
    request_config  JSONB         NOT NULL,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

CREATE TABLE report_sections (
    id                  UUID          NOT NULL DEFAULT gen_random_uuid(),
    report_id           UUID          NOT NULL,
    section_order       INTEGER       NOT NULL,
    title               VARCHAR(500)  NOT NULL,
    content             TEXT,
    status              VARCHAR(30)   NOT NULL,
    model_name          VARCHAR(100),
    prompt_version      VARCHAR(50),
    generation_run_id   UUID,
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE TABLE report_citations (
    id                    UUID          NOT NULL DEFAULT gen_random_uuid(),
    section_id            UUID          NOT NULL,
    document_version_id   UUID          NOT NULL,
    source_start_line     INTEGER,
    source_end_line       INTEGER,
    quoted_text           TEXT,
    relevance_score       NUMERIC(5,4),
    citation_order        INTEGER,
    created_at            TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE TABLE artifacts (
    id             UUID          NOT NULL DEFAULT gen_random_uuid(),
    report_id      UUID          NOT NULL,
    artifact_type  VARCHAR(20)   NOT NULL,
    object_key     TEXT          NOT NULL,
    version        INTEGER       NOT NULL,
    file_size      INTEGER,
    mime_type      VARCHAR(100),
    created_by     UUID,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT now()
);


-- ------------------------------------------------------------
-- 5. chat_sessions / chat_messages / message_citations
-- ------------------------------------------------------------

CREATE TABLE chat_sessions (
    id            UUID          NOT NULL DEFAULT gen_random_uuid(),
    workspace_id  UUID          NOT NULL,
    user_id       UUID          NOT NULL,
    title         VARCHAR(500),
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE TABLE chat_messages (
    id              UUID          NOT NULL DEFAULT gen_random_uuid(),
    session_id      UUID          NOT NULL,
    role            VARCHAR(20)   NOT NULL,
    content         TEXT          NOT NULL,
    model_name      VARCHAR(100),
    prompt_version  VARCHAR(50),
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE TABLE message_citations (
    id                    UUID          NOT NULL DEFAULT gen_random_uuid(),
    message_id            UUID          NOT NULL,
    document_version_id   UUID          NOT NULL,
    qmd_uri               TEXT,
    source_start_line     INTEGER,
    source_end_line       INTEGER,
    quoted_text           TEXT,
    relevance_score       NUMERIC(5,4),
    citation_order        INTEGER,
    created_at            TIMESTAMPTZ   NOT NULL DEFAULT now()
);


-- ------------------------------------------------------------
-- 6. pipeline_jobs / qmd_index_entries
-- ------------------------------------------------------------

CREATE TABLE pipeline_jobs (
    id                UUID           NOT NULL DEFAULT gen_random_uuid(),
    workspace_id      UUID           NOT NULL,
    job_type          VARCHAR(50)    NOT NULL,
    target_type       VARCHAR(50),
    target_id         UUID,
    status            VARCHAR(30)    NOT NULL,
    progress          INTEGER        NOT NULL DEFAULT 0,
    error_message     TEXT,
    requested_by      UUID,
    payload           JSONB          NOT NULL DEFAULT '{}'::jsonb,
    result            JSONB,
    retry_count       INTEGER        NOT NULL DEFAULT 0,
    idempotency_key   VARCHAR(200),
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
    collection_name       VARCHAR(100)  NOT NULL,
    status                VARCHAR(30)   NOT NULL,
    qmd_uri               TEXT,
    qmd_docid             VARCHAR(20),
    index_generation      INTEGER       NOT NULL,
    indexed_at            TIMESTAMPTZ,
    last_error            TEXT,
    created_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ   NOT NULL DEFAULT now()
);


-- ============================================================
-- PRIMARY KEYS
-- ============================================================

ALTER TABLE workspaces           ADD CONSTRAINT pk_workspaces          PRIMARY KEY (id);
ALTER TABLE workspace_members    ADD CONSTRAINT pk_workspace_members   PRIMARY KEY (id);
ALTER TABLE profiles             ADD CONSTRAINT pk_profiles            PRIMARY KEY (id);
ALTER TABLE sources              ADD CONSTRAINT pk_sources             PRIMARY KEY (id);
ALTER TABLE documents            ADD CONSTRAINT pk_documents           PRIMARY KEY (id);
ALTER TABLE document_versions    ADD CONSTRAINT pk_document_versions   PRIMARY KEY (id);
ALTER TABLE wiki_pages           ADD CONSTRAINT pk_wiki_pages          PRIMARY KEY (id);
ALTER TABLE wiki_page_versions   ADD CONSTRAINT pk_wiki_page_versions  PRIMARY KEY (id);
ALTER TABLE wiki_page_sources    ADD CONSTRAINT pk_wiki_page_sources   PRIMARY KEY (id);
ALTER TABLE reports              ADD CONSTRAINT pk_reports             PRIMARY KEY (id);
ALTER TABLE report_sections      ADD CONSTRAINT pk_report_sections     PRIMARY KEY (id);
ALTER TABLE report_citations     ADD CONSTRAINT pk_report_citations    PRIMARY KEY (id);
ALTER TABLE artifacts            ADD CONSTRAINT pk_artifacts           PRIMARY KEY (id);
ALTER TABLE chat_sessions        ADD CONSTRAINT pk_chat_sessions       PRIMARY KEY (id);
ALTER TABLE chat_messages        ADD CONSTRAINT pk_chat_messages       PRIMARY KEY (id);
ALTER TABLE message_citations    ADD CONSTRAINT pk_message_citations   PRIMARY KEY (id);
ALTER TABLE pipeline_jobs        ADD CONSTRAINT pk_pipeline_jobs       PRIMARY KEY (id);
ALTER TABLE qmd_index_entries    ADD CONSTRAINT pk_qmd_index_entries   PRIMARY KEY (id);


-- ============================================================
-- FOREIGN KEYS
-- ============================================================

ALTER TABLE profiles           ADD CONSTRAINT fk_profiles_auth_user   FOREIGN KEY (id) REFERENCES auth.users(id) ON DELETE CASCADE;

ALTER TABLE workspace_members  ADD CONSTRAINT fk_wm_workspace         FOREIGN KEY (workspace_id) REFERENCES workspaces(id);
ALTER TABLE workspace_members  ADD CONSTRAINT fk_wm_user              FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE sources             ADD CONSTRAINT fk_sources_workspace           FOREIGN KEY (workspace_id) REFERENCES workspaces(id);

ALTER TABLE documents           ADD CONSTRAINT fk_documents_workspace         FOREIGN KEY (workspace_id) REFERENCES workspaces(id);
ALTER TABLE documents           ADD CONSTRAINT fk_documents_source            FOREIGN KEY (source_id) REFERENCES sources(id);
ALTER TABLE documents           ADD CONSTRAINT fk_documents_uploaded_by       FOREIGN KEY (uploaded_by) REFERENCES profiles(id) ON DELETE SET NULL;

ALTER TABLE document_versions   ADD CONSTRAINT fk_dv_document                 FOREIGN KEY (document_id) REFERENCES documents(id);

ALTER TABLE wiki_pages          ADD CONSTRAINT fk_wiki_pages_workspace        FOREIGN KEY (workspace_id) REFERENCES workspaces(id);
ALTER TABLE wiki_pages          ADD CONSTRAINT fk_wiki_pages_parent           FOREIGN KEY (parent_page_id) REFERENCES wiki_pages(id);
ALTER TABLE wiki_pages          ADD CONSTRAINT fk_wiki_pages_current_version  FOREIGN KEY (current_version_id) REFERENCES wiki_page_versions(id);

ALTER TABLE wiki_page_versions  ADD CONSTRAINT fk_wpv_page                    FOREIGN KEY (page_id) REFERENCES wiki_pages(id);
ALTER TABLE wiki_page_versions  ADD CONSTRAINT fk_wpv_created_by              FOREIGN KEY (created_by) REFERENCES profiles(id) ON DELETE SET NULL;
ALTER TABLE wiki_page_versions  ADD CONSTRAINT fk_wpv_reviewed_by             FOREIGN KEY (reviewed_by) REFERENCES profiles(id) ON DELETE SET NULL;

ALTER TABLE wiki_page_sources   ADD CONSTRAINT fk_wps_wiki_version            FOREIGN KEY (wiki_version_id) REFERENCES wiki_page_versions(id);
ALTER TABLE wiki_page_sources   ADD CONSTRAINT fk_wps_document_version        FOREIGN KEY (document_version_id) REFERENCES document_versions(id);

ALTER TABLE reports              ADD CONSTRAINT fk_reports_workspace          FOREIGN KEY (workspace_id) REFERENCES workspaces(id);
ALTER TABLE reports              ADD CONSTRAINT fk_reports_requested_by       FOREIGN KEY (requested_by) REFERENCES profiles(id) ON DELETE SET NULL;

ALTER TABLE report_sections      ADD CONSTRAINT fk_rs_report                  FOREIGN KEY (report_id) REFERENCES reports(id);

ALTER TABLE report_citations     ADD CONSTRAINT fk_rc_section                 FOREIGN KEY (section_id) REFERENCES report_sections(id);
ALTER TABLE report_citations     ADD CONSTRAINT fk_rc_document_version        FOREIGN KEY (document_version_id) REFERENCES document_versions(id);

ALTER TABLE artifacts            ADD CONSTRAINT fk_artifacts_report           FOREIGN KEY (report_id) REFERENCES reports(id);
ALTER TABLE artifacts            ADD CONSTRAINT fk_artifacts_created_by       FOREIGN KEY (created_by) REFERENCES profiles(id) ON DELETE SET NULL;

ALTER TABLE chat_sessions        ADD CONSTRAINT fk_cs_workspace               FOREIGN KEY (workspace_id) REFERENCES workspaces(id);
ALTER TABLE chat_sessions        ADD CONSTRAINT fk_cs_user                    FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE chat_messages        ADD CONSTRAINT fk_cm_session                 FOREIGN KEY (session_id) REFERENCES chat_sessions(id);

ALTER TABLE message_citations    ADD CONSTRAINT fk_mc_message                 FOREIGN KEY (message_id) REFERENCES chat_messages(id);
ALTER TABLE message_citations    ADD CONSTRAINT fk_mc_document_version        FOREIGN KEY (document_version_id) REFERENCES document_versions(id);

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
ALTER TABLE sources              ADD CONSTRAINT ck_sources_type      CHECK (source_type IN ('news','rss','disclosure','report','website','manual_upload'));

ALTER TABLE documents            ADD CONSTRAINT ck_documents_status  CHECK (status IN ('active','deleted','blocked','failed'));
ALTER TABLE document_versions    ADD CONSTRAINT ck_dv_versionno      CHECK (version_no >= 1);

-- [7/29] page_type: ERD 메모 원문 기준(industry/company/technology/issue/term)
-- review_policy: 기존 메모는 manual/auto/hybrid였으나, LLM 자율 진행 방식으로
-- 설계 변경하여 draft/review/confirmed 로 교체함 (2026-07-29 팀 확인)
ALTER TABLE wiki_pages           ADD CONSTRAINT ck_wp_page_type      CHECK (page_type IN ('industry','company','technology','issue','term'));
ALTER TABLE wiki_pages           ADD CONSTRAINT ck_wp_review_policy  CHECK (review_policy IN ('draft','review','confirmed'));
ALTER TABLE wiki_pages           ADD CONSTRAINT ck_wiki_pages_status CHECK (status IN ('draft','published','archived'));
ALTER TABLE wiki_page_versions   ADD CONSTRAINT ck_wpv_versionno     CHECK (version_no >= 1);
ALTER TABLE wiki_page_versions   ADD CONSTRAINT ck_wpv_review_status CHECK (review_status IN ('pending','approved','rejected'));
ALTER TABLE wiki_page_versions   ADD CONSTRAINT ck_wpv_generated_by  CHECK (generated_by IN ('human','llm'));
ALTER TABLE wiki_page_versions   ADD CONSTRAINT ck_wpv_validation_status CHECK (validation_status IN ('pending','passed','failed'));
ALTER TABLE wiki_page_versions   ADD CONSTRAINT ck_wpv_confidence    CHECK (confidence_score >= 0 AND confidence_score <= 1);

ALTER TABLE reports              ADD CONSTRAINT ck_reports_status    CHECK (status IN ('pending','generating','completed','failed'));
ALTER TABLE reports              ADD CONSTRAINT ck_reports_version   CHECK (version >= 1);

ALTER TABLE report_sections      ADD CONSTRAINT ck_rs_status         CHECK (status IN ('pending','generating','completed','failed'));

ALTER TABLE report_citations     ADD CONSTRAINT ck_rc_relevance      CHECK (relevance_score >= 0 AND relevance_score <= 1);

ALTER TABLE artifacts            ADD CONSTRAINT ck_artifacts_type    CHECK (artifact_type IN ('markdown','pdf','pptx','docx'));
ALTER TABLE artifacts            ADD CONSTRAINT ck_artifacts_version CHECK (version >= 1);

ALTER TABLE message_citations    ADD CONSTRAINT ck_mc_relevance      CHECK (relevance_score >= 0 AND relevance_score <= 1);

ALTER TABLE pipeline_jobs        ADD CONSTRAINT ck_pj_status         CHECK (status IN ('pending','running','completed','failed','cancelled'));
ALTER TABLE pipeline_jobs        ADD CONSTRAINT ck_pj_progress       CHECK (progress >= 0 AND progress <= 100);
ALTER TABLE pipeline_jobs        ADD CONSTRAINT ck_pj_retry_count    CHECK (retry_count >= 0);

ALTER TABLE qmd_index_entries    ADD CONSTRAINT ck_qmd_status        CHECK (status IN ('pending','indexing','indexed','failed','stale'));

ALTER TABLE sources              ADD CONSTRAINT ck_sources_reliability CHECK (reliability_score >= 0 AND reliability_score <= 1);


-- ============================================================
-- object_key 경로 설계 가이드 (애플리케이션 레벨 규칙, DB 제약 아님)
--   raw/{workspace_id}/{document_id}/{version_no}.{ext}
--   processed/{workspace_id}/{document_id}/{version_no}.md
--   wiki/{workspace_id}/{page_id}/{version_no}.md
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


-- ============================================================
-- 회원가입 시 profiles 자동 생성 트리거
-- ============================================================

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  INSERT INTO public.profiles (id, display_name, created_at, updated_at)
  VALUES (
    NEW.id,
    COALESCE(NEW.raw_user_meta_data->>'full_name', NEW.raw_user_meta_data->>'name', split_part(NEW.email, '@', 1), 'unnamed'),
    now(),
    now()
  )
  ON CONFLICT (id) DO NOTHING;
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


-- ============================================================
-- Storage 버킷
-- ============================================================

INSERT INTO storage.buckets (id, name, public)
VALUES ('raw', 'raw', false), ('processed', 'processed', false), ('wiki', 'wiki', false)
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

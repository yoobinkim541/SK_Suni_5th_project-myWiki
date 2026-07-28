-- ============================================================
-- Supabase SQL Editor용 (PostgreSQL 문법, backtick 제거)
-- 실행 순서: 1) CREATE TABLE -> 2) PK -> 3) FK -> 4) UNIQUE -> 5) CHECK
-- 전체를 그대로 New Query에 붙여넣고 Run 하면 됩니다.
-- ============================================================

-- ============================================================
-- myWiki 스키마 v2 (멘토님 피드백 반영본)
-- 원본: myWiki.sql
-- 변경 요약:
--   1) workspaces / workspace_members 추가 → RLS로 팀 데이터 격리
--   2) reports를 재생성 시마다 새 row(버전)를 쌓는 구조로 변경
--   3) artifacts 테이블 신설 → 보고서 산출물(md/pdf/pptx/docx)을 버전별로 관리
--   4) 중복 방지 UNIQUE 제약 추가
--   5) 값 범위 CHECK 제약 추가
--   6) object_key 버전 충돌 방지용 UNIQUE 추가 (+ 파일 경로 설계 가이드는 하단 주석 참고)
--   7) [7/27 멘토링 반영] profiles.role 제거 → 권한은 workspace_members.role 하나로만 관리 (역할 중복 해소)
-- ============================================================


-- ------------------------------------------------------------
-- 0. workspace 관련 (신규)
-- ------------------------------------------------------------

CREATE TABLE workspaces (
	id	UUID	NOT NULL,
	name	VARCHAR(200)	NOT NULL,
	slug	VARCHAR(100)	NOT NULL,
	created_at	TIMESTAMPTZ	NOT NULL,
	updated_at	TIMESTAMPTZ	NOT NULL
);

CREATE TABLE workspace_members (
	id	UUID	NOT NULL,
	workspace_id	UUID	NOT NULL,
	user_id	UUID	NOT NULL,
	role	VARCHAR(20)	NOT NULL,	-- 유일한 권한 소스. admin/editor/viewer. profiles.role은 제거됨(중복 방지)
	created_at	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 1. reports (변경: markdown_object_key/pdf_object_key 제거, 버전 필드 추가)
-- ------------------------------------------------------------

CREATE TABLE reports (
	id	UUID	NOT NULL,
	workspace_id	UUID	NOT NULL,
	report_key	VARCHAR(200)	NOT NULL,	-- 같은 보고서 계열을 묶는 키 (예: "daily-semiconductor-trend")
	version	INTEGER	NOT NULL,	-- 재생성할 때마다 +1, row는 새로 INSERT (UPDATE 금지)
	requested_by	UUID	NULL,
	title	VARCHAR(500)	NOT NULL,
	report_type	VARCHAR(50)	NOT NULL,
	status	VARCHAR(30)	NOT NULL,
	request_config	JSONB	NOT NULL,
	created_at	TIMESTAMPTZ	NOT NULL,
	updated_at	TIMESTAMPTZ	NOT NULL,
	completed_at	TIMESTAMPTZ	NULL
);


-- ------------------------------------------------------------
-- 2. artifacts (신규) — 보고서 산출물(md/pdf/pptx/docx)을 report 1:N으로 관리
-- ------------------------------------------------------------

CREATE TABLE artifacts (
	id	UUID	NOT NULL,
	report_id	UUID	NOT NULL,
	artifact_type	VARCHAR(20)	NOT NULL,	-- 'markdown' | 'pdf' | 'pptx' | 'docx'
	object_key	TEXT	NOT NULL,	-- 버전을 경로에 포함해서 저장 (하단 가이드 참고)
	version	INTEGER	NOT NULL,
	file_size	INTEGER	NULL,
	mime_type	VARCHAR(100)	NULL,
	created_by	UUID	NULL,
	created_at	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 3. pipeline_jobs (변경: workspace_id 추가)
-- ------------------------------------------------------------

CREATE TABLE pipeline_jobs (
	id	UUID	NOT NULL,
	workspace_id	UUID	NOT NULL,
	job_type	VARCHAR(50)	NOT NULL,
	target_type	VARCHAR(50)	NULL,
	target_id	UUID	NULL,
	status	VARCHAR(30)	NOT NULL,
	progress	INTEGER	NOT NULL,
	error_message	TEXT	NULL,
	requested_by	UUID	NULL,
	payload	JSONB	NOT NULL,
	result	JSONB	NULL,
	retry_count	INTEGER	NOT NULL,
	idempotency_key	VARCHAR(200)	NULL,
	started_at	TIMESTAMPTZ	NULL,
	completed_at	TIMESTAMPTZ	NULL,
	created_at	TIMESTAMPTZ	NOT NULL,
	updated_at	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 4. qmd_index_entries (변경 없음)
-- ------------------------------------------------------------

CREATE TABLE qmd_index_entries (
	id	UUID	NOT NULL,
	document_version_id	UUID	NULL,
	wiki_version_id	UUID	NULL,
	report_id	UUID	NULL,
	collection_name	VARCHAR(100)	NOT NULL,
	status	VARCHAR(30)	NOT NULL,
	qmd_uri	TEXT	NULL,
	qmd_docid	VARCHAR(20)	NULL,
	index_generation	INTEGER	NOT NULL,
	indexed_at	TIMESTAMPTZ	NULL,
	last_error	TEXT	NULL,
	created_at	TIMESTAMPTZ	NOT NULL,
	updated_at	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 5. wiki_page_sources (변경 없음)
-- ------------------------------------------------------------

CREATE TABLE wiki_page_sources (
	id	UUID	NOT NULL,
	wiki_version_id	UUID	NOT NULL,
	document_version_id	UUID	NOT NULL,
	claim_text	TEXT	NULL,
	source_start_line	INTEGER	NULL,
	source_end_line	INTEGER	NULL,
	support_type	VARCHAR(20)	NULL,
	citation_order	INTEGER	NULL,
	created_at	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 6. wiki_pages (변경: workspace_id 추가)
-- ------------------------------------------------------------

CREATE TABLE wiki_pages (
	id	UUID	NOT NULL,
	workspace_id	UUID	NOT NULL,
	parent_page_id	UUID	NULL,
	slug	VARCHAR(300)	NOT NULL,
	title	VARCHAR(500)	NOT NULL,
	page_type	VARCHAR(30)	NOT NULL,
	status	VARCHAR(30)	NOT NULL,
	review_policy	VARCHAR(20)	NOT NULL,
	current_version_id	UUID	NULL,
	published_at	TIMESTAMPTZ	NULL,
	created_at	TIMESTAMPTZ	NOT NULL,
	updated_at	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 7. profiles (변경: role 컬럼 제거 — 7/27 멘토링 지적사항, 권한은 workspace_members.role로 일원화)
-- ------------------------------------------------------------

CREATE TABLE profiles (
	id	UUID	NOT NULL,
	display_name	VARCHAR(100)	NOT NULL,
	department	VARCHAR(100)	NULL,
	created_at	TIMESTAMPTZ	NOT NULL,
	updated_at	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 8. sources (변경: workspace_id 추가)
-- ------------------------------------------------------------

CREATE TABLE sources (
	id	UUID	NOT NULL,
	workspace_id	UUID	NOT NULL,
	name	VARCHAR(200)	NOT NULL,
	source_type	VARCHAR(30)	NOT NULL,
	base_url	TEXT	NULL,
	reliability_score	DECIMAL(5,4)	NULL,
	config	JSONB	NOT NULL,
	enabled	BOOLEAN	NOT NULL,
	created_at	TIMESTAMPTZ	NOT NULL,
	updated_at	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 9. chat_messages (변경 없음)
-- ------------------------------------------------------------

CREATE TABLE chat_messages (
	id	UUID	NOT NULL,
	session_id	UUID	NOT NULL,
	role	VARCHAR(20)	NOT NULL,
	content	TEXT	NOT NULL,
	model_name	VARCHAR(100)	NULL,
	prompt_version	VARCHAR(50)	NULL,
	created_at	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 10. report_sections (변경 없음)
-- ------------------------------------------------------------

CREATE TABLE report_sections (
	id	UUID	NOT NULL,
	report_id	UUID	NOT NULL,
	section_order	INTEGER	NOT NULL,
	title	VARCHAR(500)	NOT NULL,
	content	TEXT	NULL,
	status	VARCHAR(30)	NOT NULL,
	model_name	VARCHAR(100)	NULL,
	prompt_version	VARCHAR(50)	NULL,
	generation_run_id	UUID	NULL,
	created_at	TIMESTAMPTZ	NOT NULL,
	updated_at	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 11. message_citations (변경 없음, CHECK만 하단 추가)
-- ------------------------------------------------------------

CREATE TABLE message_citations (
	id	UUID	NOT NULL,
	message_id	UUID	NOT NULL,
	document_version_id	UUID	NOT NULL,
	qmd_uri	TEXT	NULL,
	source_start_line	INTEGER	NULL,
	source_end_line	INTEGER	NULL,
	quoted_text	TEXT	NULL,
	relevance_score	DECIMAL(5,4)	NULL,
	citation_order	INTEGER	NULL,
	created_at	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 12. document_versions (변경 없음, UNIQUE만 하단 추가)
-- ------------------------------------------------------------

CREATE TABLE document_versions (
	id	UUID	NOT NULL,
	document_id	UUID	NOT NULL,
	version_no	INTEGER	NOT NULL,
	content_hash	VARCHAR(64)	NOT NULL,
	raw_object_key	TEXT	NULL,
	markdown_object_key	TEXT	NOT NULL,
	parser_version	VARCHAR(50)	NULL,
	language	VARCHAR(10)	NULL,
	created_at	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 13. report_citations (변경 없음, CHECK만 하단 추가)
-- ------------------------------------------------------------

CREATE TABLE report_citations (
	id	UUID	NOT NULL,
	section_id	UUID	NOT NULL,
	document_version_id	UUID	NOT NULL,
	source_start_line	INTEGER	NULL,
	source_end_line	INTEGER	NULL,
	quoted_text	TEXT	NULL,
	relevance_score	DECIMAL(5,4)	NULL,
	citation_order	INTEGER	NULL,
	created_at	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 14. documents (변경: workspace_id 추가)
-- ------------------------------------------------------------

CREATE TABLE documents (
	id	UUID	NOT NULL,
	workspace_id	UUID	NOT NULL,
	source_id	UUID	NULL,
	title	VARCHAR(500)	NOT NULL,
	canonical_url	TEXT	NULL,
	published_at	TIMESTAMPTZ	NULL,
	status	VARCHAR(30)	NOT NULL,
	uploaded_by	UUID	NULL,
	created_at	TIMESTAMPTZ	NOT NULL,
	updated_at	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 15. chat_sessions (변경: workspace_id 추가)
-- ------------------------------------------------------------

CREATE TABLE chat_sessions (
	id	UUID	NOT NULL,
	workspace_id	UUID	NOT NULL,
	user_id	UUID	NOT NULL,
	title	VARCHAR(500)	NULL,
	created_at	TIMESTAMPTZ	NOT NULL,
	updated_at	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 16. wiki_page_versions (변경 없음, UNIQUE/CHECK만 하단 추가)
-- ------------------------------------------------------------

CREATE TABLE wiki_page_versions (
	id	UUID	NOT NULL,
	page_id	UUID	NOT NULL,
	version_no	INTEGER	NOT NULL,
	markdown_object_key	TEXT	NOT NULL,
	content_hash	VARCHAR(64)	NOT NULL,
	change_summary	TEXT	NULL,
	created_by	UUID	NULL,
	review_status	VARCHAR(30)	NOT NULL,
	reviewed_by	UUID	NULL,
	reviewed_at	TIMESTAMPTZ	NULL,
	generated_by	VARCHAR(20)	NOT NULL,
	generator_model	VARCHAR(100)	NULL,
	generator_prompt_version	VARCHAR(50)	NULL,
	generation_run_id	UUID	NULL,
	validation_status	VARCHAR(30)	NOT NULL,
	confidence_score	DECIMAL(5,4)	NULL,
	created_at	TIMESTAMPTZ	NOT NULL
);


-- ============================================================
-- PRIMARY KEYS
-- ============================================================

ALTER TABLE workspaces ADD CONSTRAINT PK_WORKSPACES PRIMARY KEY (id);
ALTER TABLE workspace_members ADD CONSTRAINT PK_WORKSPACE_MEMBERS PRIMARY KEY (id);
ALTER TABLE artifacts ADD CONSTRAINT PK_ARTIFACTS PRIMARY KEY (id);
ALTER TABLE reports ADD CONSTRAINT PK_REPORTS PRIMARY KEY (id);
ALTER TABLE pipeline_jobs ADD CONSTRAINT PK_PIPELINE_JOBS PRIMARY KEY (id);
ALTER TABLE qmd_index_entries ADD CONSTRAINT PK_QMD_INDEX_ENTRIES PRIMARY KEY (id);
ALTER TABLE wiki_page_sources ADD CONSTRAINT PK_WIKI_PAGE_SOURCES PRIMARY KEY (id);
ALTER TABLE wiki_pages ADD CONSTRAINT PK_WIKI_PAGES PRIMARY KEY (id);
ALTER TABLE profiles ADD CONSTRAINT PK_PROFILES PRIMARY KEY (id);
ALTER TABLE sources ADD CONSTRAINT PK_SOURCES PRIMARY KEY (id);
ALTER TABLE chat_messages ADD CONSTRAINT PK_CHAT_MESSAGES PRIMARY KEY (id);
ALTER TABLE report_sections ADD CONSTRAINT PK_REPORT_SECTIONS PRIMARY KEY (id);
ALTER TABLE message_citations ADD CONSTRAINT PK_MESSAGE_CITATIONS PRIMARY KEY (id);
ALTER TABLE document_versions ADD CONSTRAINT PK_DOCUMENT_VERSIONS PRIMARY KEY (id);
ALTER TABLE report_citations ADD CONSTRAINT PK_REPORT_CITATIONS PRIMARY KEY (id);
ALTER TABLE documents ADD CONSTRAINT PK_DOCUMENTS PRIMARY KEY (id);
ALTER TABLE chat_sessions ADD CONSTRAINT PK_CHAT_SESSIONS PRIMARY KEY (id);
ALTER TABLE wiki_page_versions ADD CONSTRAINT PK_WIKI_PAGE_VERSIONS PRIMARY KEY (id);


-- ============================================================
-- FOREIGN KEYS (원본 SQL엔 없었지만, workspace 격리·이력 추적을 위해 명시)
-- ============================================================

-- profiles.id는 Supabase Auth 사용자와 1:1 — auth.users가 지워지면 profiles도 함께 정리
ALTER TABLE profiles ADD CONSTRAINT FK_PROFILES_AUTH_USER FOREIGN KEY (id) REFERENCES auth.users(id) ON DELETE CASCADE;

ALTER TABLE workspace_members ADD CONSTRAINT FK_WM_WORKSPACE FOREIGN KEY (workspace_id) REFERENCES workspaces(id);
ALTER TABLE workspace_members ADD CONSTRAINT FK_WM_USER FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;

ALTER TABLE sources ADD CONSTRAINT FK_SOURCES_WORKSPACE FOREIGN KEY (workspace_id) REFERENCES workspaces(id);
ALTER TABLE documents ADD CONSTRAINT FK_DOCUMENTS_WORKSPACE FOREIGN KEY (workspace_id) REFERENCES workspaces(id);
ALTER TABLE documents ADD CONSTRAINT FK_DOCUMENTS_SOURCE FOREIGN KEY (source_id) REFERENCES sources(id);
ALTER TABLE documents ADD CONSTRAINT FK_DOCUMENTS_UPLOADED_BY FOREIGN KEY (uploaded_by) REFERENCES profiles(id) ON DELETE SET NULL;
ALTER TABLE document_versions ADD CONSTRAINT FK_DV_DOCUMENT FOREIGN KEY (document_id) REFERENCES documents(id);

ALTER TABLE wiki_pages ADD CONSTRAINT FK_WIKI_PAGES_WORKSPACE FOREIGN KEY (workspace_id) REFERENCES workspaces(id);
ALTER TABLE wiki_pages ADD CONSTRAINT FK_WIKI_PAGES_PARENT FOREIGN KEY (parent_page_id) REFERENCES wiki_pages(id);
ALTER TABLE wiki_pages ADD CONSTRAINT FK_WIKI_PAGES_CURRENT_VERSION FOREIGN KEY (current_version_id) REFERENCES wiki_page_versions(id);
ALTER TABLE wiki_page_versions ADD CONSTRAINT FK_WPV_PAGE FOREIGN KEY (page_id) REFERENCES wiki_pages(id);
ALTER TABLE wiki_page_versions ADD CONSTRAINT FK_WPV_CREATED_BY FOREIGN KEY (created_by) REFERENCES profiles(id) ON DELETE SET NULL;
ALTER TABLE wiki_page_versions ADD CONSTRAINT FK_WPV_REVIEWED_BY FOREIGN KEY (reviewed_by) REFERENCES profiles(id) ON DELETE SET NULL;
ALTER TABLE wiki_page_sources ADD CONSTRAINT FK_WPS_WIKI_VERSION FOREIGN KEY (wiki_version_id) REFERENCES wiki_page_versions(id);
ALTER TABLE wiki_page_sources ADD CONSTRAINT FK_WPS_DOCUMENT_VERSION FOREIGN KEY (document_version_id) REFERENCES document_versions(id);

ALTER TABLE reports ADD CONSTRAINT FK_REPORTS_WORKSPACE FOREIGN KEY (workspace_id) REFERENCES workspaces(id);
ALTER TABLE reports ADD CONSTRAINT FK_REPORTS_REQUESTED_BY FOREIGN KEY (requested_by) REFERENCES profiles(id) ON DELETE SET NULL;
ALTER TABLE report_sections ADD CONSTRAINT FK_RS_REPORT FOREIGN KEY (report_id) REFERENCES reports(id);
ALTER TABLE report_citations ADD CONSTRAINT FK_RC_SECTION FOREIGN KEY (section_id) REFERENCES report_sections(id);
ALTER TABLE report_citations ADD CONSTRAINT FK_RC_DOCUMENT_VERSION FOREIGN KEY (document_version_id) REFERENCES document_versions(id);
ALTER TABLE artifacts ADD CONSTRAINT FK_ARTIFACTS_REPORT FOREIGN KEY (report_id) REFERENCES reports(id);
ALTER TABLE artifacts ADD CONSTRAINT FK_ARTIFACTS_CREATED_BY FOREIGN KEY (created_by) REFERENCES profiles(id) ON DELETE SET NULL;

ALTER TABLE chat_sessions ADD CONSTRAINT FK_CS_WORKSPACE FOREIGN KEY (workspace_id) REFERENCES workspaces(id);
ALTER TABLE chat_sessions ADD CONSTRAINT FK_CS_USER FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
ALTER TABLE chat_messages ADD CONSTRAINT FK_CM_SESSION FOREIGN KEY (session_id) REFERENCES chat_sessions(id);
ALTER TABLE message_citations ADD CONSTRAINT FK_MC_MESSAGE FOREIGN KEY (message_id) REFERENCES chat_messages(id);
ALTER TABLE message_citations ADD CONSTRAINT FK_MC_DOCUMENT_VERSION FOREIGN KEY (document_version_id) REFERENCES document_versions(id);

ALTER TABLE pipeline_jobs ADD CONSTRAINT FK_PJ_WORKSPACE FOREIGN KEY (workspace_id) REFERENCES workspaces(id);
ALTER TABLE pipeline_jobs ADD CONSTRAINT FK_PJ_REQUESTED_BY FOREIGN KEY (requested_by) REFERENCES profiles(id) ON DELETE SET NULL;

ALTER TABLE qmd_index_entries ADD CONSTRAINT FK_QMD_DOCUMENT_VERSION FOREIGN KEY (document_version_id) REFERENCES document_versions(id);
ALTER TABLE qmd_index_entries ADD CONSTRAINT FK_QMD_WIKI_VERSION FOREIGN KEY (wiki_version_id) REFERENCES wiki_page_versions(id);
ALTER TABLE qmd_index_entries ADD CONSTRAINT FK_QMD_REPORT FOREIGN KEY (report_id) REFERENCES reports(id);


-- ============================================================
-- UNIQUE 제약 (중복 방지)
-- ============================================================

ALTER TABLE workspaces ADD CONSTRAINT UQ_WORKSPACES_SLUG UNIQUE (slug);

ALTER TABLE workspace_members ADD CONSTRAINT UQ_WM_WORKSPACE_USER UNIQUE (workspace_id, user_id);

ALTER TABLE sources ADD CONSTRAINT UQ_SOURCES_WORKSPACE_NAME UNIQUE (workspace_id, name);

ALTER TABLE documents ADD CONSTRAINT UQ_DOCUMENTS_WORKSPACE_URL UNIQUE (workspace_id, canonical_url);

ALTER TABLE document_versions ADD CONSTRAINT UQ_DV_DOCUMENT_HASH UNIQUE (document_id, content_hash);
ALTER TABLE document_versions ADD CONSTRAINT UQ_DV_DOCUMENT_VERSIONNO UNIQUE (document_id, version_no);
ALTER TABLE document_versions ADD CONSTRAINT UQ_DV_MARKDOWN_OBJECT_KEY UNIQUE (markdown_object_key);

ALTER TABLE wiki_pages ADD CONSTRAINT UQ_WIKI_PAGES_WORKSPACE_SLUG UNIQUE (workspace_id, slug);

ALTER TABLE wiki_page_versions ADD CONSTRAINT UQ_WPV_PAGE_VERSIONNO UNIQUE (page_id, version_no);
ALTER TABLE wiki_page_versions ADD CONSTRAINT UQ_WPV_MARKDOWN_OBJECT_KEY UNIQUE (markdown_object_key);

ALTER TABLE reports ADD CONSTRAINT UQ_REPORTS_WORKSPACE_KEY_VERSION UNIQUE (workspace_id, report_key, version);

ALTER TABLE artifacts ADD CONSTRAINT UQ_ARTIFACTS_REPORT_TYPE_VERSION UNIQUE (report_id, artifact_type, version);
ALTER TABLE artifacts ADD CONSTRAINT UQ_ARTIFACTS_OBJECT_KEY UNIQUE (object_key);

ALTER TABLE pipeline_jobs ADD CONSTRAINT UQ_PJ_IDEMPOTENCY_KEY UNIQUE (idempotency_key);


-- ============================================================
-- CHECK 제약 (값 범위)
-- ============================================================

-- 권한 값 고정 (admin/editor/viewer 외 값 차단)
ALTER TABLE workspace_members ADD CONSTRAINT CK_WM_ROLE CHECK (role IN ('admin','editor','viewer'));
ALTER TABLE wiki_page_versions ADD CONSTRAINT CK_WPV_GENERATED_BY CHECK (generated_by IN ('human','llm'));

-- 진행률 0~100
ALTER TABLE pipeline_jobs ADD CONSTRAINT CK_PJ_PROGRESS CHECK (progress BETWEEN 0 AND 100);
ALTER TABLE pipeline_jobs ADD CONSTRAINT CK_PJ_RETRY_COUNT CHECK (retry_count >= 0);
ALTER TABLE pipeline_jobs ADD CONSTRAINT CK_PJ_STATUS CHECK (status IN ('pending','running','completed','failed','cancelled'));

-- 점수류 0~1
ALTER TABLE sources ADD CONSTRAINT CK_SOURCES_RELIABILITY CHECK (reliability_score BETWEEN 0 AND 1);
ALTER TABLE wiki_page_versions ADD CONSTRAINT CK_WPV_CONFIDENCE CHECK (confidence_score BETWEEN 0 AND 1);
ALTER TABLE message_citations ADD CONSTRAINT CK_MC_RELEVANCE CHECK (relevance_score BETWEEN 0 AND 1);
ALTER TABLE report_citations ADD CONSTRAINT CK_RC_RELEVANCE CHECK (relevance_score BETWEEN 0 AND 1);

-- 버전 번호는 1 이상
ALTER TABLE document_versions ADD CONSTRAINT CK_DV_VERSIONNO CHECK (version_no >= 1);
ALTER TABLE wiki_page_versions ADD CONSTRAINT CK_WPV_VERSIONNO CHECK (version_no >= 1);
ALTER TABLE reports ADD CONSTRAINT CK_REPORTS_VERSION CHECK (version >= 1);
ALTER TABLE artifacts ADD CONSTRAINT CK_ARTIFACTS_VERSION CHECK (version >= 1);

-- 상태값 enum 고정
ALTER TABLE documents ADD CONSTRAINT CK_DOCUMENTS_STATUS CHECK (status IN ('active','deleted','blocked','failed'));
ALTER TABLE wiki_pages ADD CONSTRAINT CK_WIKI_PAGES_STATUS CHECK (status IN ('draft','published','archived'));
ALTER TABLE wiki_page_versions ADD CONSTRAINT CK_WPV_REVIEW_STATUS CHECK (review_status IN ('pending','approved','rejected'));
ALTER TABLE wiki_page_versions ADD CONSTRAINT CK_WPV_VALIDATION_STATUS CHECK (validation_status IN ('pending','passed','failed'));
ALTER TABLE reports ADD CONSTRAINT CK_REPORTS_STATUS CHECK (status IN ('pending','generating','completed','failed'));
ALTER TABLE report_sections ADD CONSTRAINT CK_RS_STATUS CHECK (status IN ('pending','generating','completed','failed'));
ALTER TABLE qmd_index_entries ADD CONSTRAINT CK_QMD_STATUS CHECK (status IN ('pending','indexing','indexed','failed','stale'));
ALTER TABLE artifacts ADD CONSTRAINT CK_ARTIFACTS_TYPE CHECK (artifact_type IN ('markdown','pdf','pptx','docx'));


-- ============================================================
-- object_key 경로 설계 가이드 (DB 제약이 아니라 애플리케이션 규칙)
-- ============================================================
-- 모든 Storage 경로는 workspace/엔티티/버전을 경로 자체에 포함시켜서,
-- 같은 경로를 실수로 덮어쓰는 일이 없도록 합니다.
--
--   document_versions.markdown_object_key:
--     {workspace_id}/documents/{document_id}/v{version_no}-{content_hash}.md
--
--   wiki_page_versions.markdown_object_key:
--     {workspace_id}/wiki/{page_id}/v{version_no}-{content_hash}.md
--
--   artifacts.object_key:
--     {workspace_id}/reports/{report_id}/{artifact_type}/v{version}.{ext}
--
-- 위 UNIQUE(object_key) 제약이 안전장치 역할을 하므로,
-- 경로 규칙을 어기고 같은 키로 다시 쓰려고 하면 INSERT 시점에 바로 에러가 납니다.

-- ============================================================
-- RLS 정책 (라이브 DB에 적용 완료, 2026-07-29)
-- 원칙: workspace_members 기준으로 workspace 단위 격리.
--   실제 쓰기(수집/분석/보고서 생성 등)는 백엔드(src/api)가 service_role로 수행해
--   RLS를 우회하므로, 아래 정책은 기본적으로 "같은 workspace 멤버는 조회 가능"에
--   집중하고 profiles 본인수정 / workspace_members·workspaces 관리(admin)만
--   클라이언트 쓰기 정책을 추가했다.
-- ============================================================

-- workspace_members 자기참조로 인한 "infinite recursion detected in policy" 방지용
-- SECURITY DEFINER 헬퍼 함수 (Supabase 공식 권장 패턴)
CREATE OR REPLACE FUNCTION is_workspace_member(p_workspace_id uuid, p_user_id uuid DEFAULT auth.uid())
RETURNS boolean
LANGUAGE sql
SECURITY DEFINER
STABLE
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
SECURITY DEFINER
STABLE
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1 FROM workspace_members
    WHERE workspace_id = p_workspace_id AND user_id = p_user_id AND role = ANY(p_roles)
  );
$$;

-- anon(비로그인)이 헬퍼 함수를 /rest/v1/rpc/...로 직접 호출해 멤버십을 프로빙하지 못하도록 차단
-- (authenticated는 RLS 정책 평가 시 이 함수를 실제로 호출해야 하므로 유지)
REVOKE EXECUTE ON FUNCTION is_workspace_member(uuid, uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION has_workspace_role(uuid, text[], uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION is_workspace_member(uuid, uuid) TO authenticated;
GRANT EXECUTE ON FUNCTION has_workspace_role(uuid, text[], uuid) TO authenticated;

ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE wiki_pages ENABLE ROW LEVEL SECURITY;
ALTER TABLE wiki_page_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE wiki_page_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE report_sections ENABLE ROW LEVEL SECURITY;
ALTER TABLE report_citations ENABLE ROW LEVEL SECURITY;
ALTER TABLE artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE message_citations ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE qmd_index_entries ENABLE ROW LEVEL SECURITY;

CREATE POLICY profiles_select_own ON profiles FOR SELECT USING (id = auth.uid());
CREATE POLICY profiles_update_own ON profiles FOR UPDATE USING (id = auth.uid()) WITH CHECK (id = auth.uid());

CREATE POLICY workspaces_select_member ON workspaces FOR SELECT USING (is_workspace_member(id));
CREATE POLICY workspaces_update_admin ON workspaces FOR UPDATE USING (has_workspace_role(id, ARRAY['admin'])) WITH CHECK (has_workspace_role(id, ARRAY['admin']));

CREATE POLICY wm_select_same_workspace ON workspace_members FOR SELECT USING (is_workspace_member(workspace_id));
CREATE POLICY wm_insert_admin ON workspace_members FOR INSERT WITH CHECK (has_workspace_role(workspace_id, ARRAY['admin']));
CREATE POLICY wm_update_admin ON workspace_members FOR UPDATE USING (has_workspace_role(workspace_id, ARRAY['admin'])) WITH CHECK (has_workspace_role(workspace_id, ARRAY['admin']));
CREATE POLICY wm_delete_admin ON workspace_members FOR DELETE USING (has_workspace_role(workspace_id, ARRAY['admin']));

CREATE POLICY sources_select ON sources FOR SELECT USING (is_workspace_member(workspace_id));
CREATE POLICY documents_select ON documents FOR SELECT USING (is_workspace_member(workspace_id));
CREATE POLICY wiki_pages_select ON wiki_pages FOR SELECT USING (is_workspace_member(workspace_id));
CREATE POLICY reports_select ON reports FOR SELECT USING (is_workspace_member(workspace_id));
CREATE POLICY chat_sessions_select ON chat_sessions FOR SELECT USING (is_workspace_member(workspace_id));
CREATE POLICY pipeline_jobs_select ON pipeline_jobs FOR SELECT USING (is_workspace_member(workspace_id));

CREATE POLICY document_versions_select ON document_versions FOR SELECT USING (
  EXISTS (SELECT 1 FROM documents d WHERE d.id = document_versions.document_id AND is_workspace_member(d.workspace_id))
);

CREATE POLICY wiki_page_versions_select ON wiki_page_versions FOR SELECT USING (
  EXISTS (SELECT 1 FROM wiki_pages p WHERE p.id = wiki_page_versions.page_id AND is_workspace_member(p.workspace_id))
);

CREATE POLICY wiki_page_sources_select ON wiki_page_sources FOR SELECT USING (
  EXISTS (
    SELECT 1 FROM wiki_page_versions wpv
    JOIN wiki_pages p ON p.id = wpv.page_id
    WHERE wpv.id = wiki_page_sources.wiki_version_id AND is_workspace_member(p.workspace_id)
  )
);

CREATE POLICY report_sections_select ON report_sections FOR SELECT USING (
  EXISTS (SELECT 1 FROM reports r WHERE r.id = report_sections.report_id AND is_workspace_member(r.workspace_id))
);

CREATE POLICY report_citations_select ON report_citations FOR SELECT USING (
  EXISTS (
    SELECT 1 FROM report_sections rs
    JOIN reports r ON r.id = rs.report_id
    WHERE rs.id = report_citations.section_id AND is_workspace_member(r.workspace_id)
  )
);

CREATE POLICY artifacts_select ON artifacts FOR SELECT USING (
  EXISTS (SELECT 1 FROM reports r WHERE r.id = artifacts.report_id AND is_workspace_member(r.workspace_id))
);

CREATE POLICY chat_messages_select ON chat_messages FOR SELECT USING (
  EXISTS (SELECT 1 FROM chat_sessions cs WHERE cs.id = chat_messages.session_id AND is_workspace_member(cs.workspace_id))
);

CREATE POLICY message_citations_select ON message_citations FOR SELECT USING (
  EXISTS (
    SELECT 1 FROM chat_messages cm
    JOIN chat_sessions cs ON cs.id = cm.session_id
    WHERE cm.id = message_citations.message_id AND is_workspace_member(cs.workspace_id)
  )
);

CREATE POLICY qmd_index_entries_select ON qmd_index_entries FOR SELECT USING (
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
-- 회원가입 시 profiles 자동 생성 트리거 (라이브 DB에 적용 완료, 2026-07-29)
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
-- updated_at 자동 갱신 트리거 (라이브 DB 적용 완료, 2026-07-29)
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

CREATE TRIGGER trg_workspaces_updated_at BEFORE UPDATE ON workspaces FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER trg_profiles_updated_at BEFORE UPDATE ON profiles FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER trg_sources_updated_at BEFORE UPDATE ON sources FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER trg_documents_updated_at BEFORE UPDATE ON documents FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER trg_wiki_pages_updated_at BEFORE UPDATE ON wiki_pages FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER trg_reports_updated_at BEFORE UPDATE ON reports FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER trg_report_sections_updated_at BEFORE UPDATE ON report_sections FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER trg_chat_sessions_updated_at BEFORE UPDATE ON chat_sessions FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER trg_pipeline_jobs_updated_at BEFORE UPDATE ON pipeline_jobs FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER trg_qmd_index_entries_updated_at BEFORE UPDATE ON qmd_index_entries FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


-- ============================================================
-- Storage 버킷 (라이브 DB 적용 완료, 2026-07-29)
-- object_key 경로 가이드 기준: raw / processed / wiki, 전부 비공개
-- ============================================================
INSERT INTO storage.buckets (id, name, public)
VALUES
  ('raw', 'raw', false),
  ('processed', 'processed', false),
  ('wiki', 'wiki', false)
ON CONFLICT (id) DO NOTHING;


-- ============================================================
-- [참고] 이 파일 밖에서 처리해야 하는 것 (SQL로 불가능, Dashboard/외부 설정 필요)
-- ============================================================
-- 1) Google OAuth 로그인: Google Cloud Console에서 OAuth Client 생성 후,
--    Supabase Dashboard > Authentication > Providers > Google 에 Client ID/Secret 입력 필요.
--    Redirect URI는 Supabase 대시보드 Google Provider 페이지에 표시되는 콜백 URL 사용.
-- 2) 이메일/비밀번호 로그인: Supabase 기본 활성화 상태라 별도 작업 불필요 (끈 적 없으면 그대로 동작).
-- 3) 소셜로그인·이메일 로그인 계정 자동 연결(같은 이메일이면 한 계정으로): Supabase Auth 기본 동작.
--    이메일이 검증된 상태라면 별도 코드/설정 없이 자동으로 동일 계정에 identity가 연결됨.
-- 4) 스키마를 public 외로 분리할 계획이 있다면 Project Settings > API > Exposed schemas 등록 필요 (현재는 계획 없음, public만 사용)

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
-- ============================================================


-- ------------------------------------------------------------
-- 0. workspace 관련 (신규)
-- ------------------------------------------------------------

CREATE TABLE `workspaces` (
	`id`	UUID	NOT NULL,
	`name`	VARCHAR(200)	NOT NULL,
	`slug`	VARCHAR(100)	NOT NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL,
	`updated_at`	TIMESTAMPTZ	NOT NULL
);

CREATE TABLE `workspace_members` (
	`id`	UUID	NOT NULL,
	`workspace_id`	UUID	NOT NULL,
	`user_id`	UUID	NOT NULL,
	`role`	VARCHAR(20)	NOT NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 1. reports (변경: markdown_object_key/pdf_object_key 제거, 버전 필드 추가)
-- ------------------------------------------------------------

CREATE TABLE `reports` (
	`id`	UUID	NOT NULL,
	`workspace_id`	UUID	NOT NULL,
	`report_key`	VARCHAR(200)	NOT NULL,	-- 같은 보고서 계열을 묶는 키 (예: "daily-semiconductor-trend")
	`version`	INTEGER	NOT NULL,	-- 재생성할 때마다 +1, row는 새로 INSERT (UPDATE 금지)
	`requested_by`	UUID	NULL,
	`title`	VARCHAR(500)	NOT NULL,
	`report_type`	VARCHAR(50)	NOT NULL,
	`status`	VARCHAR(30)	NOT NULL,
	`request_config`	JSONB	NOT NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL,
	`updated_at`	TIMESTAMPTZ	NOT NULL,
	`completed_at`	TIMESTAMPTZ	NULL
);


-- ------------------------------------------------------------
-- 2. artifacts (신규) — 보고서 산출물(md/pdf/pptx/docx)을 report 1:N으로 관리
-- ------------------------------------------------------------

CREATE TABLE `artifacts` (
	`id`	UUID	NOT NULL,
	`report_id`	UUID	NOT NULL,
	`artifact_type`	VARCHAR(20)	NOT NULL,	-- 'markdown' | 'pdf' | 'pptx' | 'docx'
	`object_key`	TEXT	NOT NULL,	-- 버전을 경로에 포함해서 저장 (하단 가이드 참고)
	`version`	INTEGER	NOT NULL,
	`file_size`	INTEGER	NULL,
	`mime_type`	VARCHAR(100)	NULL,
	`created_by`	UUID	NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 3. pipeline_jobs (변경: workspace_id 추가)
-- ------------------------------------------------------------

CREATE TABLE `pipeline_jobs` (
	`id`	UUID	NOT NULL,
	`workspace_id`	UUID	NOT NULL,
	`job_type`	VARCHAR(50)	NOT NULL,
	`target_type`	VARCHAR(50)	NULL,
	`target_id`	UUID	NULL,
	`status`	VARCHAR(30)	NOT NULL,
	`progress`	INTEGER	NOT NULL,
	`error_message`	TEXT	NULL,
	`requested_by`	UUID	NULL,
	`payload`	JSONB	NOT NULL,
	`result`	JSONB	NULL,
	`retry_count`	INTEGER	NOT NULL,
	`idempotency_key`	VARCHAR(200)	NULL,
	`started_at`	TIMESTAMPTZ	NULL,
	`completed_at`	TIMESTAMPTZ	NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL,
	`updated_at`	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 4. qmd_index_entries (변경 없음)
-- ------------------------------------------------------------

CREATE TABLE `qmd_index_entries` (
	`id`	UUID	NOT NULL,
	`document_version_id`	UUID	NULL,
	`wiki_version_id`	UUID	NULL,
	`report_id`	UUID	NULL,
	`collection_name`	VARCHAR(100)	NOT NULL,
	`status`	VARCHAR(30)	NOT NULL,
	`qmd_uri`	TEXT	NULL,
	`qmd_docid`	VARCHAR(20)	NULL,
	`index_generation`	INTEGER	NOT NULL,
	`indexed_at`	TIMESTAMPTZ	NULL,
	`last_error`	TEXT	NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL,
	`updated_at`	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 5. wiki_page_sources (변경 없음)
-- ------------------------------------------------------------

CREATE TABLE `wiki_page_sources` (
	`id`	UUID	NOT NULL,
	`wiki_version_id`	UUID	NOT NULL,
	`document_version_id`	UUID	NOT NULL,
	`claim_text`	TEXT	NULL,
	`source_start_line`	INTEGER	NULL,
	`source_end_line`	INTEGER	NULL,
	`support_type`	VARCHAR(20)	NULL,
	`citation_order`	INTEGER	NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 6. wiki_pages (변경: workspace_id 추가)
-- ------------------------------------------------------------

CREATE TABLE `wiki_pages` (
	`id`	UUID	NOT NULL,
	`workspace_id`	UUID	NOT NULL,
	`parent_page_id`	UUID	NULL,
	`slug`	VARCHAR(300)	NOT NULL,
	`title`	VARCHAR(500)	NOT NULL,
	`page_type`	VARCHAR(30)	NOT NULL,
	`status`	VARCHAR(30)	NOT NULL,
	`review_policy`	VARCHAR(20)	NOT NULL,
	`current_version_id`	UUID	NULL,
	`published_at`	TIMESTAMPTZ	NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL,
	`updated_at`	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 7. profiles (변경 없음)
-- ------------------------------------------------------------

CREATE TABLE `profiles` (
	`id`	UUID	NOT NULL,
	`display_name`	VARCHAR(100)	NOT NULL,
	`department`	VARCHAR(100)	NULL,
	`role`	VARCHAR(20)	NOT NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL,
	`updated_at`	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 8. sources (변경: workspace_id 추가)
-- ------------------------------------------------------------

CREATE TABLE `sources` (
	`id`	UUID	NOT NULL,
	`workspace_id`	UUID	NOT NULL,
	`name`	VARCHAR(200)	NOT NULL,
	`source_type`	VARCHAR(30)	NOT NULL,
	`base_url`	TEXT	NULL,
	`reliability_score`	DECIMAL(5,4)	NULL,
	`config`	JSONB	NOT NULL,
	`enabled`	BOOLEAN	NOT NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL,
	`updated_at`	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 9. chat_messages (변경 없음)
-- ------------------------------------------------------------

CREATE TABLE `chat_messages` (
	`id`	UUID	NOT NULL,
	`session_id`	UUID	NOT NULL,
	`role`	VARCHAR(20)	NOT NULL,
	`content`	TEXT	NOT NULL,
	`model_name`	VARCHAR(100)	NULL,
	`prompt_version`	VARCHAR(50)	NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 10. report_sections (변경 없음)
-- ------------------------------------------------------------

CREATE TABLE `report_sections` (
	`id`	UUID	NOT NULL,
	`report_id`	UUID	NOT NULL,
	`section_order`	INTEGER	NOT NULL,
	`title`	VARCHAR(500)	NOT NULL,
	`content`	TEXT	NULL,
	`status`	VARCHAR(30)	NOT NULL,
	`model_name`	VARCHAR(100)	NULL,
	`prompt_version`	VARCHAR(50)	NULL,
	`generation_run_id`	UUID	NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL,
	`updated_at`	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 11. message_citations (변경 없음, CHECK만 하단 추가)
-- ------------------------------------------------------------

CREATE TABLE `message_citations` (
	`id`	UUID	NOT NULL,
	`message_id`	UUID	NOT NULL,
	`document_version_id`	UUID	NOT NULL,
	`qmd_uri`	TEXT	NULL,
	`source_start_line`	INTEGER	NULL,
	`source_end_line`	INTEGER	NULL,
	`quoted_text`	TEXT	NULL,
	`relevance_score`	DECIMAL(5,4)	NULL,
	`citation_order`	INTEGER	NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 12. document_versions (변경 없음, UNIQUE만 하단 추가)
-- ------------------------------------------------------------

CREATE TABLE `document_versions` (
	`id`	UUID	NOT NULL,
	`document_id`	UUID	NOT NULL,
	`version_no`	INTEGER	NOT NULL,
	`content_hash`	VARCHAR(64)	NOT NULL,
	`raw_object_key`	TEXT	NULL,
	`markdown_object_key`	TEXT	NOT NULL,
	`parser_version`	VARCHAR(50)	NULL,
	`language`	VARCHAR(10)	NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 13. report_citations (변경 없음, CHECK만 하단 추가)
-- ------------------------------------------------------------

CREATE TABLE `report_citations` (
	`id`	UUID	NOT NULL,
	`section_id`	UUID	NOT NULL,
	`document_version_id`	UUID	NOT NULL,
	`source_start_line`	INTEGER	NULL,
	`source_end_line`	INTEGER	NULL,
	`quoted_text`	TEXT	NULL,
	`relevance_score`	DECIMAL(5,4)	NULL,
	`citation_order`	INTEGER	NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 14. documents (변경: workspace_id 추가)
-- ------------------------------------------------------------

CREATE TABLE `documents` (
	`id`	UUID	NOT NULL,
	`workspace_id`	UUID	NOT NULL,
	`source_id`	UUID	NULL,
	`title`	VARCHAR(500)	NOT NULL,
	`canonical_url`	TEXT	NULL,
	`published_at`	TIMESTAMPTZ	NULL,
	`status`	VARCHAR(30)	NOT NULL,
	`uploaded_by`	UUID	NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL,
	`updated_at`	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 15. chat_sessions (변경: workspace_id 추가)
-- ------------------------------------------------------------

CREATE TABLE `chat_sessions` (
	`id`	UUID	NOT NULL,
	`workspace_id`	UUID	NOT NULL,
	`user_id`	UUID	NOT NULL,
	`title`	VARCHAR(500)	NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL,
	`updated_at`	TIMESTAMPTZ	NOT NULL
);


-- ------------------------------------------------------------
-- 16. wiki_page_versions (변경 없음, UNIQUE/CHECK만 하단 추가)
-- ------------------------------------------------------------

CREATE TABLE `wiki_page_versions` (
	`id`	UUID	NOT NULL,
	`page_id`	UUID	NOT NULL,
	`version_no`	INTEGER	NOT NULL,
	`markdown_object_key`	TEXT	NOT NULL,
	`content_hash`	VARCHAR(64)	NOT NULL,
	`change_summary`	TEXT	NULL,
	`created_by`	UUID	NULL,
	`review_status`	VARCHAR(30)	NOT NULL,
	`reviewed_by`	UUID	NULL,
	`reviewed_at`	TIMESTAMPTZ	NULL,
	`generated_by`	VARCHAR(20)	NOT NULL,
	`generator_model`	VARCHAR(100)	NULL,
	`generator_prompt_version`	VARCHAR(50)	NULL,
	`generation_run_id`	UUID	NULL,
	`validation_status`	VARCHAR(30)	NOT NULL,
	`confidence_score`	DECIMAL(5,4)	NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL
);


-- ============================================================
-- PRIMARY KEYS
-- ============================================================

ALTER TABLE `workspaces` ADD CONSTRAINT `PK_WORKSPACES` PRIMARY KEY (`id`);
ALTER TABLE `workspace_members` ADD CONSTRAINT `PK_WORKSPACE_MEMBERS` PRIMARY KEY (`id`);
ALTER TABLE `artifacts` ADD CONSTRAINT `PK_ARTIFACTS` PRIMARY KEY (`id`);
ALTER TABLE `reports` ADD CONSTRAINT `PK_REPORTS` PRIMARY KEY (`id`);
ALTER TABLE `pipeline_jobs` ADD CONSTRAINT `PK_PIPELINE_JOBS` PRIMARY KEY (`id`);
ALTER TABLE `qmd_index_entries` ADD CONSTRAINT `PK_QMD_INDEX_ENTRIES` PRIMARY KEY (`id`);
ALTER TABLE `wiki_page_sources` ADD CONSTRAINT `PK_WIKI_PAGE_SOURCES` PRIMARY KEY (`id`);
ALTER TABLE `wiki_pages` ADD CONSTRAINT `PK_WIKI_PAGES` PRIMARY KEY (`id`);
ALTER TABLE `profiles` ADD CONSTRAINT `PK_PROFILES` PRIMARY KEY (`id`);
ALTER TABLE `sources` ADD CONSTRAINT `PK_SOURCES` PRIMARY KEY (`id`);
ALTER TABLE `chat_messages` ADD CONSTRAINT `PK_CHAT_MESSAGES` PRIMARY KEY (`id`);
ALTER TABLE `report_sections` ADD CONSTRAINT `PK_REPORT_SECTIONS` PRIMARY KEY (`id`);
ALTER TABLE `message_citations` ADD CONSTRAINT `PK_MESSAGE_CITATIONS` PRIMARY KEY (`id`);
ALTER TABLE `document_versions` ADD CONSTRAINT `PK_DOCUMENT_VERSIONS` PRIMARY KEY (`id`);
ALTER TABLE `report_citations` ADD CONSTRAINT `PK_REPORT_CITATIONS` PRIMARY KEY (`id`);
ALTER TABLE `documents` ADD CONSTRAINT `PK_DOCUMENTS` PRIMARY KEY (`id`);
ALTER TABLE `chat_sessions` ADD CONSTRAINT `PK_CHAT_SESSIONS` PRIMARY KEY (`id`);
ALTER TABLE `wiki_page_versions` ADD CONSTRAINT `PK_WIKI_PAGE_VERSIONS` PRIMARY KEY (`id`);


-- ============================================================
-- FOREIGN KEYS (원본 SQL엔 없었지만, workspace 격리·이력 추적을 위해 명시)
-- ============================================================

ALTER TABLE `workspace_members` ADD CONSTRAINT `FK_WM_WORKSPACE` FOREIGN KEY (`workspace_id`) REFERENCES `workspaces`(`id`);
ALTER TABLE `workspace_members` ADD CONSTRAINT `FK_WM_USER` FOREIGN KEY (`user_id`) REFERENCES `profiles`(`id`);

ALTER TABLE `sources` ADD CONSTRAINT `FK_SOURCES_WORKSPACE` FOREIGN KEY (`workspace_id`) REFERENCES `workspaces`(`id`);
ALTER TABLE `documents` ADD CONSTRAINT `FK_DOCUMENTS_WORKSPACE` FOREIGN KEY (`workspace_id`) REFERENCES `workspaces`(`id`);
ALTER TABLE `documents` ADD CONSTRAINT `FK_DOCUMENTS_SOURCE` FOREIGN KEY (`source_id`) REFERENCES `sources`(`id`);
ALTER TABLE `document_versions` ADD CONSTRAINT `FK_DV_DOCUMENT` FOREIGN KEY (`document_id`) REFERENCES `documents`(`id`);

ALTER TABLE `wiki_pages` ADD CONSTRAINT `FK_WIKI_PAGES_WORKSPACE` FOREIGN KEY (`workspace_id`) REFERENCES `workspaces`(`id`);
ALTER TABLE `wiki_pages` ADD CONSTRAINT `FK_WIKI_PAGES_PARENT` FOREIGN KEY (`parent_page_id`) REFERENCES `wiki_pages`(`id`);
ALTER TABLE `wiki_pages` ADD CONSTRAINT `FK_WIKI_PAGES_CURRENT_VERSION` FOREIGN KEY (`current_version_id`) REFERENCES `wiki_page_versions`(`id`);
ALTER TABLE `wiki_page_versions` ADD CONSTRAINT `FK_WPV_PAGE` FOREIGN KEY (`page_id`) REFERENCES `wiki_pages`(`id`);
ALTER TABLE `wiki_page_sources` ADD CONSTRAINT `FK_WPS_WIKI_VERSION` FOREIGN KEY (`wiki_version_id`) REFERENCES `wiki_page_versions`(`id`);
ALTER TABLE `wiki_page_sources` ADD CONSTRAINT `FK_WPS_DOCUMENT_VERSION` FOREIGN KEY (`document_version_id`) REFERENCES `document_versions`(`id`);

ALTER TABLE `reports` ADD CONSTRAINT `FK_REPORTS_WORKSPACE` FOREIGN KEY (`workspace_id`) REFERENCES `workspaces`(`id`);
ALTER TABLE `report_sections` ADD CONSTRAINT `FK_RS_REPORT` FOREIGN KEY (`report_id`) REFERENCES `reports`(`id`);
ALTER TABLE `report_citations` ADD CONSTRAINT `FK_RC_SECTION` FOREIGN KEY (`section_id`) REFERENCES `report_sections`(`id`);
ALTER TABLE `report_citations` ADD CONSTRAINT `FK_RC_DOCUMENT_VERSION` FOREIGN KEY (`document_version_id`) REFERENCES `document_versions`(`id`);
ALTER TABLE `artifacts` ADD CONSTRAINT `FK_ARTIFACTS_REPORT` FOREIGN KEY (`report_id`) REFERENCES `reports`(`id`);

ALTER TABLE `chat_sessions` ADD CONSTRAINT `FK_CS_WORKSPACE` FOREIGN KEY (`workspace_id`) REFERENCES `workspaces`(`id`);
ALTER TABLE `chat_sessions` ADD CONSTRAINT `FK_CS_USER` FOREIGN KEY (`user_id`) REFERENCES `profiles`(`id`);
ALTER TABLE `chat_messages` ADD CONSTRAINT `FK_CM_SESSION` FOREIGN KEY (`session_id`) REFERENCES `chat_sessions`(`id`);
ALTER TABLE `message_citations` ADD CONSTRAINT `FK_MC_MESSAGE` FOREIGN KEY (`message_id`) REFERENCES `chat_messages`(`id`);
ALTER TABLE `message_citations` ADD CONSTRAINT `FK_MC_DOCUMENT_VERSION` FOREIGN KEY (`document_version_id`) REFERENCES `document_versions`(`id`);

ALTER TABLE `pipeline_jobs` ADD CONSTRAINT `FK_PJ_WORKSPACE` FOREIGN KEY (`workspace_id`) REFERENCES `workspaces`(`id`);

ALTER TABLE `qmd_index_entries` ADD CONSTRAINT `FK_QMD_DOCUMENT_VERSION` FOREIGN KEY (`document_version_id`) REFERENCES `document_versions`(`id`);
ALTER TABLE `qmd_index_entries` ADD CONSTRAINT `FK_QMD_WIKI_VERSION` FOREIGN KEY (`wiki_version_id`) REFERENCES `wiki_page_versions`(`id`);
ALTER TABLE `qmd_index_entries` ADD CONSTRAINT `FK_QMD_REPORT` FOREIGN KEY (`report_id`) REFERENCES `reports`(`id`);


-- ============================================================
-- UNIQUE 제약 (중복 방지)
-- ============================================================

ALTER TABLE `workspace_members` ADD CONSTRAINT `UQ_WM_WORKSPACE_USER` UNIQUE (`workspace_id`, `user_id`);

ALTER TABLE `sources` ADD CONSTRAINT `UQ_SOURCES_WORKSPACE_NAME` UNIQUE (`workspace_id`, `name`);

ALTER TABLE `documents` ADD CONSTRAINT `UQ_DOCUMENTS_WORKSPACE_URL` UNIQUE (`workspace_id`, `canonical_url`);

ALTER TABLE `document_versions` ADD CONSTRAINT `UQ_DV_DOCUMENT_HASH` UNIQUE (`document_id`, `content_hash`);
ALTER TABLE `document_versions` ADD CONSTRAINT `UQ_DV_DOCUMENT_VERSIONNO` UNIQUE (`document_id`, `version_no`);
ALTER TABLE `document_versions` ADD CONSTRAINT `UQ_DV_MARKDOWN_OBJECT_KEY` UNIQUE (`markdown_object_key`);

ALTER TABLE `wiki_pages` ADD CONSTRAINT `UQ_WIKI_PAGES_WORKSPACE_SLUG` UNIQUE (`workspace_id`, `slug`);

ALTER TABLE `wiki_page_versions` ADD CONSTRAINT `UQ_WPV_PAGE_VERSIONNO` UNIQUE (`page_id`, `version_no`);
ALTER TABLE `wiki_page_versions` ADD CONSTRAINT `UQ_WPV_MARKDOWN_OBJECT_KEY` UNIQUE (`markdown_object_key`);

ALTER TABLE `reports` ADD CONSTRAINT `UQ_REPORTS_WORKSPACE_KEY_VERSION` UNIQUE (`workspace_id`, `report_key`, `version`);

ALTER TABLE `artifacts` ADD CONSTRAINT `UQ_ARTIFACTS_REPORT_TYPE_VERSION` UNIQUE (`report_id`, `artifact_type`, `version`);
ALTER TABLE `artifacts` ADD CONSTRAINT `UQ_ARTIFACTS_OBJECT_KEY` UNIQUE (`object_key`);

ALTER TABLE `pipeline_jobs` ADD CONSTRAINT `UQ_PJ_IDEMPOTENCY_KEY` UNIQUE (`idempotency_key`);


-- ============================================================
-- CHECK 제약 (값 범위)
-- ============================================================

-- 진행률 0~100
ALTER TABLE `pipeline_jobs` ADD CONSTRAINT `CK_PJ_PROGRESS` CHECK (`progress` BETWEEN 0 AND 100);
ALTER TABLE `pipeline_jobs` ADD CONSTRAINT `CK_PJ_RETRY_COUNT` CHECK (`retry_count` >= 0);
ALTER TABLE `pipeline_jobs` ADD CONSTRAINT `CK_PJ_STATUS` CHECK (`status` IN ('pending','running','completed','failed','cancelled'));

-- 점수류 0~1
ALTER TABLE `sources` ADD CONSTRAINT `CK_SOURCES_RELIABILITY` CHECK (`reliability_score` BETWEEN 0 AND 1);
ALTER TABLE `wiki_page_versions` ADD CONSTRAINT `CK_WPV_CONFIDENCE` CHECK (`confidence_score` BETWEEN 0 AND 1);
ALTER TABLE `message_citations` ADD CONSTRAINT `CK_MC_RELEVANCE` CHECK (`relevance_score` BETWEEN 0 AND 1);
ALTER TABLE `report_citations` ADD CONSTRAINT `CK_RC_RELEVANCE` CHECK (`relevance_score` BETWEEN 0 AND 1);

-- 버전 번호는 1 이상
ALTER TABLE `document_versions` ADD CONSTRAINT `CK_DV_VERSIONNO` CHECK (`version_no` >= 1);
ALTER TABLE `wiki_page_versions` ADD CONSTRAINT `CK_WPV_VERSIONNO` CHECK (`version_no` >= 1);
ALTER TABLE `reports` ADD CONSTRAINT `CK_REPORTS_VERSION` CHECK (`version` >= 1);
ALTER TABLE `artifacts` ADD CONSTRAINT `CK_ARTIFACTS_VERSION` CHECK (`version` >= 1);

-- 상태값 enum 고정
ALTER TABLE `documents` ADD CONSTRAINT `CK_DOCUMENTS_STATUS` CHECK (`status` IN ('active','deleted','blocked','failed'));
ALTER TABLE `wiki_pages` ADD CONSTRAINT `CK_WIKI_PAGES_STATUS` CHECK (`status` IN ('draft','published','archived'));
ALTER TABLE `wiki_page_versions` ADD CONSTRAINT `CK_WPV_REVIEW_STATUS` CHECK (`review_status` IN ('pending','approved','rejected'));
ALTER TABLE `wiki_page_versions` ADD CONSTRAINT `CK_WPV_VALIDATION_STATUS` CHECK (`validation_status` IN ('pending','passed','failed'));
ALTER TABLE `reports` ADD CONSTRAINT `CK_REPORTS_STATUS` CHECK (`status` IN ('pending','generating','completed','failed'));
ALTER TABLE `report_sections` ADD CONSTRAINT `CK_RS_STATUS` CHECK (`status` IN ('pending','generating','completed','failed'));
ALTER TABLE `qmd_index_entries` ADD CONSTRAINT `CK_QMD_STATUS` CHECK (`status` IN ('pending','indexing','indexed','failed','stale'));
ALTER TABLE `artifacts` ADD CONSTRAINT `CK_ARTIFACTS_TYPE` CHECK (`artifact_type` IN ('markdown','pdf','pptx','docx'));


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

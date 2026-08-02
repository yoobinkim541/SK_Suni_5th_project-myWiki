CREATE TABLE IF NOT EXISTS report_wiki_references (
    id               UUID         NOT NULL DEFAULT gen_random_uuid(),
    section_id       UUID         NOT NULL,
    wiki_page_id     UUID         NOT NULL,
    wiki_version_id  UUID         NOT NULL,
    reference_order  INTEGER      NOT NULL,
    relevance_score  NUMERIC(5,4),
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
);

ALTER TABLE report_wiki_references
    DROP CONSTRAINT IF EXISTS pk_report_wiki_references;
ALTER TABLE report_wiki_references
    ADD CONSTRAINT pk_report_wiki_references PRIMARY KEY (id);

ALTER TABLE report_wiki_references
    DROP CONSTRAINT IF EXISTS fk_rwr_section;
ALTER TABLE report_wiki_references
    ADD CONSTRAINT fk_rwr_section FOREIGN KEY (section_id) REFERENCES report_sections(id) ON DELETE CASCADE;

ALTER TABLE report_wiki_references
    DROP CONSTRAINT IF EXISTS fk_rwr_wiki_page;
ALTER TABLE report_wiki_references
    ADD CONSTRAINT fk_rwr_wiki_page FOREIGN KEY (wiki_page_id) REFERENCES wiki_pages(id);

ALTER TABLE report_wiki_references
    DROP CONSTRAINT IF EXISTS fk_rwr_wiki_version;
ALTER TABLE report_wiki_references
    ADD CONSTRAINT fk_rwr_wiki_version FOREIGN KEY (wiki_version_id) REFERENCES wiki_page_versions(id);

ALTER TABLE report_wiki_references
    DROP CONSTRAINT IF EXISTS uq_rwr_section_wiki_version;
ALTER TABLE report_wiki_references
    ADD CONSTRAINT uq_rwr_section_wiki_version UNIQUE (section_id, wiki_version_id);

ALTER TABLE report_wiki_references
    DROP CONSTRAINT IF EXISTS ck_rwr_relevance;
ALTER TABLE report_wiki_references
    ADD CONSTRAINT ck_rwr_relevance CHECK (relevance_score >= 0 AND relevance_score <= 1);

CREATE INDEX IF NOT EXISTS idx_report_wiki_references_section
ON report_wiki_references(section_id);

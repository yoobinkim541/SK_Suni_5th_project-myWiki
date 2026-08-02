ALTER TABLE report_sections
ADD COLUMN IF NOT EXISTS issue_key TEXT;

ALTER TABLE report_sections
DROP CONSTRAINT IF EXISTS uq_report_sections_report_issue;

ALTER TABLE report_sections
ADD CONSTRAINT uq_report_sections_report_issue
UNIQUE (report_id, issue_key);

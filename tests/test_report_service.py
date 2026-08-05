from __future__ import annotations

from datetime import date

from src.report import service as report_service


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, supabase: "FakeSupabase", name: str):
        self.supabase = supabase
        self.name = name
        self.rows = supabase.tables.get(name, [])
        self.eq_filters: list[tuple[str, object]] = []
        self.in_filters: list[tuple[str, set[object]]] = []
        self.order_field: str | None = None
        self.order_desc = False

    def select(self, _fields: str) -> "FakeTable":
        return self

    def eq(self, field: str, value: object) -> "FakeTable":
        self.eq_filters.append((field, value))
        return self

    def in_(self, field: str, values) -> "FakeTable":
        self.in_filters.append((field, set(values)))
        return self

    def order(self, field: str, desc: bool = False) -> "FakeTable":
        self.order_field = field
        self.order_desc = desc
        return self

    def execute(self) -> FakeResult:
        rows = self.rows
        for field, value in self.eq_filters:
            rows = [row for row in rows if row.get(field) == value]
        for field, values in self.in_filters:
            rows = [row for row in rows if row.get(field) in values]
        if self.order_field is not None:
            rows = sorted(rows, key=lambda row: row.get(self.order_field), reverse=self.order_desc)
        return FakeResult([dict(row) for row in rows])


class FakeSupabase:
    def __init__(self):
        self.tables = {
            "reports": [
                {
                    "id": "report-1",
                    "workspace_id": "ws-1",
                    "report_key": "daily:ws-1:2026-08-05",
                    "version": 1,
                    "title": "2026-08-05 ?? ???",
                    "report_type": "daily",
                    "status": "completed",
                    "created_at": "2026-08-05T09:00:00+09:00",
                    "completed_at": "2026-08-05T09:05:00+09:00",
                }
            ],
            "report_sections": [
                {
                    "id": "section-1",
                    "report_id": "report-1",
                    "issue_key": "issue-hbm",
                    "section_order": 1,
                    "title": "HBM ?? ??",
                    "content": '{"current_summary":"HBM ??? ???? ??.","key_facts":["?? ??"]}',
                    "status": "completed",
                    "model_name": "gpt-4.1-mini",
                    "prompt_version": "report-v1",
                    "created_at": "2026-08-05T09:01:00+09:00",
                    "updated_at": "2026-08-05T09:02:00+09:00",
                }
            ],
            "report_citations": [
                {
                    "id": "citation-1",
                    "section_id": "section-1",
                    "document_version_id": "doc-ver-1",
                    "source_start_line": 10,
                    "source_end_line": 12,
                    "quoted_text": "HBM demand is increasing.",
                    "relevance_score": 0.92,
                    "citation_order": 1,
                }
            ],
            "document_versions": [{"id": "doc-ver-1", "document_id": "doc-1"}],
            "documents": [
                {
                    "id": "doc-1",
                    "title": "HBM ?? ??",
                    "canonical_url": "https://example.com/hbm",
                    "published_at": "2026-08-05T08:00:00+09:00",
                    "source_id": "source-1",
                }
            ],
            "sources": [{"id": "source-1", "name": "GeekNews"}],
        }

    def table(self, name: str) -> FakeTable:
        return FakeTable(self, name)


def test_get_daily_report_returns_report_with_sections_and_citations() -> None:
    supabase = FakeSupabase()

    result = report_service.get_daily_report("ws-1", date(2026, 8, 5), supabase=supabase)

    assert result is not None
    assert result["report_id"] == "report-1"
    assert result["report_key"] == "daily:ws-1:2026-08-05"
    assert result["sections"][0]["issue_key"] == "issue-hbm"
    assert result["sections"][0]["content"]["current_summary"] == "HBM ??? ???? ??."
    assert result["sections"][0]["citations"][0]["document_title"] == "HBM ?? ??"
    assert result["sections"][0]["citations"][0]["source_name"] == "GeekNews"


def test_get_daily_report_returns_none_when_missing() -> None:
    supabase = FakeSupabase()
    supabase.tables["reports"] = []

    result = report_service.get_daily_report("ws-1", date(2026, 8, 5), supabase=supabase)

    assert result is None

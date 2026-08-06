from __future__ import annotations

from datetime import date

from src.report import service


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
        self.limit_count: int | None = None

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

    def limit(self, count: int) -> "FakeTable":
        self.limit_count = count
        return self

    def execute(self) -> FakeResult:
        rows = [dict(row) for row in self.rows]
        for field, value in self.eq_filters:
            rows = [row for row in rows if row.get(field) == value]
        for field, values in self.in_filters:
            rows = [row for row in rows if row.get(field) in values]
        if self.order_field is not None:
            rows = sorted(rows, key=lambda row: row.get(self.order_field), reverse=self.order_desc)
        if self.limit_count is not None:
            rows = rows[: self.limit_count]
        return FakeResult(rows)


class FakeSupabase:
    def __init__(self, tables: dict[str, list[dict[str, object]]]):
        self.tables = tables

    def table(self, name: str) -> FakeTable:
        return FakeTable(self, name)


def test_get_daily_report_enriches_citations_with_document_metadata() -> None:
    supabase = FakeSupabase(
        {
            "reports": [
                {
                    "id": "report-1",
                    "workspace_id": "ws-1",
                    "report_key": "daily:ws-1:2026-08-05",
                    "version": 2,
                    "title": "?? ?? ?? ???",
                    "report_type": "daily",
                    "status": "completed",
                    "created_at": "2026-08-05T09:00:00+09:00",
                    "completed_at": "2026-08-05T09:05:00+09:00",
                    "request_config": {"report_date": "2026-08-05"},
                }
            ],
            "report_sections": [
                {
                    "id": "section-1",
                    "report_id": "report-1",
                    "issue_key": "issue-1",
                    "section_order": 1,
                    "title": "HBM4 ?? ??",
                    "content": '{"category":"?????","importance_score":88,"current_summary":"??"}',
                    "status": "completed",
                    "model_name": "gpt-test",
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
                    "source_end_line": 18,
                    "quoted_text": "HBM4 demand is rising",
                    "relevance_score": 0.92,
                    "citation_order": 1,
                }
            ],
            "document_versions": [
                {
                    "id": "doc-ver-1",
                    "document_id": "doc-1",
                }
            ],
            "documents": [
                {
                    "id": "doc-1",
                    "title": "SK hynix HBM4 roadmap",
                    "canonical_url": "https://example.com/hbm4",
                    "published_at": "2026-08-05T07:30:00+09:00",
                    "source_id": "source-1",
                }
            ],
            "sources": [
                {
                    "id": "source-1",
                    "name": "????",
                }
            ],
        }
    )

    report = service.get_daily_report(
        "ws-1",
        date(2026, 8, 5),
        supabase=supabase,
    )

    assert report is not None
    citation = report["sections"][0]["citations"][0]
    assert citation["document_title"] == "SK hynix HBM4 roadmap"
    assert citation["source_url"] == "https://example.com/hbm4"
    assert citation["source_name"] == "????"
    assert citation["published_at"] == "2026-08-05T07:30:00+09:00"


def test_get_daily_report_keeps_citation_when_document_metadata_is_missing() -> None:
    supabase = FakeSupabase(
        {
            "reports": [
                {
                    "id": "report-1",
                    "workspace_id": "ws-1",
                    "report_key": "daily:ws-1:2026-08-05",
                    "version": 1,
                    "title": "?? ?? ?? ???",
                    "report_type": "daily",
                    "status": "completed",
                    "created_at": "2026-08-05T09:00:00+09:00",
                    "completed_at": "2026-08-05T09:05:00+09:00",
                    "request_config": {"report_date": "2026-08-05"},
                }
            ],
            "report_sections": [
                {
                    "id": "section-1",
                    "report_id": "report-1",
                    "issue_key": "issue-1",
                    "section_order": 1,
                    "title": "HBM4 ?? ??",
                    "content": "{}",
                    "status": "completed",
                    "model_name": None,
                    "prompt_version": None,
                    "created_at": None,
                    "updated_at": None,
                }
            ],
            "report_citations": [
                {
                    "id": "citation-1",
                    "section_id": "section-1",
                    "document_version_id": "doc-ver-missing",
                    "source_start_line": None,
                    "source_end_line": None,
                    "quoted_text": "quoted",
                    "relevance_score": 0.5,
                    "citation_order": 1,
                }
            ],
            "document_versions": [],
            "documents": [],
            "sources": [],
        }
    )

    report = service.get_daily_report(
        "ws-1",
        date(2026, 8, 5),
        supabase=supabase,
    )

    assert report is not None
    citation = report["sections"][0]["citations"][0]
    assert citation["document_version_id"] == "doc-ver-missing"
    assert citation["document_title"] is None
    assert citation["source_url"] is None
    assert citation["source_name"] is None
    assert citation["published_at"] is None

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
        self.table_calls: list[str] = []

    def table(self, name: str) -> FakeTable:
        self.table_calls.append(name)
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


def _history_report(
    report_id: str,
    *,
    workspace_id: str = "ws-1",
    report_date: str = "2026-08-05",
    version: int = 1,
    status: str = "completed",
    request_config: object | None = None,
):
    return {
        "id": report_id,
        "workspace_id": workspace_id,
        "report_key": f"daily:{workspace_id}:{report_date}",
        "version": version,
        "title": f"Daily {report_date} v{version}",
        "report_type": "daily",
        "status": status,
        "request_config": request_config if request_config is not None else {"report_date": report_date},
        "created_at": f"{report_date}T09:00:00+09:00",
        "completed_at": f"{report_date}T09:05:00+09:00",
    }


def test_get_daily_report_history_returns_latest_completed_by_date_with_batch_counts() -> None:
    supabase = FakeSupabase(
        {
            "reports": [
                _history_report("r-0808-v1", report_date="2026-08-08", version=1),
                _history_report("r-0808-v2", report_date="2026-08-08", version=2),
                _history_report("r-0807-v3", report_date="2026-08-07", version=3),
                _history_report("r-0809-v1", report_date="2026-08-09", version=1),
            ],
            "report_sections": [
                {"id": "s1", "report_id": "r-0808-v2", "issue_key": "issue-1"},
                {"id": "s2", "report_id": "r-0808-v2", "issue_key": "issue-2"},
                {"id": "s3", "report_id": "r-0808-v2", "issue_key": None},
                {"id": "s4", "report_id": "r-0807-v3", "issue_key": "issue-3"},
                {"id": "s5", "report_id": "r-0809-v1", "issue_key": "issue-4"},
            ],
            "artifacts": [
                {"id": "a1", "report_id": "r-0808-v2", "artifact_type": "pdf", "version": 2},
                {"id": "a2", "report_id": "r-0808-v2", "artifact_type": "docx", "version": 2},
                {"id": "a3", "report_id": "r-0809-v1", "artifact_type": "pptx", "version": 1},
            ],
        }
    )

    history = service.get_daily_report_history("ws-1", supabase=supabase)

    assert [item["date"] for item in history] == ["2026-08-09", "2026-08-08", "2026-08-07"]
    assert [item["report_id"] for item in history] == ["r-0809-v1", "r-0808-v2", "r-0807-v3"]
    assert history[1]["issue_count"] == 2
    assert history[1]["has_pdf"] is True
    assert history[1]["has_docx"] is True
    assert history[1]["has_pptx"] is False
    assert supabase.table_calls == ["reports", "report_sections", "artifacts"]


def test_get_daily_report_history_ignores_failed_newer_version() -> None:
    supabase = FakeSupabase(
        {
            "reports": [
                _history_report("completed-v3", report_date="2026-08-08", version=3),
                _history_report("failed-v4", report_date="2026-08-08", version=4, status="failed"),
            ],
            "report_sections": [],
            "artifacts": [],
        }
    )

    history = service.get_daily_report_history("ws-1", supabase=supabase)

    assert len(history) == 1
    assert history[0]["report_id"] == "completed-v3"
    assert history[0]["version"] == 3


def test_get_daily_report_history_filters_workspace_and_applies_limit_after_grouping() -> None:
    supabase = FakeSupabase(
        {
            "reports": [
                _history_report("ws1-0808-v1", workspace_id="ws-1", report_date="2026-08-08", version=1),
                _history_report("ws1-0808-v2", workspace_id="ws-1", report_date="2026-08-08", version=2),
                _history_report("ws1-0807-v1", workspace_id="ws-1", report_date="2026-08-07", version=1),
                _history_report("ws1-0806-v1", workspace_id="ws-1", report_date="2026-08-06", version=1),
                _history_report("ws2-0809-v1", workspace_id="ws-2", report_date="2026-08-09", version=1),
            ],
            "report_sections": [],
            "artifacts": [],
        }
    )

    history = service.get_daily_report_history("ws-1", limit=2, supabase=supabase)

    assert [(item["date"], item["report_id"]) for item in history] == [
        ("2026-08-08", "ws1-0808-v2"),
        ("2026-08-07", "ws1-0807-v1"),
    ]


def test_get_daily_report_history_skips_malformed_report_date_without_failing() -> None:
    malformed = _history_report("malformed", report_date="2026-08-10", version=1, request_config={"report_date": "not-a-date"})
    malformed["report_key"] = "daily:ws-1:not-a-date"
    missing_config = _history_report("fallback", report_date="2026-08-09", version=1, request_config={})
    supabase = FakeSupabase(
        {
            "reports": [malformed, missing_config],
            "report_sections": [],
            "artifacts": [],
        }
    )

    history = service.get_daily_report_history("ws-1", supabase=supabase)

    assert len(history) == 1
    assert history[0]["report_id"] == "fallback"
    assert history[0]["date"] == "2026-08-09"

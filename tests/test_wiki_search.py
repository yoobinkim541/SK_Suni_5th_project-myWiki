from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.analysis.models import Category
from src.wiki.interface import add_wiki_version, search_wiki_contexts, upsert_wiki_page
from src.wiki.models import WikiSearchRequest
from src.wiki.repository import WikiSearchError


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeStorageBucket:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects

    def download(self, object_key: str) -> bytes:
        if object_key not in self.objects:
            raise FileNotFoundError(object_key)
        return self.objects[object_key]


class FakeStorage:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects

    def from_(self, _bucket: str) -> FakeStorageBucket:
        return FakeStorageBucket(self.objects)


class FakeTable:
    def __init__(self, supabase: "FakeSupabase", name: str):
        self.supabase = supabase
        self.name = name
        self.rows = [dict(row) for row in supabase.tables.get(name, [])]
        self.eq_filters: list[tuple[str, object]] = []
        self.in_filters: list[tuple[str, set[object]]] = []
        self.ordering: list[tuple[str, bool]] = []
        self.row_limit: int | None = None

    def select(self, _fields: str) -> "FakeTable":
        self.supabase.query_log.append(("select", self.name))
        return self

    def eq(self, field: str, value: object) -> "FakeTable":
        self.eq_filters.append((field, value))
        return self

    def in_(self, field: str, values: list[object]) -> "FakeTable":
        self.in_filters.append((field, set(values)))
        return self

    def order(self, field: str, desc: bool = False) -> "FakeTable":
        self.ordering.append((field, desc))
        return self

    def limit(self, value: int) -> "FakeTable":
        self.row_limit = value
        return self

    def execute(self) -> FakeResult:
        rows = self.rows
        for field, value in self.eq_filters:
            rows = [row for row in rows if row.get(field) == value]
        for field, values in self.in_filters:
            rows = [row for row in rows if row.get(field) in values]
        for field, desc in reversed(self.ordering):
            rows.sort(key=lambda row: _sort_value(row.get(field)), reverse=desc)
        if self.row_limit is not None:
            rows = rows[: self.row_limit]
        return FakeResult(rows)


class FakeSupabase:
    def __init__(self, tables: dict[str, list[dict[str, object]]], objects: dict[str, bytes]):
        self.tables = tables
        self.storage = FakeStorage(objects)
        self.query_log: list[tuple[str, str]] = []

    def table(self, name: str) -> FakeTable:
        return FakeTable(self, name)


def test_existing_wiki_write_interfaces_still_export() -> None:
    assert callable(upsert_wiki_page)
    assert callable(add_wiki_version)


def test_search_request_requires_query_or_query_terms() -> None:
    with pytest.raises(ValueError, match="query or query_terms"):
        WikiSearchRequest(workspace_id="ws-1", query=" ", query_terms=(), limit=1)


def test_search_request_rejects_empty_workspace_id() -> None:
    with pytest.raises(ValueError, match="workspace_id"):
        WikiSearchRequest(workspace_id=" ", query="hbm", limit=1)


def test_search_request_rejects_non_positive_limit() -> None:
    with pytest.raises(ValueError):
        WikiSearchRequest(workspace_id="ws-1", query="hbm", limit=0)


def test_search_request_deduplicates_query_terms() -> None:
    request = WikiSearchRequest(
        workspace_id="ws-1",
        query="HBM",
        query_terms=("HBM", "HBM", "SK hynix", "SK hynix"),
        limit=3,
    )

    assert request.query_terms == ("HBM", "SK hynix")


def test_search_wiki_contexts_returns_only_latest_current_version_per_page() -> None:
    supabase = FakeSupabase(
        tables={
            "wiki_pages": [
                {
                    "id": "page-1",
                    "workspace_id": "ws-1",
                    "title": "HBM roadmap",
                    "status": "published",
                    "current_version_id": "ver-1b",
                    "updated_at": "2026-08-02T09:00:00+00:00",
                }
            ],
            "wiki_page_versions": [
                {
                    "id": "ver-1a",
                    "page_id": "page-1",
                    "version_no": 1,
                    "markdown_object_key": "wiki/ws-1/page-1/1.md",
                    "created_at": "2026-08-01T09:00:00+00:00",
                },
                {
                    "id": "ver-1b",
                    "page_id": "page-1",
                    "version_no": 2,
                    "markdown_object_key": "wiki/ws-1/page-1/2.md",
                    "created_at": "2026-08-02T09:00:00+00:00",
                },
            ],
            "wiki_page_sources": [
                {"wiki_version_id": "ver-1b", "document_version_id": "doc-ver-1", "citation_order": 1}
            ],
        },
        objects={
            "wiki/ws-1/page-1/2.md": b"HBM3E and SK hynix roadmap details",
        },
    )

    results = search_wiki_contexts(
        WikiSearchRequest(
            workspace_id="ws-1",
            query="HBM3E roadmap",
            query_terms=("hbm3e", "roadmap"),
            category=Category.PRODUCT_TECHNOLOGY,
            limit=3,
        ),
        supabase=supabase,
    )

    assert len(results) == 1
    assert results[0].wiki_page_id == "page-1"
    assert results[0].wiki_version_id == "ver-1b"
    assert results[0].content == "HBM3E and SK hynix roadmap details"
    assert results[0].source_document_version_ids == ["doc-ver-1"]


def test_search_wiki_contexts_is_workspace_scoped() -> None:
    supabase = FakeSupabase(
        tables={
            "wiki_pages": [
                {
                    "id": "page-1",
                    "workspace_id": "ws-1",
                    "title": "HBM update",
                    "status": "published",
                    "current_version_id": "ver-1",
                    "updated_at": "2026-08-02T09:00:00+00:00",
                },
                {
                    "id": "page-2",
                    "workspace_id": "ws-2",
                    "title": "HBM update",
                    "status": "published",
                    "current_version_id": "ver-2",
                    "updated_at": "2026-08-02T10:00:00+00:00",
                },
            ],
            "wiki_page_versions": [
                {
                    "id": "ver-1",
                    "page_id": "page-1",
                    "version_no": 1,
                    "markdown_object_key": "one.md",
                    "created_at": "2026-08-02T09:00:00+00:00",
                },
                {
                    "id": "ver-2",
                    "page_id": "page-2",
                    "version_no": 1,
                    "markdown_object_key": "two.md",
                    "created_at": "2026-08-02T10:00:00+00:00",
                },
            ],
            "wiki_page_sources": [],
        },
        objects={
            "one.md": b"HBM content",
            "two.md": b"HBM content",
        },
    )

    results = search_wiki_contexts(
        WikiSearchRequest(workspace_id="ws-1", query="HBM", query_terms=("hbm",), limit=5),
        supabase=supabase,
    )

    assert [result.wiki_page_id for result in results] == ["page-1"]


def test_search_wiki_contexts_orders_by_relevance_then_recency_then_id() -> None:
    supabase = FakeSupabase(
        tables={
            "wiki_pages": [
                {
                    "id": "page-a",
                    "workspace_id": "ws-1",
                    "title": "HBM3E demand outlook",
                    "status": "published",
                    "current_version_id": "ver-a",
                    "updated_at": "2026-08-02T08:00:00+00:00",
                },
                {
                    "id": "page-b",
                    "workspace_id": "ws-1",
                    "title": "HBM3E",
                    "status": "published",
                    "current_version_id": "ver-b",
                    "updated_at": "2026-08-02T09:00:00+00:00",
                },
                {
                    "id": "page-c",
                    "workspace_id": "ws-1",
                    "title": "Unrelated memory",
                    "status": "published",
                    "current_version_id": "ver-c",
                    "updated_at": "2026-08-02T10:00:00+00:00",
                },
            ],
            "wiki_page_versions": [
                {"id": "ver-a", "page_id": "page-a", "version_no": 1, "markdown_object_key": "a.md", "created_at": "2026-08-02T08:00:00+00:00"},
                {"id": "ver-b", "page_id": "page-b", "version_no": 1, "markdown_object_key": "b.md", "created_at": "2026-08-02T09:00:00+00:00"},
                {"id": "ver-c", "page_id": "page-c", "version_no": 1, "markdown_object_key": "c.md", "created_at": "2026-08-02T10:00:00+00:00"},
            ],
            "wiki_page_sources": [],
        },
        objects={
            "a.md": b"HBM3E demand outlook for AI servers",
            "b.md": b"HBM3E only",
            "c.md": b"legacy DRAM history",
        },
    )

    results = search_wiki_contexts(
        WikiSearchRequest(
            workspace_id="ws-1",
            query="HBM3E demand",
            query_terms=("hbm3e", "demand"),
            limit=5,
        ),
        supabase=supabase,
    )

    assert [result.wiki_page_id for result in results] == ["page-a", "page-b"]
    assert results[0].score > results[1].score


def test_search_wiki_contexts_excludes_zero_overlap_pages() -> None:
    supabase = FakeSupabase(
        tables={
            "wiki_pages": [
                {
                    "id": "page-1",
                    "workspace_id": "ws-1",
                    "title": "Auto market",
                    "status": "published",
                    "current_version_id": "ver-1",
                    "updated_at": "2026-08-02T09:00:00+00:00",
                }
            ],
            "wiki_page_versions": [
                {"id": "ver-1", "page_id": "page-1", "version_no": 1, "markdown_object_key": "one.md", "created_at": "2026-08-02T09:00:00+00:00"}
            ],
            "wiki_page_sources": [],
        },
        objects={"one.md": b"automotive supply chain update"},
    )

    results = search_wiki_contexts(
        WikiSearchRequest(workspace_id="ws-1", query="HBM", query_terms=("hbm",), limit=5),
        supabase=supabase,
    )

    assert results == []


def test_search_wiki_contexts_applies_limit() -> None:
    supabase = FakeSupabase(
        tables={
            "wiki_pages": [
                {
                    "id": f"page-{index}",
                    "workspace_id": "ws-1",
                    "title": f"HBM page {index}",
                    "status": "published",
                    "current_version_id": f"ver-{index}",
                    "updated_at": f"2026-08-02T0{index}:00:00+00:00",
                }
                for index in range(1, 4)
            ],
            "wiki_page_versions": [
                {
                    "id": f"ver-{index}",
                    "page_id": f"page-{index}",
                    "version_no": 1,
                    "markdown_object_key": f"{index}.md",
                    "created_at": f"2026-08-02T0{index}:00:00+00:00",
                }
                for index in range(1, 4)
            ],
            "wiki_page_sources": [],
        },
        objects={f"{index}.md": f"HBM{index}".encode("utf-8") for index in range(1, 4)},
    )

    results = search_wiki_contexts(
        WikiSearchRequest(workspace_id="ws-1", query="HBM", query_terms=("hbm",), limit=2),
        supabase=supabase,
    )

    assert len(results) == 2


def test_search_wiki_contexts_keeps_result_order_deterministic_when_scores_tie() -> None:
    supabase = FakeSupabase(
        tables={
            "wiki_pages": [
                {
                    "id": "page-b",
                    "workspace_id": "ws-1",
                    "title": "HBM overview",
                    "status": "published",
                    "current_version_id": "ver-b",
                    "updated_at": "2026-08-02T09:00:00+00:00",
                },
                {
                    "id": "page-a",
                    "workspace_id": "ws-1",
                    "title": "HBM overview",
                    "status": "published",
                    "current_version_id": "ver-a",
                    "updated_at": "2026-08-02T09:00:00+00:00",
                },
            ],
            "wiki_page_versions": [
                {"id": "ver-a", "page_id": "page-a", "version_no": 1, "markdown_object_key": "a.md", "created_at": "2026-08-02T09:00:00+00:00"},
                {"id": "ver-b", "page_id": "page-b", "version_no": 1, "markdown_object_key": "b.md", "created_at": "2026-08-02T09:00:00+00:00"},
            ],
            "wiki_page_sources": [],
        },
        objects={
            "a.md": b"HBM overview",
            "b.md": b"HBM overview",
        },
    )

    results = search_wiki_contexts(
        WikiSearchRequest(workspace_id="ws-1", query="HBM", query_terms=("hbm",), limit=5),
        supabase=supabase,
    )

    assert [result.wiki_page_id for result in results] == ["page-a", "page-b"]


def test_search_wiki_contexts_avoids_n_plus_one_db_queries() -> None:
    supabase = FakeSupabase(
        tables={
            "wiki_pages": [
                {
                    "id": "page-1",
                    "workspace_id": "ws-1",
                    "title": "HBM",
                    "status": "published",
                    "current_version_id": "ver-1",
                    "updated_at": "2026-08-02T09:00:00+00:00",
                },
                {
                    "id": "page-2",
                    "workspace_id": "ws-1",
                    "title": "HBM roadmap",
                    "status": "published",
                    "current_version_id": "ver-2",
                    "updated_at": "2026-08-02T10:00:00+00:00",
                },
            ],
            "wiki_page_versions": [
                {"id": "ver-1", "page_id": "page-1", "version_no": 1, "markdown_object_key": "1.md", "created_at": "2026-08-02T09:00:00+00:00"},
                {"id": "ver-2", "page_id": "page-2", "version_no": 1, "markdown_object_key": "2.md", "created_at": "2026-08-02T10:00:00+00:00"},
            ],
            "wiki_page_sources": [
                {"wiki_version_id": "ver-1", "document_version_id": "doc-1", "citation_order": 1},
                {"wiki_version_id": "ver-2", "document_version_id": "doc-2", "citation_order": 1},
            ],
        },
        objects={"1.md": b"HBM", "2.md": b"HBM roadmap"},
    )

    results = search_wiki_contexts(
        WikiSearchRequest(workspace_id="ws-1", query="HBM", query_terms=("hbm",), limit=5),
        supabase=supabase,
    )

    assert len(results) == 2
    assert supabase.query_log.count(("select", "wiki_pages")) == 1
    assert supabase.query_log.count(("select", "wiki_page_versions")) == 1
    assert supabase.query_log.count(("select", "wiki_page_sources")) == 1


def test_search_wiki_contexts_wraps_lookup_failures_as_wiki_search_error() -> None:
    supabase = FakeSupabase(
        tables={
            "wiki_pages": [
                {
                    "id": "page-1",
                    "workspace_id": "ws-1",
                    "title": "HBM",
                    "status": "published",
                    "current_version_id": "ver-1",
                    "updated_at": "2026-08-02T09:00:00+00:00",
                }
            ],
            "wiki_page_versions": [
                {"id": "ver-1", "page_id": "page-1", "version_no": 1, "markdown_object_key": "missing.md", "created_at": "2026-08-02T09:00:00+00:00"}
            ],
            "wiki_page_sources": [],
        },
        objects={},
    )

    with pytest.raises(WikiSearchError):
        search_wiki_contexts(
            WikiSearchRequest(workspace_id="ws-1", query="HBM", query_terms=("hbm",), limit=5),
            supabase=supabase,
        )


def _sort_value(value: object) -> object:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    return value

"""src/wiki/query.py의 _get_related_pages() 단위 테스트 — DB는 FakeTable로 대체한다."""
from __future__ import annotations

from src.wiki.interface import WikiRelatedPage
from src.wiki.query import _get_related_pages

WORKSPACE_ID = "ws-1"
CURRENT_PAGE_ID = "page-current"
CURRENT_VERSION_ID = "v-current"


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []

    def select(self, _fields):
        return self

    def eq(self, field, value):
        self.filters.append(("eq", field, value))
        return self

    def neq(self, field, value):
        self.filters.append(("neq", field, value))
        return self

    def in_(self, field, values):
        self.filters.append(("in", field, set(values)))
        return self

    def execute(self):
        rows = self.rows
        for op, field, value in self.filters:
            if op == "eq":
                rows = [r for r in rows if r.get(field) == value]
            elif op == "neq":
                rows = [r for r in rows if r.get(field) != value]
            elif op == "in":
                rows = [r for r in rows if r.get(field) in value]
        return FakeResult([dict(r) for r in rows])


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return FakeTable(self.tables[name])


def test_no_document_version_ids_returns_empty_without_querying():
    db = FakeSupabase({"wiki_page_sources": [], "wiki_pages": []})
    result = _get_related_pages(db, WORKSPACE_ID, CURRENT_PAGE_ID, CURRENT_VERSION_ID, [])
    assert result == ()


def test_shared_source_document_links_to_other_published_page():
    db = FakeSupabase(
        {
            "wiki_page_sources": [
                {"wiki_version_id": "v-other-1", "document_version_id": "doc-1"},
                {"wiki_version_id": "v-other-1", "document_version_id": "doc-2"},
                {"wiki_version_id": CURRENT_VERSION_ID, "document_version_id": "doc-1"},
            ],
            "wiki_pages": [
                {
                    "id": "page-other-1",
                    "workspace_id": WORKSPACE_ID,
                    "status": "published",
                    "slug": "other-1",
                    "title": "Other 1",
                    "page_type": "company",
                    "current_version_id": "v-other-1",
                }
            ],
        }
    )
    result = _get_related_pages(
        db, WORKSPACE_ID, CURRENT_PAGE_ID, CURRENT_VERSION_ID, ["doc-1", "doc-2"]
    )
    assert result == (
        WikiRelatedPage(
            page_id="page-other-1",
            slug="other-1",
            title="Other 1",
            page_type="company",
            shared_source_count=2,
        ),
    )


def test_duplicate_citations_of_same_document_count_once():
    db = FakeSupabase(
        {
            "wiki_page_sources": [
                {"wiki_version_id": "v-other-1", "document_version_id": "doc-1"},
                {"wiki_version_id": "v-other-1", "document_version_id": "doc-1"},
            ],
            "wiki_pages": [
                {
                    "id": "page-other-1",
                    "workspace_id": WORKSPACE_ID,
                    "status": "published",
                    "slug": "other-1",
                    "title": "Other 1",
                    "page_type": "company",
                    "current_version_id": "v-other-1",
                }
            ],
        }
    )
    result = _get_related_pages(db, WORKSPACE_ID, CURRENT_PAGE_ID, CURRENT_VERSION_ID, ["doc-1"])
    assert len(result) == 1
    assert result[0].shared_source_count == 1


def test_stale_version_not_current_is_excluded():
    db = FakeSupabase(
        {
            "wiki_page_sources": [
                {"wiki_version_id": "v-stale", "document_version_id": "doc-1"},
            ],
            "wiki_pages": [
                {
                    "id": "page-other-1",
                    "workspace_id": WORKSPACE_ID,
                    "status": "published",
                    "slug": "other-1",
                    "title": "Other 1",
                    "page_type": "company",
                    "current_version_id": "v-other-1-newer",
                }
            ],
        }
    )
    result = _get_related_pages(db, WORKSPACE_ID, CURRENT_PAGE_ID, CURRENT_VERSION_ID, ["doc-1"])
    assert result == ()


def test_other_workspace_page_is_excluded():
    db = FakeSupabase(
        {
            "wiki_page_sources": [
                {"wiki_version_id": "v-other-1", "document_version_id": "doc-1"},
            ],
            "wiki_pages": [
                {
                    "id": "page-other-1",
                    "workspace_id": "ws-2",
                    "status": "published",
                    "slug": "other-1",
                    "title": "Other 1",
                    "page_type": "company",
                    "current_version_id": "v-other-1",
                }
            ],
        }
    )
    result = _get_related_pages(db, WORKSPACE_ID, CURRENT_PAGE_ID, CURRENT_VERSION_ID, ["doc-1"])
    assert result == ()


def test_sorted_desc_and_limited():
    db = FakeSupabase(
        {
            "wiki_page_sources": [
                {"wiki_version_id": "v-a", "document_version_id": "doc-1"},
                {"wiki_version_id": "v-b", "document_version_id": "doc-1"},
                {"wiki_version_id": "v-b", "document_version_id": "doc-2"},
                {"wiki_version_id": "v-b", "document_version_id": "doc-3"},
                {"wiki_version_id": "v-c", "document_version_id": "doc-1"},
                {"wiki_version_id": "v-c", "document_version_id": "doc-2"},
            ],
            "wiki_pages": [
                {
                    "id": "page-a", "workspace_id": WORKSPACE_ID, "status": "published",
                    "slug": "a", "title": "A", "page_type": "company", "current_version_id": "v-a",
                },
                {
                    "id": "page-b", "workspace_id": WORKSPACE_ID, "status": "published",
                    "slug": "b", "title": "B", "page_type": "company", "current_version_id": "v-b",
                },
                {
                    "id": "page-c", "workspace_id": WORKSPACE_ID, "status": "published",
                    "slug": "c", "title": "C", "page_type": "company", "current_version_id": "v-c",
                },
            ],
        }
    )
    result = _get_related_pages(
        db, WORKSPACE_ID, CURRENT_PAGE_ID, CURRENT_VERSION_ID, ["doc-1", "doc-2", "doc-3"], limit=2
    )
    assert [r.slug for r in result] == ["b", "c"]
    assert [r.shared_source_count for r in result] == [3, 2]

"""src/wiki/query.py의 list_published_wiki_pages() 단위 테스트 — DB는 FakeTable로 대체한다."""
from __future__ import annotations

from src.wiki import query as wiki_query

WORKSPACE_ID = "ws-1"


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []
        self.in_filters = []
        self.ilike_filters = []
        self._limit = None
        self._offset = None
        self._selected_fields = None

    def select(self, fields):
        self._selected_fields = [f.strip() for f in fields.split(",")]
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def in_(self, field, values):
        self.in_filters.append((field, set(values)))
        return self

    def ilike(self, field, pattern):
        self.ilike_filters.append((field, pattern))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def offset(self, n):
        self._offset = n
        return self

    def execute(self):
        rows = self.rows
        for field, value in self.filters:
            rows = [r for r in rows if r.get(field) == value]
        for field, values in self.in_filters:
            rows = [r for r in rows if r.get(field) in values]
        result_rows = []
        for row in rows:
            if self._selected_fields:
                result_rows.append({k: v for k, v in row.items() if k in self._selected_fields})
            else:
                result_rows.append(dict(row))
        return FakeResult(result_rows)


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return FakeTable(self.tables.get(name, []))


def test_list_published_wiki_pages_filters_by_keyword(monkeypatch):
    db = FakeSupabase({
        "wiki_pages": [
            {"id": "page-1", "workspace_id": WORKSPACE_ID, "slug": "hbm4", "title": "HBM4", "page_type": "technology",
             "status": "published", "parent_page_id": None, "published_at": "2026-08-01T00:00:00Z"},
            {"id": "page-2", "workspace_id": WORKSPACE_ID, "slug": "supply", "title": "공급망", "page_type": "supply_chain",
             "status": "published", "parent_page_id": None, "published_at": "2026-08-01T00:00:00Z"},
        ],
        "wiki_page_keywords": [{"page_id": "page-1", "keyword": "HBM"}],
    })
    monkeypatch.setattr(wiki_query, "_get_client", lambda: db)

    results = wiki_query.list_published_wiki_pages(WORKSPACE_ID, keyword="HBM")

    assert [r.slug for r in results] == ["hbm4"]


def test_list_published_wiki_pages_keyword_no_match_returns_empty(monkeypatch):
    db = FakeSupabase({
        "wiki_pages": [
            {"id": "page-1", "workspace_id": WORKSPACE_ID, "slug": "hbm4", "title": "HBM4", "page_type": "technology",
             "status": "published", "parent_page_id": None, "published_at": "2026-08-01T00:00:00Z"},
        ],
        "wiki_page_keywords": [],
    })
    monkeypatch.setattr(wiki_query, "_get_client", lambda: db)

    results = wiki_query.list_published_wiki_pages(WORKSPACE_ID, keyword="수출통제")

    assert results == []

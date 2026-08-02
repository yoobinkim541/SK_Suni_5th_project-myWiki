from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.wiki.generation_repository import (
    archive_wiki_page,
    find_stale_published_page_ids,
    get_wiki_page_identity,
    list_top_level_topic_pages,
)


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, supabase, name):
        self.supabase = supabase
        self.name = name
        self.rows = supabase.tables.setdefault(name, [])
        self.filters = []
        self.is_filters = []
        self.update_payload = None
        self._limit = None

    def select(self, _fields):
        return self

    def limit(self, value):
        self._limit = value
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def is_(self, field, value):
        self.is_filters.append((field, value))
        return self

    def in_(self, field, values):
        values = set(values)
        self.filters.append((field, values))
        return self

    def lt(self, field, value):
        self.filters.append((f"lt:{field}", value))
        return self

    def update(self, payload):
        self.update_payload = dict(payload)
        return self

    def execute(self):
        if self.update_payload is not None:
            for row in self._filtered_rows():
                row.update(self.update_payload)
            return FakeResult([dict(row) for row in self._filtered_rows()])
        rows = self._filtered_rows()
        if self._limit is not None:
            rows = rows[: self._limit]
        return FakeResult([dict(row) for row in rows])

    def _filtered_rows(self):
        rows = self.rows
        for field, value in self.is_filters:
            rows = [row for row in rows if row.get(field) is value]
        for field, value in self.filters:
            if isinstance(field, str) and field.startswith("lt:"):
                real_field = field[3:]
                rows = [row for row in rows if row.get(real_field) is not None and row[real_field] < value]
            elif isinstance(value, set):
                rows = [row for row in rows if row.get(field) in value]
            else:
                rows = [row for row in rows if row.get(field) == value]
        return rows


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return FakeTable(self, name)


def test_list_top_level_topic_pages_excludes_issue_and_child_pages():
    supabase = FakeSupabase(
        {
            "wiki_pages": [
                {"id": "p1", "workspace_id": "ws-1", "title": "SK하이닉스", "page_type": "company", "parent_page_id": None, "status": "published"},
                {"id": "p2", "workspace_id": "ws-1", "title": "HBM4", "page_type": "technology", "parent_page_id": "p1", "status": "published"},
                {"id": "p3", "workspace_id": "ws-1", "title": "이슈 2026-08-02", "page_type": "issue", "parent_page_id": None, "status": "published"},
                {"id": "p4", "workspace_id": "ws-1", "title": "미공개 주제", "page_type": "industry", "parent_page_id": None, "status": "draft"},
            ]
        }
    )
    pages = list_top_level_topic_pages("ws-1", supabase=supabase)
    assert [page.wiki_page_id for page in pages] == ["p1"]


def test_find_stale_published_page_ids_only_returns_pages_past_threshold():
    now = datetime.now(timezone.utc)
    stale_time = (now - timedelta(days=91)).isoformat()
    fresh_time = (now - timedelta(days=10)).isoformat()
    supabase = FakeSupabase(
        {
            "wiki_pages": [
                {"id": "p1", "workspace_id": "ws-1", "status": "published", "current_version_id": "v1"},
                {"id": "p2", "workspace_id": "ws-1", "status": "published", "current_version_id": "v2"},
                {"id": "p3", "workspace_id": "ws-1", "status": "draft", "current_version_id": "v3"},
            ],
            "wiki_page_versions": [
                {"id": "v1", "page_id": "p1", "created_at": stale_time},
                {"id": "v2", "page_id": "p2", "created_at": fresh_time},
                {"id": "v3", "page_id": "p3", "created_at": stale_time},
            ],
        }
    )
    stale_ids = find_stale_published_page_ids("ws-1", staleness_days=90, supabase=supabase)
    assert stale_ids == ["p1"]


def test_find_stale_published_page_ids_excludes_other_workspaces():
    now = datetime.now(timezone.utc)
    stale_time = (now - timedelta(days=91)).isoformat()
    supabase = FakeSupabase(
        {
            "wiki_pages": [
                {"id": "p1", "workspace_id": "ws-1", "status": "published", "current_version_id": "v1"},
                {"id": "p2", "workspace_id": "ws-2", "status": "published", "current_version_id": "v2"},
            ],
            "wiki_page_versions": [
                {"id": "v1", "page_id": "p1", "created_at": stale_time},
                {"id": "v2", "page_id": "p2", "created_at": stale_time},
            ],
        }
    )
    stale_ids = find_stale_published_page_ids("ws-1", staleness_days=90, supabase=supabase)
    assert stale_ids == ["p1"]


def test_archive_wiki_page_sets_status_archived():
    supabase = FakeSupabase(
        {"wiki_pages": [{"id": "p1", "workspace_id": "ws-1", "status": "published"}]}
    )
    archive_wiki_page("p1", supabase=supabase)
    assert supabase.tables["wiki_pages"][0]["status"] == "archived"


def test_get_wiki_page_identity_returns_slug_title_type_parent():
    supabase = FakeSupabase(
        {
            "wiki_pages": [
                {
                    "id": "page-existing",
                    "slug": "hbm4-supply",
                    "title": "HBM4_수급현황",
                    "page_type": "technology",
                    "parent_page_id": "page-parent",
                }
            ]
        }
    )
    identity = get_wiki_page_identity("page-existing", supabase=supabase)
    assert identity is not None
    assert identity.slug == "hbm4-supply"
    assert identity.title == "HBM4_수급현황"
    assert identity.page_type == "technology"
    assert identity.parent_page_id == "page-parent"


def test_get_wiki_page_identity_returns_none_when_missing():
    supabase = FakeSupabase({"wiki_pages": []})
    assert get_wiki_page_identity("page-missing", supabase=supabase) is None

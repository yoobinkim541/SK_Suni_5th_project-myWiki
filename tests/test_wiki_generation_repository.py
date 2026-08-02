from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.wiki.generation_repository import (
    archive_wiki_page,
    filter_to_topic_page_ids,
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


def test_find_stale_published_page_ids_keeps_parent_of_live_child():
    """오래됐어도 살아있는 자식이 가리키는 부모는 아카이빙 대상에서 제외한다."""
    now = datetime.now(timezone.utc)
    stale_time = (now - timedelta(days=91)).isoformat()
    supabase = FakeSupabase(
        {
            "wiki_pages": [
                {"id": "parent", "workspace_id": "ws-1", "status": "published", "current_version_id": "v1", "parent_page_id": None},
                {"id": "child", "workspace_id": "ws-1", "status": "published", "current_version_id": "v2", "parent_page_id": "parent"},
            ],
            "wiki_page_versions": [
                {"id": "v1", "page_id": "parent", "created_at": stale_time},
                {"id": "v2", "page_id": "child", "created_at": stale_time},
            ],
        }
    )
    stale_ids = find_stale_published_page_ids("ws-1", staleness_days=90, supabase=supabase)
    assert stale_ids == ["child"]


def test_find_stale_published_page_ids_archives_parent_when_children_archived():
    """자식이 이미 모두 archived이면 부모도 아카이빙 대상이 된다."""
    now = datetime.now(timezone.utc)
    stale_time = (now - timedelta(days=91)).isoformat()
    supabase = FakeSupabase(
        {
            "wiki_pages": [
                {"id": "parent", "workspace_id": "ws-1", "status": "published", "current_version_id": "v1", "parent_page_id": None},
                {"id": "child", "workspace_id": "ws-1", "status": "archived", "current_version_id": "v2", "parent_page_id": "parent"},
                {"id": "lonely", "workspace_id": "ws-1", "status": "published", "current_version_id": "v3", "parent_page_id": None},
            ],
            "wiki_page_versions": [
                {"id": "v1", "page_id": "parent", "created_at": stale_time},
                {"id": "v2", "page_id": "child", "created_at": stale_time},
                {"id": "v3", "page_id": "lonely", "created_at": stale_time},
            ],
        }
    )
    stale_ids = find_stale_published_page_ids("ws-1", staleness_days=90, supabase=supabase)
    assert stale_ids == ["parent", "lonely"]


def test_filter_to_topic_page_ids_drops_issue_pages():
    supabase = FakeSupabase(
        {
            "wiki_pages": [
                {"id": "p1", "workspace_id": "ws-1", "page_type": "technology"},
                {"id": "p2", "workspace_id": "ws-1", "page_type": "issue"},
                {"id": "p3", "workspace_id": "ws-1", "page_type": "company"},
            ]
        }
    )
    assert filter_to_topic_page_ids(["p1", "p2", "p3"], workspace_id="ws-1", supabase=supabase) == {"p1", "p3"}


def test_filter_to_topic_page_ids_excludes_other_workspaces_and_unknown_ids():
    supabase = FakeSupabase(
        {
            "wiki_pages": [
                {"id": "p1", "workspace_id": "ws-1", "page_type": "technology"},
                {"id": "p2", "workspace_id": "ws-2", "page_type": "technology"},
            ]
        }
    )
    assert filter_to_topic_page_ids(
        ["p1", "p2", "p-missing"], workspace_id="ws-1", supabase=supabase
    ) == {"p1"}


def test_filter_to_topic_page_ids_returns_empty_without_querying():
    class ExplodingSupabase:
        def table(self, name):  # pragma: no cover - 호출되면 안 된다
            raise AssertionError("빈 입력에서는 조회하지 않아야 한다.")

    assert filter_to_topic_page_ids([], workspace_id="ws-1", supabase=ExplodingSupabase()) == set()


def test_archive_wiki_page_sets_status_archived():
    supabase = FakeSupabase(
        {"wiki_pages": [{"id": "p1", "workspace_id": "ws-1", "status": "published"}]}
    )
    archive_wiki_page("p1", supabase=supabase)
    assert supabase.tables["wiki_pages"][0]["status"] == "archived"


def _identity_supabase(page_type: str = "technology", workspace_id: str = "ws-1") -> FakeSupabase:
    return FakeSupabase(
        {
            "wiki_pages": [
                {
                    "id": "page-existing",
                    "workspace_id": workspace_id,
                    "slug": "hbm4-supply",
                    "title": "HBM4_수급현황",
                    "page_type": page_type,
                    "parent_page_id": "page-parent",
                }
            ]
        }
    )


def test_get_wiki_page_identity_returns_slug_title_type_parent():
    identity = get_wiki_page_identity("page-existing", workspace_id="ws-1", supabase=_identity_supabase())
    assert identity is not None
    assert identity.slug == "hbm4-supply"
    assert identity.title == "HBM4_수급현황"
    assert identity.page_type == "technology"
    assert identity.parent_page_id == "page-parent"


def test_get_wiki_page_identity_returns_none_when_missing():
    supabase = FakeSupabase({"wiki_pages": []})
    assert get_wiki_page_identity("page-missing", workspace_id="ws-1", supabase=supabase) is None


def test_get_wiki_page_identity_returns_none_for_other_workspace():
    """다른 workspace의 페이지 id를 받아도 해석되지 않아야 한다(테넌트 격리)."""
    supabase = _identity_supabase(workspace_id="ws-2")
    assert get_wiki_page_identity("page-existing", workspace_id="ws-1", supabase=supabase) is None


def test_get_wiki_page_identity_returns_none_for_issue_page():
    """page_type='issue'는 TopicPageType이 아니므로 ValidationError 대신 None을 반환한다."""
    supabase = _identity_supabase(page_type="issue")
    assert get_wiki_page_identity("page-existing", workspace_id="ws-1", supabase=supabase) is None

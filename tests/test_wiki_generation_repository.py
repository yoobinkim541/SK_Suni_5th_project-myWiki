from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.wiki.generation_repository import (
    archive_wiki_page,
    filter_to_topic_page_ids,
    find_matching_issue_page,
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


def _wiki_page(id_, *, slug, title="제목", page_type="issue", parent_page_id=None, status="published", current_version_id=None, workspace_id="ws-1"):
    return {
        "id": id_, "workspace_id": workspace_id, "slug": slug, "title": title,
        "page_type": page_type, "parent_page_id": parent_page_id, "status": status,
        "current_version_id": current_version_id,
    }


def _wiki_version(id_, *, page_id, created_at):
    return {"id": id_, "page_id": page_id, "created_at": created_at}


def _wiki_source(*, wiki_version_id, document_version_id):
    return {"wiki_version_id": wiki_version_id, "document_version_id": document_version_id}


def _analysis_row(*, document_version_id, primary_category, workspace_id="ws-1"):
    return {"document_version_id": document_version_id, "primary_category": primary_category, "workspace_id": workspace_id}


def test_find_matching_issue_page_matches_on_category_and_majority_overlap():
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=1)).isoformat()
    supabase = FakeSupabase(
        {
            "wiki_pages": [_wiki_page("page-1", slug="issue-old", current_version_id="v1")],
            "wiki_page_versions": [_wiki_version("v1", page_id="page-1", created_at=recent)],
            "wiki_page_sources": [
                _wiki_source(wiki_version_id="v1", document_version_id="doc-1"),
                _wiki_source(wiki_version_id="v1", document_version_id="doc-2"),
            ],
            "document_analysis_results": [
                _analysis_row(document_version_id="doc-1", primary_category="제품·기술"),
                _analysis_row(document_version_id="doc-2", primary_category="제품·기술"),
            ],
        }
    )

    # 이번 이슈 근거 2건 중 1건(doc-1)이 겹침 -> 50% 이상, 카테고리도 일치
    result = find_matching_issue_page(
        "ws-1", category="제품·기술", document_version_ids=["doc-1", "doc-3"], supabase=supabase,
    )

    assert result is not None
    assert result.page_id == "page-1"
    assert result.slug == "issue-old"


def test_find_matching_issue_page_rejects_category_mismatch():
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=1)).isoformat()
    supabase = FakeSupabase(
        {
            "wiki_pages": [_wiki_page("page-1", slug="issue-old", current_version_id="v1")],
            "wiki_page_versions": [_wiki_version("v1", page_id="page-1", created_at=recent)],
            "wiki_page_sources": [_wiki_source(wiki_version_id="v1", document_version_id="doc-1")],
            "document_analysis_results": [_analysis_row(document_version_id="doc-1", primary_category="경쟁사")],
        }
    )

    result = find_matching_issue_page(
        "ws-1", category="제품·기술", document_version_ids=["doc-1"], supabase=supabase,
    )

    assert result is None


def test_find_matching_issue_page_rejects_below_majority_overlap():
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=1)).isoformat()
    supabase = FakeSupabase(
        {
            "wiki_pages": [_wiki_page("page-1", slug="issue-old", current_version_id="v1")],
            "wiki_page_versions": [_wiki_version("v1", page_id="page-1", created_at=recent)],
            "wiki_page_sources": [_wiki_source(wiki_version_id="v1", document_version_id="doc-1")],
            "document_analysis_results": [_analysis_row(document_version_id="doc-1", primary_category="제품·기술")],
        }
    )

    # 이번 이슈 근거 3건 중 1건만 겹침 -> 33%, 50% 미달
    result = find_matching_issue_page(
        "ws-1", category="제품·기술", document_version_ids=["doc-1", "doc-2", "doc-3"], supabase=supabase,
    )

    assert result is None


def test_find_matching_issue_page_excludes_pages_older_than_within_days():
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=10)).isoformat()
    supabase = FakeSupabase(
        {
            "wiki_pages": [_wiki_page("page-1", slug="issue-old", current_version_id="v1")],
            "wiki_page_versions": [_wiki_version("v1", page_id="page-1", created_at=old)],
            "wiki_page_sources": [_wiki_source(wiki_version_id="v1", document_version_id="doc-1")],
            "document_analysis_results": [_analysis_row(document_version_id="doc-1", primary_category="제품·기술")],
        }
    )

    result = find_matching_issue_page(
        "ws-1", category="제품·기술", document_version_ids=["doc-1"], within_days=7, supabase=supabase,
    )

    assert result is None


def test_find_matching_issue_page_excludes_non_issue_page_type():
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=1)).isoformat()
    supabase = FakeSupabase(
        {
            "wiki_pages": [_wiki_page("page-1", slug="topic-page", page_type="technology", current_version_id="v1")],
            "wiki_page_versions": [_wiki_version("v1", page_id="page-1", created_at=recent)],
            "wiki_page_sources": [_wiki_source(wiki_version_id="v1", document_version_id="doc-1")],
            "document_analysis_results": [_analysis_row(document_version_id="doc-1", primary_category="제품·기술")],
        }
    )

    result = find_matching_issue_page(
        "ws-1", category="제품·기술", document_version_ids=["doc-1"], supabase=supabase,
    )

    assert result is None


def test_find_matching_issue_page_returns_none_for_empty_document_version_ids():
    supabase = FakeSupabase({"wiki_pages": []})
    result = find_matching_issue_page("ws-1", category="제품·기술", document_version_ids=[], supabase=supabase)
    assert result is None


def test_find_matching_issue_page_picks_highest_overlap_among_multiple_matches():
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=1)).isoformat()
    supabase = FakeSupabase(
        {
            "wiki_pages": [
                _wiki_page("page-low", slug="issue-low", current_version_id="v-low"),
                _wiki_page("page-high", slug="issue-high", current_version_id="v-high"),
            ],
            "wiki_page_versions": [
                _wiki_version("v-low", page_id="page-low", created_at=recent),
                _wiki_version("v-high", page_id="page-high", created_at=recent),
            ],
            "wiki_page_sources": [
                _wiki_source(wiki_version_id="v-low", document_version_id="doc-1"),
                _wiki_source(wiki_version_id="v-high", document_version_id="doc-1"),
                _wiki_source(wiki_version_id="v-high", document_version_id="doc-2"),
            ],
            "document_analysis_results": [
                _analysis_row(document_version_id="doc-1", primary_category="제품·기술"),
                _analysis_row(document_version_id="doc-2", primary_category="제품·기술"),
            ],
        }
    )

    # 이번 이슈 근거: doc-1, doc-2 둘 다.
    # issue-low는 doc-1만 겹침(50%), issue-high는 doc-1,doc-2 다 겹침(100%) -> issue-high가 이겨야 함
    result = find_matching_issue_page(
        "ws-1", category="제품·기술", document_version_ids=["doc-1", "doc-2"], supabase=supabase,
    )

    assert result is not None
    assert result.page_id == "page-high"


def test_find_matching_issue_page_null_category_does_not_suppress_valid_category():
    """document_analysis_results에 primary_category=NULL인 행(분류 실패)이 있어도
    같은 document_version_id에 유효한 카테고리 행이 있으면 그걸로 매칭돼야 한다.
    (dict 대신 set으로 모아서 NULL 행이 유효한 값을 덮어쓰지 않는지 검증)"""
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=1)).isoformat()
    supabase = FakeSupabase(
        {
            "wiki_pages": [_wiki_page("page-1", slug="issue-old", current_version_id="v1")],
            "wiki_page_versions": [_wiki_version("v1", page_id="page-1", created_at=recent)],
            "wiki_page_sources": [_wiki_source(wiki_version_id="v1", document_version_id="doc-1")],
            "document_analysis_results": [_analysis_row(document_version_id="doc-1", primary_category=None)],
        }
    )

    # NULL 카테고리 행만 있으면 매칭 신호가 없으므로 None (크래시도 안 남)
    result = find_matching_issue_page(
        "ws-1", category="제품·기술", document_version_ids=["doc-1"], supabase=supabase,
    )
    assert result is None

    # 같은 document_version_id에 유효한 카테고리 행을 추가하면, NULL 행이 있어도 매칭돼야 한다.
    supabase.tables["document_analysis_results"].append(
        _analysis_row(document_version_id="doc-1", primary_category="제품·기술")
    )
    result = find_matching_issue_page(
        "ws-1", category="제품·기술", document_version_ids=["doc-1"], supabase=supabase,
    )
    assert result is not None
    assert result.page_id == "page-1"

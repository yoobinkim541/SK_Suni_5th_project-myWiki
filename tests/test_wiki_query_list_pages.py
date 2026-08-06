"""
src/wiki/query.py::list_published_wiki_pages() 단위 테스트 — DB는 FakeTable로 대체한다.

Agent(WikiTools.list_wiki_topics)가 정렬 없는 목록의 앞부분만 보고 최신 위키를
놓치는 문제(§ published 페이지가 limit을 넘으면 일부가 아예 안 보임)의 회귀 테스트다.
"""
from __future__ import annotations

from src.wiki import query


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, rows: list[dict]):
        self.rows = list(rows)
        self.fields: list[str] | None = None
        self.eq_filters: list[tuple[str, object]] = []
        self.ordering: list[tuple[str, bool]] = []
        self.row_limit: int | None = None
        self.row_offset: int = 0

    def select(self, fields: str):
        self.fields = [f.strip() for f in fields.split(",")]
        return self

    def eq(self, field, value):
        self.eq_filters.append((field, value))
        return self

    def ilike(self, field, pattern):
        return self

    def order(self, field, desc: bool = False):
        self.ordering.append((field, desc))
        return self

    def limit(self, value):
        self.row_limit = value
        return self

    def offset(self, value):
        self.row_offset = value
        return self

    def execute(self):
        rows = self.rows
        for field, value in self.eq_filters:
            rows = [r for r in rows if r.get(field) == value]
        for field, desc in reversed(self.ordering):
            rows = sorted(rows, key=lambda r: r.get(field), reverse=desc)
        rows = rows[self.row_offset :]
        if self.row_limit is not None:
            rows = rows[: self.row_limit]
        if self.fields is not None:
            rows = [{f: r[f] for f in self.fields} for r in rows]
        return FakeResult(rows)


class FakeSupabase:
    def __init__(self, tables: dict[str, list[dict]]):
        self.tables = tables

    def table(self, name):
        return FakeTable(self.tables[name])


def _page(page_id: str, published_at: str) -> dict:
    return {
        "id": page_id,
        "workspace_id": "ws-1",
        "slug": f"slug-{page_id}",
        "title": f"title-{page_id}",
        "page_type": "technology",
        "status": "published",
        "parent_page_id": None,
        "published_at": published_at,
    }


def test_list_published_wiki_pages_orders_by_published_at_desc(monkeypatch):
    pages = [
        _page("old", "2026-08-01T00:00:00+00:00"),
        _page("new", "2026-08-05T00:00:00+00:00"),
        _page("mid", "2026-08-03T00:00:00+00:00"),
    ]
    fake_db = FakeSupabase({"wiki_pages": pages})
    monkeypatch.setattr(query, "_get_client", lambda: fake_db)

    results = query.list_published_wiki_pages("ws-1")

    assert [r.id for r in results] == ["new", "mid", "old"]


def test_list_published_wiki_pages_does_not_drop_recent_pages_past_default_limit(monkeypatch):
    """limit(기본값)보다 published 페이지가 많을 때, 잘려나가는 건 오래된 쪽이어야 한다
    — 정렬이 없으면 최신 문서가 임의로 잘려나갈 수 있었다."""
    pages = [_page(f"p{i}", f"2026-08-01T00:00:{i:02d}+00:00") for i in range(1, 60)]
    fake_db = FakeSupabase({"wiki_pages": pages})
    monkeypatch.setattr(query, "_get_client", lambda: fake_db)

    results = query.list_published_wiki_pages("ws-1")

    assert results[0].id == "p59"
    assert all(int(r.id[1:]) > 59 - len(results) for r in results)

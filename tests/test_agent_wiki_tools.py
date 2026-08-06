"""
src/agent/wiki_tools.py 유닛 테스트.

search_wiki_pages()가 src/wiki/interface.py::search_wiki_contexts()에 올바른
WikiSearchRequest를 넘기고, 그 결과를 title/body 스코어링 기반으로 얇게(slug/title/score만)
돌려주는지 검증한다 — 실제 DB/Storage 접근은 monkeypatch로 대체한다.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.agent.wiki_tools import WikiTools


@dataclass
class FakeSearchResult:
    wiki_page_id: str
    wiki_version_id: str
    workspace_id: str
    slug: str
    title: str
    content: str
    score: float
    updated_at: object = None
    source_document_version_ids: list = None


def test_list_wiki_topics_requests_higher_limit_than_db_default(monkeypatch):
    """list_published_wiki_pages()의 기본 limit=50은 UI 페이지네이션용이다 — Agent가
    전체 published 목록을 훑을 때 이 기본값에 묶이면 50건을 넘는 순간부터 최신 위키가
    안 보일 수 있었다. 명시적으로 더 큰 limit을 요청해야 한다."""
    captured = {}

    def fake_list_published_wiki_pages(workspace_id, **kwargs):
        captured["workspace_id"] = workspace_id
        captured["kwargs"] = kwargs
        return []

    monkeypatch.setattr(
        "src.agent.wiki_tools.wiki_query.list_published_wiki_pages",
        fake_list_published_wiki_pages,
    )

    tools = WikiTools(workspace_id="ws-1")
    tools.list_wiki_topics()

    assert captured["workspace_id"] == "ws-1"
    assert captured["kwargs"]["limit"] > 50


def test_search_wiki_pages_returns_slug_title_score(monkeypatch):
    captured = {}

    def fake_search_wiki_contexts(request, *, supabase=None):
        captured["request"] = request
        return [
            FakeSearchResult(
                wiki_page_id="page-1",
                wiki_version_id="ver-1",
                workspace_id="ws-1",
                slug="hbm4",
                title="HBM4",
                content="HBM4는 차세대 메모리다.",
                score=0.83,
            )
        ]

    monkeypatch.setattr("src.agent.wiki_tools.search_wiki_contexts", fake_search_wiki_contexts)

    tools = WikiTools(workspace_id="ws-1")
    hits = tools.search_wiki_pages("HBM4 수요")

    assert len(hits) == 1
    assert hits[0].slug == "hbm4"
    assert hits[0].title == "HBM4"
    assert hits[0].score == 0.83

    request = captured["request"]
    assert request.workspace_id == "ws-1"
    assert request.query == "HBM4 수요"


def test_search_wiki_pages_passes_limit(monkeypatch):
    captured = {}

    def fake_search_wiki_contexts(request, *, supabase=None):
        captured["request"] = request
        return []

    monkeypatch.setattr("src.agent.wiki_tools.search_wiki_contexts", fake_search_wiki_contexts)

    tools = WikiTools(workspace_id="ws-1")
    tools.search_wiki_pages("HBM4 수요", limit=3)

    assert captured["request"].limit == 3


def test_search_wiki_pages_returns_empty_list_when_no_match(monkeypatch):
    monkeypatch.setattr(
        "src.agent.wiki_tools.search_wiki_contexts", lambda request, *, supabase=None: []
    )

    tools = WikiTools(workspace_id="ws-1")
    hits = tools.search_wiki_pages("존재하지 않는 주제")

    assert hits == []

"""
src/api/wiki_router.py 스모크 테스트 — DB/네트워크는 monkeypatch로 대체한다.

get_current_user 의존성과 db.get_default_workspace_id, src.wiki.query 함수를 전부
monkeypatch하므로 실제 SUPABASE_* 환경변수는 필요 없다(lru_cache된 클라이언트가
호출되지 않는다). 여기서 환경변수를 임의로 세팅하면 dotenv를 쓰는 다른 테스트 모듈
(test_wiki_service.py)의 실제 접속값을 덮어써버리므로 절대 설정하지 않는다.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import db
from src.api.auth import get_current_user
from src.api.main import app
from src.wiki import query as wiki_query
from src.wiki.interface import WikiPageContent, WikiPageSummary, WikiVersionSummary

WORKSPACE_ID = "11111111-1111-1111-1111-111111111111"
PAGE_ID = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def client(monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: {"id": "user-1"}
    monkeypatch.setattr(db, "get_default_workspace_id", lambda user_id: WORKSPACE_ID)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_list_pages(client, monkeypatch):
    monkeypatch.setattr(
        wiki_query,
        "list_published_wiki_pages",
        lambda workspace_id, **kw: [
            WikiPageSummary(
                id=PAGE_ID,
                slug="hbm4",
                title="HBM4",
                page_type="technology",
                status="published",
                parent_page_id=None,
                published_at="2026-07-24T00:00:00Z",
            )
        ],
    )
    res = client.get("/wiki/pages")
    assert res.status_code == 200
    assert res.json()[0]["slug"] == "hbm4"


def test_get_page_not_found(client, monkeypatch):
    monkeypatch.setattr(wiki_query, "get_published_wiki_page", lambda workspace_id, slug: None)
    res = client.get("/wiki/pages/does-not-exist")
    assert res.status_code == 404


def test_get_page_found(client, monkeypatch):
    content = WikiPageContent(
        page_id=PAGE_ID,
        slug="hbm4",
        title="HBM4",
        page_type="technology",
        published_at="2026-07-24T00:00:00Z",
        version_id="33333333-3333-3333-3333-333333333333",
        version_no=2,
        markdown="# HBM4\n본문",
        change_summary="쟁점 문단 갱신",
        confidence_score=0.7,
        validation_status="passed",
        review_status="approved",
        generated_by="llm",
        generator_model="claude",
        created_at="2026-07-24T00:00:00Z",
        sources=(),
        versions=(),
    )
    monkeypatch.setattr(wiki_query, "get_published_wiki_page", lambda workspace_id, slug: content)
    res = client.get("/wiki/pages/hbm4")
    assert res.status_code == 200
    assert res.json()["markdown"] == "# HBM4\n본문"


def test_get_versions(client, monkeypatch):
    monkeypatch.setattr(
        wiki_query,
        "list_wiki_versions",
        lambda workspace_id, page_id: [
            WikiVersionSummary(id="v1", version_no=1, change_summary=None, created_at="2026-07-20T00:00:00Z")
        ],
    )
    res = client.get(f"/wiki/pages/{PAGE_ID}/versions")
    assert res.status_code == 200
    assert res.json()[0]["version_no"] == 1


def test_no_workspace_returns_403(client, monkeypatch):
    monkeypatch.setattr(db, "get_default_workspace_id", lambda user_id: None)
    res = client.get("/wiki/pages")
    assert res.status_code == 403

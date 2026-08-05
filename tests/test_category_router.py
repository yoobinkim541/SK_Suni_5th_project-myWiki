"""
src/api/category_router.py 스모크 테스트 — DB/네트워크는 monkeypatch로 대체한다.

tests/test_dashboard_router.py와 같은 방식이다.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import db
from src.api.auth import get_current_user
from src.api.main import app
from src.categories import service as category_service
from src.categories.models import (
    CategoryDocument,
    CategoryKeyword,
    CategoryStat,
    CategoryStats,
)

WORKSPACE_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def client(monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: {"id": "user-1"}
    monkeypatch.setattr(db, "get_default_workspace_id", lambda user_id: WORKSPACE_ID)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_get_stats_returns_service_result(client, monkeypatch):
    stats = CategoryStats(
        total_documents=427,
        categories=[
            CategoryStat(
                id="product-tech", name="제품·기술", count=69,
                top_issue="SK하이닉스, HBF 첫 표준규격 공개",
                tags=["HBM", "메모리"], level="low",
                keywords=[
                    CategoryKeyword(word="HBM", count=21),
                    CategoryKeyword(word="메모리", count=13),
                ],
                recent_documents=[
                    CategoryDocument(
                        title="SK하이닉스, HBF 첫 표준규격 공개",
                        quote="차세대 스토리지 표준이 공개됐다.",
                        source_label="yna.co.kr",
                        source_url="https://www.yna.co.kr/view/1",
                        published_at="2026-08-05T10:22:30+00:00",
                    )
                ],
            ),
        ],
    )
    monkeypatch.setattr(
        category_service, "get_category_stats", lambda workspace_id, **k: stats
    )

    res = client.get("/categories/stats")

    assert res.status_code == 200
    assert res.json() == {
        "total_documents": 427,
        "categories": [
            {
                "id": "product-tech",
                "name": "제품·기술",
                "count": 69,
                "top_issue": "SK하이닉스, HBF 첫 표준규격 공개",
                "tags": ["HBM", "메모리"],
                "level": "low",
                "keywords": [
                    {"word": "HBM", "count": 21},
                    {"word": "메모리", "count": 13},
                ],
                "recent_documents": [
                    {
                        "title": "SK하이닉스, HBF 첫 표준규격 공개",
                        "quote": "차세대 스토리지 표준이 공개됐다.",
                        "source_label": "yna.co.kr",
                        "source_url": "https://www.yna.co.kr/view/1",
                        "published_at": "2026-08-05T10:22:30+00:00",
                    }
                ],
            }
        ],
    }


def test_workspace_소속이_없으면_403(client, monkeypatch):
    monkeypatch.setattr(db, "get_default_workspace_id", lambda user_id: None)

    res = client.get("/categories/stats")

    assert res.status_code == 403


def test_토큰이_없으면_401():
    """의존성 오버라이드 없이 부르면 인증 게이트에 걸려야 한다."""
    res = TestClient(app).get("/categories/stats")

    assert res.status_code == 401

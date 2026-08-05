"""
src/api/dashboard_router.py 스모크 테스트 — DB/네트워크는 monkeypatch로 대체한다.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import db
from src.api.auth import get_current_user
from src.api.main import app
from src.dashboard import service as dashboard_service
from src.dashboard.models import DashboardSummary

WORKSPACE_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def client(monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: {"id": "user-1"}
    monkeypatch.setattr(db, "get_default_workspace_id", lambda user_id: WORKSPACE_ID)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_get_summary_returns_service_result(client, monkeypatch):
    summary = DashboardSummary(
        collected_docs=312, collected_docs_today=48,
        generated_reports=18, wiki_docs=124, wiki_docs_new_today=6,
        avg_reliability_label="보통",
    )
    monkeypatch.setattr(
        dashboard_service, "get_dashboard_summary", lambda workspace_id, **k: summary
    )

    res = client.get("/dashboard/summary")

    assert res.status_code == 200
    assert res.json() == {
        "collected_docs": 312,
        "collected_docs_today": 48,
        "generated_reports": 18,
        "wiki_docs": 124,
        "wiki_docs_new_today": 6,
        "avg_reliability_label": "보통",
    }

"""
src/api/dashboard_router.py 스모크 테스트 — DB/네트워크는 monkeypatch로 대체한다.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from src.api import db
from src.api.auth import get_current_user
from src.api.main import app
from src.dashboard import service as dashboard_service
from src.dashboard.models import (
    DashboardIssue,
    DashboardIssues,
    DashboardSummary,
    DashboardTrend,
    TrendDay,
)

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


def test_get_trend_returns_service_result(client, monkeypatch):
    trend = DashboardTrend(
        days=[
            TrendDay(date=date(2026, 8, 5), collected=135, adopted=1, news=132, disclosure=3),
            TrendDay(date=date(2026, 8, 6), collected=86, adopted=0, news=84, disclosure=2),
        ]
    )
    monkeypatch.setattr(dashboard_service, "get_dashboard_trend", lambda workspace_id, **k: trend)

    res = client.get("/dashboard/trend")

    assert res.status_code == 200
    assert res.json() == {
        "days": [
            # date는 'YYYY-MM-DD'로 직렬화된다 — 프론트가 그대로 라벨로 쓴다
            {"date": "2026-08-05", "collected": 135, "adopted": 1, "news": 132, "disclosure": 3},
            {"date": "2026-08-06", "collected": 86, "adopted": 0, "news": 84, "disclosure": 2},
        ]
    }


def test_get_trend_requires_workspace(client, monkeypatch):
    monkeypatch.setattr(db, "get_default_workspace_id", lambda user_id: None)

    res = client.get("/dashboard/trend")

    assert res.status_code == 403


def test_get_issues_returns_service_result(client, monkeypatch):
    """'최근 산업 이슈' 응답 계약 — 화면(IssueList)이 level로 필터링하므로 그 값이 살아 와야 한다."""
    issues = DashboardIssues(
        items=[
            DashboardIssue(
                id="doc-1",
                level="high",
                category="공급망·생산",
                title="청주 M15X 신규 설비 투자",
                summary="신규 설비 투자 관련 공시가 접수됐다.",
                source_label="거래소공시",
                source_url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=1",
                published_at=None,
                is_doc=True,
            )
        ]
    )
    monkeypatch.setattr(
        dashboard_service, "get_dashboard_issues", lambda workspace_id: issues
    )

    response = client.get("/dashboard/issues")

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["level"] == "high"
    assert item["source_label"] == "거래소공시"
    assert item["is_doc"] is True


def test_get_issues_requires_workspace(client, monkeypatch):
    monkeypatch.setattr(db, "get_default_workspace_id", lambda user_id: None)

    assert client.get("/dashboard/issues").status_code == 403

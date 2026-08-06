from __future__ import annotations

import sys
import types

import pytest
from fastapi.testclient import TestClient

if "pywebpush" not in sys.modules:
    pywebpush_stub = types.ModuleType("pywebpush")
    pywebpush_stub.WebPushException = Exception
    pywebpush_stub.webpush = lambda *args, **kwargs: None
    sys.modules["pywebpush"] = pywebpush_stub

from src.api import db
from src.api.auth import get_current_user
from src.api.main import app
from src.report import service as report_service

WORKSPACE_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def client(monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: {"id": "user-1"}
    monkeypatch.setattr(db, "get_default_workspace_id", lambda user_id: WORKSPACE_ID)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_get_daily_report_returns_service_result(client, monkeypatch):
    monkeypatch.setattr(
        report_service,
        "get_daily_report",
        lambda workspace_id, report_date, **kwargs: {
            "report_id": "report-1",
            "workspace_id": workspace_id,
            "report_key": "daily:11111111-1111-1111-1111-111111111111:2026-08-05",
            "version": 1,
            "title": "일일 산업 동향 보고서",
            "report_type": "daily",
            "status": "completed",
            "date": report_date.isoformat(),
            "created_at": "2026-08-05T09:00:00+09:00",
            "completed_at": "2026-08-05T09:05:00+09:00",
            "sections": [],
        },
    )

    res = client.get("/reports/daily?date=2026-08-05")

    assert res.status_code == 200
    assert res.json()["report_id"] == "report-1"
    assert res.json()["date"] == "2026-08-05"


def test_get_daily_report_returns_404_when_missing(client, monkeypatch):
    monkeypatch.setattr(report_service, "get_daily_report", lambda workspace_id, report_date, **kwargs: None)

    res = client.get("/reports/daily?date=2026-08-05")

    assert res.status_code == 404

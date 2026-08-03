# tests/test_settings_router.py
"""src/api/settings_router.py 스모크 테스트 — DB는 monkeypatch로 대체한다."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import db
from src.api.auth import get_current_user
from src.api.main import app
from src.settings import service as settings_service
from src.settings.models import WorkspaceSettings

WORKSPACE_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def client(monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: {"id": "user-1"}
    monkeypatch.setattr(db, "get_default_workspace_id", lambda user_id: WORKSPACE_ID)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _settings(**overrides) -> WorkspaceSettings:
    base = dict(
        workspace_id=WORKSPACE_ID,
        wiki_update_cycle_minutes=360,
        chat_retention_days=90,
        last_wiki_refresh_at=None,
        updated_at="2026-08-03T00:00:00Z",
    )
    base.update(overrides)
    return WorkspaceSettings(**base)


def test_get_settings(client, monkeypatch):
    monkeypatch.setattr(settings_service, "get_workspace_settings", lambda workspace_id, **kw: _settings())
    res = client.get("/settings")
    assert res.status_code == 200
    assert res.json()["wiki_update_cycle_minutes"] == 360


def test_patch_settings_updates_wiki_cycle(client, monkeypatch):
    captured = {}

    def fake_update(workspace_id, **kwargs):
        captured.update(kwargs)
        return _settings(wiki_update_cycle_minutes=kwargs.get("wiki_update_cycle_minutes", 360))

    monkeypatch.setattr(settings_service, "update_workspace_settings", fake_update)
    res = client.patch("/settings", json={"wiki_update_cycle_minutes": 60})
    assert res.status_code == 200
    assert res.json()["wiki_update_cycle_minutes"] == 60
    assert captured["updated_by"] == "user-1"


def test_patch_settings_rejects_invalid_cycle(client):
    res = client.patch("/settings", json={"wiki_update_cycle_minutes": 45})
    assert res.status_code == 422


def test_patch_settings_accepts_null_chat_retention(client, monkeypatch):
    captured = {}

    def fake_update(workspace_id, **kwargs):
        captured.update(kwargs)
        return _settings(chat_retention_days=None)

    monkeypatch.setattr(settings_service, "update_workspace_settings", fake_update)
    res = client.patch("/settings", json={"chat_retention_days": None})
    assert res.status_code == 200
    assert res.json()["chat_retention_days"] is None
    assert captured["chat_retention_days"] is None


def test_patch_settings_omitted_field_not_forwarded(client, monkeypatch):
    """chat_retention_days를 아예 안 보내면 update_workspace_settings에 전달되지 않아야
    한다 — "null로 바꿈"과 "안 건드림"을 구분하는 핵심 동작."""
    captured = {"called_with_chat_retention_days": False}

    def fake_update(workspace_id, **kwargs):
        if "chat_retention_days" in kwargs:
            captured["called_with_chat_retention_days"] = True
        return _settings()

    monkeypatch.setattr(settings_service, "update_workspace_settings", fake_update)
    res = client.patch("/settings", json={"wiki_update_cycle_minutes": 60})
    assert res.status_code == 200
    assert captured["called_with_chat_retention_days"] is False


def test_no_workspace_returns_403(client, monkeypatch):
    monkeypatch.setattr(db, "get_default_workspace_id", lambda user_id: None)
    res = client.get("/settings")
    assert res.status_code == 403

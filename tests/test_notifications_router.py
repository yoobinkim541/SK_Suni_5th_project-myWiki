from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import db
from src.api.auth import get_current_user
from src.api.main import app
from src.notifications import service as notifications_service

WORKSPACE_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def client(monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: {"id": "user-1"}
    monkeypatch.setattr(db, "get_default_workspace_id", lambda user_id: WORKSPACE_ID)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_subscribe_saves_subscription(client, monkeypatch):
    captured = {}

    def fake_save(workspace_id, user_id, endpoint, p256dh, auth_key, **kw):
        captured.update(
            workspace_id=workspace_id, user_id=user_id, endpoint=endpoint, p256dh=p256dh, auth_key=auth_key,
        )

    monkeypatch.setattr(notifications_service, "save_subscription", fake_save)

    res = client.post(
        "/notifications/subscribe",
        json={"endpoint": "https://ep/1", "keys": {"p256dh": "p1", "auth": "a1"}},
    )

    assert res.status_code == 204
    assert captured == {
        "workspace_id": WORKSPACE_ID,
        "user_id": "user-1",
        "endpoint": "https://ep/1",
        "p256dh": "p1",
        "auth_key": "a1",
    }


def test_unsubscribe_deletes_subscription(client, monkeypatch):
    captured = {}

    def fake_delete(user_id, endpoint, **kw):
        captured.update(user_id=user_id, endpoint=endpoint)

    monkeypatch.setattr(notifications_service, "delete_subscription", fake_delete)

    res = client.delete("/notifications/subscribe", params={"endpoint": "https://ep/1"})

    assert res.status_code == 204
    assert captured == {"user_id": "user-1", "endpoint": "https://ep/1"}


def test_subscribe_requires_workspace(client, monkeypatch):
    monkeypatch.setattr(db, "get_default_workspace_id", lambda user_id: None)

    res = client.post(
        "/notifications/subscribe",
        json={"endpoint": "https://ep/1", "keys": {"p256dh": "p1", "auth": "a1"}},
    )

    assert res.status_code == 403

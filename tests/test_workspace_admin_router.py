"""
오너 전용 워크스페이스 관리 라우터(/workspace/members/{id}, /workspace/sessions*) 테스트.
db.* 함수를 직접 monkeypatch해서 엔드포인트의 권한 체크·응답 형식만 검증한다
(db 함수 자체의 동작은 tests/test_workspace_admin.py에서 이미 확인함).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import db
from src.api.auth import get_current_user
from src.api.main import app

WORKSPACE_ID = "44444444-4444-4444-4444-444444444444"
OWNER_ID = "55555555-5555-5555-5555-555555555555"
TARGET_ID = "66666666-6666-6666-6666-666666666666"


@pytest.fixture
def client_as(monkeypatch):
    def _make(user_id: str) -> TestClient:
        app.dependency_overrides[get_current_user] = lambda: {"id": user_id, "deleted_at": None}
        return TestClient(app)
    yield _make
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(autouse=True)
def default_workspace(monkeypatch):
    monkeypatch.setattr(db, "get_default_workspace_id", lambda uid: WORKSPACE_ID)


def test_remove_member_requires_owner(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_role", lambda wid, uid: "admin")
    calls = []
    monkeypatch.setattr(db, "remove_workspace_member", lambda wid, uid: calls.append((wid, uid)))

    res = client_as(OWNER_ID).delete(f"/workspace/members/{TARGET_ID}")

    assert res.status_code == 403
    assert calls == []


def test_remove_member_success_for_owner(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_role", lambda wid, uid: "owner")
    calls = []
    monkeypatch.setattr(db, "remove_workspace_member", lambda wid, uid: calls.append((wid, uid)))

    res = client_as(OWNER_ID).delete(f"/workspace/members/{TARGET_ID}")

    assert res.status_code == 204
    assert calls == [(WORKSPACE_ID, TARGET_ID)]


def test_remove_member_rejects_self(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_role", lambda wid, uid: "owner")
    calls = []
    monkeypatch.setattr(db, "remove_workspace_member", lambda wid, uid: calls.append((wid, uid)))

    res = client_as(OWNER_ID).delete(f"/workspace/members/{OWNER_ID}")

    assert res.status_code == 400
    assert calls == []


def test_update_role_requires_owner(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_role", lambda wid, uid: "editor")
    calls = []
    monkeypatch.setattr(db, "update_workspace_member_role", lambda wid, uid, role: calls.append((wid, uid, role)))

    res = client_as(OWNER_ID).patch(f"/workspace/members/{TARGET_ID}/role", json={"role": "admin"})

    assert res.status_code == 403
    assert calls == []


def test_update_role_success_for_owner(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_role", lambda wid, uid: "owner" if uid == OWNER_ID else "admin")
    calls = []
    monkeypatch.setattr(db, "update_workspace_member_role", lambda wid, uid, role: calls.append((wid, uid, role)))
    monkeypatch.setattr(
        db, "list_workspace_members",
        lambda wid: [{"user_id": TARGET_ID, "display_name": "박하늘", "role": "admin"}],
    )

    res = client_as(OWNER_ID).patch(f"/workspace/members/{TARGET_ID}/role", json={"role": "admin"})

    assert res.status_code == 200
    assert res.json() == {"user_id": TARGET_ID, "display_name": "박하늘", "email": None, "role": "admin"}
    assert calls == [(WORKSPACE_ID, TARGET_ID, "admin")]


def test_update_role_rejects_self(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_role", lambda wid, uid: "owner")
    calls = []
    monkeypatch.setattr(db, "update_workspace_member_role", lambda wid, uid, role: calls.append((wid, uid, role)))

    res = client_as(OWNER_ID).patch(f"/workspace/members/{OWNER_ID}/role", json={"role": "admin"})

    assert res.status_code == 400
    assert calls == []


def test_update_role_rejects_invalid_role_value(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_role", lambda wid, uid: "owner")

    res = client_as(OWNER_ID).patch(f"/workspace/members/{TARGET_ID}/role", json={"role": "owner"})

    assert res.status_code == 422


def test_list_sessions_requires_owner(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_role", lambda wid, uid: "editor")

    res = client_as(OWNER_ID).get("/workspace/sessions", params={"visibility": "team"})

    assert res.status_code == 403


def test_list_sessions_returns_admin_session_list(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_role", lambda wid, uid: "owner")
    monkeypatch.setattr(
        db, "list_workspace_sessions_for_admin",
        lambda wid, visibility: [{
            "id": "sess-1", "workspace_id": wid, "user_id": TARGET_ID, "title": "팀 세션",
            "visibility": visibility, "owner_name": "박하늘", "archived_at": None,
            "created_at": "2026-08-07T00:00:00Z", "updated_at": "2026-08-07T00:00:00Z",
        }],
    )

    res = client_as(OWNER_ID).get("/workspace/sessions", params={"visibility": "team"})

    assert res.status_code == 200
    assert res.json()[0]["owner_name"] == "박하늘"
    assert res.json()[0]["id"] == "sess-1"


def test_list_sessions_rejects_invalid_visibility(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_role", lambda wid, uid: "owner")

    res = client_as(OWNER_ID).get("/workspace/sessions", params={"visibility": "bogus"})

    assert res.status_code == 422


def test_get_admin_session_messages_requires_owner(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_role", lambda wid, uid: "editor")

    res = client_as(OWNER_ID).get("/workspace/sessions/sess-1/messages")

    assert res.status_code == 403


def test_get_admin_session_messages_404_for_missing_session(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_role", lambda wid, uid: "owner")
    monkeypatch.setattr(db, "get_chat_session_for_admin", lambda sid, wid: None)

    res = client_as(OWNER_ID).get("/workspace/sessions/sess-missing/messages")

    assert res.status_code == 404


def test_get_admin_session_messages_success(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_role", lambda wid, uid: "owner")
    monkeypatch.setattr(db, "get_chat_session_for_admin", lambda sid, wid: {"id": sid, "workspace_id": wid})
    monkeypatch.setattr(
        db, "list_chat_messages",
        lambda sid: [{
            "id": "msg-1", "session_id": sid, "role": "user", "content": "질문",
            "created_at": "2026-08-07T00:00:00Z",
        }],
    )

    res = client_as(OWNER_ID).get("/workspace/sessions/sess-1/messages")

    assert res.status_code == 200
    assert res.json()[0]["content"] == "질문"

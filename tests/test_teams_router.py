"""팀 관리 라우터 테스트. db.* 함수를 monkeypatch해서 권한 체크·응답 형식만 검증한다
(db 함수 자체 동작은 tests/test_teams.py에서 이미 확인함) — test_workspace_admin_router.py와
동일 패턴."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import db
from src.api.auth import get_current_user
from src.api.main import app

WORKSPACE_ID = "44444444-4444-4444-4444-444444444444"
TEAM_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TEAM_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
OWNER_ID = "55555555-5555-5555-5555-555555555555"
LEAD_ID = "66666666-6666-6666-6666-666666666666"
MEMBER_ID = "77777777-7777-7777-7777-777777777777"
OTHER_LEAD_ID = "99999999-9999-9999-9999-999999999999"
UNASSIGNED_ID = "88888888-8888-8888-8888-888888888888"


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


def test_create_team_requires_owner(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_role", lambda wid, uid: "admin")

    res = client_as(LEAD_ID).post("/teams", json={"name": "C팀"})

    assert res.status_code == 403


def test_create_team_success_for_owner(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_role", lambda wid, uid: "owner")
    monkeypatch.setattr(db, "create_team", lambda wid, name: {"id": "new-team", "name": name})

    res = client_as(OWNER_ID).post("/teams", json={"name": "C팀"})

    assert res.status_code == 200
    assert res.json() == {"id": "new-team", "name": "C팀", "member_count": 0}


def test_create_team_duplicate_name_returns_400(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_role", lambda wid, uid: "owner")

    def _raise(wid, name):
        raise ValueError("이미 존재하는 팀 이름")

    monkeypatch.setattr(db, "create_team", _raise)

    res = client_as(OWNER_ID).post("/teams", json={"name": "A팀"})

    assert res.status_code == 400


def test_delete_team_blocks_when_members_exist(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_role", lambda wid, uid: "owner")

    def _raise(team_id):
        raise ValueError("팀에 소속된 인원이 있어 삭제할 수 없음")

    monkeypatch.setattr(db, "delete_team", _raise)

    res = client_as(OWNER_ID).delete(f"/teams/{TEAM_A}")

    assert res.status_code == 400


def test_list_teams_open_to_any_member(client_as, monkeypatch):
    monkeypatch.setattr(
        db, "list_teams",
        lambda wid: [{"id": TEAM_A, "name": "A팀", "member_count": 2}],
    )

    res = client_as(MEMBER_ID).get("/teams")

    assert res.status_code == 200
    assert res.json() == [{"id": TEAM_A, "name": "A팀", "member_count": 2}]


def test_list_team_members_open_to_any_member(client_as, monkeypatch):
    monkeypatch.setattr(
        db, "list_team_members",
        lambda team_id: [{"user_id": MEMBER_ID, "display_name": "팀원1", "role": "editor"}],
    )

    res = client_as(MEMBER_ID).get(f"/teams/{TEAM_A}/members")

    assert res.status_code == 200
    assert res.json()[0]["user_id"] == MEMBER_ID


def test_list_all_users_requires_owner(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_role", lambda wid, uid: "admin")

    res = client_as(LEAD_ID).get("/admin/users")

    assert res.status_code == 403


def test_list_all_users_success_for_owner(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_role", lambda wid, uid: "owner")
    monkeypatch.setattr(
        db, "list_workspace_users_with_team",
        lambda wid: [{"user_id": MEMBER_ID, "display_name": "팀원1", "role": "editor",
                       "team_id": TEAM_A, "team_name": "A팀"}],
    )

    res = client_as(OWNER_ID).get("/admin/users")

    assert res.status_code == 200
    assert res.json()[0]["team_name"] == "A팀"


def test_assign_user_team_requires_owner(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_role", lambda wid, uid: "admin")

    res = client_as(LEAD_ID).patch(f"/admin/users/{MEMBER_ID}/team", json={"team_id": TEAM_B})

    assert res.status_code == 403


def test_assign_user_team_success_for_owner(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_role", lambda wid, uid: "owner")
    calls = []
    monkeypatch.setattr(
        db, "move_member_to_team",
        lambda wid, uid, tid: calls.append((wid, uid, tid)),
    )

    res = client_as(OWNER_ID).patch(f"/admin/users/{MEMBER_ID}/team", json={"team_id": TEAM_B})

    assert res.status_code == 204
    assert calls == [(WORKSPACE_ID, MEMBER_ID, TEAM_B)]


def test_invite_requires_actor_in_target_team(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_member", lambda wid, uid: {"role": "editor", "team_id": TEAM_B})

    res = client_as(MEMBER_ID).post(f"/teams/{TEAM_A}/members", json={"user_id": UNASSIGNED_ID})

    assert res.status_code == 403


def test_invite_rejects_already_assigned_target(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_member", lambda wid, uid: (
        {"role": "editor", "team_id": TEAM_A} if uid == MEMBER_ID
        else {"role": "editor", "team_id": TEAM_B}
    ))

    res = client_as(MEMBER_ID).post(f"/teams/{TEAM_A}/members", json={"user_id": "already-on-team-b"})

    assert res.status_code == 400


def test_invite_success_for_member(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_member", lambda wid, uid: (
        {"role": "editor", "team_id": TEAM_A} if uid == MEMBER_ID
        else {"role": "editor", "team_id": None}
    ))
    calls = []
    monkeypatch.setattr(db, "move_member_to_team", lambda wid, uid, tid: calls.append((wid, uid, tid)))

    res = client_as(MEMBER_ID).post(f"/teams/{TEAM_A}/members", json={"user_id": UNASSIGNED_ID})

    assert res.status_code == 204
    assert calls == [(WORKSPACE_ID, UNASSIGNED_ID, TEAM_A)]


def test_recruit_requires_lead_role(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_member", lambda wid, uid: {"role": "editor", "team_id": TEAM_A})

    res = client_as(MEMBER_ID).post(f"/teams/{TEAM_A}/members/recruit", json={"user_id": OTHER_LEAD_ID})

    assert res.status_code == 403


def test_recruit_allows_already_assigned_target(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_member", lambda wid, uid: (
        {"role": "admin", "team_id": TEAM_A} if uid == LEAD_ID
        else {"role": "editor", "team_id": TEAM_B}
    ))
    calls = []
    monkeypatch.setattr(db, "move_member_to_team", lambda wid, uid, tid: calls.append((wid, uid, tid)))

    res = client_as(LEAD_ID).post(f"/teams/{TEAM_A}/members/recruit", json={"user_id": "on-team-b"})

    assert res.status_code == 204
    assert calls == [(WORKSPACE_ID, "on-team-b", TEAM_A)]


def test_recruit_rejects_already_same_team(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_member", lambda wid, uid: {"role": "admin", "team_id": TEAM_A})

    res = client_as(LEAD_ID).post(f"/teams/{TEAM_A}/members/recruit", json={"user_id": MEMBER_ID})

    assert res.status_code == 400


def test_remove_team_member_requires_lead_role(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_member", lambda wid, uid: {"role": "editor", "team_id": TEAM_A})

    res = client_as(MEMBER_ID).delete(f"/teams/{TEAM_A}/members/{MEMBER_ID}")

    assert res.status_code == 403


def test_remove_team_member_rejects_self(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_member", lambda wid, uid: {"role": "admin", "team_id": TEAM_A})

    res = client_as(LEAD_ID).delete(f"/teams/{TEAM_A}/members/{LEAD_ID}")

    assert res.status_code == 400


def test_remove_team_member_success(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_member", lambda wid, uid: (
        {"role": "admin", "team_id": TEAM_A} if uid == LEAD_ID
        else {"role": "editor", "team_id": TEAM_A}
    ))
    calls = []
    monkeypatch.setattr(db, "move_member_to_team", lambda wid, uid, tid: calls.append((wid, uid, tid)))

    res = client_as(LEAD_ID).delete(f"/teams/{TEAM_A}/members/{MEMBER_ID}")

    assert res.status_code == 204
    assert calls == [(WORKSPACE_ID, MEMBER_ID, None)]


def test_remove_team_member_404_when_not_in_team(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace_member", lambda wid, uid: (
        {"role": "admin", "team_id": TEAM_A} if uid == LEAD_ID
        else {"role": "editor", "team_id": TEAM_B}
    ))

    res = client_as(LEAD_ID).delete(f"/teams/{TEAM_A}/members/{MEMBER_ID}")

    assert res.status_code == 404

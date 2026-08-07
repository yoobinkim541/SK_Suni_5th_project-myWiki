"""
회원 탈퇴(DELETE /account) 테스트 — DB/네트워크는 monkeypatch로 대체한다.

두 층을 나눠서 검증한다:
1. src/api/db.py의 soft_delete_profile/remove_all_workspace_memberships/
   delete_push_subscriptions_for_user — 최소 fake Supabase 클라이언트로 실제 쿼리를 태운다.
2. src/api/main.py의 DELETE /account 라우터 — db.* 함수를 직접 monkeypatch해서
   정상 흐름과, 정리 단계 일부가 실패해도 요청 자체는 성공(204)하는지 확인한다.

tests/test_chat_sessions.py와 동일한 fake Supabase 패턴을 그대로 재사용한다.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import db
from src.api.auth import get_current_user
from src.api.main import app

USER_ID = "22222222-2222-2222-2222-222222222222"


# ---------------------------------------------------------------------------
# 1. db.py 함수 자체 — fake Supabase 클라이언트로 실제 쿼리를 태운다
# ---------------------------------------------------------------------------

class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeUpdateQuery:
    def __init__(self, rows: list[dict], patch: dict):
        self._rows = rows
        self._patch = patch
        self._filters: list[tuple] = []

    def eq(self, key, value):
        self._filters.append((key, value))
        return self

    def execute(self):
        matched = [r for r in self._rows if all(r.get(k) == v for k, v in self._filters)]
        for r in matched:
            r.update(self._patch)
        return FakeResult(matched)


class FakeDeleteQuery:
    def __init__(self, rows: list[dict]):
        self._rows = rows
        self._filters: list[tuple] = []

    def eq(self, key, value):
        self._filters.append((key, value))
        return self

    def execute(self):
        matched = [r for r in self._rows if all(r.get(k) == v for k, v in self._filters)]
        for r in matched:
            self._rows.remove(r)
        return FakeResult(matched)


class FakeTable:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def update(self, patch: dict):
        return FakeUpdateQuery(self._rows, patch)

    def delete(self):
        return FakeDeleteQuery(self._rows)


class FakeAuthAdmin:
    def __init__(self):
        self.ban_calls: list[tuple[str, dict]] = []

    def update_user_by_id(self, user_id: str, attributes: dict):
        self.ban_calls.append((user_id, attributes))


class FakeAuth:
    def __init__(self):
        self.admin = FakeAuthAdmin()


class FakeSupabaseClient:
    def __init__(self, data: dict[str, list[dict]]):
        self._data = data
        self.auth = FakeAuth()

    def table(self, name: str):
        return FakeTable(self._data.get(name, []))


@pytest.fixture
def fake_db(monkeypatch):
    client = FakeSupabaseClient({
        "profiles": [{"id": USER_ID, "display_name": "탈퇴 예정", "deleted_at": None}],
        "workspace_members": [
            {"id": "wm-1", "workspace_id": "ws-1", "user_id": USER_ID, "role": "member"},
            {"id": "wm-2", "workspace_id": "ws-1", "user_id": "other-user", "role": "member"},
        ],
        "push_subscriptions": [
            {"id": "push-1", "user_id": USER_ID, "workspace_id": "ws-1", "endpoint": "https://example.com/1"},
        ],
    })
    monkeypatch.setattr(db, "get_supabase", lambda: client)
    return client


def test_soft_delete_profile_sets_deleted_at(fake_db):
    db.soft_delete_profile(USER_ID)

    profile = fake_db._data["profiles"][0]
    assert profile["deleted_at"] is not None


def test_remove_all_workspace_memberships_only_removes_target_user(fake_db):
    db.remove_all_workspace_memberships(USER_ID)

    remaining = fake_db._data["workspace_members"]
    assert [r["user_id"] for r in remaining] == ["other-user"]


def test_delete_push_subscriptions_for_user_removes_rows(fake_db):
    db.delete_push_subscriptions_for_user(USER_ID)

    assert fake_db._data["push_subscriptions"] == []


def test_ban_auth_user_calls_admin_api_with_ban_duration(fake_db):
    """auth.users 행을 지우면 fk_profiles_auth_user(ON DELETE CASCADE)가 profiles까지
    지워버려(그리고 이어서 chat_sessions까지) soft_delete_profile로 피하려던 문제를
    뒷문으로 재현한다(2026-08-07 프로덕션에서 확인) — 그래서 delete_user 대신
    ban_duration으로 로그인만 막는다."""
    db.ban_auth_user(USER_ID)

    assert fake_db.auth.admin.ban_calls == [(USER_ID, {"ban_duration": db.PERMANENT_BAN_DURATION})]


# ---------------------------------------------------------------------------
# 2. DELETE /account 라우터 — db.* 함수를 monkeypatch
# ---------------------------------------------------------------------------

@pytest.fixture
def client_as(monkeypatch):
    def _make(user_id: str) -> TestClient:
        app.dependency_overrides[get_current_user] = lambda: {"id": user_id, "deleted_at": None}
        return TestClient(app)
    yield _make
    app.dependency_overrides.pop(get_current_user, None)


def test_delete_account_calls_all_cleanup_steps_and_returns_204(client_as, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(db, "soft_delete_profile", lambda uid: calls.append(f"soft_delete:{uid}"))
    monkeypatch.setattr(db, "remove_all_workspace_memberships", lambda uid: calls.append(f"remove_memberships:{uid}"))
    monkeypatch.setattr(db, "delete_push_subscriptions_for_user", lambda uid: calls.append(f"delete_push:{uid}"))
    monkeypatch.setattr(db, "ban_auth_user", lambda uid: calls.append(f"ban_auth:{uid}"))

    response = client_as(USER_ID).delete("/account")

    assert response.status_code == 204
    assert calls == [
        f"soft_delete:{USER_ID}",
        f"remove_memberships:{USER_ID}",
        f"delete_push:{USER_ID}",
        f"ban_auth:{USER_ID}",
    ]


def test_delete_account_soft_delete_happens_before_cleanup_steps(client_as, monkeypatch):
    """soft_delete_profile은 다른 정리 단계보다 먼저 실행돼야 한다 — 이후 단계가 실패해도
    이미 deleted_at은 남아 있어 get_current_user가 재사용을 막아준다."""
    order: list[str] = []
    monkeypatch.setattr(db, "soft_delete_profile", lambda uid: order.append("soft_delete"))
    monkeypatch.setattr(db, "remove_all_workspace_memberships", lambda uid: order.append("memberships"))
    monkeypatch.setattr(db, "delete_push_subscriptions_for_user", lambda uid: order.append("push"))
    monkeypatch.setattr(db, "ban_auth_user", lambda uid: order.append("auth"))

    client_as(USER_ID).delete("/account")

    assert order[0] == "soft_delete"


@pytest.mark.parametrize(
    "failing_step",
    ["remove_all_workspace_memberships", "delete_push_subscriptions_for_user", "ban_auth_user"],
)
def test_delete_account_returns_204_even_when_a_cleanup_step_fails(client_as, monkeypatch, failing_step):
    """정리 단계(멤버십/구독/인증) 중 하나가 예외를 던져도, 이미 soft_delete_profile로
    탈퇴 처리는 끝났으므로 요청 자체는 성공(204)해야 한다 — 외부 API 일시 장애 때문에
    탈퇴가 실패한 것처럼 보이면 안 된다."""
    monkeypatch.setattr(db, "soft_delete_profile", lambda uid: None)
    for step in ["remove_all_workspace_memberships", "delete_push_subscriptions_for_user", "ban_auth_user"]:
        if step == failing_step:
            def _raise(uid):
                raise RuntimeError("transient failure")
            monkeypatch.setattr(db, step, _raise)
        else:
            monkeypatch.setattr(db, step, lambda uid: None)

    response = client_as(USER_ID).delete("/account")

    assert response.status_code == 204


def test_delete_account_fails_when_soft_delete_itself_fails(client_as, monkeypatch):
    """탈퇴 처리의 핵심 단계(soft_delete_profile)가 실패하면, 나머지 정리 단계와 달리
    요청도 실패로 처리돼야 한다 — 탈퇴가 안 됐는데 성공했다고 보이면 안 된다."""
    def _raise(uid):
        raise RuntimeError("db unavailable")
    monkeypatch.setattr(db, "soft_delete_profile", _raise)
    monkeypatch.setattr(db, "remove_all_workspace_memberships", lambda uid: None)
    monkeypatch.setattr(db, "delete_push_subscriptions_for_user", lambda uid: None)
    monkeypatch.setattr(db, "ban_auth_user", lambda uid: None)

    with pytest.raises(RuntimeError):
        client_as(USER_ID).delete("/account")


def test_delete_account_only_targets_the_authenticated_users_own_id(client_as, monkeypatch):
    """엔드포인트가 user_id를 URL/바디로 받지 않으므로, 항상 인증된 본인 id로만
    호출된다 — 다른 사람 계정을 지울 방법이 없다는 걸 명시적으로 확인한다."""
    seen_ids: list[str] = []
    monkeypatch.setattr(db, "soft_delete_profile", lambda uid: seen_ids.append(uid))
    monkeypatch.setattr(db, "remove_all_workspace_memberships", lambda uid: None)
    monkeypatch.setattr(db, "delete_push_subscriptions_for_user", lambda uid: None)
    monkeypatch.setattr(db, "ban_auth_user", lambda uid: None)

    client_as(USER_ID).delete("/account")

    assert seen_ids == [USER_ID]


def test_delete_account_requires_authentication():
    app.dependency_overrides.pop(get_current_user, None)
    client = TestClient(app)

    response = client.delete("/account")

    assert response.status_code == 401

"""
오너 전용 워크스페이스 관리 기능(멤버 방출·역할 변경·전체 세션 열람) 테스트.
DB/네트워크는 최소 fake Supabase 클라이언트로 대체한다 — tests/test_account_deletion.py와
동일한 패턴(FakeResult/FakeTable/FakeSupabaseClient)을 재사용한다.
"""
from __future__ import annotations

import pytest

from src.api import db

WORKSPACE_ID = "44444444-4444-4444-4444-444444444444"
OWNER_ID = "55555555-5555-5555-5555-555555555555"
TARGET_ID = "66666666-6666-6666-6666-666666666666"
OTHER_WORKSPACE_ID = "77777777-7777-7777-7777-777777777777"


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, rows: list[dict]):
        self._rows = rows
        self._single = False

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, key, value):
        self._rows = [r for r in self._rows if r.get(key) == value]
        return self

    def in_(self, key, values):
        values = set(values)
        self._rows = [r for r in self._rows if r.get(key) in values]
        return self

    def is_(self, key, value):
        if value == "null":
            self._rows = [r for r in self._rows if r.get(key) is None]
        else:
            self._rows = [r for r in self._rows if r.get(key) is not None]
        return self

    def order(self, *_args, **_kwargs):
        return self

    def maybe_single(self):
        self._single = True
        return self

    def execute(self):
        if self._single:
            return FakeResult(self._rows[0] if self._rows else None)
        return FakeResult(list(self._rows))


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

    def in_(self, key, values):
        values = set(values)
        self._filters.append(("__in__" + key, values))
        return self

    def execute(self):
        def matches(r):
            for k, v in self._filters:
                if k.startswith("__in__"):
                    if r.get(k[6:]) not in v:
                        return False
                elif r.get(k) != v:
                    return False
            return True
        matched = [r for r in self._rows if matches(r)]
        for r in matched:
            self._rows.remove(r)
        return FakeResult(matched)


class FakeTable:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def select(self, *_args, **_kwargs):
        return FakeQuery(list(self._rows))

    def update(self, patch: dict):
        return FakeUpdateQuery(self._rows, patch)

    def delete(self):
        return FakeDeleteQuery(self._rows)


class FakeSupabaseClient:
    def __init__(self, data: dict[str, list[dict]]):
        self._data = data

    def table(self, name: str):
        return FakeTable(self._data.setdefault(name, []))


@pytest.fixture
def fake_db(monkeypatch):
    client = FakeSupabaseClient({
        "workspace_members": [
            {"workspace_id": WORKSPACE_ID, "user_id": OWNER_ID, "role": "owner"},
            {"workspace_id": WORKSPACE_ID, "user_id": TARGET_ID, "role": "editor"},
        ],
        "chat_sessions": [
            {
                "id": "sess-1", "workspace_id": WORKSPACE_ID, "user_id": TARGET_ID,
                "visibility": "team", "title": "팀 세션 하나", "updated_at": "2026-08-07T00:00:00Z",
                "profiles": {"display_name": "박하늘"},
            },
            {
                "id": "sess-2", "workspace_id": OTHER_WORKSPACE_ID, "user_id": TARGET_ID,
                "visibility": "team", "title": "다른 워크스페이스 세션", "updated_at": "2026-08-07T00:00:00Z",
                "profiles": {"display_name": "박하늘"},
            },
            {
                "id": "sess-3", "workspace_id": WORKSPACE_ID, "user_id": OWNER_ID,
                "visibility": "private", "title": "오너의 개인 세션", "updated_at": "2026-08-07T00:00:00Z",
                "profiles": {"display_name": "오너"},
            },
        ],
        "chat_session_participants": [
            {"session_id": "sess-1", "user_id": TARGET_ID},
            {"session_id": "sess-2", "user_id": TARGET_ID},
        ],
    })
    monkeypatch.setattr(db, "get_supabase", lambda: client)
    return client


def test_remove_workspace_member_deletes_membership_row(fake_db):
    db.remove_workspace_member(WORKSPACE_ID, TARGET_ID)

    remaining = fake_db._data["workspace_members"]
    assert [r["user_id"] for r in remaining] == [OWNER_ID]


def test_remove_workspace_member_removes_session_participation_in_same_workspace_only(fake_db):
    """sess-1은 WORKSPACE_ID 소속이라 참여자 행이 지워져야 하고, sess-2는 다른
    워크스페이스 소속이라 그대로 남아야 한다 — 워크스페이스 경계를 넘어 지우면 안 된다."""
    db.remove_workspace_member(WORKSPACE_ID, TARGET_ID)

    remaining = fake_db._data["chat_session_participants"]
    assert [r["session_id"] for r in remaining] == ["sess-2"]


def test_update_workspace_member_role_updates_row(fake_db):
    db.update_workspace_member_role(WORKSPACE_ID, TARGET_ID, "admin")

    updated = next(r for r in fake_db._data["workspace_members"] if r["user_id"] == TARGET_ID)
    assert updated["role"] == "admin"


def test_list_workspace_sessions_for_admin_filters_by_workspace_and_visibility(fake_db):
    result = db.list_workspace_sessions_for_admin(WORKSPACE_ID, "team")

    assert [r["id"] for r in result] == ["sess-1"]


def test_list_workspace_sessions_for_admin_attaches_owner_name(fake_db):
    result = db.list_workspace_sessions_for_admin(WORKSPACE_ID, "team")

    assert result[0]["owner_name"] == "박하늘"
    assert "profiles" not in result[0]


def test_list_workspace_sessions_for_admin_private_scope(fake_db):
    result = db.list_workspace_sessions_for_admin(WORKSPACE_ID, "private")

    assert [r["id"] for r in result] == ["sess-3"]


def test_get_chat_session_for_admin_ignores_participation(fake_db):
    """OWNER_ID는 sess-1의 참여자가 아니지만(위 fixture 참고), 관리자 조회이므로
    워크스페이스만 맞으면 그냥 조회돼야 한다."""
    result = db.get_chat_session_for_admin("sess-1", WORKSPACE_ID)

    assert result is not None
    assert result["id"] == "sess-1"


def test_get_chat_session_for_admin_blocks_cross_workspace(fake_db):
    result = db.get_chat_session_for_admin("sess-2", WORKSPACE_ID)

    assert result is None

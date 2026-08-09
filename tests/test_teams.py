"""팀 관리 db.py 함수 테스트. tests/test_workspace_admin.py와 동일한 fake Supabase 패턴."""
from __future__ import annotations

import pytest

from src.api import db

WORKSPACE_ID = "44444444-4444-4444-4444-444444444444"
TEAM_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TEAM_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
OWNER_ID = "55555555-5555-5555-5555-555555555555"
LEAD_ID = "66666666-6666-6666-6666-666666666666"
MEMBER_ID = "77777777-7777-7777-7777-777777777777"
UNASSIGNED_ID = "88888888-8888-8888-8888-888888888888"


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

    def order(self, *_args, **_kwargs):
        return self

    def maybe_single(self):
        self._single = True
        return self

    def execute(self):
        if self._single:
            return FakeResult(self._rows[0] if self._rows else None)
        return FakeResult(list(self._rows))


class FakeInsertQuery:
    def __init__(self, sink: list[dict], row: dict):
        self._row = {**row, "id": row.get("id") or f"generated-{len(sink)}"}
        sink.append(self._row)

    def execute(self):
        return FakeResult([self._row])


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

    def select(self, *_args, **_kwargs):
        return FakeQuery(list(self._rows))

    def insert(self, row: dict):
        return FakeInsertQuery(self._rows, row)

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
        "teams": [
            {"id": TEAM_A, "workspace_id": WORKSPACE_ID, "name": "A팀"},
            {"id": TEAM_B, "workspace_id": WORKSPACE_ID, "name": "B팀"},
        ],
        "workspace_members": [
            {"workspace_id": WORKSPACE_ID, "user_id": OWNER_ID, "role": "owner", "team_id": None},
            {"workspace_id": WORKSPACE_ID, "user_id": LEAD_ID, "role": "admin", "team_id": TEAM_A},
            {"workspace_id": WORKSPACE_ID, "user_id": MEMBER_ID, "role": "editor", "team_id": TEAM_A,
             "profiles": {"display_name": "팀원1"}},
            {"workspace_id": WORKSPACE_ID, "user_id": UNASSIGNED_ID, "role": "editor", "team_id": None,
             "profiles": {"display_name": "미배치"}},
        ],
    })
    monkeypatch.setattr(db, "get_supabase", lambda: client)
    return client


def test_get_workspace_member_returns_role_and_team(fake_db):
    result = db.get_workspace_member(WORKSPACE_ID, LEAD_ID)

    assert result["role"] == "admin"
    assert result["team_id"] == TEAM_A


def test_create_team_inserts_row(fake_db):
    team = db.create_team(WORKSPACE_ID, "C팀")

    assert team["name"] == "C팀"
    assert any(t["name"] == "C팀" for t in fake_db._data["teams"])


def test_create_team_rejects_duplicate_name(fake_db):
    with pytest.raises(ValueError):
        db.create_team(WORKSPACE_ID, "A팀")


def test_list_teams_includes_member_counts(fake_db):
    result = db.list_teams(WORKSPACE_ID)

    by_id = {t["id"]: t for t in result}
    assert by_id[TEAM_A]["member_count"] == 2
    assert by_id[TEAM_B]["member_count"] == 0


def test_delete_team_blocks_when_members_exist(fake_db):
    with pytest.raises(ValueError):
        db.delete_team(TEAM_A)

    assert any(t["id"] == TEAM_A for t in fake_db._data["teams"])


def test_delete_team_succeeds_when_empty(fake_db):
    db.delete_team(TEAM_B)

    assert not any(t["id"] == TEAM_B for t in fake_db._data["teams"])


def test_list_team_members_returns_display_name_and_role(fake_db):
    result = db.list_team_members(TEAM_A)

    ids = {r["user_id"] for r in result}
    assert ids == {LEAD_ID, MEMBER_ID}
    member_row = next(r for r in result if r["user_id"] == MEMBER_ID)
    assert member_row["display_name"] == "팀원1"
    assert member_row["role"] == "editor"


def test_list_workspace_users_with_team_attaches_team_name(fake_db):
    result = db.list_workspace_users_with_team(WORKSPACE_ID)

    lead_row = next(r for r in result if r["user_id"] == LEAD_ID)
    assert lead_row["team_name"] == "A팀"
    unassigned_row = next(r for r in result if r["user_id"] == UNASSIGNED_ID)
    assert unassigned_row["team_name"] is None


def test_move_member_to_team_sets_team_id(fake_db):
    db.move_member_to_team(WORKSPACE_ID, UNASSIGNED_ID, TEAM_B)

    updated = next(r for r in fake_db._data["workspace_members"] if r["user_id"] == UNASSIGNED_ID)
    assert updated["team_id"] == TEAM_B


def test_move_member_to_team_unassigns_with_none(fake_db):
    db.move_member_to_team(WORKSPACE_ID, MEMBER_ID, None)

    updated = next(r for r in fake_db._data["workspace_members"] if r["user_id"] == MEMBER_ID)
    assert updated["team_id"] is None

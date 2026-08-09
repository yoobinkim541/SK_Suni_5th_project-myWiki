"""GET /workspace(워크스페이스 이름 조회) 테스트. 설정 화면의 "소속 팀" 표시가
workspaceName=null로 항상 비어 보이던 문제 — 이 엔드포인트가 없어서 발생했다."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import db
from src.api.auth import get_current_user
from src.api.main import app

WORKSPACE_ID = "44444444-4444-4444-4444-444444444444"
USER_ID = "55555555-5555-5555-5555-555555555555"


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, rows):
        self._rows = rows
        self._single = False

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, key, value):
        self._rows = [r for r in self._rows if r.get(key) == value]
        return self

    def maybe_single(self):
        self._single = True
        return self

    def execute(self):
        if self._single:
            return FakeResult(self._rows[0] if self._rows else None)
        return FakeResult(list(self._rows))


class FakeTable:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_args, **_kwargs):
        return FakeQuery(list(self._rows))


class FakeSupabaseClient:
    def __init__(self, data):
        self._data = data

    def table(self, name):
        return FakeTable(self._data.setdefault(name, []))


@pytest.fixture
def fake_db(monkeypatch):
    client = FakeSupabaseClient({
        "workspaces": [{"id": WORKSPACE_ID, "name": "myWiki"}],
    })
    monkeypatch.setattr(db, "get_supabase", lambda: client)
    return client


def test_get_workspace_returns_name(fake_db):
    result = db.get_workspace(WORKSPACE_ID)

    assert result == {"id": WORKSPACE_ID, "name": "myWiki"}


def test_get_workspace_returns_none_for_missing(fake_db):
    result = db.get_workspace("does-not-exist")

    assert result is None


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


def test_get_workspace_endpoint_returns_name(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace", lambda wid: {"id": wid, "name": "myWiki"})

    res = client_as(USER_ID).get("/workspace")

    assert res.status_code == 200
    assert res.json() == {"id": WORKSPACE_ID, "name": "myWiki"}


def test_get_workspace_endpoint_404_when_missing(client_as, monkeypatch):
    monkeypatch.setattr(db, "get_workspace", lambda wid: None)

    res = client_as(USER_ID).get("/workspace")

    assert res.status_code == 404

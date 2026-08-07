# 오너 전용 워크스페이스 관리 패널 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 워크스페이스 오너가 멤버를 방출하고, 멤버 역할(팀장/팀원/게스트)을 지정하고, 워크스페이스의 모든 팀 세션·개인 세션을 참여 여부/소유자 무관하게 읽기 전용으로 열람할 수 있게 만든다.

**Architecture:** 기존 `get_chat_session`/`list_chat_sessions`(일반 사용자 접근 제어)는 건드리지 않고, 완전히 분리된 관리자 전용 DB 함수·엔드포인트 4개를 새로 추가한다. 모든 관리자 엔드포인트는 `_require_owner` 헬퍼로 오너 여부를 먼저 검증한다. 프론트는 `SettingsPage`에 오너에게만 보이는 "관리" 섹션을 추가한다.

**Tech Stack:** FastAPI + Supabase(Python SDK) 백엔드, React 프론트(테스트 프레임워크 없음 — `npm run build`로 검증하는 기존 관례를 따른다).

## Global Constraints

- 새 엔드포인트 4개는 전부 오너 전용이다 — `db.get_workspace_role(workspace_id, profile["id"]) != "owner"`면 403.
- 오너 본인을 방출/역할변경 대상으로 지정하면 400.
- `PATCH .../role`의 `role`은 `admin`/`editor`/`viewer`만 허용(오너로 바꾸는 건 불가 — pydantic `Literal`로 스키마 레벨 차단).
- 기존 `get_chat_session`/`list_chat_sessions`/`ChatSessionOut`/`ChatMessageOut`은 이 작업에서 수정하지 않는다(일반 사용자 접근 제어와 완전히 분리 유지).
- DB 스키마 변경 없음 — 기존 `workspace_members.role`, `chat_sessions`, `chat_session_participants` 테이블만 사용.
- 이 작업은 `feat/workspace-roles-backend` 브랜치(PR #151, `db.get_workspace_role` 포함) 위에서 진행한다 — `develop`에 아직 안 머지됐으므로 그 브랜치를 베이스로 새 워크트리를 판다.

---

## Task 1: DB 레이어 — 멤버 방출·역할 변경

**Files:**
- Modify: `src/api/db.py` (파일 끝에 추가)
- Test: `tests/test_workspace_admin.py` (신규)

**Interfaces:**
- Consumes: `get_supabase()`(기존, `src/api/db.py` 최상단 정의)
- Produces:
  - `remove_workspace_member(workspace_id: str, user_id: str) -> None`
  - `update_workspace_member_role(workspace_id: str, user_id: str, role: str) -> None`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_workspace_admin.py` 신규 생성:

```python
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
            {"id": "sess-1", "workspace_id": WORKSPACE_ID, "user_id": TARGET_ID, "visibility": "team"},
            {"id": "sess-2", "workspace_id": OTHER_WORKSPACE_ID, "user_id": TARGET_ID, "visibility": "team"},
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
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest tests/test_workspace_admin.py -v`
Expected: FAIL — `AttributeError: module 'src.api.db' has no attribute 'remove_workspace_member'`

- [ ] **Step 3: 최소 구현 작성**

`src/api/db.py` 파일 끝(마지막 함수 `copy_message_citations` 뒤)에 추가:

```python


# ---------------------------------------------------------------------------
# 오너 전용 워크스페이스 관리 — 멤버 방출·역할 변경.
# 기존 get_chat_session/list_chat_sessions(일반 사용자 접근 제어)는 건드리지 않고
# 완전히 분리된 함수로 둔다 — 오너 권한 체크는 호출부(main.py)의 몫이다.
# ---------------------------------------------------------------------------


def remove_workspace_member(workspace_id: str, user_id: str) -> None:
    """workspace_members 행 삭제 + 이 워크스페이스 소속 세션들의 참여자 행도 함께
    삭제한다 — 방출됐는데 팀 세션엔 계속 참여자로 남는 상태를 방지한다."""
    session_ids_res = (
        get_supabase()
        .table("chat_sessions")
        .select("id")
        .eq("workspace_id", workspace_id)
        .execute()
    )
    session_ids = [row["id"] for row in session_ids_res.data]
    if session_ids:
        (
            get_supabase()
            .table("chat_session_participants")
            .delete()
            .eq("user_id", user_id)
            .in_("session_id", session_ids)
            .execute()
        )

    get_supabase().table("workspace_members").delete().eq(
        "workspace_id", workspace_id
    ).eq("user_id", user_id).execute()


def update_workspace_member_role(workspace_id: str, user_id: str, role: str) -> None:
    get_supabase().table("workspace_members").update({"role": role}).eq(
        "workspace_id", workspace_id
    ).eq("user_id", user_id).execute()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_workspace_admin.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/api/db.py tests/test_workspace_admin.py
git commit -m "feat: 워크스페이스 멤버 방출/역할 변경 DB 함수 추가"
```

---

## Task 2: DB 레이어 — 전체 세션 조회(관리자용)

**Files:**
- Modify: `src/api/db.py` (Task 1에서 추가한 함수들 뒤)
- Modify: `tests/test_workspace_admin.py`

**Interfaces:**
- Consumes: `get_supabase()`
- Produces:
  - `list_workspace_sessions_for_admin(workspace_id: str, visibility: str) -> list[dict]` — 각 행에 `owner_name` 키 포함(참여자/소유자 필터 없음).
  - `get_chat_session_for_admin(session_id: str, workspace_id: str) -> Optional[dict]` — workspace_id만 확인, 참여자/소유자 여부 무관.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_workspace_admin.py`의 `fake_db` fixture에 `chat_sessions` 행을 보강하고(아래처럼 `profiles` 임베드 포함), 파일 끝에 테스트 추가:

`fake_db` fixture의 `"chat_sessions"` 리스트를 아래로 교체(기존 sess-1/sess-2에 `title`/`profiles`/`updated_at` 추가):

```python
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
```

(`FakeQuery.select`가 컬럼 목록을 무시하고 행을 그대로 돌려주므로, `profiles` 서브셀렉트를 실제로 흉내내려면 위처럼 fixture 행 자체에 `profiles` 키를 미리 넣어둔다 — tests/test_chat_sessions.py의 관례와 동일.)

파일 끝에 추가:

```python
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
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest tests/test_workspace_admin.py -v`
Expected: FAIL — `AttributeError: module 'src.api.db' has no attribute 'list_workspace_sessions_for_admin'`

- [ ] **Step 3: 최소 구현 작성**

`src/api/db.py`의 `update_workspace_member_role` 함수 뒤에 추가:

```python


def list_workspace_sessions_for_admin(workspace_id: str, visibility: str) -> list[dict]:
    """참여자/소유자 필터 없이 워크스페이스의 세션을 전부 조회한다(오너 전용 열람용).
    get_chat_session/list_chat_sessions(일반 사용자용, 접근 제어 있음)와는 별개 함수다."""
    res = (
        get_supabase()
        .table("chat_sessions")
        .select("*, profiles(display_name)")
        .eq("workspace_id", workspace_id)
        .eq("visibility", visibility)
        .is_("deleted_at", "null")
        .order("updated_at", desc=True)
        .execute()
    )
    rows = []
    for row in res.data:
        profile = row.pop("profiles", None) or {}
        row["owner_name"] = profile.get("display_name")
        rows.append(row)
    return rows


def get_chat_session_for_admin(session_id: str, workspace_id: str) -> Optional[dict]:
    """get_chat_session과 달리 참여자/소유자 여부를 확인하지 않는다 — workspace_id
    일치만 확인한다(오너 전용 열람용)."""
    res = (
        get_supabase()
        .table("chat_sessions")
        .select("*")
        .eq("id", session_id)
        .eq("workspace_id", workspace_id)
        .maybe_single()
        .execute()
    )
    return res.data
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_workspace_admin.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/api/db.py tests/test_workspace_admin.py
git commit -m "feat: 워크스페이스 전체 세션 관리자 조회 DB 함수 추가"
```

---

## Task 3: API 레이어 — 멤버 관리 엔드포인트

**Files:**
- Modify: `src/api/schemas.py`
- Modify: `src/api/main.py`
- Test: `tests/test_workspace_admin_router.py` (신규)

**Interfaces:**
- Consumes: `db.get_workspace_role`(기존, PR #151), `db.remove_workspace_member`/`db.update_workspace_member_role`(Task 1), `get_current_user`(기존, `src/api/auth.py`)
- Produces:
  - `_require_owner(profile: dict, workspace_id: str) -> None` — `src/api/main.py` 내부 헬퍼, 오너 아니면 `HTTPException(403)`.
  - `DELETE /workspace/members/{user_id}` — 204, 본인 대상 400, 오너 아니면 403.
  - `PATCH /workspace/members/{user_id}/role` — `WorkspaceMemberOut` 반환, 본인 대상 400, 오너 아니면 403.
  - `UpdateMemberRoleRequest(BaseModel)` — `src/api/schemas.py`, `role: Literal["admin", "editor", "viewer"]`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_workspace_admin_router.py` 신규 생성:

```python
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
```

**주의**: `test_update_role_success_for_owner`는 `_require_owner`(요청자 role 조회)와, 응답을 만들기 위한 멤버 재조회 둘 다에서 `db.get_workspace_role`이 호출될 수 있으므로, `lambda wid, uid: "owner" if uid == OWNER_ID else "admin"`처럼 호출자에 따라 다른 값을 주는 fake를 쓴다.

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest tests/test_workspace_admin_router.py -v`
Expected: FAIL — 404 Not Found(라우트가 아직 없음)

- [ ] **Step 3: 최소 구현 작성**

`src/api/schemas.py`의 `WorkspaceMemberOut` 클래스(현재 `role: Optional[str] = None`으로 끝남) 바로 뒤에 추가:

```python


class UpdateMemberRoleRequest(BaseModel):
    role: Literal["admin", "editor", "viewer"]
```

`src/api/main.py` 상단 임포트 블록의 `from .schemas import (...)`에 `UpdateMemberRoleRequest`를 알파벳 순서로 추가:

```python
from .schemas import (
    AddParticipantRequest,
    ChatMessageOut,
    ChatSessionOut,
    CitationOut,
    CreateSessionRequest,
    ParticipantOut,
    RenameSessionRequest,
    SaveToWikiResponse,
    SendMessageRequest,
    SendMessageResponse,
    ShareToTeamRequest,
    UpdateMemberRoleRequest,
    WorkspaceMemberOut,
)
```

`src/api/main.py`의 `_require_workspace` 함수 바로 뒤에 `_require_owner` 헬퍼 추가:

```python


def _require_owner(profile: dict, workspace_id: str) -> None:
    if db.get_workspace_role(workspace_id, profile["id"]) != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="오너만 할 수 있음")
```

`src/api/main.py`의 `list_members`(`GET /workspace/members`) 엔드포인트 바로 뒤, `/health` 앞에 추가:

```python


@app.delete("/workspace/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(user_id: str, profile: dict = Depends(get_current_user)):
    """워크스페이스에서 멤버를 방출한다 — 오너 전용, 본인은 방출 대상이 될 수 없다."""
    workspace_id = _require_workspace(profile)
    _require_owner(profile, workspace_id)
    if user_id == profile["id"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="오너 본인은 방출할 수 없음")

    db.remove_workspace_member(workspace_id, user_id)


@app.patch("/workspace/members/{user_id}/role", response_model=WorkspaceMemberOut)
def update_member_role(
    user_id: str, body: UpdateMemberRoleRequest, profile: dict = Depends(get_current_user)
):
    """멤버 역할을 팀장/팀원/게스트로 바꾼다 — 오너 전용, 본인 역할은 이 엔드포인트로
    바꿀 수 없다(실수로 자기 권한을 낮춰서 아무도 못 돌리는 상황 방지)."""
    workspace_id = _require_workspace(profile)
    _require_owner(profile, workspace_id)
    if user_id == profile["id"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="본인 역할은 이 방법으로 바꿀 수 없음")

    db.update_workspace_member_role(workspace_id, user_id, body.role)
    rows = db.list_workspace_members(workspace_id)
    updated = next(r for r in rows if r["user_id"] == user_id)
    return WorkspaceMemberOut(
        user_id=updated["user_id"], display_name=updated.get("display_name"),
        email=updated.get("email"), role=updated.get("role"),
    )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_workspace_admin_router.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: 회귀 확인**

Run: `python -m pytest tests/ -q`
Expected: 이 작업 이전과 동일한 실패 목록만 남고(사전 존재하던 무관한 실패들), 새로 깨진 테스트가 없어야 한다.

- [ ] **Step 6: 커밋**

```bash
git add src/api/schemas.py src/api/main.py tests/test_workspace_admin_router.py
git commit -m "feat: 오너 전용 멤버 방출/역할 변경 엔드포인트 추가"
```

---

## Task 4: API 레이어 — 전체 세션 열람 엔드포인트

**Files:**
- Modify: `src/api/schemas.py`
- Modify: `src/api/main.py`
- Modify: `tests/test_workspace_admin_router.py`

**Interfaces:**
- Consumes: `db.list_workspace_sessions_for_admin`/`db.get_chat_session_for_admin`(Task 2), `db.list_chat_messages`(기존), `_require_owner`(Task 3)
- Produces:
  - `GET /workspace/sessions?visibility=team|private` → `list[AdminSessionOut]`
  - `GET /workspace/sessions/{session_id}/messages` → `list[ChatMessageOut]`
  - `AdminSessionOut(BaseModel)` — `src/api/schemas.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_workspace_admin_router.py` 파일 끝에 추가:

```python
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
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest tests/test_workspace_admin_router.py -v`
Expected: FAIL — 새로 추가한 6개 테스트가 404(라우트 없음)로 실패

- [ ] **Step 3: 최소 구현 작성**

`src/api/schemas.py`의 `UpdateMemberRoleRequest` 클래스 뒤에 추가:

```python


class AdminSessionOut(BaseModel):
    id: str
    workspace_id: str
    user_id: str
    title: Optional[str]
    visibility: str
    owner_name: Optional[str] = None
    archived_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
```

`src/api/main.py` 상단 임포트에서 `AdminSessionOut`도 함께 가져오도록 수정(알파벳 순):

```python
from .schemas import (
    AddParticipantRequest,
    AdminSessionOut,
    ChatMessageOut,
    ChatSessionOut,
    CitationOut,
    CreateSessionRequest,
    ParticipantOut,
    RenameSessionRequest,
    SaveToWikiResponse,
    SendMessageRequest,
    SendMessageResponse,
    ShareToTeamRequest,
    UpdateMemberRoleRequest,
    WorkspaceMemberOut,
)
```

`typing`에서 `Literal`을 이미 쓰고 있으므로(schemas.py의 `Literal` import 확인 — 없으면 `from typing import Literal, Optional`로 보강) `main.py` 상단에 쿼리 파라미터 타입용 `Literal` import를 추가:

```python
from typing import Literal
```

(`main.py` 최상단, 기존 `from typing import Literal` import가 없다면 `import logging` 근처에 추가한다. `test_chat_sessions.py`의 `scope: Literal["mine", "team"]` 패턴을 보면 이미 `Literal`이 임포트돼 있을 가능성이 높다 — 있으면 이 스텝은 건너뛴다.)

`update_member_role` 엔드포인트 뒤, `/health` 앞에 추가:

```python


@app.get("/workspace/sessions", response_model=list[AdminSessionOut])
def list_admin_sessions(
    visibility: Literal["team", "private"] = Query(...), profile: dict = Depends(get_current_user)
):
    """오너가 워크스페이스의 모든 세션을 참여 여부/소유자 무관하게 열람한다."""
    workspace_id = _require_workspace(profile)
    _require_owner(profile, workspace_id)

    rows = db.list_workspace_sessions_for_admin(workspace_id, visibility)
    return [AdminSessionOut(**r) for r in rows]


@app.get("/workspace/sessions/{session_id}/messages", response_model=list[ChatMessageOut])
def get_admin_session_messages(session_id: str, profile: dict = Depends(get_current_user)):
    """오너가 세션 하나의 대화 내용을 읽기 전용으로 조회한다."""
    workspace_id = _require_workspace(profile)
    _require_owner(profile, workspace_id)

    session = db.get_chat_session_for_admin(session_id, workspace_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="세션을 찾을 수 없음")

    messages = db.list_chat_messages(session_id)
    return [_to_message_out(m) for m in messages]
```

`Query`가 `fastapi`에서 이미 임포트돼 있는지 확인한다(`main.py` 상단 `from fastapi import Depends, FastAPI, HTTPException, status` 줄에 `Query`가 없으면 추가):

```python
from fastapi import Depends, FastAPI, HTTPException, Query, status
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_workspace_admin_router.py -v`
Expected: PASS (13 passed)

- [ ] **Step 5: 전체 회귀 확인**

Run: `python -m pytest tests/ -q`
Expected: 새로 깨진 테스트 없음(사전 존재 실패만 남음).

- [ ] **Step 6: 커밋 + 브랜치 푸시 + PR**

```bash
git add src/api/schemas.py src/api/main.py tests/test_workspace_admin_router.py
git commit -m "feat: 오너 전용 워크스페이스 전체 세션 열람 엔드포인트 추가"
git push -u origin feat/workspace-admin-panel
gh pr create --base feat/workspace-roles-backend --title "Feat: 오너 전용 워크스페이스 관리(방출/역할지정/세션 전체 열람) 백엔드" --body "PR #151(워크스페이스 role) 위에 쌓은 브랜치 — #151이 develop에 먼저 머지된 뒤 base를 develop으로 바꿔야 함. 상세 설계는 docs/superpowers/specs/2026-08-07-workspace-admin-panel-design.md 참고."
```

(PR base가 `feat/workspace-roles-backend`인 이유: 이 작업이 `db.get_workspace_role`에 의존하는데 그게 아직 `develop`에 없다. #151이 먼저 머지되면 GitHub이 이 PR의 base를 `develop`으로 자동 제안하거나, 수동으로 `gh pr edit --base develop`으로 바꾼다.)

---

## Task 5: 프론트엔드 — admin.js API 클라이언트

**⚠ 시작 전**: 프론트엔드는 `develop` 대신 `develop-frontend` 브랜치를 베이스로 쓴다(이 저장소 관례 — 백엔드/프론트가 분리된 브랜치). Task 5 시작 전에 새 워크트리를 판다:

```bash
git fetch origin
git worktree add .claude/worktrees/workspace-admin-panel-frontend -b feat/workspace-admin-panel-frontend origin/develop-frontend
```

이후 Task 5-8은 전부 이 워크트리(`.claude/worktrees/workspace-admin-panel-frontend`)에서 진행한다.

**Files:**
- Create: `frontend/src/api/admin.js`

**Interfaces:**
- Consumes: `apiFetch`(기존, `frontend/src/api/client.js`)
- Produces:
  - `removeWorkspaceMember(userId)`
  - `updateWorkspaceMemberRole(userId, role)`
  - `listWorkspaceSessions(visibility)`
  - `getWorkspaceSessionMessages(sessionId)`

- [ ] **Step 1: 파일 작성**

`frontend/src/api/admin.js` 신규 생성:

```js
// [LIVE] src/api/main.py의 오너 전용 워크스페이스 관리 엔드포인트 연결.
// 4개 전부 서버가 오너 role을 확인해서 막는다(403) — 여기선 UI만 가린다.
import { apiFetch } from './client';

/**
 * 워크스페이스에서 멤버를 방출한다. 오너 본인은 대상이 될 수 없다(서버가 400).
 * @returns {Promise<null>}
 */
export function removeWorkspaceMember(userId) {
  return apiFetch(`/workspace/members/${userId}`, { method: 'DELETE' });
}

/**
 * 멤버 역할을 바꾼다.
 * @param {'admin'|'editor'|'viewer'} role
 * @returns {Promise<{user_id, display_name, email, role}>}
 */
export function updateWorkspaceMemberRole(userId, role) {
  return apiFetch(`/workspace/members/${userId}/role`, { method: 'PATCH', body: { role } });
}

/**
 * 워크스페이스의 모든 팀/개인 세션(참여 여부·소유자 무관)을 조회한다.
 * @param {'team'|'private'} visibility
 * @returns {Promise<{id, workspace_id, user_id, title, visibility, owner_name, archived_at, created_at, updated_at}[]>}
 */
export function listWorkspaceSessions(visibility) {
  return apiFetch(`/workspace/sessions?visibility=${visibility}`);
}

/**
 * 세션 하나의 대화 내용을 읽기 전용으로 조회한다.
 * @returns {Promise<{id, session_id, role, content, created_at, citations}[]>}
 */
export function getWorkspaceSessionMessages(sessionId) {
  return apiFetch(`/workspace/sessions/${sessionId}/messages`);
}
```

- [ ] **Step 2: 문법 오류 없는지 확인**

Run: `cd frontend && npm run build`
Expected: 빌드 성공(이 파일은 아직 아무 데서도 import 안 하므로, 빌드가 깨진다면 이 파일 자체의 문법 오류다).

- [ ] **Step 3: 커밋**

```bash
git add frontend/src/api/admin.js
git commit -m "feat: 워크스페이스 관리자 API 클라이언트 추가"
```

---

## Task 6: 프론트엔드 — 세션 읽기 전용 열람 모달

**Files:**
- Create: `frontend/src/components/settings/AdminSessionViewModal.jsx`

**Interfaces:**
- Consumes: 없음(순수 프레젠테이션 컴포넌트, 데이터는 부모가 props로 내려줌)
- Produces: `AdminSessionViewModal` 컴포넌트 — props `{ open, title, messages, loading, error, onClose }`

- [ ] **Step 1: 파일 작성**

`frontend/src/components/settings/AdminSessionViewModal.jsx` 신규 생성. 모달 틀은 `ParticipantsModal.jsx`/`DeleteAccountModal.jsx`와 같은 `.mw-scrim`/`.mw-modal`/`.mw-hd`/`.mw-body` 클래스를 재사용한다:

```jsx
// 오너 전용 "세션 전체 보기"에서 세션 하나를 고르면 뜨는 읽기 전용 대화 열람 모달.
//
// AgentPage를 재사용하지 않고 새로 만든다 — AgentPage는 입력창/재생성/공유/삭제 등
// 액션이 많아서 읽기 전용으로 억지로 끄는 것보다 새로 만드는 게 더 단순하고 안전하다.
// 각주 클릭 이동 같은 인터랙션 없이 role+content만 마크다운으로 보여준다
// (오너가 내용을 확인하는 용도로 충분 — 클릭해서 원문으로 이동할 필요는 없음).
//
// 모달 틀은 ParticipantsModal.jsx와 같은 시안 클래스를 재사용한다.

import { useEffect } from 'react';
import ReactMarkdown from 'react-markdown';

export default function AdminSessionViewModal({ open, title, messages, loading, error, onClose }) {
  useEffect(() => {
    if (!open) return;
    function handleKey(e) {
      if (e.key === 'Escape') onClose?.();
    }
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <>
      <div className="mw-scrim open" onClick={onClose}></div>
      <div className="mw-modal open" role="dialog" aria-modal="true" aria-label="세션 열람">
        <div className="mw-hd">
          <div>
            <div className="eb">SESSION VIEW</div>
            <h3>{title || '대화 내용'}</h3>
          </div>
          <button className="mw-x" onClick={onClose} aria-label="닫기">✕</button>
        </div>

        <div className="mw-body">
          {error && <div className="kwm-empty">{error}</div>}
          {loading && <div className="kwm-empty">불러오는 중…</div>}
          {!loading && !error && (messages ?? []).length === 0 && (
            <div className="kwm-empty">메시지가 없습니다.</div>
          )}
          {!loading && (messages ?? []).map((m) => (
            <div key={m.id} className="set-row" style={{ display: 'block', padding: '10px 0' }}>
              <div className="ds" style={{ marginBottom: 4 }}>
                {m.role === 'user' ? '질문' : '답변'}
              </div>
              <div className="vl">
                <ReactMarkdown>{m.content}</ReactMarkdown>
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
```

- [ ] **Step 2: 빌드 확인**

Run: `cd frontend && npm run build`
Expected: 빌드 성공.

- [ ] **Step 3: 커밋**

```bash
git add frontend/src/components/settings/AdminSessionViewModal.jsx
git commit -m "feat: 오너용 세션 읽기 전용 열람 모달 추가"
```

---

## Task 7: 프론트엔드 — AdminPanel 컴포넌트

**Files:**
- Create: `frontend/src/components/settings/AdminPanel.jsx`

**Interfaces:**
- Consumes:
  - `frontend/src/api/admin.js`(Task 5)의 4개 함수
  - `frontend/src/services/agentApi.js`의 `listWorkspaceMembers()`(기존)
  - `AdminSessionViewModal`(Task 6)
  - `frontend/src/components/settings/SettingsGroup.jsx`, `SettingsRow.jsx`(기존)
  - `frontend/src/constants/roles.js`의 `roleLabel`, `roleClass`(기존)
- Produces: `AdminPanel` 컴포넌트 — props 없음(자체적으로 멤버·세션 목록을 fetch), default export.

- [ ] **Step 1: 파일 작성**

`frontend/src/components/settings/AdminPanel.jsx` 신규 생성:

```jsx
// 설정 화면의 "관리" 섹션 — 오너에게만 렌더링된다(SettingsPage.jsx에서 myRole 체크 후 렌더).
// 3개 하위 블록: 팀원 목록(역할 변경/방출), 팀 세션 전체 보기, 개인 세션 전체 보기.
//
// 방출은 회원 탈퇴 모달(DeleteAccountModal)과 달리 확인 문구 입력까지는 요구하지 않는다 —
// 대상이 본인이 아니라 타인이라 그 정도로 무겁게 막을 필요는 없고, 버튼 2단계 확인
// (한 번 누르면 "정말 방출?"로 바뀌고 다시 눌러야 실행) 정도면 충분하다는 설계 결정.

import { useEffect, useState } from 'react';
import SettingsGroup from './SettingsGroup';
import SettingsRow from './SettingsRow';
import AdminSessionViewModal from './AdminSessionViewModal';
import { roleLabel, roleClass } from '../../constants/roles';
import { listWorkspaceMembers } from '../../services/agentApi';
import {
  removeWorkspaceMember,
  updateWorkspaceMemberRole,
  listWorkspaceSessions,
  getWorkspaceSessionMessages,
} from '../../api/admin';

const ASSIGNABLE_ROLES = ['admin', 'editor', 'viewer'];

function MemberRow({ member, onRemove, onChangeRole, busy }) {
  const [confirmingRemove, setConfirmingRemove] = useState(false);

  useEffect(() => {
    if (!confirmingRemove) return;
    const t = window.setTimeout(() => setConfirmingRemove(false), 3000);
    return () => window.clearTimeout(t);
  }, [confirmingRemove]);

  return (
    <SettingsRow label={member.display_name || member.user_id} desc={member.email || ''}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <span className={`pt-role ${roleClass(member.role)}`}>{roleLabel(member.role)}</span>
        <select
          className="fld"
          value={member.role || ''}
          disabled={busy}
          onChange={(e) => onChangeRole(member.user_id, e.target.value)}
        >
          {ASSIGNABLE_ROLES.map((r) => (
            <option key={r} value={r}>{roleLabel(r)}</option>
          ))}
        </select>
        <button
          className="dlbtn danger"
          disabled={busy}
          onClick={() => {
            if (!confirmingRemove) {
              setConfirmingRemove(true);
              return;
            }
            setConfirmingRemove(false);
            onRemove(member.user_id);
          }}
        >
          {confirmingRemove ? '정말 방출?' : '방출'}
        </button>
      </div>
    </SettingsRow>
  );
}

function SessionListBlock({ title, visibility, onOpenSession }) {
  const [sessions, setSessions] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    listWorkspaceSessions(visibility)
      .then((rows) => alive && setSessions(rows))
      .catch((e) => alive && setError(e.message || '세션 목록을 불러오지 못했습니다.'));
    return () => { alive = false; };
  }, [visibility]);

  return (
    <SettingsGroup title={title}>
      {error && <SettingsRow label="오류" desc={error}><div /></SettingsRow>}
      {!error && sessions === null && (
        <SettingsRow label="불러오는 중…" desc=""><div /></SettingsRow>
      )}
      {!error && sessions !== null && sessions.length === 0 && (
        <SettingsRow label="세션이 없습니다" desc=""><div /></SettingsRow>
      )}
      {!error && (sessions ?? []).map((s) => (
        <SettingsRow key={s.id} label={s.title || '(제목 없음)'} desc={`작성자: ${s.owner_name || '알 수 없음'}`}>
          <button className="dlbtn" onClick={() => onOpenSession(s)}>보기</button>
        </SettingsRow>
      ))}
    </SettingsGroup>
  );
}

export default function AdminPanel() {
  const [members, setMembers] = useState(null);
  const [membersError, setMembersError] = useState(null);
  const [busyUserId, setBusyUserId] = useState(null);

  const [viewingSession, setViewingSession] = useState(null);
  const [sessionMessages, setSessionMessages] = useState(null);
  const [sessionMessagesLoading, setSessionMessagesLoading] = useState(false);
  const [sessionMessagesError, setSessionMessagesError] = useState(null);

  function loadMembers() {
    listWorkspaceMembers()
      .then((rows) => setMembers(rows))
      .catch((e) => setMembersError(e.message || '멤버 목록을 불러오지 못했습니다.'));
  }

  useEffect(() => {
    loadMembers();
  }, []);

  async function handleRemove(userId) {
    setBusyUserId(userId);
    try {
      await removeWorkspaceMember(userId);
      loadMembers();
    } catch (e) {
      setMembersError(e.message || '방출에 실패했습니다.');
    } finally {
      setBusyUserId(null);
    }
  }

  async function handleChangeRole(userId, role) {
    setBusyUserId(userId);
    try {
      await updateWorkspaceMemberRole(userId, role);
      loadMembers();
    } catch (e) {
      setMembersError(e.message || '역할 변경에 실패했습니다.');
    } finally {
      setBusyUserId(null);
    }
  }

  function openSession(session) {
    setViewingSession(session);
    setSessionMessages(null);
    setSessionMessagesError(null);
    setSessionMessagesLoading(true);
    getWorkspaceSessionMessages(session.id)
      .then((rows) => setSessionMessages(rows))
      .catch((e) => setSessionMessagesError(e.message || '대화 내용을 불러오지 못했습니다.'))
      .finally(() => setSessionMessagesLoading(false));
  }

  return (
    <>
      <SettingsGroup title="관리">
        {membersError && <SettingsRow label="오류" desc={membersError}><div /></SettingsRow>}
        {!membersError && members === null && (
          <SettingsRow label="불러오는 중…" desc=""><div /></SettingsRow>
        )}
        {!membersError && (members ?? []).map((m) => (
          <MemberRow
            key={m.user_id}
            member={m}
            busy={busyUserId === m.user_id}
            onRemove={handleRemove}
            onChangeRole={handleChangeRole}
          />
        ))}
      </SettingsGroup>

      <SessionListBlock title="팀 세션 전체 보기" visibility="team" onOpenSession={openSession} />
      <SessionListBlock title="개인 세션 전체 보기" visibility="private" onOpenSession={openSession} />

      <AdminSessionViewModal
        open={viewingSession !== null}
        title={viewingSession?.title}
        messages={sessionMessages}
        loading={sessionMessagesLoading}
        error={sessionMessagesError}
        onClose={() => setViewingSession(null)}
      />
    </>
  );
}
```

- [ ] **Step 2: 빌드 확인**

Run: `cd frontend && npm run build`
Expected: 빌드 성공.

- [ ] **Step 3: 커밋**

```bash
git add frontend/src/components/settings/AdminPanel.jsx
git commit -m "feat: 오너 전용 관리 패널 컴포넌트 추가(팀원 관리 + 세션 전체 보기)"
```

---

## Task 8: 프론트엔드 — SettingsPage에 연결

**Files:**
- Modify: `frontend/src/pages/SettingsPage.jsx`

**Interfaces:**
- Consumes: `AdminPanel`(Task 7), `myRole` prop(기존, `App.jsx`가 이미 내려주고 있음)

- [ ] **Step 1: import 추가**

`frontend/src/pages/SettingsPage.jsx` 상단 import 블록(`import { roleLabel, roleClass } from '../constants/roles';` 바로 뒤)에 추가:

```jsx
import AdminPanel from '../components/settings/AdminPanel';
```

- [ ] **Step 2: "세션" SettingsGroup 뒤에 조건부 렌더링 추가**

기존 "세션" `<SettingsGroup>`(로그아웃/회원 탈퇴 두 줄이 있는 블록) 바로 뒤, 그 다음에 이어지는 섹션(화면/데이터·파이프라인 등) 앞에 추가:

```jsx
      {myRole === 'owner' && <AdminPanel />}
```

정확한 삽입 위치를 찾으려면 `SettingsPage.jsx`에서 아래 패턴을 검색한다:

```jsx
        <SettingsRow label="회원 탈퇴" desc="계정과 모든 데이터가 삭제됩니다. 되돌릴 수 없습니다.">
          <button className="dlbtn danger" onClick={() => onDeleteAccount?.()}>회원 탈퇴</button>
        </SettingsRow>
      </SettingsGroup>
```

이 블록의 닫는 `</SettingsGroup>` 바로 다음 줄에 `{myRole === 'owner' && <AdminPanel />}`를 추가한다.

- [ ] **Step 3: 빌드 확인**

Run: `cd frontend && npm run build`
Expected: 빌드 성공.

- [ ] **Step 4: 로컬 수동 확인**

Run: `cd frontend && npm run dev`, 브라우저에서 오너 계정(`sunnycmywiki@gmail.com`)으로 로그인 후 설정 화면 진입 → "관리" 섹션이 보이는지, 팀원 목록/역할 변경 드롭다운/방출 버튼/팀 세션 목록/개인 세션 목록이 각각 렌더링되는지, 세션 "보기" 클릭 시 모달이 뜨고 대화 내용이 표시되는지 확인. 오너가 아닌 계정으로는 "관리" 섹션이 아예 안 보이는지도 함께 확인.

- [ ] **Step 5: 커밋 + 브랜치 푸시 + PR**

```bash
git add frontend/src/pages/SettingsPage.jsx
git commit -m "feat: 설정 화면에 오너 전용 관리 섹션 연결"
git push -u origin feat/workspace-admin-panel-frontend
gh pr create --base develop-frontend --title "Feat: 설정 화면에 오너 전용 관리 섹션(팀원 방출/역할지정/세션 전체 보기) 추가" --body "백엔드 PR(feat/workspace-admin-panel, base: feat/workspace-roles-backend → 이후 develop)이 먼저 머지되어야 실제로 동작함. 상세 설계는 docs/superpowers/specs/2026-08-07-workspace-admin-panel-design.md 참고."
```

---

## 최종 확인 (전체 작업 완료 후)

- [ ] 백엔드: `python -m pytest tests/ -q` — 이 작업으로 인한 신규 실패 없음.
- [ ] 프론트: `npm run build` — 성공.
- [ ] 백엔드 PR(feat/workspace-admin-panel)이 `feat/workspace-roles-backend` → (그 PR 머지 후) `develop`으로 정상 머지.
- [ ] 프론트 PR(feat/workspace-admin-panel-frontend)이 `develop-frontend`로 정상 머지.
- [ ] 배포 후 실제 오너 계정(`sunnycmywiki@gmail.com`)으로 로그인해 4개 기능(방출/역할지정/팀세션열람/개인세션열람) 전부 라이브 확인.

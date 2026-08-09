# 팀 기반 역할·권한 관리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `teams` 테이블과 `workspace_members.team_id`로 팀 소속을 표현하고, 기존 `role`(owner/admin/editor)을 관리자/팀장/팀원으로 재해석해 팀 단위 초대/영입/제외 및 관리자 전체 배치 관리를 구현한다.

**Architecture:** 새 테이블 `teams` + `workspace_members.team_id` 컬럼만 추가(새 역할 컬럼 없음). `db.py`에 인가 없는 원시 함수를 추가하고, `main.py`가 `_require_owner`(기존)와 `_require_team_scope`(신규)로 역할·팀 범위를 검증한다. 상세 설계는 [`docs/superpowers/specs/2026-08-09-team-based-permissions-design.md`](../specs/2026-08-09-team-based-permissions-design.md) 참고.

**Tech Stack:** FastAPI, Supabase(Postgres + PostgREST), pytest, TestClient.

## Global Constraints

- 새 역할/플래그 컬럼 추가 금지 — `owner`=관리자, `admin`=팀장, `editor`=팀원을 그대로 재사용한다.
- `team_id`는 `profiles`가 아니라 `workspace_members`에 둔다.
- `db.py` 함수는 인가를 검증하지 않는 원시 동작만 한다 — 역할/팀 범위 검증은 전부 `main.py`.
- 팀 삭제는 소속 인원이 있으면 차단한다(DB `ON DELETE RESTRICT` + API 사전 체크로 이중 방어).
- 팀장/팀원의 초대·영입·제외는 자기 팀(`team_id` 일치) 범위 밖으로 나갈 수 없다.
- 커밋마다 `pytest`가 통과해야 한다.

---

### Task 1: 마이그레이션 — `teams` 테이블 + `workspace_members.team_id`

**Files:**
- Create: `supabase/migrations/20260809100000_create_teams.sql`

**Interfaces:**
- Produces: 테이블 `public.teams(id, workspace_id, name, created_at, updated_at)`, 컬럼 `public.workspace_members.team_id`(nullable uuid FK). 이후 모든 Task가 이 스키마를 전제로 한다.

- [ ] **Step 1: 마이그레이션 파일 작성**

```sql
CREATE TABLE IF NOT EXISTS public.teams (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  name text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (workspace_id, name)
);

DROP TRIGGER IF EXISTS trg_teams_updated_at ON public.teams;
CREATE TRIGGER trg_teams_updated_at
BEFORE UPDATE ON public.teams
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.teams ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS teams_select ON public.teams;
CREATE POLICY teams_select ON public.teams
FOR SELECT
USING (is_workspace_member(workspace_id));

ALTER TABLE public.workspace_members
  ADD COLUMN IF NOT EXISTS team_id uuid REFERENCES public.teams(id) ON DELETE RESTRICT;

CREATE INDEX IF NOT EXISTS idx_workspace_members_team_id ON public.workspace_members(team_id);
```

- [ ] **Step 2: 라이브 Supabase 프로젝트에 적용**

Supabase MCP `apply_migration` 도구로 project_id `uhzjshqmnlahhvqzygkp`에 위 SQL을 이름 `create_teams`로 적용한다.

- [ ] **Step 3: 적용 확인**

Supabase MCP `list_tables`로 `public.teams`가 생기고 `public.workspace_members`에 `team_id` 컬럼이 보이는지 확인(`verbose: true`).

- [ ] **Step 4: 커밋**

```bash
git add supabase/migrations/20260809100000_create_teams.sql
git commit -m "Feat: teams 테이블 + workspace_members.team_id 추가"
```

---

### Task 2: 스키마 (`src/api/schemas.py`)

**Files:**
- Modify: `src/api/schemas.py` (파일 끝에 추가)

**Interfaces:**
- Consumes: 없음(순수 Pydantic 모델).
- Produces: `TeamOut(id, name, member_count)`, `TeamMemberOut(user_id, display_name, role)`, `AdminUserOut(user_id, display_name, role, team_id, team_name)`, `CreateTeamRequest(name)`, `AssignTeamRequest(team_id: Optional[str])`. Task 4가 그대로 import해서 쓴다.

- [ ] **Step 1: 모델 추가**

`src/api/schemas.py` 끝에 추가:

```python
class TeamOut(BaseModel):
    id: str
    name: str
    member_count: int = 0


class TeamMemberOut(BaseModel):
    user_id: str
    display_name: Optional[str] = None
    role: Optional[str] = None


class AdminUserOut(BaseModel):
    user_id: str
    display_name: Optional[str] = None
    role: Optional[str] = None
    team_id: Optional[str] = None
    team_name: Optional[str] = None


class CreateTeamRequest(BaseModel):
    name: str


class AssignTeamRequest(BaseModel):
    team_id: Optional[str] = None
```

- [ ] **Step 2: import 확인**

Run: `python -c "from src.api.schemas import TeamOut, TeamMemberOut, AdminUserOut, CreateTeamRequest, AssignTeamRequest"`
Expected: 에러 없이 종료.

- [ ] **Step 3: 커밋**

```bash
git add src/api/schemas.py
git commit -m "Feat: 팀 관리 API 스키마 추가"
```

---

### Task 3: `db.py` 팀 함수 + 단위 테스트

**Files:**
- Modify: `src/api/db.py` (파일 끝에 추가)
- Test: `tests/test_teams.py` (신규)

**Interfaces:**
- Consumes: `db.get_supabase()`, `db._flatten_display_name(row)`(기존 헬퍼, `src/api/db.py:186`).
- Produces: `get_workspace_member(workspace_id, user_id) -> Optional[dict]`(user_id/role/team_id), `create_team(workspace_id, name) -> dict`(중복 이름이면 `ValueError`), `list_teams(workspace_id) -> list[dict]`(id/name/member_count), `delete_team(team_id) -> None`(인원 있으면 `ValueError`), `list_team_members(team_id) -> list[dict]`(user_id/display_name/role), `list_workspace_users_with_team(workspace_id) -> list[dict]`(user_id/display_name/role/team_id/team_name), `move_member_to_team(workspace_id, user_id, team_id: Optional[str]) -> None`. Task 4가 이 시그니처들을 그대로 호출한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_teams.py` 신규 생성:

```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_teams.py -v`
Expected: `ModuleNotFoundError` 또는 `AttributeError: module 'src.api.db' has no attribute 'get_workspace_member'` 등으로 전부 FAIL.

- [ ] **Step 3: `src/api/db.py`에 함수 구현**

파일 끝에 추가(기존 `_flatten_display_name`, `get_supabase`를 그대로 사용):

```python
# ---------------------------------------------------------------------------
# 팀 관리 — teams 테이블 + workspace_members.team_id.
# role(owner/admin/editor)을 관리자/팀장/팀원으로 재해석해 재사용한다(새 역할
# 컬럼 없음). 여기 함수들은 인가를 검증하지 않는 원시 동작만 한다 — 역할·팀
# 범위 검증은 호출부(main.py)의 몫이다(기존 오너 전용 관리 함수들과 동일 패턴).
# ---------------------------------------------------------------------------


def get_workspace_member(workspace_id: str, user_id: str) -> Optional[dict]:
    res = (
        get_supabase()
        .table("workspace_members")
        .select("user_id, role, team_id")
        .eq("workspace_id", workspace_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    return res.data


def create_team(workspace_id: str, name: str) -> dict:
    existing_res = (
        get_supabase()
        .table("teams")
        .select("id")
        .eq("workspace_id", workspace_id)
        .eq("name", name)
        .execute()
    )
    if existing_res.data:
        raise ValueError("이미 존재하는 팀 이름")

    res = (
        get_supabase()
        .table("teams")
        .insert({"workspace_id": workspace_id, "name": name})
        .execute()
    )
    return res.data[0]


def list_teams(workspace_id: str) -> list[dict]:
    teams_res = (
        get_supabase()
        .table("teams")
        .select("id, name")
        .eq("workspace_id", workspace_id)
        .order("name")
        .execute()
    )
    members_res = (
        get_supabase()
        .table("workspace_members")
        .select("team_id")
        .eq("workspace_id", workspace_id)
        .execute()
    )
    counts: dict[str, int] = {}
    for row in members_res.data:
        team_id = row.get("team_id")
        if team_id:
            counts[team_id] = counts.get(team_id, 0) + 1

    return [
        {"id": t["id"], "name": t["name"], "member_count": counts.get(t["id"], 0)}
        for t in teams_res.data
    ]


def delete_team(team_id: str) -> None:
    members_res = (
        get_supabase()
        .table("workspace_members")
        .select("user_id")
        .eq("team_id", team_id)
        .execute()
    )
    if members_res.data:
        raise ValueError("팀에 소속된 인원이 있어 삭제할 수 없음")

    get_supabase().table("teams").delete().eq("id", team_id).execute()


def list_team_members(team_id: str) -> list[dict]:
    res = (
        get_supabase()
        .table("workspace_members")
        .select("user_id, role, profiles(display_name)")
        .eq("team_id", team_id)
        .execute()
    )
    return [_flatten_display_name(row) for row in res.data]


def list_workspace_users_with_team(workspace_id: str) -> list[dict]:
    members_res = (
        get_supabase()
        .table("workspace_members")
        .select("user_id, role, team_id, profiles(display_name)")
        .eq("workspace_id", workspace_id)
        .execute()
    )
    rows = [_flatten_display_name(row) for row in members_res.data]

    teams_res = (
        get_supabase()
        .table("teams")
        .select("id, name")
        .eq("workspace_id", workspace_id)
        .execute()
    )
    team_names = {t["id"]: t["name"] for t in teams_res.data}

    for row in rows:
        row["team_name"] = team_names.get(row.get("team_id"))
    return rows


def move_member_to_team(workspace_id: str, user_id: str, team_id: Optional[str]) -> None:
    get_supabase().table("workspace_members").update({"team_id": team_id}).eq(
        "workspace_id", workspace_id
    ).eq("user_id", user_id).execute()
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_teams.py -v`
Expected: 전부 PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/api/db.py tests/test_teams.py
git commit -m "Feat: 팀 관리 db.py 함수 + 단위 테스트"
```

---

### Task 4: `main.py` 엔드포인트 + 라우터 테스트

**Files:**
- Modify: `src/api/main.py`
- Test: `tests/test_teams_router.py` (신규)

**Interfaces:**
- Consumes: Task 2의 `TeamOut`/`TeamMemberOut`/`AdminUserOut`/`CreateTeamRequest`/`AssignTeamRequest`, Task 3의 `db.get_workspace_member`/`create_team`/`list_teams`/`delete_team`/`list_team_members`/`list_workspace_users_with_team`/`move_member_to_team`, 기존 `_require_workspace`/`_require_owner`(`src/api/main.py:108-117`), 기존 `AddParticipantRequest` 스키마(`user_id: str`).
- Produces: 8개 엔드포인트(`POST /teams`, `DELETE /teams/{team_id}`, `GET /teams`, `GET /teams/{team_id}/members`, `GET /admin/users`, `PATCH /admin/users/{user_id}/team`, `POST /teams/{team_id}/members`, `POST /teams/{team_id}/members/recruit`, `DELETE /teams/{team_id}/members/{user_id}`).

- [ ] **Step 1: 실패하는 라우터 테스트 작성**

`tests/test_teams_router.py` 신규 생성:

```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_teams_router.py -v`
Expected: 404(라우트 없음) 등으로 전부 FAIL.

- [ ] **Step 3: `src/api/main.py`에 구현**

`src/api/schemas.py` import 목록(`main.py:30-45`)에 추가:

```python
from .schemas import (
    AddParticipantRequest,
    AdminSessionOut,
    AdminUserOut,
    AssignTeamRequest,
    ChatMessageOut,
    ChatSessionOut,
    CitationOut,
    CreateSessionRequest,
    CreateTeamRequest,
    ParticipantOut,
    RenameSessionRequest,
    SaveToWikiResponse,
    SendMessageRequest,
    SendMessageResponse,
    ShareToTeamRequest,
    TeamMemberOut,
    TeamOut,
    UpdateMemberRoleRequest,
    WorkspaceMemberOut,
)
```

`_require_owner` 정의(`main.py:115-117`) 바로 뒤에 헬퍼 추가:

```python
def _require_team_scope(profile: dict, workspace_id: str, team_id: str, allow_roles: set[str]) -> dict:
    member = db.get_workspace_member(workspace_id, profile["id"])
    if member is None or member.get("role") not in allow_roles or member.get("team_id") != team_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="이 팀에 대한 권한이 없음")
    return member
```

파일 끝에 엔드포인트 추가:

```python
@app.post("/teams", response_model=TeamOut)
def create_team(body: CreateTeamRequest, profile: dict = Depends(get_current_user)):
    """팀 생성 — 관리자(오너) 전용."""
    workspace_id = _require_workspace(profile)
    _require_owner(profile, workspace_id)
    try:
        team = db.create_team(workspace_id, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TeamOut(id=team["id"], name=team["name"], member_count=0)


@app.delete("/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team(team_id: str, profile: dict = Depends(get_current_user)):
    """팀 삭제 — 관리자(오너) 전용. 소속 인원이 있으면 400."""
    workspace_id = _require_workspace(profile)
    _require_owner(profile, workspace_id)
    try:
        db.delete_team(team_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.get("/teams", response_model=list[TeamOut])
def list_teams(profile: dict = Depends(get_current_user)):
    """팀 목록 + 인원수 — 워크스페이스 멤버 누구나 열람 가능."""
    workspace_id = _require_workspace(profile)
    rows = db.list_teams(workspace_id)
    return [TeamOut(**r) for r in rows]


@app.get("/teams/{team_id}/members", response_model=list[TeamMemberOut])
def list_team_members(team_id: str, profile: dict = Depends(get_current_user)):
    """팀별 멤버 명단 — 워크스페이스 멤버 누구나 열람 가능."""
    _require_workspace(profile)
    rows = db.list_team_members(team_id)
    return [
        TeamMemberOut(user_id=r["user_id"], display_name=r.get("display_name"), role=r.get("role"))
        for r in rows
    ]


@app.get("/admin/users", response_model=list[AdminUserOut])
def list_all_users(profile: dict = Depends(get_current_user)):
    """전체 사용자 + 소속 팀 — 관리자(오너) 전용."""
    workspace_id = _require_workspace(profile)
    _require_owner(profile, workspace_id)
    rows = db.list_workspace_users_with_team(workspace_id)
    return [
        AdminUserOut(
            user_id=r["user_id"], display_name=r.get("display_name"), role=r.get("role"),
            team_id=r.get("team_id"), team_name=r.get("team_name"),
        )
        for r in rows
    ]


@app.patch("/admin/users/{user_id}/team", status_code=status.HTTP_204_NO_CONTENT)
def assign_user_team(user_id: str, body: AssignTeamRequest, profile: dict = Depends(get_current_user)):
    """사용자를 임의 팀에 배치/제외(team_id=null) — 관리자(오너) 전용, 자기 팀 범위 제한 없음."""
    workspace_id = _require_workspace(profile)
    _require_owner(profile, workspace_id)
    db.move_member_to_team(workspace_id, user_id, body.team_id)


@app.post("/teams/{team_id}/members", status_code=status.HTTP_204_NO_CONTENT)
def invite_team_member(team_id: str, body: AddParticipantRequest, profile: dict = Depends(get_current_user)):
    """팀원 초대 — 팀원/팀장 모두 자기 팀에만 가능. 대상은 미배치 사용자만(이미 배치된
    사용자는 팀장의 영입 엔드포인트를 써야 함)."""
    workspace_id = _require_workspace(profile)
    _require_team_scope(profile, workspace_id, team_id, {"admin", "editor"})

    target = db.get_workspace_member(workspace_id, body.user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="워크스페이스 멤버가 아님")
    if target.get("team_id") is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이미 배치된 사용자입니다. 팀장만 영입할 수 있음",
        )

    db.move_member_to_team(workspace_id, body.user_id, team_id)


@app.post("/teams/{team_id}/members/recruit", status_code=status.HTTP_204_NO_CONTENT)
def recruit_team_member(team_id: str, body: AddParticipantRequest, profile: dict = Depends(get_current_user)):
    """팀원 영입 — 팀장 전용, 자기 팀만. 대상이 다른 팀 소속이어도 데려올 수 있다."""
    workspace_id = _require_workspace(profile)
    _require_team_scope(profile, workspace_id, team_id, {"admin"})

    target = db.get_workspace_member(workspace_id, body.user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="워크스페이스 멤버가 아님")
    if target.get("team_id") == team_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="이미 같은 팀임")

    db.move_member_to_team(workspace_id, body.user_id, team_id)


@app.delete("/teams/{team_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_team_member(team_id: str, user_id: str, profile: dict = Depends(get_current_user)):
    """팀원 제외(팀에서만, 워크스페이스 방출 아님) — 팀장 전용, 자기 팀만. 본인은 대상 불가."""
    workspace_id = _require_workspace(profile)
    _require_team_scope(profile, workspace_id, team_id, {"admin"})
    if user_id == profile["id"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="본인은 제외할 수 없음")

    target = db.get_workspace_member(workspace_id, user_id)
    if target is None or target.get("team_id") != team_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="이 팀 소속이 아님")

    db.move_member_to_team(workspace_id, user_id, None)
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_teams_router.py -v`
Expected: 전부 PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/api/main.py tests/test_teams_router.py
git commit -m "Feat: 팀 관리 API 엔드포인트 8종 추가"
```

---

### Task 5: 문서 동기화

**Files:**
- Modify: `docs/architecture/mywiki-erd.md`

**Interfaces:**
- Consumes: Task 1에서 확정된 스키마.
- Produces: 없음(문서만).

- [ ] **Step 1: ERD 문서에 `teams` 테이블 반영**

`docs/architecture/mywiki-erd.md`의 `app` 섹션 표(`workspace_members` 행 다음)에 행 추가:

```markdown
| `teams` | `id`, `workspace_id`, `name`, `created_at`, `updated_at` | `(workspace_id, name)` UNIQUE |
```

`workspace_members` 행의 "핵심 컬럼"에 `team_id` 추가:

```markdown
| `workspace_members` | `id`, `workspace_id`, `user_id`, `role`, `team_id`, `created_at` | role은 `owner/admin/editor/viewer`; (workspace_id, user_id) UNIQUE |
```

`## 3. 역할` 섹션 마지막에 추가:

```markdown
`admin`(팀장)·`editor`(팀원)는 `workspace_members.team_id`로 소속 팀이 정해지며, 팀장은
자기 팀 범위 안에서만 팀원 초대/제외/영입할 수 있다. `owner`(관리자/인사팀)는 팀 범위와
무관하게 전체 사용자·팀별 명단을 조회하고 임의로 팀 배치를 바꿀 수 있다.
```

ERD mermaid 다이어그램(`## 1. 전체 ERD`)에 관계 추가:

```
    APP_WORKSPACES ||--o{ APP_TEAMS : has
    APP_TEAMS ||--o{ APP_WORKSPACE_MEMBERS : groups
```

- [ ] **Step 2: ERDCloud 다이어그램 동기화**

ERDCloud MCP로 라이브 다이어그램에 반영한다:
1. `create_table`로 `teams` 테이블 생성(컬럼: `id`(PK, uuid domain), `workspace_id`(uuid, FK 예정), `name`(varchar255 또는 text domain), `created_at`/`updated_at`(datetime domain)). 기존 도메인이 있으면 재사용, 없으면 `create_domain`으로 먼저 만든다.
2. `add_column`으로 `workspace_members`에 `team_id`(uuid, nullable) 추가.
3. `create_relation`으로 `workspaces` → `teams`(1:N), `teams` → `workspace_members`(1:N) 관계선 연결.

대상 다이어그램 식별자는 메모리 `erdcloud-mcp.md` 참고 — 연결이 끊겨 있으면 이 단계는 스킵하고 사용자에게 안내한다(마이그레이션 자체는 이미 라이브 DB에 적용됐으므로 기능 동작에는 영향 없음, 다이어그램 동기화만 지연됨).

- [ ] **Step 3: 커밋**

```bash
git add docs/architecture/mywiki-erd.md
git commit -m "Docs: ERD 문서에 teams 테이블 반영"
```

---

### Task 6: 전체 테스트 + PR + 머지

**Files:** 없음(검증·배포 전용 태스크)

- [ ] **Step 1: 전체 테스트 스위트 실행**

Run: `pytest`
Expected: 전부 PASS, 실패 0건.

- [ ] **Step 2: 브랜치 푸시**

```bash
git push -u origin claude/role-based-user-management-7c735e
```

- [ ] **Step 3: PR 생성 (base: develop)**

```bash
gh pr create --base develop --title "Feat: 팀 기반 역할·권한 관리(팀원/팀장/관리자)" --body "$(cat <<'EOF'
## Summary
- teams 테이블 + workspace_members.team_id 추가(새 역할 컬럼 없이 기존 owner/admin/editor를 관리자/팀장/팀원으로 재해석)
- 팀원: 미배치 사용자를 자기 팀으로 초대
- 팀장: 자기 팀 범위 안에서 초대/제외 + 타 팀 인원 영입
- 관리자(오너): 전체 사용자·팀별 명단 조회, 임의 팀 배치/제외, 팀 생성·삭제

## Test plan
- [x] pytest 전체 통과
- [x] 라이브 Supabase에 마이그레이션 적용 확인(list_tables)

설계: docs/superpowers/specs/2026-08-09-team-based-permissions-design.md
계획: docs/superpowers/plans/2026-08-09-team-based-permissions.md

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: PR 머지**

```bash
gh pr merge --squash --delete-branch
```

- [ ] **Step 5: 머지 확인**

Run: `gh pr view --json state,mergedAt`
Expected: `state: MERGED`.

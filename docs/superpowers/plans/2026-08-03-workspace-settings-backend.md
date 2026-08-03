# 워크스페이스 설정 백엔드 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wiki 업데이트 주기·에이전트 대화 보관 기간을 워크스페이스 공유 설정으로 DB에 저장하고, 실제로 위키 갱신 주기와 오래된 대화 삭제를 구동하는 백엔드를 만든다.

**Architecture:** 신규 `src/settings/` 모듈(models.py + service.py, `src/wiki/query.py`와 같은 구조) + `src/api/settings_router.py`(REST) + 2개 배치 스크립트(위키 갱신 게이트, 대화 정리) + 2개 GitHub Actions 워크플로우.

**Tech Stack:** Python 3.12, FastAPI, Supabase Python client, pytest.

## Global Constraints

- `workspace_settings` 테이블은 이미 라이브 DB에 적용 완료(마이그레이션 `supabase/migrations/20260803020000_create_workspace_settings.sql`, 커밋 완료). 이 플랜의 태스크들은 이 테이블이 이미 존재한다고 가정하고 실 DB 통합 테스트를 바로 돌릴 수 있다.
- 컬럼: `workspace_id`(PK), `wiki_update_cycle_minutes`(int, CHECK IN (30,60,180,360,720,1440), 기본 360), `chat_retention_days`(int, CHECK IN (7,30,90) 또는 NULL=영구보관), `last_wiki_refresh_at`(timestamptz, nullable), `updated_by`(uuid, nullable), `updated_at`(timestamptz, 트리거로 자동 갱신).
- `chat_sessions.updated_at`은 메시지 추가 시 갱신되지 않는다(확인 완료) — "마지막 활동"은 `chat_messages`에서 세션별 최신 `created_at`을 직접 조회해서 판단한다.
- `refresh_wiki.py`(PR #17)는 그대로 둔다 — 게이트는 그 앞에 얹는 새 진입점이지 기존 스크립트를 고치는 게 아니다. `refresh_wiki_from_recent_analysis()`는 이미 이슈 페이지 중복방지 로직이 있어 여러 번 겹쳐 호출돼도 안전하다.
- Wiki 주기 게이트는 크론 자체를 재작성하지 않는다 — GitHub Actions는 30분 고정 주기로 돌고, 매번 DB의 `wiki_update_cycle_minutes`/`last_wiki_refresh_at`을 비교해서 실행 여부만 판단한다.
- 무인 배치는 실패 시 예외를 그대로 던져서 GitHub Actions가 실패로 표시하게 둔다(`refresh_wiki.py`의 기존 방침과 동일).

---

## File Structure

```
src/settings/
├── models.py         # WorkspaceSettings frozen dataclass
└── service.py         # get_workspace_settings / update_workspace_settings / mark_wiki_refreshed

src/api/
├── schemas.py         # WorkspaceSettingsOut, UpdateWorkspaceSettingsRequest 추가
└── settings_router.py # GET/PATCH /settings

scripts/
├── refresh_wiki_scheduled.py  # 게이트 + refresh_wiki_from_recent_analysis 호출
└── cleanup_old_chats.py        # 보관 기간 지난 대화 삭제

.github/workflows/
├── wiki-refresh-gate.yml
└── chat-retention-cleanup.yml

tests/
├── test_settings_service.py       # 실 DB 통합 테스트
├── test_settings_router.py        # monkeypatch 라우터 테스트
├── test_refresh_wiki_scheduled.py # 게이트 판단 로직 유닛 테스트 + 통합
└── test_cleanup_old_chats.py      # 삭제 대상 판정 실 DB 통합 테스트
```

---

### Task 1: `src/settings/models.py` + `service.py`

**Files:**
- Create: `src/settings/__init__.py` (빈 파일)
- Create: `src/settings/models.py`
- Create: `src/settings/service.py`
- Test: `tests/test_settings_service.py`

**Interfaces:**
- Produces: `WorkspaceSettings`(frozen dataclass: `workspace_id, wiki_update_cycle_minutes, chat_retention_days, last_wiki_refresh_at, updated_at`), `get_workspace_settings(workspace_id, *, supabase=None) -> WorkspaceSettings`, `update_workspace_settings(workspace_id, *, wiki_update_cycle_minutes=None, chat_retention_days=_UNSET, updated_by, supabase=None) -> WorkspaceSettings`(`updated_by`는 기본값 없음 — 호출부가 항상 명시적으로 넘기게 강제해서 감사 추적 누락을 막는다), `mark_wiki_refreshed(workspace_id, *, supabase=None) -> None`, `WIKI_UPDATE_CYCLE_MINUTES_CHOICES = (30, 60, 180, 360, 720, 1440)`, `CHAT_RETENTION_DAYS_CHOICES = (7, 30, 90)`

`chat_retention_days`를 "안 바꿈"과 "명시적으로 null(영구보관)로 바꿈" 두 가지로 구분해야 해서, 파이썬 기본값 `None`을 그대로 쓸 수 없다 — sentinel 객체를 쓴다.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_settings_service.py
from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

load_dotenv()

from src.settings.models import WorkspaceSettings
from src.settings.service import (
    CHAT_RETENTION_DAYS_CHOICES,
    WIKI_UPDATE_CYCLE_MINUTES_CHOICES,
    get_workspace_settings,
    mark_wiki_refreshed,
    update_workspace_settings,
)
from src.settings import service as settings_service


@pytest.fixture(scope="module")
def workspace_id() -> str:
    if not os.environ.get("SUPABASE_URL") or not (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SECRET_KEY")
    ):
        pytest.skip("Supabase service credentials are not configured.")
    try:
        db = settings_service._get_client()
        res = db.table("workspaces").select("id").eq("slug", "mywiki").single().execute()
        return res.data["id"]
    except Exception as e:
        pytest.skip(f"Supabase connection failed (likely placeholder credentials): {type(e).__name__}")


def test_choices_match_check_constraints():
    assert WIKI_UPDATE_CYCLE_MINUTES_CHOICES == (30, 60, 180, 360, 720, 1440)
    assert CHAT_RETENTION_DAYS_CHOICES == (7, 30, 90)


def test_get_workspace_settings_returns_existing_row(workspace_id):
    settings = get_workspace_settings(workspace_id)
    assert isinstance(settings, WorkspaceSettings)
    assert settings.workspace_id == workspace_id
    assert settings.wiki_update_cycle_minutes in WIKI_UPDATE_CYCLE_MINUTES_CHOICES


def test_update_workspace_settings_changes_wiki_cycle(workspace_id):
    original = get_workspace_settings(workspace_id)
    try:
        updated = update_workspace_settings(workspace_id, wiki_update_cycle_minutes=60, updated_by=None)
        assert updated.wiki_update_cycle_minutes == 60
        refetched = get_workspace_settings(workspace_id)
        assert refetched.wiki_update_cycle_minutes == 60
    finally:
        update_workspace_settings(
            workspace_id, wiki_update_cycle_minutes=original.wiki_update_cycle_minutes, updated_by=None
        )


def test_update_workspace_settings_can_set_chat_retention_to_forever(workspace_id):
    original = get_workspace_settings(workspace_id)
    try:
        updated = update_workspace_settings(workspace_id, chat_retention_days=None, updated_by=None)
        assert updated.chat_retention_days is None
    finally:
        update_workspace_settings(
            workspace_id, chat_retention_days=original.chat_retention_days, updated_by=None
        )


def test_update_workspace_settings_without_chat_retention_leaves_it_unchanged(workspace_id):
    original = get_workspace_settings(workspace_id)
    try:
        update_workspace_settings(workspace_id, chat_retention_days=30, updated_by=None)
        updated = update_workspace_settings(workspace_id, wiki_update_cycle_minutes=180, updated_by=None)
        assert updated.chat_retention_days == 30  # 안 건드렸으니 유지
    finally:
        update_workspace_settings(
            workspace_id,
            wiki_update_cycle_minutes=original.wiki_update_cycle_minutes,
            chat_retention_days=original.chat_retention_days,
            updated_by=None,
        )


def test_mark_wiki_refreshed_sets_timestamp(workspace_id):
    mark_wiki_refreshed(workspace_id)
    settings = get_workspace_settings(workspace_id)
    assert settings.last_wiki_refresh_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_settings_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.settings'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/settings/models.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class WorkspaceSettings:
    workspace_id: str
    wiki_update_cycle_minutes: int
    chat_retention_days: Optional[int]
    last_wiki_refresh_at: Optional[str]
    updated_at: str
```

```python
# src/settings/service.py
"""워크스페이스 공유 설정(Wiki 업데이트 주기·대화 보관 기간) CRUD."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

from supabase import Client, create_client

from .models import WorkspaceSettings

WIKI_UPDATE_CYCLE_MINUTES_CHOICES = (30, 60, 180, 360, 720, 1440)
CHAT_RETENTION_DAYS_CHOICES = (7, 30, 90)

_DEFAULT_WIKI_UPDATE_CYCLE_MINUTES = 360

# chat_retention_days를 "안 바꿈"과 "명시적으로 null(영구보관)로 바꿈"으로 구분하기 위한 sentinel.
_UNSET = object()


@lru_cache(maxsize=1)
def _get_client() -> Client:
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ["SUPABASE_SECRET_KEY"]
    return create_client(os.environ["SUPABASE_URL"], key)


def _row_to_settings(row: dict) -> WorkspaceSettings:
    return WorkspaceSettings(
        workspace_id=row["workspace_id"],
        wiki_update_cycle_minutes=row["wiki_update_cycle_minutes"],
        chat_retention_days=row.get("chat_retention_days"),
        last_wiki_refresh_at=row.get("last_wiki_refresh_at"),
        updated_at=row["updated_at"],
    )


def get_workspace_settings(workspace_id: str, *, supabase: Client | None = None) -> WorkspaceSettings:
    """행이 없으면 기본값으로 즉시 생성 후 반환한다."""
    db = supabase or _get_client()
    res = (
        db.table("workspace_settings")
        .select("*")
        .eq("workspace_id", workspace_id)
        .maybe_single()
        .execute()
    )
    if res.data:
        return _row_to_settings(res.data)

    insert_res = (
        db.table("workspace_settings")
        .insert({
            "workspace_id": workspace_id,
            "wiki_update_cycle_minutes": _DEFAULT_WIKI_UPDATE_CYCLE_MINUTES,
        })
        .execute()
    )
    return _row_to_settings(insert_res.data[0])


def update_workspace_settings(
    workspace_id: str,
    *,
    wiki_update_cycle_minutes: Optional[int] = None,
    chat_retention_days: object = _UNSET,
    updated_by: Optional[str],
    supabase: Client | None = None,
) -> WorkspaceSettings:
    db = supabase or _get_client()
    get_workspace_settings(workspace_id, supabase=db)  # 행이 없으면 먼저 만든다

    patch: dict = {"updated_by": updated_by}
    if wiki_update_cycle_minutes is not None:
        if wiki_update_cycle_minutes not in WIKI_UPDATE_CYCLE_MINUTES_CHOICES:
            raise ValueError(f"허용되지 않는 wiki_update_cycle_minutes: {wiki_update_cycle_minutes}")
        patch["wiki_update_cycle_minutes"] = wiki_update_cycle_minutes
    if chat_retention_days is not _UNSET:
        if chat_retention_days is not None and chat_retention_days not in CHAT_RETENTION_DAYS_CHOICES:
            raise ValueError(f"허용되지 않는 chat_retention_days: {chat_retention_days}")
        patch["chat_retention_days"] = chat_retention_days

    res = (
        db.table("workspace_settings")
        .update(patch)
        .eq("workspace_id", workspace_id)
        .execute()
    )
    return _row_to_settings(res.data[0])


def mark_wiki_refreshed(workspace_id: str, *, supabase: Client | None = None) -> None:
    db = supabase or _get_client()
    now = datetime.now(timezone.utc).isoformat()
    db.table("workspace_settings").update({"last_wiki_refresh_at": now}).eq(
        "workspace_id", workspace_id
    ).execute()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_settings_service.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/settings/ tests/test_settings_service.py
git commit -m "Feat: 워크스페이스 설정 CRUD 서비스 추가"
```

---

### Task 2: `src/api/settings_router.py`

**Files:**
- Modify: `src/api/schemas.py` (끝에 추가)
- Create: `src/api/settings_router.py`
- Modify: `src/api/main.py:1-31` (import + `app.include_router` 추가)
- Test: `tests/test_settings_router.py`

**Interfaces:**
- Consumes: Task 1의 `get_workspace_settings`, `update_workspace_settings`, `WorkspaceSettings`
- Produces: `GET /settings`, `PATCH /settings` 엔드포인트

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_settings_router.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.api.settings_router'`

- [ ] **Step 3: Write minimal implementation**

`src/api/schemas.py` 끝에 추가:

```python
class WorkspaceSettingsOut(BaseModel):
    model_config = {"from_attributes": True}

    workspace_id: str
    wiki_update_cycle_minutes: int
    chat_retention_days: Optional[int]
    last_wiki_refresh_at: Optional[str]
    updated_at: str


class UpdateWorkspaceSettingsRequest(BaseModel):
    wiki_update_cycle_minutes: Optional[Literal[30, 60, 180, 360, 720, 1440]] = None
    chat_retention_days: Optional[int] = None
```

`chat_retention_days`를 `Optional[Literal[7, 30, 90]]`으로 못 쓰는 이유: 값 자체의 검증(7/30/90 또는 null)과, "필드를 아예 안 보냄"과 "명시적으로 null을 보냄"을 구분하는 문제가 섞여 있다. 후자는 pydantic v2가 모든 모델 인스턴스에 기본 제공하는 `model_fields_set: set[str]`(생성 시 실제로 전달된 필드명 집합)로 라우터에서 직접 구분한다 — 커스텀 sentinel 필드가 필요 없다. 값 자체의 검증(7/30/90 또는 null)도 라우터에서 수행한다(아래 라우터 코드 참고).

```python
# src/api/settings_router.py
"""워크스페이스 설정 REST 엔드포인트."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from . import db
from .auth import get_current_user
from .schemas import UpdateWorkspaceSettingsRequest, WorkspaceSettingsOut
from ..settings.service import (
    CHAT_RETENTION_DAYS_CHOICES,
    get_workspace_settings,
    update_workspace_settings,
)

router = APIRouter(tags=["settings"])


def _require_workspace(profile: dict) -> str:
    workspace_id = db.get_default_workspace_id(profile["id"])
    if not workspace_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="workspace 소속이 없음")
    return workspace_id


@router.get("/settings", response_model=WorkspaceSettingsOut)
def get_settings(profile: dict = Depends(get_current_user)):
    workspace_id = _require_workspace(profile)
    return get_workspace_settings(workspace_id)


@router.patch("/settings", response_model=WorkspaceSettingsOut)
def patch_settings(body: UpdateWorkspaceSettingsRequest, profile: dict = Depends(get_current_user)):
    workspace_id = _require_workspace(profile)

    kwargs: dict = {"updated_by": profile["id"]}
    if body.wiki_update_cycle_minutes is not None:
        kwargs["wiki_update_cycle_minutes"] = body.wiki_update_cycle_minutes
    if "chat_retention_days" in body.model_fields_set:
        if body.chat_retention_days is not None and body.chat_retention_days not in CHAT_RETENTION_DAYS_CHOICES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"chat_retention_days는 {CHAT_RETENTION_DAYS_CHOICES} 또는 null이어야 함",
            )
        kwargs["chat_retention_days"] = body.chat_retention_days

    try:
        return update_workspace_settings(workspace_id, **kwargs)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
```

`src/api/main.py`에서 라우터 등록(`wiki_router` 등록 부분 근처):

```python
from .settings_router import router as settings_router
```

```python
app.include_router(wiki_router)
app.include_router(settings_router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_settings_router.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/api/schemas.py src/api/settings_router.py src/api/main.py tests/test_settings_router.py
git commit -m "Feat: 워크스페이스 설정 REST API 추가 (GET/PATCH /settings)"
```

---

### Task 3: `scripts/refresh_wiki_scheduled.py` — 위키 갱신 게이트

**Files:**
- Create: `scripts/refresh_wiki_scheduled.py`
- Test: `tests/test_refresh_wiki_scheduled.py`

**Interfaces:**
- Consumes: Task 1의 `get_workspace_settings`, `mark_wiki_refreshed`; `src.wiki.generation.refresh_wiki_from_recent_analysis`(기존)
- Produces: `is_refresh_due(last_wiki_refresh_at: str | None, cycle_minutes: int, *, now: datetime) -> bool`(순수 함수, 유닛 테스트 대상)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_refresh_wiki_scheduled.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.refresh_wiki_scheduled import is_refresh_due


def test_is_refresh_due_true_when_never_refreshed():
    assert is_refresh_due(None, 360, now=datetime.now(timezone.utc)) is True


def test_is_refresh_due_false_when_cycle_not_elapsed():
    now = datetime.now(timezone.utc)
    last = (now - timedelta(minutes=100)).isoformat()
    assert is_refresh_due(last, 360, now=now) is False


def test_is_refresh_due_true_when_cycle_elapsed():
    now = datetime.now(timezone.utc)
    last = (now - timedelta(minutes=400)).isoformat()
    assert is_refresh_due(last, 360, now=now) is True


def test_is_refresh_due_true_at_exact_boundary():
    now = datetime.now(timezone.utc)
    last = (now - timedelta(minutes=360)).isoformat()
    assert is_refresh_due(last, 360, now=now) is True
```

`scripts/`는 패키지가 아니라서(`__init__.py` 없음) 이 테스트가 `from scripts.refresh_wiki_scheduled import is_refresh_due`로 바로 임포트하려면 `scripts/__init__.py`가 필요하다 — 이미 Task 1에서 만든 `src/settings/__init__.py`와 별개로, 이 태스크에서 `scripts/__init__.py`(빈 파일)를 추가한다. 기존 `scripts/*.py`들은 전부 `sys.path` 조작 후 `python scripts/xxx.py`로 직접 실행하는 방식이라 이 변경이 그 실행 방식을 깨지 않는다(패키지화해도 스크립트로 직접 실행하는 건 그대로 됨).

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_refresh_wiki_scheduled.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.refresh_wiki_scheduled'`

- [ ] **Step 3: Write minimal implementation**

```bash
touch scripts/__init__.py
```

```python
# scripts/refresh_wiki_scheduled.py
"""Wiki 업데이트 주기(workspace_settings.wiki_update_cycle_minutes)를 지킨 채
refresh_wiki_from_recent_analysis()를 돌리는 게이트.

GitHub Actions는 30분(가장 촘촘한 주기 옵션)마다 이 스크립트를 호출하지만,
실제로 갱신을 실행하는 건 설정된 주기가 지났을 때뿐이다. refresh_wiki.py는
상태 없이(stateless) 항상 "최근 N시간 분석분"만 처리하므로, 게이트를 통과할
때마다 넉넉한 고정 lookback(24시간)으로 불러도 안전하다 — 이슈 페이지
중복방지 로직(find_matching_issue_page)이 겹쳐 호출되는 경우를 막아준다.

사용법:
    python scripts/refresh_wiki_scheduled.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.pipeline_common.db import get_client
from src.settings.service import get_workspace_settings, mark_wiki_refreshed
from src.wiki.generation import refresh_wiki_from_recent_analysis
from src.wiki.generation_models import WikiDraftGenerationResult

SINCE_HOURS_LOOKBACK = 24


def log(msg: str) -> None:
    print(f"[refresh_wiki_scheduled] {msg}", flush=True)


def is_refresh_due(last_wiki_refresh_at: str | None, cycle_minutes: int, *, now: datetime) -> bool:
    """last_wiki_refresh_at이 없으면(한 번도 안 돌았으면) 무조건 실행."""
    if last_wiki_refresh_at is None:
        return True
    last = datetime.fromisoformat(last_wiki_refresh_at.replace("Z", "+00:00"))
    elapsed_minutes = (now - last).total_seconds() / 60
    return elapsed_minutes >= cycle_minutes


def get_workspace_id() -> str:
    rows = get_client().table("workspaces").select("id, name").limit(2).execute().data
    if len(rows) != 1:
        raise SystemExit(f"workspace_id를 자동으로 하나로 못 정했다 (workspaces 행 {len(rows)}개).")
    return str(rows[0]["id"])


def report_results(results: list[WikiDraftGenerationResult]) -> int:
    log(f"{len(results)}개 이슈 처리:")
    for r in results:
        log(f"  - {r.issue_key}: issue_page={r.issue_page_id} topic_action={r.topic_action}")
        if r.error_message:
            log(f"    error: {r.error_message}")
    if results and all(r.error_message is not None for r in results):
        return 1
    return 0


if __name__ == "__main__":
    workspace_id = get_workspace_id()
    settings = get_workspace_settings(workspace_id)

    now = datetime.now(timezone.utc)
    if not is_refresh_due(settings.last_wiki_refresh_at, settings.wiki_update_cycle_minutes, now=now):
        log(
            f"아직 주기 안 됨 (주기={settings.wiki_update_cycle_minutes}분, "
            f"마지막 갱신={settings.last_wiki_refresh_at})"
        )
        sys.exit(0)

    log(f"주기 도달 — 갱신 시작 (주기={settings.wiki_update_cycle_minutes}분)")
    results = refresh_wiki_from_recent_analysis(workspace_id, since_hours=SINCE_HOURS_LOOKBACK)
    exit_code = report_results(results)
    mark_wiki_refreshed(workspace_id)

    if exit_code != 0:
        raise SystemExit(exit_code)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_refresh_wiki_scheduled.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/__init__.py scripts/refresh_wiki_scheduled.py tests/test_refresh_wiki_scheduled.py
git commit -m "Feat: Wiki 업데이트 주기 설정을 실제로 지키는 갱신 게이트 스크립트 추가"
```

---

### Task 4: `scripts/cleanup_old_chats.py` — 대화 보관 기간 배치

**Files:**
- Create: `scripts/cleanup_old_chats.py`
- Test: `tests/test_cleanup_old_chats.py`

**Interfaces:**
- Consumes: Task 1의 `get_workspace_settings`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cleanup_old_chats.py
"""실 DB 통합 테스트 — 세션을 만들고 오래된 메시지로 조작한 뒤 삭제 대상 판정을 확인한다."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from dotenv import load_dotenv

load_dotenv()

from scripts.cleanup_old_chats import delete_expired_sessions, find_expired_session_ids
from src.settings.service import _get_client


@pytest.fixture(scope="module")
def workspace_id() -> str:
    if not os.environ.get("SUPABASE_URL") or not (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SECRET_KEY")
    ):
        pytest.skip("Supabase service credentials are not configured.")
    try:
        db = _get_client()
        res = db.table("workspaces").select("id").eq("slug", "mywiki").single().execute()
        return res.data["id"]
    except Exception as e:
        pytest.skip(f"Supabase connection failed (likely placeholder credentials): {type(e).__name__}")


@pytest.fixture(scope="module")
def user_id(workspace_id) -> str:
    db = _get_client()
    profile = db.table("profiles").select("id").limit(1).execute()
    if not profile.data:
        pytest.skip("profiles 데이터 없음")
    return profile.data[0]["id"]


def _make_session(workspace_id: str, user_id: str, *, last_message_days_ago: int) -> str:
    db = _get_client()
    now = datetime.now(timezone.utc)
    session = (
        db.table("chat_sessions")
        .insert({
            "workspace_id": workspace_id,
            "user_id": user_id,
            "title": f"test-{uuid.uuid4().hex[:8]}",
            "visibility": "private",
            "created_at": (now - timedelta(days=last_message_days_ago + 5)).isoformat(),
        })
        .execute()
        .data[0]
    )
    db.table("chat_messages").insert({
        "session_id": session["id"],
        "role": "user",
        "content": "테스트 메시지",
        "created_at": (now - timedelta(days=last_message_days_ago)).isoformat(),
    }).execute()
    return session["id"]


def _cleanup_session(session_id: str) -> None:
    db = _get_client()
    db.table("chat_messages").delete().eq("session_id", session_id).execute()
    db.table("chat_sessions").delete().eq("id", session_id).execute()


def test_find_expired_session_ids_uses_last_message_time(workspace_id, user_id):
    old_session_id = _make_session(workspace_id, user_id, last_message_days_ago=100)
    recent_session_id = _make_session(workspace_id, user_id, last_message_days_ago=1)
    try:
        expired = find_expired_session_ids(workspace_id, retention_days=90)
        assert old_session_id in expired
        assert recent_session_id not in expired
    finally:
        _cleanup_session(old_session_id)
        _cleanup_session(recent_session_id)


def test_delete_expired_sessions_removes_messages_and_session(workspace_id, user_id):
    old_session_id = _make_session(workspace_id, user_id, last_message_days_ago=100)
    try:
        deleted_count = delete_expired_sessions(workspace_id, retention_days=90)
        assert deleted_count >= 1

        db = _get_client()
        remaining = db.table("chat_sessions").select("id").eq("id", old_session_id).execute().data
        assert remaining == []
        remaining_messages = (
            db.table("chat_messages").select("id").eq("session_id", old_session_id).execute().data
        )
        assert remaining_messages == []
    finally:
        _cleanup_session(old_session_id)  # 이미 지워졌으면 조용히 아무것도 안 함


def test_find_expired_session_ids_empty_when_retention_none(workspace_id, user_id):
    old_session_id = _make_session(workspace_id, user_id, last_message_days_ago=1000)
    try:
        assert find_expired_session_ids(workspace_id, retention_days=None) == []
    finally:
        _cleanup_session(old_session_id)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cleanup_old_chats.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.cleanup_old_chats'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/cleanup_old_chats.py
"""워크스페이스 설정(chat_retention_days)에 따라 오래된 대화를 지운다.

chat_sessions.updated_at은 메시지가 추가돼도 갱신되지 않으므로(확인됨),
"마지막 활동 시각"은 chat_messages에서 세션별 최신 created_at을 직접
조회해서 판단한다. 메시지가 하나도 없는 세션은 chat_sessions.created_at을 쓴다.

사용법:
    python scripts/cleanup_old_chats.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.pipeline_common.db import get_client
from src.settings.service import get_workspace_settings


def log(msg: str) -> None:
    print(f"[cleanup_old_chats] {msg}", flush=True)


def get_workspace_id() -> str:
    rows = get_client().table("workspaces").select("id, name").limit(2).execute().data
    if len(rows) != 1:
        raise SystemExit(f"workspace_id를 자동으로 하나로 못 정했다 (workspaces 행 {len(rows)}개).")
    return str(rows[0]["id"])


def find_expired_session_ids(workspace_id: str, *, retention_days: int | None) -> list[str]:
    """retention_days가 None(영구 보관)이면 빈 리스트."""
    if retention_days is None:
        return []

    db = get_client()
    sessions = (
        db.table("chat_sessions")
        .select("id, created_at")
        .eq("workspace_id", workspace_id)
        .execute()
        .data
    )
    if not sessions:
        return []

    session_ids = [s["id"] for s in sessions]
    messages = (
        db.table("chat_messages")
        .select("session_id, created_at")
        .in_("session_id", session_ids)
        .order("created_at", desc=True)
        .execute()
        .data
    )
    last_message_at: dict[str, str] = {}
    for m in messages:
        last_message_at.setdefault(m["session_id"], m["created_at"])  # desc 정렬이라 첫 값이 최신

    threshold = datetime.now(timezone.utc) - timedelta(days=retention_days)
    expired: list[str] = []
    for s in sessions:
        last_activity_raw = last_message_at.get(s["id"], s["created_at"])
        last_activity = datetime.fromisoformat(str(last_activity_raw).replace("Z", "+00:00"))
        if last_activity < threshold:
            expired.append(s["id"])
    return expired


def delete_expired_sessions(workspace_id: str, *, retention_days: int | None) -> int:
    expired_ids = find_expired_session_ids(workspace_id, retention_days=retention_days)
    if not expired_ids:
        return 0

    db = get_client()
    messages = (
        db.table("chat_messages").select("id").in_("session_id", expired_ids).execute().data
    )
    message_ids = [m["id"] for m in messages]
    if message_ids:
        db.table("message_citations").delete().in_("message_id", message_ids).execute()
    db.table("chat_messages").delete().in_("session_id", expired_ids).execute()
    db.table("chat_sessions").delete().in_("id", expired_ids).execute()
    return len(expired_ids)


if __name__ == "__main__":
    workspace_id = get_workspace_id()
    settings = get_workspace_settings(workspace_id)

    if settings.chat_retention_days is None:
        log("영구 보관 설정 — 삭제 없음")
        sys.exit(0)

    log(f"보관 기간 {settings.chat_retention_days}일 기준으로 정리 시작")
    deleted_count = delete_expired_sessions(workspace_id, retention_days=settings.chat_retention_days)
    log(f"삭제된 세션: {deleted_count}건")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cleanup_old_chats.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/cleanup_old_chats.py tests/test_cleanup_old_chats.py
git commit -m "Feat: 대화 보관 기간 설정에 따라 오래된 대화를 지우는 배치 추가"
```

---

### Task 5: GitHub Actions 워크플로우 2개

**Files:**
- Create: `.github/workflows/wiki-refresh-gate.yml`
- Create: `.github/workflows/chat-retention-cleanup.yml`

**Interfaces:**
- Consumes: Task 3의 `scripts/refresh_wiki_scheduled.py`, Task 4의 `scripts/cleanup_old_chats.py`(둘 다 커맨드라인 인터페이스만)

이 태스크는 YAML 2개만 추가한다. GitHub Actions 실행 자체는 로컬 pytest로 검증 불가능하므로, "테스트"는 YAML 문법 검증 + `workflow_dispatch` 수동 실행 확인으로 대체한다.

- [ ] **Step 1: Write the workflow files**

```yaml
# .github/workflows/wiki-refresh-gate.yml
name: Wiki Refresh Gate

on:
  schedule:
    - cron: "*/30 * * * *" # 30분마다 — 실제 갱신 여부는 스크립트 안에서 주기 설정을 보고 판단
  workflow_dispatch: {}

jobs:
  refresh:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run wiki refresh gate
        run: python scripts/refresh_wiki_scheduled.py
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SECRET_KEY }}
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
```

```yaml
# .github/workflows/chat-retention-cleanup.yml
name: Chat Retention Cleanup

on:
  schedule:
    - cron: "13 3 * * *" # 매일 새벽 3시 13분(부하 회피), 하루 1회면 충분
  workflow_dispatch: {}

jobs:
  cleanup:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run chat retention cleanup
        run: python scripts/cleanup_old_chats.py
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SECRET_KEY }}
```

`OPENROUTER_API_KEY`는 wiki-refresh-gate에만 필요하다(`refresh_wiki_from_recent_analysis`가 위키 생성 LLM을 호출함) — chat-retention-cleanup은 DB 삭제만 하므로 불필요.

- [ ] **Step 2: Validate YAML and commit**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/wiki-refresh-gate.yml', encoding='utf-8'))"
python -c "import yaml; yaml.safe_load(open('.github/workflows/chat-retention-cleanup.yml', encoding='utf-8'))"
git add .github/workflows/wiki-refresh-gate.yml .github/workflows/chat-retention-cleanup.yml
git commit -m "Feat: Wiki 갱신 게이트 + 대화 정리 배치 GitHub Actions 워크플로우 추가"
```

머지 후 두 워크플로우 다 `workflow_dispatch`로 수동 1회 실행해서 정상 완료를 확인해야 한다(이 플랜 범위 밖 — PR 설명에 TODO로 남긴다).

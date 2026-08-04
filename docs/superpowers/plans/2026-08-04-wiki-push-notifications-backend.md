# 위키 발행 브라우저 푸시 알림 — 백엔드 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 위키 문서가 새로 발행될 때, 구독한 사용자에게 표준 Web Push로 브라우저 알림을 보내는 백엔드(테이블·API·발송 로직)를 만든다.

**Architecture:** 새 `push_subscriptions` 테이블에 브라우저 구독 정보를 저장하고, 새 `src/notifications/service.py`가 CRUD + `pywebpush` 발송을 맡는다. `src/api/notifications_router.py`가 구독/해지 REST를, `src/wiki/generation.py`의 배치 종료 지점이 발송 트리거를 담당한다.

**Tech Stack:** FastAPI, Supabase(Postgres), `pywebpush`(표준 Web Push, VAPID). `develop` 브랜치 기준(백엔드 전용, 프론트는 별도 계획서 `2026-08-04-wiki-push-notifications-frontend.md`).

## Global Constraints

- 배치 단위로 알림 1건만 보낸다(문서마다 보내지 않음) — 설계 §2.
- 알림 발송 실패가 위키 발행 자체를 막으면 안 된다(try/except로 격리) — 설계 §2, §7.
- 만료/취소된 구독(404/410 응답)은 그 자리에서 테이블에서 삭제한다 — 설계 §7.
- `push_subscriptions`는 `workspace_settings`와 동일한 RLS 패턴(서비스는 SERVICE_ROLE_KEY로 우회, 정책은 방어 계층)을 따른다 — 설계 §3.
- VAPID 개인키는 이 세션이 GitHub/Vercel/오라클 VM에 직접 등록하지 않는다 — 설계 §2, §6.

---

## Task 1: `push_subscriptions` 테이블 마이그레이션

**Files:**
- Create: `supabase/migrations/20260804000000_create_push_subscriptions.sql`

**Interfaces:**
- Produces: `public.push_subscriptions(id, user_id, workspace_id, endpoint, p256dh, auth, created_at)` 테이블, `UNIQUE(user_id, endpoint)` — Task 2의 `save_subscription`/`delete_subscription`이 이 테이블에 쓴다.

- [ ] **Step 1: 마이그레이션 파일 작성**

Write to `supabase/migrations/20260804000000_create_push_subscriptions.sql`:

```sql
CREATE TABLE IF NOT EXISTS public.push_subscriptions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  endpoint text NOT NULL,
  p256dh text NOT NULL,
  auth text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, endpoint)
);

ALTER TABLE public.push_subscriptions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS push_subscriptions_own ON public.push_subscriptions;

CREATE POLICY push_subscriptions_own ON public.push_subscriptions
FOR ALL
USING (user_id = auth.uid())
WITH CHECK (user_id = auth.uid());
```

- [ ] **Step 2: Supabase MCP로 라이브 DB에 적용**

`apply_migration`(project_id: `uhzjshqmnlahhvqzygkp`, name: `create_push_subscriptions`)으로 위 SQL을 그대로 적용한다. 순수 추가(새 테이블)라 기존 데이터에 영향 없음 — 만약 auto 분류기가 막으면 사용자에게 재확인을 요청한다(과거 인증 트리거 변경 때와 달리 이번엔 破괴적 변경이 아니라는 점을 설명).

- [ ] **Step 3: 테이블 생성 확인**

Supabase MCP `execute_sql`(project_id: `uhzjshqmnlahhvqzygkp`)로 확인:

```sql
select column_name, data_type from information_schema.columns where table_name = 'push_subscriptions' order by ordinal_position;
```

Expected: `id, user_id, workspace_id, endpoint, p256dh, auth, created_at` 7개 컬럼이 나온다.

- [ ] **Step 4: 커밋**

```bash
git add supabase/migrations/20260804000000_create_push_subscriptions.sql
git commit -m "Feat: push_subscriptions 테이블 마이그레이션 추가"
```

---

## Task 2: 구독 저장/삭제 (`src/notifications/service.py` 일부)

**Files:**
- Create: `src/notifications/__init__.py` (빈 파일)
- Create: `src/notifications/service.py`
- Test: `tests/test_notifications_service.py`

**Interfaces:**
- Consumes: Task 1의 `push_subscriptions` 테이블.
- Produces: `save_subscription(workspace_id: str, user_id: str, endpoint: str, p256dh: str, auth_key: str, *, supabase=None) -> None`, `delete_subscription(user_id: str, endpoint: str, *, supabase=None) -> None`, `_get_client() -> Client`(내부용, `src/settings/service.py`와 동일 패턴) — Task 4(라우터)가 앞의 두 함수를 쓴다.

- [ ] **Step 1: 빈 패키지 생성**

```bash
mkdir -p src/notifications
touch src/notifications/__init__.py
```

- [ ] **Step 2: 실패하는 테스트 작성**

이 저장소의 `tests/test_wiki_service.py`/`tests/test_settings_service.py`와 동일하게 라이브 Supabase에 직접 쓰고 지우는 통합 테스트 패턴을 따른다(이 프로젝트엔 이 계층에 mock을 쓰는 컨벤션이 없음).

Write to `tests/test_notifications_service.py`:

```python
from __future__ import annotations

import os
import uuid

import pytest
from dotenv import load_dotenv

load_dotenv()

from src.notifications import service as notifications_service


@pytest.fixture(scope="module")
def workspace_id() -> str:
    if not os.environ.get("SUPABASE_URL") or not (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SECRET_KEY")
    ):
        pytest.skip("Supabase service credentials are not configured.")
    try:
        db = notifications_service._get_client()
        res = db.table("workspaces").select("id").eq("slug", "mywiki").single().execute()
        return res.data["id"]
    except Exception as e:
        pytest.skip(f"Supabase connection failed (likely placeholder credentials): {type(e).__name__}")


@pytest.fixture(scope="module")
def user_id(workspace_id) -> str:
    db = notifications_service._get_client()
    res = db.table("workspace_members").select("user_id").eq("workspace_id", workspace_id).limit(1).execute()
    if not res.data:
        pytest.skip("workspace_members에 소속된 사용자가 없음.")
    return res.data[0]["user_id"]


def test_save_subscription_creates_row(workspace_id, user_id):
    endpoint = f"https://fcm.googleapis.com/test-{uuid.uuid4().hex[:8]}"
    notifications_service.save_subscription(workspace_id, user_id, endpoint, "p256dh-value", "auth-value")

    db = notifications_service._get_client()
    row = db.table("push_subscriptions").select("*").eq("endpoint", endpoint).single().execute()
    assert row.data["user_id"] == user_id
    assert row.data["p256dh"] == "p256dh-value"

    db.table("push_subscriptions").delete().eq("endpoint", endpoint).execute()


def test_save_subscription_upserts_on_same_endpoint(workspace_id, user_id):
    endpoint = f"https://fcm.googleapis.com/test-{uuid.uuid4().hex[:8]}"
    notifications_service.save_subscription(workspace_id, user_id, endpoint, "old-p256dh", "old-auth")
    notifications_service.save_subscription(workspace_id, user_id, endpoint, "new-p256dh", "new-auth")

    db = notifications_service._get_client()
    rows = db.table("push_subscriptions").select("*").eq("endpoint", endpoint).execute()
    assert len(rows.data) == 1
    assert rows.data[0]["p256dh"] == "new-p256dh"

    db.table("push_subscriptions").delete().eq("endpoint", endpoint).execute()


def test_delete_subscription_removes_row(workspace_id, user_id):
    endpoint = f"https://fcm.googleapis.com/test-{uuid.uuid4().hex[:8]}"
    notifications_service.save_subscription(workspace_id, user_id, endpoint, "p256dh-value", "auth-value")

    notifications_service.delete_subscription(user_id, endpoint)

    db = notifications_service._get_client()
    rows = db.table("push_subscriptions").select("*").eq("endpoint", endpoint).execute()
    assert rows.data == []
```

- [ ] **Step 3: 테스트 실행해서 실패 확인**

Run: `pytest tests/test_notifications_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.notifications.service'` (Supabase 자격 증명이 없으면 대신 SKIP만 뜰 수 있음 — 그 경우 `.env`에 `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY`가 있는지 먼저 확인).

- [ ] **Step 4: 최소 구현 작성**

Write to `src/notifications/service.py`:

```python
"""위키 발행 푸시 알림 — 구독 저장/삭제 + 발송(Web Push/VAPID)."""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache

from pywebpush import WebPushException, webpush
from supabase import Client, create_client

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_client() -> Client:
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ["SUPABASE_SECRET_KEY"]
    return create_client(os.environ["SUPABASE_URL"], key)


def save_subscription(
    workspace_id: str,
    user_id: str,
    endpoint: str,
    p256dh: str,
    auth_key: str,
    *,
    supabase: Client | None = None,
) -> None:
    db = supabase or _get_client()
    db.table("push_subscriptions").upsert(
        {
            "workspace_id": workspace_id,
            "user_id": user_id,
            "endpoint": endpoint,
            "p256dh": p256dh,
            "auth": auth_key,
        },
        on_conflict="user_id,endpoint",
    ).execute()


def delete_subscription(user_id: str, endpoint: str, *, supabase: Client | None = None) -> None:
    db = supabase or _get_client()
    db.table("push_subscriptions").delete().eq("user_id", user_id).eq("endpoint", endpoint).execute()
```

- [ ] **Step 5: 테스트 실행해서 통과 확인**

Run: `pytest tests/test_notifications_service.py -v`
Expected: PASS (3 passed) — Supabase 자격 증명이 없으면 3 skipped(이 경우 `.env` 확인 후 재실행).

- [ ] **Step 6: 커밋**

```bash
git add src/notifications/__init__.py src/notifications/service.py tests/test_notifications_service.py
git commit -m "Feat: 푸시 구독 저장/삭제(save_subscription/delete_subscription) 추가"
```

---

## Task 3: 발송 로직 (`send_wiki_notification`) + `pywebpush` 의존성

**Files:**
- Modify: `requirements.txt`
- Modify: `src/notifications/service.py`
- Test: `tests/test_notifications_service.py`

**Interfaces:**
- Consumes: `_get_client()`(Task 2), `push_subscriptions` 테이블(Task 1).
- Produces: `send_wiki_notification(workspace_id: str, published_count: int, *, supabase=None) -> None` — Task 5(`generation.py` 훅)가 이 함수를 호출한다.

- [ ] **Step 1: `pywebpush` 의존성 추가**

`requirements.txt`의 `# 테스트` 섹션 바로 위에 추가:

```
pywebpush>=2.0            # 위키 발행 브라우저 푸시 알림(표준 Web Push, VAPID)
```

- [ ] **Step 2: 설치**

Run: `pip install -r requirements.txt`
Expected: `pywebpush` 및 하위 의존성(`py-vapid`, `cryptography` 등) 설치 완료.

- [ ] **Step 3: 실패하는 테스트 작성**

`webpush()`가 실제 푸시 서비스로 나가면 안 되므로 `pywebpush.webpush`를 monkeypatch한다. `tests/test_notifications_service.py` 끝에 추가:

```python
from src.notifications import service as _svc_module


def test_send_wiki_notification_sends_to_all_workspace_subscriptions(monkeypatch):
    calls = []

    class FakeTable:
        def __init__(self, rows):
            self.rows = rows

        def select(self, *_a, **_k):
            return self

        def eq(self, *_a, **_k):
            return self

        def execute(self):
            class R:
                data = self.rows
            return R()

    class FakeClient:
        def table(self, name):
            assert name == "push_subscriptions"
            return FakeTable([
                {"id": "sub-1", "endpoint": "https://ep/1", "p256dh": "p1", "auth": "a1"},
                {"id": "sub-2", "endpoint": "https://ep/2", "p256dh": "p2", "auth": "a2"},
            ])

    def fake_webpush(*, subscription_info, data, vapid_private_key, vapid_claims):
        calls.append(subscription_info["endpoint"])

    monkeypatch.setattr(_svc_module, "webpush", fake_webpush)
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "fake-key")

    notifications_service.send_wiki_notification("ws-1", 3, supabase=FakeClient())

    assert calls == ["https://ep/1", "https://ep/2"]


def test_send_wiki_notification_deletes_expired_subscription(monkeypatch):
    deleted = []

    class FakeDeleteQuery:
        def __init__(self, sink):
            self.sink = sink

        def eq(self, field, value):
            self.sink.append(value)
            return self

        def execute(self):
            return None

    class FakeTable:
        def __init__(self, rows):
            self.rows = rows

        def select(self, *_a, **_k):
            return self

        def eq(self, *_a, **_k):
            return self

        def execute(self):
            class R:
                data = self.rows
            return R()

        def delete(self):
            return FakeDeleteQuery(deleted)

    class FakeClient:
        def table(self, name):
            return FakeTable([{"id": "sub-expired", "endpoint": "https://ep/1", "p256dh": "p1", "auth": "a1"}])

    class FakeResponse:
        status_code = 410

    def fake_webpush(**kwargs):
        raise WebPushException("gone", response=FakeResponse())

    monkeypatch.setattr(_svc_module, "webpush", fake_webpush)
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "fake-key")

    notifications_service.send_wiki_notification("ws-1", 1, supabase=FakeClient())

    assert deleted == ["sub-expired"]


def test_send_wiki_notification_skips_when_no_vapid_key(monkeypatch):
    calls = []
    monkeypatch.setattr(_svc_module, "webpush", lambda **kwargs: calls.append(1))
    monkeypatch.delenv("VAPID_PRIVATE_KEY", raising=False)

    class FakeTable:
        def select(self, *_a, **_k):
            return self

        def eq(self, *_a, **_k):
            return self

        def execute(self):
            class R:
                data = [{"id": "sub-1", "endpoint": "https://ep/1", "p256dh": "p1", "auth": "a1"}]
            return R()

    class FakeClient:
        def table(self, name):
            return FakeTable()

    notifications_service.send_wiki_notification("ws-1", 1, supabase=FakeClient())

    assert calls == []
```

`tests/test_notifications_service.py` 맨 위 import 블록에 `from pywebpush import WebPushException`도 추가한다.

- [ ] **Step 4: 테스트 실행해서 실패 확인**

Run: `pytest tests/test_notifications_service.py -k send_wiki_notification -v`
Expected: FAIL — `AttributeError: module 'src.notifications.service' has no attribute 'send_wiki_notification'`

- [ ] **Step 5: `send_wiki_notification` 구현**

`src/notifications/service.py` 맨 아래에 추가:

```python

def send_wiki_notification(workspace_id: str, published_count: int, *, supabase: Client | None = None) -> None:
    """workspace_id 구독자 전원에게 웹 푸시 발송. 만료된 구독(404/410)은 그 자리에서 삭제한다.
    구독 하나가 실패해도 나머지 발송은 계속한다."""
    db = supabase or _get_client()
    subs = db.table("push_subscriptions").select("*").eq("workspace_id", workspace_id).execute().data
    if not subs:
        return

    vapid_private_key = os.environ.get("VAPID_PRIVATE_KEY")
    if not vapid_private_key:
        logger.warning("wiki_notification_skipped_no_vapid_key", extra={"workspace_id": workspace_id})
        return

    vapid_claims = {"sub": os.environ.get("VAPID_CLAIMS_SUB", "mailto:sunnycmywiki@gmail.com")}
    payload = json.dumps({
        "title": "myWiki 위키 업데이트",
        "body": f"위키 문서 {published_count}건이 새로 업데이트됐습니다.",
    })

    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                },
                data=payload,
                vapid_private_key=vapid_private_key,
                vapid_claims=dict(vapid_claims),
            )
        except WebPushException as exc:
            status_code = getattr(exc.response, "status_code", None)
            if status_code in (404, 410):
                db.table("push_subscriptions").delete().eq("id", sub["id"]).execute()
            else:
                logger.warning(
                    "wiki_notification_send_failed",
                    extra={"subscription_id": sub["id"], "error": str(exc)},
                )
```

- [ ] **Step 6: 테스트 실행해서 통과 확인**

Run: `pytest tests/test_notifications_service.py -v`
Expected: PASS (6 passed, 자격 증명 없으면 처음 3개만 skip)

- [ ] **Step 7: 커밋**

```bash
git add requirements.txt src/notifications/service.py tests/test_notifications_service.py
git commit -m "Feat: pywebpush 기반 위키 발행 알림 발송(send_wiki_notification) 추가"
```

---

## Task 4: REST 엔드포인트 (`src/api/notifications_router.py`)

**Files:**
- Modify: `src/api/schemas.py`
- Create: `src/api/notifications_router.py`
- Modify: `src/api/main.py`
- Test: `tests/test_notifications_router.py`

**Interfaces:**
- Consumes: `save_subscription`/`delete_subscription`(Task 2), `get_current_user`(`src/api/auth.py`, 기존), `db.get_default_workspace_id`(`src/api/db.py`, 기존).
- Produces: `POST /notifications/subscribe`, `DELETE /notifications/subscribe?endpoint=...` 엔드포인트 — 프론트(별도 계획서)가 이 두 엔드포인트를 호출한다.

- [ ] **Step 1: 스키마 추가**

`src/api/schemas.py` 맨 아래에 추가:

```python


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class SubscribeRequest(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeys
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_settings_router.py`와 동일한 패턴(`TestClient` + `dependency_overrides`).

Write to `tests/test_notifications_router.py`:

```python
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
```

- [ ] **Step 3: 테스트 실행해서 실패 확인**

Run: `pytest tests/test_notifications_router.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.api.notifications_router'`

- [ ] **Step 4: 라우터 구현**

Write to `src/api/notifications_router.py`:

```python
"""위키 발행 브라우저 푸시 알림 구독 REST 엔드포인트."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from . import db
from .auth import get_current_user
from .schemas import SubscribeRequest
from ..notifications import service as notifications_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _require_workspace(profile: dict) -> str:
    workspace_id = db.get_default_workspace_id(profile["id"])
    if not workspace_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="workspace 소속이 없음")
    return workspace_id


@router.post("/subscribe", status_code=status.HTTP_204_NO_CONTENT)
def subscribe(body: SubscribeRequest, profile: dict = Depends(get_current_user)):
    workspace_id = _require_workspace(profile)
    notifications_service.save_subscription(
        workspace_id, profile["id"], body.endpoint, body.keys.p256dh, body.keys.auth,
    )


@router.delete("/subscribe", status_code=status.HTTP_204_NO_CONTENT)
def unsubscribe(endpoint: str = Query(...), profile: dict = Depends(get_current_user)):
    notifications_service.delete_subscription(profile["id"], endpoint)
```

- [ ] **Step 5: `main.py`에 라우터 등록**

`src/api/main.py`에서 아래 줄을 찾는다:

```python
from .settings_router import router as settings_router
from .wiki_router import router as wiki_router
```

아래로 교체:

```python
from .notifications_router import router as notifications_router
from .settings_router import router as settings_router
from .wiki_router import router as wiki_router
```

그리고 아래 줄을 찾는다:

```python
app.include_router(wiki_router)
app.include_router(settings_router)
```

아래로 교체:

```python
app.include_router(wiki_router)
app.include_router(settings_router)
app.include_router(notifications_router)
```

- [ ] **Step 6: 테스트 실행해서 통과 확인**

Run: `pytest tests/test_notifications_router.py -v`
Expected: PASS (3 passed)

- [ ] **Step 7: 커밋**

```bash
git add src/api/schemas.py src/api/notifications_router.py src/api/main.py tests/test_notifications_router.py
git commit -m "Feat: 푸시 구독 REST 엔드포인트(POST/DELETE /notifications/subscribe) 추가"
```

---

## Task 5: 위키 발행 배치에 알림 훅 연결

**Files:**
- Modify: `src/wiki/generation.py`
- Modify: `tests/test_wiki_generation.py`

**Interfaces:**
- Consumes: `send_wiki_notification`(Task 3).
- Produces: 이 태스크가 백엔드 마지막 — `generate_wiki_drafts_for_sections()`가 배치 종료 시 자동으로 알림을 발송한다.

- [ ] **Step 1: import 추가**

`src/wiki/generation.py` 상단의 아래 블록을 찾는다:

```python
from .interface import (
    WikiDraftInput,
    WikiSourceInput,
    create_wiki_version,
    publish_wiki_version,
    record_wiki_validation,
    review_wiki_version,
    search_wiki_contexts,
    upsert_wiki_page,
)
```

아래로 교체(마지막 줄에 새 import 한 줄 추가):

```python
from .interface import (
    WikiDraftInput,
    WikiSourceInput,
    create_wiki_version,
    publish_wiki_version,
    record_wiki_validation,
    review_wiki_version,
    search_wiki_contexts,
    upsert_wiki_page,
)
from ..notifications.service import send_wiki_notification
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_wiki_generation.py`에 새 테스트 추가(파일 끝에):

```python


def test_generate_wiki_drafts_for_sections_sends_one_notification_for_batch(monkeypatch):
    """이슈 1건 + 주제 1건이 발행되면 알림은 딱 한 번, 합산 건수(2)로 호출된다."""
    calls = []
    monkeypatch.setattr(
        generation, "_generate_topic_page",
        lambda section, wiki_contexts, **kwargs: ("create_new", "page-topic", "version-topic"),
    )
    monkeypatch.setattr(
        generation, "_generate_issue_page",
        lambda section, **kwargs: ("page-issue", "version-issue"),
    )
    monkeypatch.setattr(
        generation, "send_wiki_notification",
        lambda workspace_id, count, **kwargs: calls.append((workspace_id, count)),
    )

    generation.generate_wiki_drafts_for_sections(
        [_section("issue-ok")],
        [_enriched_group("issue-ok")],
        workspace_id="ws-1",
    )

    assert calls == [("ws-1", 2)]


def test_generate_wiki_drafts_for_sections_skips_notification_when_nothing_published(monkeypatch):
    calls = []
    monkeypatch.setattr(
        generation, "_generate_topic_page",
        lambda section, wiki_contexts, **kwargs: ("skip", None, None),
    )
    monkeypatch.setattr(
        generation, "_generate_issue_page",
        lambda section, **kwargs: (_ for _ in ()).throw(RuntimeError("실패")),
    )
    monkeypatch.setattr(
        generation, "send_wiki_notification",
        lambda workspace_id, count, **kwargs: calls.append((workspace_id, count)),
    )

    generation.generate_wiki_drafts_for_sections(
        [_section("issue-fail")],
        [_enriched_group("issue-fail")],
        workspace_id="ws-1",
    )

    assert calls == []


def test_generate_wiki_drafts_for_sections_survives_notification_failure(monkeypatch):
    monkeypatch.setattr(
        generation, "_generate_topic_page",
        lambda section, wiki_contexts, **kwargs: ("skip", None, None),
    )
    monkeypatch.setattr(
        generation, "_generate_issue_page",
        lambda section, **kwargs: ("page-issue", "version-issue"),
    )

    def raising_notification(*a, **k):
        raise RuntimeError("푸시 발송 실패")

    monkeypatch.setattr(generation, "send_wiki_notification", raising_notification)

    results = generation.generate_wiki_drafts_for_sections(
        [_section("issue-ok")],
        [_enriched_group("issue-ok")],
        workspace_id="ws-1",
    )

    assert len(results) == 1
    assert results[0].issue_page_id == "page-issue"
```

- [ ] **Step 3: 기존 6개 테스트에 no-op 모킹 추가**

아래 6개 테스트 함수 각각에서, 마지막 `monkeypatch.setattr(generation, "_generate_issue_page", ...)` 줄(또는 `_generate_topic_page`만 모킹하는 경우 그 줄) **바로 다음 줄**에 `monkeypatch.setattr(generation, "send_wiki_notification", lambda *a, **k: None)`를 추가한다 — 안 하면 각 테스트가 실제 Supabase에 접속을 시도한다(빈 결과라 안전하긴 하지만 순수 단위 테스트가 아니게 됨).

| 테스트 함수명 | 마지막 monkeypatch 줄(이 줄 다음에 추가) |
|---|---|
| `test_generate_wiki_drafts_threads_evidence_texts_into_both_pages` | `monkeypatch.setattr(generation, "_generate_issue_page", fake_generate_issue_page)` |
| `test_generate_wiki_drafts_for_sections_threads_injected_clients` | `monkeypatch.setattr(generation, "_generate_issue_page", fake_generate_issue_page)` |
| `test_generate_wiki_drafts_for_sections_isolates_issue_page_failures` | `monkeypatch.setattr(generation, "_generate_issue_page", fake_generate_issue_page)` |
| `test_generate_wiki_drafts_for_sections_isolates_topic_page_failures` | `monkeypatch.setattr(generation, "_generate_issue_page", fake_generate_issue_page)` |
| `test_generate_wiki_drafts_for_sections_links_issue_page_to_resolved_topic` | `monkeypatch.setattr(generation, "_generate_issue_page", fake_generate_issue_page)` |
| `test_generate_wiki_drafts_for_sections_passes_matching_wiki_contexts` | `monkeypatch.setattr(generation, "_generate_issue_page", lambda section, **kwargs: ("page-1", "version-1"))` |

예를 들어 `test_generate_wiki_drafts_threads_evidence_texts_into_both_pages`는:

```python
    monkeypatch.setattr(generation, "_generate_topic_page", fake_generate_topic_page)
    monkeypatch.setattr(generation, "_generate_issue_page", fake_generate_issue_page)
    monkeypatch.setattr(generation, "send_wiki_notification", lambda *a, **k: None)

    generation.generate_wiki_drafts_for_sections(
```

나머지 5개도 동일한 방식(표에 나온 마지막 monkeypatch 줄 바로 아래에 같은 한 줄 추가)으로 고친다.

- [ ] **Step 4: 테스트 실행해서 새 테스트 실패 확인**

Run: `pytest tests/test_wiki_generation.py -k "sends_one_notification or skips_notification or survives_notification" -v`
Expected: FAIL — `AttributeError` 또는 `assert calls == [...]` 실패(아직 훅이 없어서 `calls`가 빔).

- [ ] **Step 5: 훅 구현**

`src/wiki/generation.py`의 `generate_wiki_drafts_for_sections()` 함수 끝, `return results` 줄을 찾아서 아래로 교체:

```python
    published_count = sum(
        (1 if result.issue_page_id else 0) + (1 if result.topic_page_id is not None else 0)
        for result in results
    )
    if published_count > 0:
        try:
            send_wiki_notification(workspace_id, published_count, supabase=supabase)
        except Exception:  # noqa: BLE001
            logger.exception("wiki_notification_failed", extra={"workspace_id": workspace_id})

    return results
```

- [ ] **Step 6: 전체 위키 생성 테스트 실행해서 통과 확인**

Run: `pytest tests/test_wiki_generation.py -v`
Expected: PASS (기존 39개 + 새 3개 = 42 passed)

- [ ] **Step 7: 커밋**

```bash
git add src/wiki/generation.py tests/test_wiki_generation.py
git commit -m "Feat: 위키 발행 배치 종료 시 자동 알림 발송 훅 연결"
```

---

## Task 6: VAPID 키 생성 + 전체 테스트 확인

**Files:** 없음(키 생성 + 검증)

- [ ] **Step 1: VAPID 키 쌍 생성**

`py_vapid`/`pywebpush` 버전마다 헬퍼 메서드명이 달라서, `cryptography` 라이브러리로 직접 P-256 키를 만들어 `pywebpush`가 실제로 기대하는 원시 바이트 포맷(개인키: raw 32바이트 스칼라, 공개키: 비압축 EC 포인트 65바이트, 둘 다 base64url·패딩 없음)으로 인코딩한다. 이 방식은 `pywebpush`의 `webpush(vapid_private_key=<str>)` → `py_vapid.Vapid.from_string()`(문자열을 base64url 디코드한 길이가 32바이트면 raw로 처리) 경로와 직접 검증했다.

Run:
```bash
python -c "
import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

private_key = ec.generate_private_key(ec.SECP256R1())
public_key = private_key.public_key()

private_raw = private_key.private_numbers().private_value.to_bytes(32, 'big')
public_bytes = public_key.public_bytes(
    encoding=serialization.Encoding.X962,
    format=serialization.PublicFormat.UncompressedPoint,
)

def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')

print('VAPID_PRIVATE_KEY:', b64url(private_raw))
print('VITE_VAPID_PUBLIC_KEY:', b64url(public_bytes))
"
```

Expected: 두 줄 출력, `VAPID_PRIVATE_KEY`는 43자, `VITE_VAPID_PUBLIC_KEY`는 87자 안팎(둘 다 base64url, `=` 패딩 없음).

- [ ] **Step 2: 사용자에게 키 전달**

생성된 `VAPID_PRIVATE_KEY`/`VAPID_PUBLIC_KEY` 값을 사용자에게 보고한다(§6 표: `VAPID_PRIVATE_KEY`는 GitHub Actions 시크릿 + 오라클 VM `.env`, `VITE_VAPID_PUBLIC_KEY`는 Vercel 환경변수로 사용자가 직접 등록).

- [ ] **Step 3: 전체 테스트 스위트 실행**

Run: `pytest tests/ -q`
Expected: 이번 변경 이전과 같은 수의 실패(9건, 전부 이 변경과 무관한 기존 실패 — `OPENROUTER_API_KEY` env 의존 테스트 등)만 남고, 새로 추가한 테스트는 전부 통과.

- [ ] **Step 4: `deploy-backend.yml`에 `VAPID_PRIVATE_KEY` 전달 확인(필요 시 안내만)**

`.github/workflows/deploy-backend.yml`이 오라클 VM에 어떤 방식으로 환경변수를 주입하는지 확인한다(`cat .github/workflows/deploy-backend.yml`). 이미 `SUPABASE_*` 시크릿을 같은 방식으로 주입하고 있다면, `VAPID_PRIVATE_KEY`/`VAPID_CLAIMS_SUB`도 같은 목록에 추가해야 실제 배포본에서 동작한다 — 이 파일을 수정하는 것도 배포 파이프라인 변경이라 실제 반영은 사용자에게 안내만 하고 직접 고치지 않는다(§2 원칙과 동일).


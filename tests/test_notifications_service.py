from __future__ import annotations

import os
import uuid

import pytest
from dotenv import load_dotenv

load_dotenv()

from pywebpush import WebPushException

from src.notifications import service as notifications_service
from src.notifications import service as _svc_module


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

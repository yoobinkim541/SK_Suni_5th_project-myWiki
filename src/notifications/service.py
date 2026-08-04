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

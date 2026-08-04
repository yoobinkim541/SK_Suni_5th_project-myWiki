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

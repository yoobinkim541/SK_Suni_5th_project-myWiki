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
    get_workspace_settings(workspace_id, supabase=db)  # 행이 없으면 먼저 만든다
    now = datetime.now(timezone.utc).isoformat()
    db.table("workspace_settings").update({"last_wiki_refresh_at": now}).eq(
        "workspace_id", workspace_id
    ).execute()

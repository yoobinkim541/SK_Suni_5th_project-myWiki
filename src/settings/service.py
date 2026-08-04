"""워크스페이스 공유 설정(Wiki 업데이트 주기·대화 보관 기간) CRUD."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

from supabase import Client, create_client

from .models import WorkspaceSettings

WIKI_UPDATE_CYCLE_MINUTES_CHOICES = (30, 60, 180, 360, 720, 1440)
DATA_REFRESH_CYCLE_MINUTES_CHOICES = (30, 60, 120, 180, 360, 720, 1440)
CHAT_RETENTION_DAYS_CHOICES = (7, 30, 90)

_DEFAULT_WIKI_UPDATE_CYCLE_MINUTES = 360
_DEFAULT_DATA_REFRESH_CYCLE_MINUTES = 120

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
        data_refresh_cycle_minutes=row["data_refresh_cycle_minutes"],
        chat_retention_days=row.get("chat_retention_days"),
        last_wiki_refresh_at=row.get("last_wiki_refresh_at"),
        last_data_refresh_at=row.get("last_data_refresh_at"),
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
            "data_refresh_cycle_minutes": _DEFAULT_DATA_REFRESH_CYCLE_MINUTES,
        })
        .execute()
    )
    return _row_to_settings(insert_res.data[0])


def update_workspace_settings(
    workspace_id: str,
    *,
    wiki_update_cycle_minutes: Optional[int] = None,
    data_refresh_cycle_minutes: Optional[int] = None,
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
    if data_refresh_cycle_minutes is not None:
        if data_refresh_cycle_minutes not in DATA_REFRESH_CYCLE_MINUTES_CHOICES:
            raise ValueError(f"허용되지 않는 data_refresh_cycle_minutes: {data_refresh_cycle_minutes}")
        patch["data_refresh_cycle_minutes"] = data_refresh_cycle_minutes
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


def mark_data_refreshed(workspace_id: str, *, at: Optional[datetime] = None, supabase: Client | None = None) -> None:
    """last_data_refresh_at을 갱신한다.

    refresh_wiki_scheduled.py의 _mark_wiki_refreshed_at과 같은 이유로 at을 인자로 받는다 —
    수집+분석은 시간이 걸리므로 완료 시각이 아니라 게이트를 통과한 시각을 찍어야
    다음 주기가 매번 밀리지 않는다.
    """
    db = supabase or _get_client()
    get_workspace_settings(workspace_id, supabase=db)  # 행이 없으면 먼저 만든다
    when = (at or datetime.now(timezone.utc)).isoformat()
    db.table("workspace_settings").update({"last_data_refresh_at": when}).eq(
        "workspace_id", workspace_id
    ).execute()

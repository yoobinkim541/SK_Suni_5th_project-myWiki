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

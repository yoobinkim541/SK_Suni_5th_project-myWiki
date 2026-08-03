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


_PAGE_SIZE = 1000


def _select_all(make_query, *, page_size: int = _PAGE_SIZE) -> list[dict]:
    """make_query는 인자 없이 호출할 때마다 새로운(아직 .execute() 안 한) PostgREST 쿼리
    빌더를 만들어주는 함수여야 한다 — 같은 빌더 객체에 .range()를 반복 호출하면 설치된
    postgrest 클라이언트가 offset 쿼리파라미터를 교체가 아니라 append해서, 두 번째 페이지부터
    실제로는 첫 페이지가 다시 조회된다(무한루프+메모리 누수 위험). 그래서 페이지마다 빌더를
    새로 만들어야 한다. 1000행 기본 응답 상한 때문에, 한 번만 조회하면 그 상한을 넘는
    워크스페이스에서 최근 활동이 잘려나가 세션이 잘못 만료 판정될 수 있다."""
    rows: list[dict] = []
    offset = 0
    while True:
        page = make_query().range(offset, offset + page_size - 1).execute().data
        rows.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return rows


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def find_expired_session_ids(workspace_id: str, *, retention_days: int | None) -> list[str]:
    """retention_days가 None(영구 보관)이면 빈 리스트.

    세션별로 "마지막 활동 시각"을 따로 계산해서 threshold와 비교하는 대신, threshold
    이후에 메시지가 하나라도 있는 세션 id 집합을 구해서 "활동 없음" 세션만 걸러낸다.
    (세션/메시지 각각을 나눠 페이징하면서 최신값만 골라내는 방식은 페이지 경계에서
    세션의 진짜 최신 메시지를 놓칠 수 있었다 — in_() + gte() 단일 질의로 그 문제를 없앤다.)
    """
    if retention_days is None:
        return []

    db = get_client()
    sessions = _select_all(
        lambda: db.table("chat_sessions")
        .select("id, created_at")
        .eq("workspace_id", workspace_id)
        .order("id")
    )
    if not sessions:
        return []

    session_ids = [s["id"] for s in sessions]
    threshold = datetime.now(timezone.utc) - timedelta(days=retention_days)
    active_session_ids = {
        row["session_id"]
        for row in _select_all(
            lambda: db.table("chat_messages")
            .select("session_id")
            .in_("session_id", session_ids)
            .gte("created_at", threshold.isoformat())
            .order("id")
        )
    }

    expired = [
        s["id"]
        for s in sessions
        if s["id"] not in active_session_ids and _parse_ts(s["created_at"]) < threshold
    ]
    return expired


def delete_expired_sessions(workspace_id: str, *, retention_days: int | None) -> int:
    expired_ids = find_expired_session_ids(workspace_id, retention_days=retention_days)
    if not expired_ids:
        return 0

    db = get_client()
    message_ids = [
        row["id"]
        for row in _select_all(
            lambda: db.table("chat_messages").select("id").in_("session_id", expired_ids).order("id")
        )
    ]
    if message_ids:
        db.table("message_citations").delete().in_("message_id", message_ids).execute()
    db.table("chat_messages").delete().in_("session_id", expired_ids).execute()
    delete_res = (
        db.table("chat_sessions")
        .delete()
        .eq("workspace_id", workspace_id)
        .in_("id", expired_ids)
        .execute()
    )
    return len(delete_res.data)


if __name__ == "__main__":
    workspace_id = get_workspace_id()
    settings = get_workspace_settings(workspace_id)

    if settings.chat_retention_days is None:
        log("영구 보관 설정 — 삭제 없음")
        sys.exit(0)

    log(f"보관 기간 {settings.chat_retention_days}일 기준으로 정리 시작")
    deleted_count = delete_expired_sessions(workspace_id, retention_days=settings.chat_retention_days)
    log(f"삭제된 세션: {deleted_count}건")

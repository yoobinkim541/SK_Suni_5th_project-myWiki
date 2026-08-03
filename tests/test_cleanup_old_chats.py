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
    db = _get_client()
    ids_before = {
        row["id"]
        for row in db.table("chat_sessions").select("id").eq("workspace_id", workspace_id).execute().data
    }

    old_session_id = _make_session(workspace_id, user_id, last_message_days_ago=100)
    try:
        deleted_count = delete_expired_sessions(workspace_id, retention_days=90)

        ids_after = {
            row["id"]
            for row in db.table("chat_sessions").select("id").eq("workspace_id", workspace_id).execute().data
        }
        removed = ids_before.union({old_session_id}) - ids_after
        assert removed == {old_session_id}, (
            f"삭제 대상이 fixture 세션 하나만이어야 하는데 실제로는 {removed}가 삭제됨 — "
            "실제 팀 데이터가 같이 지워졌을 가능성"
        )
        assert deleted_count >= 1

        remaining_messages = (
            db.table("chat_messages").select("id").eq("session_id", old_session_id).execute().data
        )
        assert remaining_messages == []
    finally:
        _cleanup_session(old_session_id)  # 이미 지워졌으면 조용히 아무것도 안 함


def test_delete_expired_sessions_cascades_to_message_citations(workspace_id, user_id):
    """message_citations는 chat_messages.id를 FK로 참조하고 ON DELETE CASCADE가 아니므로,
    삭제 순서(message_citations -> chat_messages -> chat_sessions)가 틀리면 FK 위반으로
    배치 자체가 죽는다. 만료된 세션의 메시지에 달린 citation이 같이 지워지는지 확인한다."""
    db = _get_client()
    doc_ver = db.table("document_versions").select("id").limit(1).execute()
    if not doc_ver.data:
        pytest.skip("document_versions 데이터 없음")
    doc_ver_id = doc_ver.data[0]["id"]

    now = datetime.now(timezone.utc)
    session = (
        db.table("chat_sessions")
        .insert({
            "workspace_id": workspace_id,
            "user_id": user_id,
            "title": f"test-{uuid.uuid4().hex[:8]}",
            "visibility": "private",
            "created_at": (now - timedelta(days=105)).isoformat(),
        })
        .execute()
        .data[0]
    )
    session_id = session["id"]
    message = (
        db.table("chat_messages")
        .insert({
            "session_id": session_id,
            "role": "user",
            "content": "테스트 메시지",
            "created_at": (now - timedelta(days=100)).isoformat(),
        })
        .execute()
        .data[0]
    )
    message_id = message["id"]
    citation = (
        db.table("message_citations")
        .insert({
            "message_id": message_id,
            "document_version_id": doc_ver_id,
            "citation_order": 1,
        })
        .execute()
        .data[0]
    )
    citation_id = citation["id"]

    try:
        deleted_count = delete_expired_sessions(workspace_id, retention_days=90)
        assert deleted_count >= 1

        remaining_citation = (
            db.table("message_citations").select("id").eq("id", citation_id).execute()
        )
        assert remaining_citation.data == []
    finally:
        db.table("message_citations").delete().eq("id", citation_id).execute()
        _cleanup_session(session_id)


def test_find_expired_session_ids_empty_when_retention_none(workspace_id, user_id):
    old_session_id = _make_session(workspace_id, user_id, last_message_days_ago=1000)
    try:
        assert find_expired_session_ids(workspace_id, retention_days=None) == []
    finally:
        _cleanup_session(old_session_id)

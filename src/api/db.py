"""
Supabase 접속 + chat_sessions/chat_messages/message_citations CRUD.
Agent·API 담당 테이블만 다룬다 (profiles, chat_sessions, chat_messages, message_citations).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

from supabase import Client, create_client

from ..agent.core import AgentResult


@lru_cache
def get_supabase() -> Client:
    url = os.environ["SUPABASE_URL"]
    # service_role 키 사용 — RLS를 서버가 대신 검증하고 workspace_id로 직접 필터링한다.
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def get_profile(user_id: str) -> Optional[dict]:
    res = get_supabase().table("profiles").select("*").eq("id", user_id).maybe_single().execute()
    return res.data


def get_default_workspace_id(user_id: str) -> Optional[str]:
    """
    profiles에는 workspace_id가 없고 workspace_members로만 연결돼 있다.
    MVP 단계는 사용자당 workspace 하나라고 가정하고 첫 번째 소속을 그대로 쓴다.
    팀이 여러 workspace를 지원하게 되면, 요청에 workspace_id를 명시적으로
    받아서 이 함수 대신 소속 여부만 검증하는 방식으로 바꾸면 된다.
    """
    res = (
        get_supabase()
        .table("workspace_members")
        .select("workspace_id")
        .eq("user_id", user_id)
        .limit(1)
        .maybe_single()
        .execute()
    )
    return res.data["workspace_id"] if res.data else None


def create_chat_session(
    workspace_id: str, user_id: str, title: Optional[str] = None, visibility: str = "private"
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    res = (
        get_supabase()
        .table("chat_sessions")
        .insert({
            "workspace_id": workspace_id,
            "user_id": user_id,
            "title": title,
            "visibility": visibility,
            "created_at": now,
            "updated_at": now,
        })
        .execute()
    )
    return res.data[0]


def list_chat_sessions(workspace_id: str, user_id: str, scope: str) -> list[dict]:
    """scope='mine': 본인 소유 비공개 세션만. scope='team': workspace 전체 공유 세션."""
    query = get_supabase().table("chat_sessions").select("*").eq("workspace_id", workspace_id)
    if scope == "mine":
        query = query.eq("visibility", "private").eq("user_id", user_id)
    else:
        query = query.eq("visibility", "team")
    res = query.order("updated_at", desc=True).execute()
    return res.data


def get_chat_session(session_id: str, workspace_id: str, user_id: str) -> Optional[dict]:
    """
    visibility='private'인 세션은 소유자(user_id)만 접근 가능하다 — 워크스페이스 소속이라는
    이유만으로 타인의 비공개 세션을 ID만 알면 읽을 수 있던 문제를 여기서 막는다.
    visibility='team'인 세션은 같은 workspace 멤버 전원이 접근 가능하다.
    권한이 없으면 존재 여부를 알려주지 않도록 조회 실패(None)와 동일하게 취급한다.
    """
    res = (
        get_supabase()
        .table("chat_sessions")
        .select("*")
        .eq("id", session_id)
        .eq("workspace_id", workspace_id)  # workspace 격리 — 다른 workspace 세션 접근 차단
        .maybe_single()
        .execute()
    )
    session = res.data
    if session is None:
        return None
    if session["visibility"] == "private" and session["user_id"] != user_id:
        return None
    return session


def _flatten_author_name(row: dict) -> dict:
    """chat_messages.user_id -> profiles(display_name) 임베드 결과를 author_name으로 펼친다.
    assistant 메시지는 user_id가 없어 profiles가 비고, author_name도 None으로 남는다."""
    profile = row.pop("profiles", None) or {}
    row["author_name"] = profile.get("display_name")
    return row


def list_chat_messages(session_id: str) -> list[dict]:
    res = (
        get_supabase()
        .table("chat_messages")
        .select("*, profiles(display_name)")
        .eq("session_id", session_id)
        .order("created_at")
        .execute()
    )
    return [_flatten_author_name(row) for row in res.data]


def save_user_message(session_id: str, content: str, user_id: str) -> dict:
    res = (
        get_supabase()
        .table("chat_messages")
        .insert({
            "session_id": session_id,
            "role": "user",
            "content": content,
            "user_id": user_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        .execute()
    )
    return res.data[0]


def save_agent_message(session_id: str, result: AgentResult, prompt_version: str = "v1") -> dict:
    """
    Agent 응답을 chat_messages에 저장하고, has_answer=True면 citations도
    message_citations에 같이 저장한다. 근거 없음 상태(has_answer=False)는
    content에 그 사유를 그대로 남겨서, 화면에서 "근거 부족" 상태를 그대로 렌더링할 수 있게 한다.
    """
    db = get_supabase()
    content = result.answer if result.has_answer else (
        f"[근거 부족] {result.no_answer_reason}"
    )
    msg_res = (
        db.table("chat_messages")
        .insert({
            "session_id": session_id,
            "role": "assistant",
            "content": content,
            "model_name": result.model_name,
            "prompt_version": prompt_version,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        .execute()
    )
    message = msg_res.data[0]

    if result.has_answer and result.citations:
        rows = [
            {
                "message_id": message["id"],
                "document_version_id": c.document_version_id,
                "quoted_text": c.quote,
                "relevance_score": c.relevance_score,
                "citation_order": i,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            for i, c in enumerate(result.citations, start=1)
        ]
        db.table("message_citations").insert(rows).execute()

    return message


def _flatten_citation_source_url(row: dict) -> dict:
    """document_versions(document_id) -> documents(canonical_url) 임베드 결과를 source_url로 펼친다."""
    document_versions = row.pop("document_versions", None) or {}
    documents = document_versions.get("documents") or {}
    row["source_url"] = documents.get("canonical_url")
    return row


def list_message_citations(message_id: str) -> list[dict]:
    res = (
        get_supabase()
        .table("message_citations")
        .select("*, document_versions(document_id, documents(canonical_url))")
        .eq("message_id", message_id)
        .order("citation_order")
        .execute()
    )
    return [_flatten_citation_source_url(row) for row in res.data]


def get_chat_message(message_id: str) -> Optional[dict]:
    res = (
        get_supabase()
        .table("chat_messages")
        .select("*")
        .eq("id", message_id)
        .maybe_single()
        .execute()
    )
    return res.data


def get_preceding_user_message(session_id: str, before_created_at: str) -> Optional[dict]:
    """assistant 메시지 바로 앞에 있던 user 질문을 찾는다 — 메시지 쌍을 명시적으로 연결하는
    FK가 없어서, 같은 세션 안에서 시간순으로 바로 앞의 user 메시지를 그 짝으로 취급한다."""
    res = (
        get_supabase()
        .table("chat_messages")
        .select("*")
        .eq("session_id", session_id)
        .eq("role", "user")
        .lt("created_at", before_created_at)
        .order("created_at", desc=True)
        .limit(1)
        .maybe_single()
        .execute()
    )
    return res.data


def copy_chat_message(target_session_id: str, message: dict) -> dict:
    """공유는 항상 메시지 소유자만 할 수 있으므로, 원작성자(user_id)를 그대로 복사해도
    공유자 본인과 항상 같다 — 원작성자를 유지하는 게 맞다."""
    res = (
        get_supabase()
        .table("chat_messages")
        .insert({
            "session_id": target_session_id,
            "role": message["role"],
            "content": message["content"],
            "user_id": message.get("user_id"),
            "model_name": message.get("model_name"),
            "prompt_version": message.get("prompt_version"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        .execute()
    )
    return res.data[0]


def copy_message_citations(target_message_id: str, citations: list[dict]) -> None:
    if not citations:
        return
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "message_id": target_message_id,
            "document_version_id": c["document_version_id"],
            "qmd_uri": c.get("qmd_uri"),
            "source_start_line": c.get("source_start_line"),
            "source_end_line": c.get("source_end_line"),
            "quoted_text": c.get("quoted_text"),
            "relevance_score": c.get("relevance_score"),
            "citation_order": c.get("citation_order"),
            "created_at": now,
        }
        for c in citations
    ]
    get_supabase().table("message_citations").insert(rows).execute()

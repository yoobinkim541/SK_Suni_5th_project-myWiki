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


def create_chat_session(workspace_id: str, user_id: str, title: Optional[str] = None) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    res = (
        get_supabase()
        .table("chat_sessions")
        .insert({
            "workspace_id": workspace_id,
            "user_id": user_id,
            "title": title,
            "created_at": now,
            "updated_at": now,
        })
        .execute()
    )
    return res.data[0]


def get_chat_session(session_id: str, workspace_id: str) -> Optional[dict]:
    res = (
        get_supabase()
        .table("chat_sessions")
        .select("*")
        .eq("id", session_id)
        .eq("workspace_id", workspace_id)  # workspace 격리 — 다른 workspace 세션 접근 차단
        .maybe_single()
        .execute()
    )
    return res.data


def list_chat_messages(session_id: str) -> list[dict]:
    res = (
        get_supabase()
        .table("chat_messages")
        .select("*")
        .eq("session_id", session_id)
        .order("created_at")
        .execute()
    )
    return res.data


def save_user_message(session_id: str, content: str) -> dict:
    res = (
        get_supabase()
        .table("chat_messages")
        .insert({
            "session_id": session_id,
            "role": "user",
            "content": content,
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


def list_message_citations(message_id: str) -> list[dict]:
    res = (
        get_supabase()
        .table("message_citations")
        .select("*")
        .eq("message_id", message_id)
        .order("citation_order")
        .execute()
    )
    return res.data

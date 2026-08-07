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

# 근거 부족(has_answer=False) 응답의 content 접두사 — save_agent_message/update_agent_message가
# 여기 붙여서 저장하고, main.py의 삭제 엔드포인트가 이 접두사로 "지워도 되는 실패 응답"인지 판별한다.
NO_ANSWER_PREFIX = "[근거 부족]"


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
    session = res.data[0]
    if visibility == "team":
        # team 세션은 참여자 기반 접근 제어라, 만든 사람 본인도 참여자로 넣어두지
        # 않으면 자기가 방금 만든 세션을 자기가 못 보는 상태가 된다.
        add_chat_session_participant(session["id"], user_id)
    return session


def _participant_session_ids(user_id: str) -> list[str]:
    res = (
        get_supabase()
        .table("chat_session_participants")
        .select("session_id")
        .eq("user_id", user_id)
        .execute()
    )
    return [r["session_id"] for r in res.data]


def list_chat_sessions(workspace_id: str, user_id: str, scope: str) -> list[dict]:
    """scope='mine': 본인 소유 비공개 세션만. scope='team': 본인이 참여자인 공유 세션만
    (워크스페이스 멤버 전체가 아니다 — chat_session_participants 참여자 기반 접근 제어).
    삭제된(deleted_at IS NOT NULL) 세션은 기본적으로 목록에서 제외한다 — 보관된
    세션은 계속 보인다(보관은 숨김이 아니라 상태 표시일 뿐)."""
    query = (
        get_supabase()
        .table("chat_sessions")
        .select("*")
        .eq("workspace_id", workspace_id)
        .is_("deleted_at", "null")
    )
    if scope == "mine":
        query = query.eq("visibility", "private").eq("user_id", user_id)
    else:
        session_ids = _participant_session_ids(user_id)
        if not session_ids:
            return []
        query = query.eq("visibility", "team").in_("id", session_ids)
    res = query.order("updated_at", desc=True).execute()
    return res.data


def get_chat_session(session_id: str, workspace_id: str, user_id: str) -> Optional[dict]:
    """
    visibility='private'인 세션은 소유자(user_id)만 접근 가능하다 — 워크스페이스 소속이라는
    이유만으로 타인의 비공개 세션을 ID만 알면 읽을 수 있던 문제를 여기서 막는다.
    visibility='team'인 세션은 chat_session_participants에 있는 참여자만 접근 가능하다
    (워크스페이스 멤버 전체가 아니다 — 2026-08-05 참여자 관리 기능으로 좁혀졌다).
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
    if session.get("deleted_at") is not None:
        return None
    if session["visibility"] == "private" and session["user_id"] != user_id:
        return None
    if session["visibility"] == "team" and not is_chat_session_participant(session_id, user_id):
        return None
    return session


def is_chat_session_participant(session_id: str, user_id: str) -> bool:
    res = (
        get_supabase()
        .table("chat_session_participants")
        .select("id")
        .eq("session_id", session_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    return res.data is not None


def add_chat_session_participant(session_id: str, user_id: str) -> dict:
    res = (
        get_supabase()
        .table("chat_session_participants")
        .upsert(
            {"session_id": session_id, "user_id": user_id},
            on_conflict="session_id,user_id",
            ignore_duplicates=True,
        )
        .execute()
    )
    if res.data:
        return res.data[0]
    # 이미 참여자였으면 upsert(ignore_duplicates)가 빈 결과를 주므로 다시 조회한다.
    existing = (
        get_supabase()
        .table("chat_session_participants")
        .select("*")
        .eq("session_id", session_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    return existing.data


def remove_chat_session_participant(session_id: str, user_id: str) -> None:
    get_supabase().table("chat_session_participants").delete().eq(
        "session_id", session_id
    ).eq("user_id", user_id).execute()


def _flatten_display_name(row: dict) -> dict:
    profile = row.pop("profiles", None) or {}
    row["display_name"] = profile.get("display_name")
    return row


def list_chat_session_participants(session_id: str, workspace_id: str) -> list[dict]:
    """세션 참여자 목록 + 각자의 워크스페이스 역할(role).

    role은 chat_session_participants가 아니라 workspace_members에 있는 값이라
    (세션 참여자격과 워크스페이스 역할은 별개 테이블) 참여자 user_id들로 한 번 더
    조회해서 합친다 — frontend/src/constants/roles.js의 canInviteToSession/
    canRemoveFromSession이 이 role로 화면 버튼을 가리는 데 쓴다."""
    res = (
        get_supabase()
        .table("chat_session_participants")
        .select("*, profiles(display_name)")
        .eq("session_id", session_id)
        .order("created_at")
        .execute()
    )
    rows = [_flatten_display_name(row) for row in res.data]

    role_by_user_id = _get_workspace_roles(workspace_id, [r["user_id"] for r in rows])
    for r in rows:
        r["role"] = role_by_user_id.get(r["user_id"])
    return rows


def _get_workspace_roles(workspace_id: str, user_ids: list[str]) -> dict[str, str]:
    if not user_ids:
        return {}
    res = (
        get_supabase()
        .table("workspace_members")
        .select("user_id, role")
        .eq("workspace_id", workspace_id)
        .in_("user_id", list(set(user_ids)))
        .execute()
    )
    return {row["user_id"]: row["role"] for row in res.data}


def get_workspace_role(workspace_id: str, user_id: str) -> Optional[str]:
    return _get_workspace_roles(workspace_id, [user_id]).get(user_id)


def _get_email(user_id: str) -> Optional[str]:
    """profiles에는 email이 없다(auth.users에만 있음) — Admin API로 조회한다.
    사람 수만큼 개별 호출이라, 꼭 필요한 사람(동명이인)만 부른다."""
    try:
        res = get_supabase().auth.admin.get_user_by_id(user_id)
        return res.user.email if res and res.user else None
    except Exception:
        return None


def list_workspace_members(workspace_id: str) -> list[dict]:
    """참여자 추가 UI에서 "이 워크스페이스에 누가 있는지" 고를 때 쓴다.
    display_name이 같은 사람이 여럿이면(동명이인) 구분할 수 있게 email(전체 이메일
    주소)을 붙인다 — 겹치지 않는 사람은 Admin API를 안 부른다."""
    res = (
        get_supabase()
        .table("workspace_members")
        .select("user_id, role, profiles(display_name)")
        .eq("workspace_id", workspace_id)
        .execute()
    )
    rows = [_flatten_display_name(row) for row in res.data]

    name_counts: dict[Optional[str], int] = {}
    for r in rows:
        name_counts[r["display_name"]] = name_counts.get(r["display_name"], 0) + 1

    for r in rows:
        r["email"] = (
            _get_email(r["user_id"])
            if r["display_name"] and name_counts[r["display_name"]] > 1
            else None
        )
    return rows


def update_chat_session_title(session_id: str, title: str) -> None:
    get_supabase().table("chat_sessions").update({"title": title}).eq("id", session_id).execute()


def set_chat_session_archived(session_id: str, archived: bool) -> dict:
    """보관 토글. archived=True면 archived_at을 지금 시각으로, False면 NULL로 되돌린다."""
    archived_at = datetime.now(timezone.utc).isoformat() if archived else None
    res = (
        get_supabase()
        .table("chat_sessions")
        .update({"archived_at": archived_at})
        .eq("id", session_id)
        .execute()
    )
    return res.data[0]


def soft_delete_chat_session(session_id: str) -> None:
    get_supabase().table("chat_sessions").update(
        {"deleted_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", session_id).execute()


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
        f"{NO_ANSWER_PREFIX} {result.no_answer_reason}"
    )
    msg_res = (
        db.table("chat_messages")
        .insert({
            "session_id": session_id,
            "role": "assistant",
            "content": content,
            "model_name": result.model_name,
            "prompt_version": prompt_version,
            "is_llm_fallback": result.is_llm_fallback,
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


def update_agent_message(message_id: str, result: AgentResult, prompt_version: str = "v1") -> dict:
    """다시 생성 — 기존 assistant 메시지 행을 새 답변으로 그 자리에서 덮어쓴다(새 행을
    추가하지 않음 — 새로고침해도 옛 답변이 다시 보이지 않아야 하므로). created_at은
    그대로 둔다 — 메시지 순서/짝(get_preceding_user_message)이 시간순 비교에 의존한다.
    citations는 옛 것을 지우고 새로 채운다(citation_order가 답변마다 달라져서 갱신보다
    삭제 후 재삽입이 단순하다)."""
    db = get_supabase()
    content = result.answer if result.has_answer else (
        f"{NO_ANSWER_PREFIX} {result.no_answer_reason}"
    )
    msg_res = (
        db.table("chat_messages")
        .update({
            "content": content,
            "model_name": result.model_name,
            "prompt_version": prompt_version,
            "is_llm_fallback": result.is_llm_fallback,
        })
        .eq("id", message_id)
        .execute()
    )
    message = msg_res.data[0]

    db.table("message_citations").delete().eq("message_id", message_id).execute()
    if result.has_answer and result.citations:
        rows = [
            {
                "message_id": message_id,
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


def _enrich_message_citations(rows: list[dict]) -> list[dict]:
    """message_citations 원본 행에 문서 제목·매체명·게시일·개별 신뢰도를 붙인다.

    src/wiki/query.py의 _enrich_sources와 같은 패턴(순차 조회) — "근거 원문" 사이드바가
    렌더링하려는 발췌(quoted_text)+제목+매체명+날짜+신뢰도 중 제목/매체명/날짜/신뢰도가
    이전에는 전혀 채워지지 않아, 프론트가 그 카드를 "출처 정보 확인 중" 상태에서
    벗어나지 못하는 원인이 됐다.
    """
    if not rows:
        return rows

    document_version_ids = list({r["document_version_id"] for r in rows})
    db = get_supabase()

    versions_res = (
        db.table("document_versions")
        .select("id, document_id")
        .in_("id", document_version_ids)
        .execute()
    )
    document_id_by_version = {row["id"]: row["document_id"] for row in versions_res.data}

    document_ids = list({doc_id for doc_id in document_id_by_version.values() if doc_id})
    documents_by_id: dict[str, dict] = {}
    if document_ids:
        documents_res = (
            db.table("documents")
            .select("id, title, canonical_url, published_at, source_id")
            .in_("id", document_ids)
            .execute()
        )
        documents_by_id = {row["id"]: row for row in documents_res.data}

    source_ids = list({row["source_id"] for row in documents_by_id.values() if row.get("source_id")})
    source_name_by_id: dict[str, str] = {}
    if source_ids:
        sources_res = db.table("sources").select("id, name").in_("id", source_ids).execute()
        source_name_by_id = {row["id"]: row["name"] for row in sources_res.data}

    analysis_res = (
        db.table("document_analysis_results")
        .select("document_version_id, reliability_score")
        .in_("document_version_id", document_version_ids)
        .execute()
    )
    reliability_by_version = {
        row["document_version_id"]: row["reliability_score"]
        for row in analysis_res.data
        if row.get("reliability_score") is not None
    }

    for row in rows:
        document_id = document_id_by_version.get(row["document_version_id"])
        document = documents_by_id.get(document_id) if document_id else None
        row["document_title"] = document.get("title") if document else None
        row["source_url"] = document.get("canonical_url") if document else None
        row["published_at"] = document.get("published_at") if document else None
        row["source_name"] = source_name_by_id.get(document.get("source_id")) if document else None
        row["reliability_score"] = reliability_by_version.get(row["document_version_id"])
    return rows


def list_message_citations(message_id: str) -> list[dict]:
    res = (
        get_supabase()
        .table("message_citations")
        .select("*")
        .eq("message_id", message_id)
        .order("citation_order")
        .execute()
    )
    return _enrich_message_citations(res.data)


def delete_chat_message(message_id: str) -> None:
    """message_citations에 FK(ON DELETE CASCADE 없음)가 걸려 있어, 있을 수도 있는 citation을
    먼저 지우고 메시지를 지운다(근거 부족 답변은 보통 citation이 없지만, 방어적으로 처리)."""
    db = get_supabase()
    db.table("message_citations").delete().eq("message_id", message_id).execute()
    db.table("chat_messages").delete().eq("id", message_id).execute()


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


# ---------------------------------------------------------------------------
# 회원 탈퇴 — profiles를 하드 삭제하지 않고 소프트 삭제한다.
#
# profiles를 실제로 DELETE하면 chat_sessions.user_id/chat_session_participants.user_id가
# ON DELETE CASCADE라 이 사용자가 만든 팀 공유 대화가 다른 참여자 화면에서도 사라지고,
# chat_messages.user_id는 NO ACTION이라 그 사람이 메시지를 하나라도 남겼으면 FK 위반으로
# 삭제 자체가 막힌다. deleted_at만 세우는 소프트 삭제로 이 문제를 피한다 — 기존 콘텐츠는
# 작성자 표시(profiles(display_name) 조인)까지 그대로 남는다.
# ---------------------------------------------------------------------------


def soft_delete_profile(user_id: str) -> None:
    get_supabase().table("profiles").update(
        {"deleted_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", user_id).execute()


def remove_all_workspace_memberships(user_id: str) -> None:
    """workspace_members는 하드 삭제한다 — 소속 종료는 팀 목록에서 즉시 안 보여야 하고,
    다른 테이블처럼 이 행을 참조하며 "보존해야 할 콘텐츠"가 없다."""
    get_supabase().table("workspace_members").delete().eq("user_id", user_id).execute()


def delete_push_subscriptions_for_user(user_id: str) -> None:
    get_supabase().table("push_subscriptions").delete().eq("user_id", user_id).execute()


def delete_auth_user(user_id: str) -> None:
    """Supabase Auth의 실제 로그인 자격을 없앤다(auth.users 행 삭제) — service_role
    Admin API로만 가능하다(본인이 자기 계정을 클라이언트에서 지울 수 없음).

    profiles.id는 auth.users.id를 FK로 참조하지 않으므로(DB 레벨 제약 없음) 이 호출이
    profiles/chat_sessions 등 우리 테이블에 어떤 CASCADE도 일으키지 않는다 — soft_delete_profile로
    이미 남긴 deleted_at 흔적은 그대로 유지된다."""
    get_supabase().auth.admin.delete_user(user_id)

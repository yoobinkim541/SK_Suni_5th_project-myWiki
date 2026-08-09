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


def get_workspace(workspace_id: str) -> Optional[dict]:
    res = (
        get_supabase()
        .table("workspaces")
        .select("id, name")
        .eq("id", workspace_id)
        .maybe_single()
        .execute()
    )
    return res.data


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


def _citation_rows(message_id: str, citations: list) -> list[dict]:
    """message_citations insert용 행을 만든다 — save_agent_message/update_agent_message가
    공유한다(예전엔 두 함수가 이 9줄을 각각 중복해서 갖고 있었다)."""
    now = datetime.now(timezone.utc).isoformat()
    return [
        {
            "message_id": message_id,
            "document_version_id": c.document_version_id,
            "source_url": c.source_url,
            "source_title": c.source_title,
            "published_at": c.source_published_at,
            "quoted_text": c.quote,
            "relevance_score": c.relevance_score,
            "citation_order": i,
            "created_at": now,
        }
        for i, c in enumerate(citations, start=1)
    ]


def save_agent_message(session_id: str, result: AgentResult, prompt_version: str = "v1") -> dict:
    """
    Agent 응답을 chat_messages에 저장하고, citations가 있으면 has_answer 여부와
    무관하게 message_citations에도 같이 저장한다 — submit_no_answer도 이제
    참고할 만큼만 읽은 문서를 citations로 선택적으로 실어 보낼 수 있어서(완전한
    답은 아니지만 reason의 [N] 각주가 실제 문서로 연결되게), has_answer=False라고
    citations를 버리면 안 된다. 근거 없음 상태(has_answer=False)는 content에 그
    사유를 그대로 남겨서, 화면에서 "근거 부족" 상태를 그대로 렌더링할 수 있게 한다.
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

    if result.citations:
        rows = _citation_rows(message["id"], result.citations)
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
    if result.citations:
        rows = _citation_rows(message_id, result.citations)
        db.table("message_citations").insert(rows).execute()

    return message


def _enrich_message_citations(rows: list[dict]) -> list[dict]:
    """message_citations 원본 행에 문서 제목·매체명·게시일·개별 신뢰도를 붙인다.

    document_version_id가 있는 행(위키/원문 근거)만 documents/document_versions를
    조인해서 채운다. document_version_id가 없는 행(웹 검색 근거)은 저장 시점에 이미
    자기 행에 source_url/source_title/published_at을 직접 채워뒀으므로(조인할 DB
    행 자체가 없음) 그대로 통과시키고 document_title 필드명만 맞춰준다.
    """
    if not rows:
        return rows

    joinable_rows = []
    for row in rows:
        if row["document_version_id"] is None:
            row["document_title"] = row.pop("source_title", None)
            row["source_name"] = None
            row["reliability_score"] = None
        else:
            joinable_rows.append(row)

    if not joinable_rows:
        return rows

    document_version_ids = list({r["document_version_id"] for r in joinable_rows})
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

    for row in joinable_rows:
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
# 회원 탈퇴 — profiles/auth.users를 하드 삭제하지 않는다.
#
# profiles를 실제로 DELETE하면 chat_sessions.user_id/chat_session_participants.user_id가
# ON DELETE CASCADE라 이 사용자가 만든 팀 공유 대화가 다른 참여자 화면에서도 사라지고,
# chat_messages.user_id는 NO ACTION이라 그 사람이 메시지를 하나라도 남겼으면 FK 위반으로
# 삭제 자체가 막힌다. deleted_at만 세우는 소프트 삭제로 이 문제를 피한다 — 기존 콘텐츠는
# 작성자 표시(profiles(display_name) 조인)까지 그대로 남는다.
#
# 같은 이유로 auth.users도 하드 삭제하지 않는다 — profiles.id -> auth.users.id에도
# ON DELETE CASCADE(fk_profiles_auth_user)가 걸려 있어서, auth.users를 지우면 위에서
# 피하려던 CASCADE 체인이 뒷문으로 그대로 재현된다(ban_auth_user 참고).
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


# 100년 — GoTrue의 ban_duration은 유한한 값만 받아서 "영구"를 문자 그대로 표현할 방법이
# 없다. 사실상 영구 차단으로 취급할 수 있는 값을 쓴다.
PERMANENT_BAN_DURATION = "876000h"


def ban_auth_user(user_id: str) -> None:
    """Supabase Auth의 실제 로그인을 막는다(auth.users 행은 지우지 않고 ban만 건다) —
    service_role Admin API로만 가능하다(본인이 자기 계정을 클라이언트에서 못 지움).

    ⚠ 처음엔 auth.admin.delete_user()로 auth.users 행 자체를 지우려 했으나, 실제로는
    profiles.id -> auth.users.id에 ON DELETE CASCADE FK(fk_profiles_auth_user)가 걸려
    있어서(information_schema 기반 조회로는 안 잡히고 pg_constraint로 직접 조회해야
    보임 — cross-schema FK를 information_schema.constraint_column_usage가 못 잡는
    경우가 있다) auth.users 삭제가 profiles까지 실제로 CASCADE 삭제해 버렸다. 이어서
    chat_sessions.user_id -> profiles.id도 CASCADE라 이 사용자의 세션까지 지우려다
    chat_messages의 FK(NO ACTION)에 막혀 통째로 실패하는 걸 프로덕션 auth 로그에서
    확인했다(2026-08-07) — 즉 soft_delete_profile로 지키려던 것과 정확히 같은 문제를
    delete_auth_user가 뒷문으로 재현하고 있었다. ban_duration으로 로그인만 막으면
    auth.users 행이 그대로 남아 이 CASCADE가 전혀 발동하지 않는다."""
    get_supabase().auth.admin.update_user_by_id(user_id, {"ban_duration": PERMANENT_BAN_DURATION})


# ---------------------------------------------------------------------------
# 오너 전용 워크스페이스 관리 — 멤버 방출·역할 변경.
# 기존 get_chat_session/list_chat_sessions(일반 사용자 접근 제어)는 건드리지 않고
# 완전히 분리된 함수로 둔다 — 오너 권한 체크는 호출부(main.py)의 몫이다.
# ---------------------------------------------------------------------------


def remove_workspace_member(workspace_id: str, user_id: str) -> None:
    """workspace_members 행 삭제 + 이 워크스페이스 소속 세션들의 참여자 행도 함께
    삭제한다 — 방출됐는데 팀 세션엔 계속 참여자로 남는 상태를 방지한다."""
    session_ids_res = (
        get_supabase()
        .table("chat_sessions")
        .select("id")
        .eq("workspace_id", workspace_id)
        .execute()
    )
    session_ids = [row["id"] for row in session_ids_res.data]
    if session_ids:
        (
            get_supabase()
            .table("chat_session_participants")
            .delete()
            .eq("user_id", user_id)
            .in_("session_id", session_ids)
            .execute()
        )

    get_supabase().table("workspace_members").delete().eq(
        "workspace_id", workspace_id
    ).eq("user_id", user_id).execute()


def update_workspace_member_role(workspace_id: str, user_id: str, role: str) -> None:
    get_supabase().table("workspace_members").update({"role": role}).eq(
        "workspace_id", workspace_id
    ).eq("user_id", user_id).execute()


def list_workspace_sessions_for_admin(workspace_id: str, visibility: str) -> list[dict]:
    """참여자/소유자 필터 없이 워크스페이스의 세션을 전부 조회한다(오너 전용 열람용).
    get_chat_session/list_chat_sessions(일반 사용자용, 접근 제어 있음)와는 별개 함수다."""
    res = (
        get_supabase()
        .table("chat_sessions")
        .select("*, profiles(display_name)")
        .eq("workspace_id", workspace_id)
        .eq("visibility", visibility)
        .is_("deleted_at", "null")
        .order("updated_at", desc=True)
        .execute()
    )
    rows = []
    for row in res.data:
        profile = row.pop("profiles", None) or {}
        row["owner_name"] = profile.get("display_name")
        rows.append(row)
    return rows


def get_chat_session_for_admin(session_id: str, workspace_id: str) -> Optional[dict]:
    """get_chat_session과 달리 참여자/소유자 여부를 확인하지 않는다 — workspace_id
    일치만 확인한다(오너 전용 열람용).

    삭제(soft-delete)된 세션도 조회된다 — list_workspace_sessions_for_admin과 달리
    deleted_at 필터가 없다. 오너 감사 목적상 사용자가 세션을 지워도 오너의 조회
    권한까지 사라지면 안 된다(의도적 설계, 누락 아님)."""
    res = (
        get_supabase()
        .table("chat_sessions")
        .select("*")
        .eq("id", session_id)
        .eq("workspace_id", workspace_id)
        .maybe_single()
        .execute()
    )
    return res.data


# ---------------------------------------------------------------------------
# 팀 관리 — teams 테이블 + workspace_members.team_id.
# role(owner/admin/editor)을 관리자/팀장/팀원으로 재해석해 재사용한다(새 역할
# 컬럼 없음). 여기 함수들은 인가를 검증하지 않는 원시 동작만 한다 — 역할·팀
# 범위 검증은 호출부(main.py)의 몫이다(기존 오너 전용 관리 함수들과 동일 패턴).
# ---------------------------------------------------------------------------


def get_workspace_member(workspace_id: str, user_id: str) -> Optional[dict]:
    res = (
        get_supabase()
        .table("workspace_members")
        .select("user_id, role, team_id")
        .eq("workspace_id", workspace_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    return res.data


def create_team(workspace_id: str, name: str) -> dict:
    existing_res = (
        get_supabase()
        .table("teams")
        .select("id")
        .eq("workspace_id", workspace_id)
        .eq("name", name)
        .execute()
    )
    if existing_res.data:
        raise ValueError("이미 존재하는 팀 이름")

    res = (
        get_supabase()
        .table("teams")
        .insert({"workspace_id": workspace_id, "name": name})
        .execute()
    )
    return res.data[0]


def list_teams(workspace_id: str) -> list[dict]:
    teams_res = (
        get_supabase()
        .table("teams")
        .select("id, name")
        .eq("workspace_id", workspace_id)
        .order("name")
        .execute()
    )
    members_res = (
        get_supabase()
        .table("workspace_members")
        .select("team_id")
        .eq("workspace_id", workspace_id)
        .execute()
    )
    counts: dict[str, int] = {}
    for row in members_res.data:
        team_id = row.get("team_id")
        if team_id:
            counts[team_id] = counts.get(team_id, 0) + 1

    return [
        {"id": t["id"], "name": t["name"], "member_count": counts.get(t["id"], 0)}
        for t in teams_res.data
    ]


def delete_team(team_id: str) -> None:
    members_res = (
        get_supabase()
        .table("workspace_members")
        .select("user_id")
        .eq("team_id", team_id)
        .execute()
    )
    if members_res.data:
        raise ValueError("팀에 소속된 인원이 있어 삭제할 수 없음")

    get_supabase().table("teams").delete().eq("id", team_id).execute()


def list_team_members(team_id: str) -> list[dict]:
    res = (
        get_supabase()
        .table("workspace_members")
        .select("user_id, role, profiles(display_name)")
        .eq("team_id", team_id)
        .execute()
    )
    return [_flatten_display_name(row) for row in res.data]


def list_workspace_users_with_team(workspace_id: str) -> list[dict]:
    members_res = (
        get_supabase()
        .table("workspace_members")
        .select("user_id, role, team_id, profiles(display_name)")
        .eq("workspace_id", workspace_id)
        .execute()
    )
    rows = [_flatten_display_name(row) for row in members_res.data]

    teams_res = (
        get_supabase()
        .table("teams")
        .select("id, name")
        .eq("workspace_id", workspace_id)
        .execute()
    )
    team_names = {t["id"]: t["name"] for t in teams_res.data}

    for row in rows:
        row["team_name"] = team_names.get(row.get("team_id"))
    return rows


def move_member_to_team(workspace_id: str, user_id: str, team_id: Optional[str]) -> None:
    get_supabase().table("workspace_members").update({"team_id": team_id}).eq(
        "workspace_id", workspace_id
    ).eq("user_id", user_id).execute()


# ---------------------------------------------------------------------------
# 프로필 편집 — 이름(profiles.display_name) + 프로필 사진(avatars 버킷, 비공개).
# 다른 버킷들과 동일하게 프론트는 Storage에 직접 접근하지 않는다 — 백엔드가
# GET /profile/avatar에서 바이트를 직접 스트리밍해서 내려준다(서명 URL 방식 아님).
# ---------------------------------------------------------------------------

AVATAR_BUCKET = "avatars"


def update_profile_display_name(user_id: str, display_name: str) -> dict:
    res = (
        get_supabase()
        .table("profiles")
        .update({"display_name": display_name})
        .eq("id", user_id)
        .execute()
    )
    return res.data[0]


def set_profile_avatar_object_key(user_id: str, object_key: Optional[str]) -> None:
    get_supabase().table("profiles").update({"avatar_object_key": object_key}).eq("id", user_id).execute()


def upload_avatar_object(object_key: str, data: bytes, content_type: str) -> None:
    get_supabase().storage.from_(AVATAR_BUCKET).upload(
        path=object_key, file=data, file_options={"content-type": content_type, "upsert": "true"},
    )


def download_avatar_object(object_key: str) -> bytes:
    return get_supabase().storage.from_(AVATAR_BUCKET).download(object_key)


def delete_avatar_object(object_key: str) -> None:
    get_supabase().storage.from_(AVATAR_BUCKET).remove([object_key])

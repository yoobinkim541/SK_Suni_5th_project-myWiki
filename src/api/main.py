"""
Agent·API 담당 FastAPI 서버.
엔드포인트: 채팅 세션 생성/조회, 메시지 전송(Agent 호출 포함), 메시지 이력 조회.

실행:
    uvicorn src.api.main:app --reload
"""
from __future__ import annotations

import logging
from typing import Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

# db.py/auth.py는 SUPABASE_* 값을 요청 처리 중(첫 호출 시점)에 os.environ에서 직접 읽는다 —
# `uvicorn src.api.main:app`을 README 그대로 실행하면 .env가 자동으로 로드되지 않아서,
# 실제 인증 토큰이 들어오는 요청마다 KeyError로 500이 났다(빈 토큰이면 먼저 401로 걸러져서
# 이 문제가 안 드러났었다). 여기서 한 번 로드해두면 실행 방식과 무관하게 항상 채워진다.
load_dotenv()

# 앱 전역에 logging 설정이 하나도 없으면, 핸들러가 없는 로거는 Python의 "handler of
# last resort"로 떨어지는데 이건 WARNING 이상만 찍는다 — logger.info는 아무 설정 없이는
# 콘솔에 전혀 안 찍힌다. 여기서 명시적으로 INFO까지 보이게 설정한다.
logging.basicConfig(level=logging.INFO)

from . import db
from .auth import get_current_user
from .schemas import (
    AddParticipantRequest,
    ChatMessageOut,
    ChatSessionOut,
    CitationOut,
    CreateSessionRequest,
    ParticipantOut,
    RenameSessionRequest,
    SaveToWikiResponse,
    SendMessageRequest,
    SendMessageResponse,
    ShareToTeamRequest,
    WorkspaceMemberOut,
)
from .category_router import router as category_router
from .dashboard_router import router as dashboard_router
from .notifications_router import router as notifications_router
from .report_router import router as report_router
from .settings_router import router as settings_router
from .wiki_router import router as wiki_router
from ..agent.core import WikiAgent
from ..agent.titling import generate_session_title
from ..agent.wiki_tools import WikiTools
from ..wiki.chat_wiki import compose_chat_wiki_draft
from ..wiki.interface import (
    WikiDraftInput,
    WikiSourceInput,
    create_wiki_version,
    publish_wiki_version,
    record_wiki_validation,
    review_wiki_version,
    upsert_wiki_page,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="myWiki Agent API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://mywiki.pe.kr",
        "https://www.mywiki.pe.kr",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(wiki_router)
app.include_router(settings_router)
app.include_router(notifications_router)
app.include_router(dashboard_router)
app.include_router(category_router)
app.include_router(report_router)


TITLE_MAX_LEN = 40


def _truncate_title(text: str) -> str:
    """자동 제목 폴백 — LLM 요약이 실패하면(generate_session_title이 None) 첫 질문
    텍스트를 그대로 잘라 쓴다. 실패해도 제목이 계속 "새 대화 N"으로 남는 일이 없게 한다."""
    text = text.strip()
    if len(text) <= TITLE_MAX_LEN:
        return text
    return text[:TITLE_MAX_LEN].rstrip() + "…"


def _auto_title(question: str) -> str:
    """첫 질문으로 세션 제목을 정한다 — LLM 요약을 먼저 시도하고, 실패하면(예외/빈 응답)
    단순 truncate로 대체한다. generate_session_title은 모든 예외를 자체적으로 삼키므로
    여기서 별도 예외 처리가 필요 없다."""
    return generate_session_title(question) or _truncate_title(question)


def _require_workspace(profile: dict) -> str:
    workspace_id = db.get_default_workspace_id(profile["id"])
    if not workspace_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="workspace 소속이 없음")
    return workspace_id


def _to_message_out(message: dict) -> ChatMessageOut:
    citations = db.list_message_citations(message["id"]) if message["role"] == "assistant" else []
    return ChatMessageOut(**message, citations=[CitationOut(**c) for c in citations])


@app.get("/chat/sessions", response_model=list[ChatSessionOut])
def list_sessions(scope: Literal["mine", "team"] = "mine", profile: dict = Depends(get_current_user)):
    workspace_id = _require_workspace(profile)
    sessions = db.list_chat_sessions(workspace_id, profile["id"], scope)
    return [ChatSessionOut(**s) for s in sessions]


@app.post("/chat/sessions", response_model=ChatSessionOut)
def create_session(body: CreateSessionRequest, profile: dict = Depends(get_current_user)):
    workspace_id = _require_workspace(profile)
    session = db.create_chat_session(workspace_id, profile["id"], body.title, body.visibility)
    return ChatSessionOut(**session)


@app.get("/chat/sessions/{session_id}/messages", response_model=list[ChatMessageOut])
def get_messages(session_id: str, profile: dict = Depends(get_current_user)):
    workspace_id = _require_workspace(profile)
    session = db.get_chat_session(session_id, workspace_id, profile["id"])
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="세션을 찾을 수 없음")

    messages = db.list_chat_messages(session_id)
    return [_to_message_out(m) for m in messages]


@app.post("/chat/sessions/{session_id}/messages", response_model=SendMessageResponse)
def send_message(
    session_id: str, body: SendMessageRequest, profile: dict = Depends(get_current_user)
):
    workspace_id = _require_workspace(profile)
    session = db.get_chat_session(session_id, workspace_id, profile["id"])
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="세션을 찾을 수 없음")

    user_message = db.save_user_message(session_id, body.content, profile["id"])

    # 이전 대화 이력을 Agent에게 넘겨서 멀티턴 맥락을 유지한다.
    history = [
        {"role": "user" if m["role"] == "user" else "assistant", "content": m["content"]}
        for m in db.list_chat_messages(session_id)
        if m["id"] != user_message["id"]
    ]
    is_first_message = not history

    wiki_tools = WikiTools(workspace_id=workspace_id)
    agent = WikiAgent(wiki_tools)
    result = agent.answer(body.content, history=history)

    assistant_message = db.save_agent_message(session_id, result)

    # 세션의 첫 질문이면(개인/팀 공통) LLM으로 그 질문을 요약해 제목으로 채운다.
    # 실패하면(reasoning 토큰 과다 소비 등으로 LLM 응답을 못 받으면) _auto_title이
    # 알아서 단순 truncate로 대체하므로, 제목이 "새 대화 N"으로 계속 남는 일은 없다.
    if is_first_message:
        title = _auto_title(body.content)
        db.update_chat_session_title(session_id, title)
        logger.info("auto title set from first question: session_id=%s title=%r", session_id, title)

    return SendMessageResponse(
        user_message=_to_message_out(user_message),
        assistant_message=_to_message_out(assistant_message),
        has_answer=result.has_answer,
    )


def _get_owned_message(session_id: str, message_id: str, workspace_id: str, user_id: str) -> dict:
    session = db.get_chat_session(session_id, workspace_id, user_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="세션을 찾을 수 없음")

    message = db.get_chat_message(message_id)
    if message is None or message["session_id"] != session_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="메시지를 찾을 수 없음")
    if message["role"] != "assistant":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="assistant 답변만 대상으로 할 수 있음")

    return message


@app.post("/chat/sessions/{session_id}/messages/{message_id}/share-to-team", response_model=ChatMessageOut)
def share_message_to_team(
    session_id: str,
    message_id: str,
    body: ShareToTeamRequest = ShareToTeamRequest(),
    profile: dict = Depends(get_current_user),
):
    workspace_id = _require_workspace(profile)
    message = _get_owned_message(session_id, message_id, workspace_id, profile["id"])

    user_message = db.get_preceding_user_message(session_id, message["created_at"])
    if user_message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="짝이 되는 질문 메시지를 찾을 수 없음")

    is_new_target_session = False
    if body.target_session_id:
        target_session = db.get_chat_session(body.target_session_id, workspace_id, profile["id"])
        if target_session is None or target_session["visibility"] != "team":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="유효한 팀 공유 세션이 아님")
    else:
        target_session = db.create_chat_session(workspace_id, profile["id"], title="새 공유 대화", visibility="team")
        is_new_target_session = True

    db.copy_chat_message(target_session["id"], user_message)
    copied_assistant = db.copy_chat_message(target_session["id"], message)

    citations = db.list_message_citations(message_id)
    db.copy_message_citations(copied_assistant["id"], citations)

    # 새로 만든 공유 세션이면, 방금 옮긴 질문을 요약해 제목으로 채운다.
    if is_new_target_session:
        db.update_chat_session_title(target_session["id"], _auto_title(user_message["content"]))

    return _to_message_out(copied_assistant)


@app.delete(
    "/chat/sessions/{session_id}/messages/{message_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_message(session_id: str, message_id: str, profile: dict = Depends(get_current_user)):
    """질문/답변 쌍 하나를 완전 삭제한다(soft-delete 없이 바로 지움). 정상 답변이어도
    지울 수 있다 — 이미 위키에 저장했거나 팀에 공유한 답변은 그때 별도 행으로 복사돼
    있으므로(copy_chat_message/upsert_wiki_page), 원본 쌍을 지워도 영향받지 않는다."""
    workspace_id = _require_workspace(profile)
    message = _get_owned_message(session_id, message_id, workspace_id, profile["id"])

    user_message = db.get_preceding_user_message(session_id, message["created_at"])

    db.delete_chat_message(message_id)
    if user_message:
        db.delete_chat_message(user_message["id"])


@app.post("/chat/sessions/{session_id}/messages/{message_id}/regenerate", response_model=ChatMessageOut)
def regenerate_message(session_id: str, message_id: str, profile: dict = Depends(get_current_user)):
    """다시 생성 — 같은 질문으로 Agent를 다시 호출해 답변 행을 그 자리에서 교체한다.
    (프론트가 새 Q&A를 아래에 덧붙이는 방식도 가능하지만, 그러면 새로고침 시 옛 답변이
    DB에 남아 있어 다시 나타난다 — 진짜 "다시 생성"이 되려면 in-place 교체가 필요하다.)"""
    workspace_id = _require_workspace(profile)
    message = _get_owned_message(session_id, message_id, workspace_id, profile["id"])

    user_message = db.get_preceding_user_message(session_id, message["created_at"])
    if user_message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="짝이 되는 질문 메시지를 찾을 수 없음")

    # 재답변 시점에 이 질문/답변 쌍은 이력에서 빼야 한다 — 안 그러면 Agent가 자기 자신의
    # 옛 답변을 맥락으로 다시 참고하게 된다.
    history = [
        {"role": "user" if m["role"] == "user" else "assistant", "content": m["content"]}
        for m in db.list_chat_messages(session_id)
        if m["id"] not in (user_message["id"], message_id)
    ]

    wiki_tools = WikiTools(workspace_id=workspace_id)
    agent = WikiAgent(wiki_tools)
    result = agent.answer(user_message["content"], history=history)

    updated = db.update_agent_message(message_id, result)
    return _to_message_out(updated)


@app.post("/chat/sessions/{session_id}/messages/{message_id}/save-to-wiki", response_model=SaveToWikiResponse)
def save_message_to_wiki(session_id: str, message_id: str, profile: dict = Depends(get_current_user)):
    workspace_id = _require_workspace(profile)
    message = _get_owned_message(session_id, message_id, workspace_id, profile["id"])

    # LLM 폴백 답변(위키 근거 없이 일반 지식으로 답한 것)은 citations가 항상 비어 있어
    # 아래 citations 체크로도 걸리지만, 할루시네이션 가능성이 있는 답을 위키 지식으로
    # 굳어버리는 걸 막는다는 의도를 명확히 드러내려고 이 케이스를 따로 앞에서 걸러낸다.
    if message.get("is_llm_fallback"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="위키 근거 없이 LLM 일반 지식으로 답한 내용은 위키에 저장할 수 없음(할루시네이션 가능성)",
        )

    citations = db.list_message_citations(message_id)
    if not citations:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="근거(citation)가 없는 답변은 위키에 저장할 수 없음"
        )

    user_message = db.get_preceding_user_message(session_id, message["created_at"])
    question = user_message["content"] if user_message else "채팅에서 저장된 답변"
    chat_draft = compose_chat_wiki_draft(question, message["content"], citations)
    title = chat_draft.title
    slug = f"chat-{message_id[:8]}"

    page_id = upsert_wiki_page(workspace_id, slug, title, "issue")
    draft = WikiDraftInput(
        workspace_id=workspace_id,
        slug=slug,
        title=title,
        page_type="issue",
        markdown=chat_draft.markdown,
        sources=[
            WikiSourceInput(
                document_version_id=c["document_version_id"],
                claim_text=c.get("quoted_text") or "",
                source_start_line=c.get("source_start_line"),
                source_end_line=c.get("source_end_line"),
                support_type="supports",
                citation_order=c.get("citation_order"),
            )
            for c in citations
        ],
        created_by=profile["id"],
        generated_by="llm",
        generator_model=message.get("model_name"),
    )
    version_id = create_wiki_version(draft)
    record_wiki_validation(version_id, "passed", None)
    review_wiki_version(version_id, None, "approved")
    publish_wiki_version(page_id, version_id)

    return SaveToWikiResponse(page_id=page_id, version_id=version_id, slug=slug)


MANUAL_TITLE_MAX_LEN = 100


@app.patch("/chat/sessions/{session_id}/title", response_model=ChatSessionOut)
def rename_session(session_id: str, body: RenameSessionRequest, profile: dict = Depends(get_current_user)):
    """대화 제목을 사용자가 직접 바꾼다 — 첫 질문에서 자동으로 채워진 제목을 언제든
    덮어쓸 수 있다. 보관과 같은 접근 규칙(개인은 소유자만, 팀은 참여자 누구나)을 쓴다."""
    workspace_id = _require_workspace(profile)
    session = db.get_chat_session(session_id, workspace_id, profile["id"])
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="세션을 찾을 수 없음")

    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="제목을 입력해야 함")
    if len(title) > MANUAL_TITLE_MAX_LEN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"제목은 {MANUAL_TITLE_MAX_LEN}자를 넘을 수 없음"
        )

    db.update_chat_session_title(session_id, title)
    updated = db.get_chat_session(session_id, workspace_id, profile["id"])
    return ChatSessionOut(**updated)


@app.patch("/chat/sessions/{session_id}/archive", response_model=ChatSessionOut)
def archive_session(session_id: str, profile: dict = Depends(get_current_user)):
    """보관 토글 — 개인 세션은 소유자만, 팀 세션은 워크스페이스 멤버 누구나 가능하다
    (get_chat_session의 기존 접근 규칙을 그대로 재사용)."""
    workspace_id = _require_workspace(profile)
    session = db.get_chat_session(session_id, workspace_id, profile["id"])
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="세션을 찾을 수 없음")

    updated = db.set_chat_session_archived(session_id, archived=session.get("archived_at") is None)
    return ChatSessionOut(**updated)


@app.delete("/chat/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: str, profile: dict = Depends(get_current_user)):
    """소프트 삭제 — 개인/팀 세션 모두 생성자만 삭제할 수 있다(팀 세션은 보관과 달리
    아무 멤버나 지울 수 없도록 get_chat_session 통과 후 소유자 여부를 별도로 확인한다)."""
    workspace_id = _require_workspace(profile)
    session = db.get_chat_session(session_id, workspace_id, profile["id"])
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="세션을 찾을 수 없음")
    if session["user_id"] != profile["id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="세션 생성자만 삭제할 수 있음")

    db.soft_delete_chat_session(session_id)


@app.get("/chat/sessions/{session_id}/participants", response_model=list[ParticipantOut])
def list_participants(session_id: str, profile: dict = Depends(get_current_user)):
    workspace_id = _require_workspace(profile)
    session = db.get_chat_session(session_id, workspace_id, profile["id"])
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="세션을 찾을 수 없음")

    rows = db.list_chat_session_participants(session_id)
    return [ParticipantOut(user_id=r["user_id"], display_name=r.get("display_name")) for r in rows]


@app.post(
    "/chat/sessions/{session_id}/participants",
    response_model=ParticipantOut,
    status_code=status.HTTP_201_CREATED,
)
def add_participant(
    session_id: str, body: AddParticipantRequest, profile: dict = Depends(get_current_user)
):
    """참여자 추가는 이미 참여 중인 사람이면 누구나 할 수 있다(get_chat_session이 이미
    참여자만 통과시키므로 별도 체크가 필요 없다). 추가 대상은 같은 워크스페이스
    소속이어야 한다 — 안 그러면 다른 워크스페이스 사람을 끌어들일 수 있다."""
    workspace_id = _require_workspace(profile)
    session = db.get_chat_session(session_id, workspace_id, profile["id"])
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="세션을 찾을 수 없음")
    if session["visibility"] != "team":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="팀 공유 세션에서만 참여자를 관리할 수 있음")

    if db.get_default_workspace_id(body.user_id) != workspace_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="같은 워크스페이스 멤버만 추가할 수 있음")

    db.add_chat_session_participant(session_id, body.user_id)
    added_profile = db.get_profile(body.user_id)
    return ParticipantOut(
        user_id=body.user_id, display_name=added_profile.get("display_name") if added_profile else None
    )


@app.delete(
    "/chat/sessions/{session_id}/participants/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_participant(session_id: str, user_id: str, profile: dict = Depends(get_current_user)):
    """본인 탈퇴는 항상 허용한다. 다른 사람을 빼는 건 세션 생성자만 가능하다 —
    참여자끼리 서로 쫓아내지 못하게 막는다."""
    workspace_id = _require_workspace(profile)
    session = db.get_chat_session(session_id, workspace_id, profile["id"])
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="세션을 찾을 수 없음")
    if session["visibility"] != "team":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="팀 공유 세션에서만 참여자를 관리할 수 있음")

    if user_id != profile["id"] and session["user_id"] != profile["id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="다른 참여자는 세션 생성자만 뺄 수 있음")

    db.remove_chat_session_participant(session_id, user_id)


@app.get("/workspace/members", response_model=list[WorkspaceMemberOut])
def list_members(profile: dict = Depends(get_current_user)):
    """참여자 추가 UI가 "누구를 추가할지" 고를 목록으로 쓴다."""
    workspace_id = _require_workspace(profile)
    rows = db.list_workspace_members(workspace_id)
    return [
        WorkspaceMemberOut(user_id=r["user_id"], display_name=r.get("display_name"), email=r.get("email"))
        for r in rows
    ]


@app.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(profile: dict = Depends(get_current_user)):
    """회원 탈퇴 — 본인 계정만 지울 수 있다(user_id를 URL/바디로 받지 않음).

    profiles는 하드 삭제하지 않고 soft_delete_profile로 deleted_at만 남긴다(이유는
    db.py의 관련 함수 docstring 참고) — 팀 공유 대화 등 다른 사람이 보는 콘텐츠가
    이 사람의 탈퇴로 함께 사라지지 않게 하기 위함이다. 이후 get_current_user가
    deleted_at을 확인해 재로그인을 막고, auth 사용자 자체도 지워 완전히 로그인 불가능하게 한다.

    auth 사용자 삭제(delete_auth_user)가 실패해도 요청 자체를 실패로 만들지 않는다 —
    이미 deleted_at이 찍혀 get_current_user가 이후 요청을 막아주므로, 외부 Admin API
    호출 한 번의 일시적 실패 때문에 탈퇴 자체가 안 된 것처럼 보이면 안 된다.
    """
    user_id = profile["id"]

    db.soft_delete_profile(user_id)

    try:
        db.remove_all_workspace_memberships(user_id)
    except Exception:
        logger.exception("account_deletion_workspace_membership_cleanup_failed", extra={"user_id": user_id})

    try:
        db.delete_push_subscriptions_for_user(user_id)
    except Exception:
        logger.exception("account_deletion_push_subscription_cleanup_failed", extra={"user_id": user_id})

    try:
        db.delete_auth_user(user_id)
    except Exception:
        logger.exception("account_deletion_auth_user_delete_failed", extra={"user_id": user_id})


@app.get("/health")
def health():
    return {"status": "ok"}

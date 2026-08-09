"""
Agent·API 담당 FastAPI 서버.
엔드포인트: 채팅 세션 생성/조회, 메시지 전송(Agent 호출 포함), 메시지 이력 조회.

실행:
    uvicorn src.api.main:app --reload
"""
from __future__ import annotations

import logging
from typing import Literal, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, Query, Response, UploadFile, status
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
    AdminSessionOut,
    AdminUserOut,
    AssignTeamRequest,
    ChatMessageOut,
    ChatSessionOut,
    CitationOut,
    CreateSessionRequest,
    CreateTeamRequest,
    ParticipantOut,
    ProfileOut,
    RenameSessionRequest,
    SaveToWikiResponse,
    SendMessageRequest,
    SendMessageResponse,
    ShareToTeamRequest,
    TeamMemberOut,
    TeamOut,
    UpdateMemberRoleRequest,
    UpdateProfileRequest,
    WorkspaceMemberOut,
    WorkspaceOut,
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
    update_wiki_page_title,
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

# 확장자를 mimetypes 모듈(OS 레지스트리 의존, 플랫폼마다 다른 값을 줄 수 있음) 대신
# 직접 매핑한다 — src/pipeline_common/storage.py의 EXT_BY_CONTENT_TYPE과 동일 이유.
AVATAR_EXT_BY_CONTENT_TYPE = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}
AVATAR_CONTENT_TYPE_BY_EXT = {v: k for k, v in AVATAR_EXT_BY_CONTENT_TYPE.items()}
MAX_AVATAR_BYTES = 3 * 1024 * 1024


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


def _require_owner(profile: dict, workspace_id: str) -> None:
    if db.get_workspace_role(workspace_id, profile["id"]) != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="오너만 할 수 있음")


def _require_team_scope(profile: dict, workspace_id: str, team_id: str, allow_roles: set[str]) -> dict:
    member = db.get_workspace_member(workspace_id, profile["id"])
    if member is None or member.get("role") not in allow_roles or member.get("team_id") != team_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="이 팀에 대한 권한이 없음")
    return member


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
    # allow_web_search를 안 넘긴다(기본값 False) — 실제 외부 API를 호출하는 웹/DART
    # 검색은 "웹에서 찾아줘" 클릭 시(POST .../regenerate?allow_web_search=true)에만
    # 시도한다. 위키·원문 실패 후에도 agent.answer()가 일반 지식 폴백은 항상 자동으로
    # 시도하므로, 새로고침 없이 답이 오는 동작은 그대로 유지된다.
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
def regenerate_message(
    session_id: str,
    message_id: str,
    allow_web_search: bool = False,
    profile: dict = Depends(get_current_user),
):
    """다시 생성 — 같은 질문으로 Agent를 다시 호출해 답변 행을 그 자리에서 교체한다.
    (프론트가 새 Q&A를 아래에 덧붙이는 방식도 가능하지만, 그러면 새로고침 시 옛 답변이
    DB에 남아 있어 다시 나타난다 — 진짜 "다시 생성"이 되려면 in-place 교체가 필요하다.)

    allow_web_search=true는 1턴(위키+원문)에서 근거를 못 찾은 뒤, 사용자가 명시적으로
    "웹에서 찾아줘"를 요청했을 때 프론트가 이 엔드포인트를 다시 호출하며 붙이는
    쿼리 파라미터다 — 웹 검색 그라운딩(그리고 그것도 실패하면 일반 지식 폴백까지)을
    허용한다."""
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
    result = agent.answer(user_message["content"], history=history, allow_web_search=allow_web_search)

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

    # submit_no_answer도 이제 참고할 만큼만 읽은 문서를 citations로 선택적으로 실어
    # 보낼 수 있어서(불완전한 답변이지만 각주 클릭이 죽은 링크가 아니게 하기 위함),
    # "citations가 있으면 저장 가능"으로만 판단하면 근거 부족 응답도 위키에 저장될 수
    # 있다 — has_answer=False는 content가 NO_ANSWER_PREFIX로 시작하는 것으로 구분되므로
    # 별도로 걸러낸다.
    if message["content"].startswith(db.NO_ANSWER_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="근거가 부족해 확정된 답이 아닌 내용은 위키에 저장할 수 없음"
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
    # upsert_wiki_page()는 ignore_duplicates=True라 이미 있는 페이지의 title을 절대 안
    # 바꾼다 — 같은 메시지를 재저장하면 사이드바 제목이 최초 저장 시점 값에 영구히
    # 고정돼 이번에 새로 만든 LLM 제목과 어긋난다. 명시적으로 맞춰준다.
    update_wiki_page_title(page_id, title)
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

    rows = db.list_chat_session_participants(session_id, workspace_id)
    return [
        ParticipantOut(user_id=r["user_id"], display_name=r.get("display_name"), role=r.get("role"))
        for r in rows
    ]


@app.post(
    "/chat/sessions/{session_id}/participants",
    response_model=ParticipantOut,
    status_code=status.HTTP_201_CREATED,
)
def add_participant(
    session_id: str, body: AddParticipantRequest, profile: dict = Depends(get_current_user)
):
    """참여자 추가는 get_chat_session을 통과한(=이미 참여 중인) 사람 중, 워크스페이스
    역할이 게스트(viewer)가 아니면 할 수 있다 — frontend/src/constants/roles.js의
    canInviteToSession(owner/admin/editor만 허용, viewer 제외)과 서버 권한을 맞춘다.
    추가 대상은 같은 워크스페이스 소속이어야 한다 — 안 그러면 다른 워크스페이스
    사람을 끌어들일 수 있다."""
    workspace_id = _require_workspace(profile)
    session = db.get_chat_session(session_id, workspace_id, profile["id"])
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="세션을 찾을 수 없음")
    if session["visibility"] != "team":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="팀 공유 세션에서만 참여자를 관리할 수 있음")

    requester_role = db.get_workspace_role(workspace_id, profile["id"])
    if requester_role == "viewer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="게스트는 참여자를 초대할 수 없음")

    if db.get_default_workspace_id(body.user_id) != workspace_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="같은 워크스페이스 멤버만 추가할 수 있음")

    db.add_chat_session_participant(session_id, body.user_id)
    added_profile = db.get_profile(body.user_id)
    return ParticipantOut(
        user_id=body.user_id,
        display_name=added_profile.get("display_name") if added_profile else None,
        role=db.get_workspace_role(workspace_id, body.user_id),
    )


@app.delete(
    "/chat/sessions/{session_id}/participants/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_participant(session_id: str, user_id: str, profile: dict = Depends(get_current_user)):
    """본인 탈퇴는 항상 허용한다. 다른 사람을 빼는 건 세션 생성자이거나(기존 규칙),
    frontend/src/constants/roles.js의 canRemoveFromSession대로 워크스페이스 역할이
    owner/admin이면 가능하다 — 화면에서 관리자·팀장에게 보여주는 제외 버튼이
    실제로도 동작해야 하므로, 버튼을 가리는 역할 규칙과 서버 권한을 일치시킨다."""
    workspace_id = _require_workspace(profile)
    session = db.get_chat_session(session_id, workspace_id, profile["id"])
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="세션을 찾을 수 없음")
    if session["visibility"] != "team":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="팀 공유 세션에서만 참여자를 관리할 수 있음")

    is_self = user_id == profile["id"]
    is_creator = session["user_id"] == profile["id"]
    if not is_self and not is_creator:
        requester_role = db.get_workspace_role(workspace_id, profile["id"])
        if requester_role not in ("owner", "admin"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="다른 참여자는 세션 생성자이거나 관리자·팀장만 뺄 수 있음")

    db.remove_chat_session_participant(session_id, user_id)


@app.get("/workspace", response_model=WorkspaceOut)
def get_workspace(profile: dict = Depends(get_current_user)):
    """내 워크스페이스 이름 — 설정 화면 "소속 팀" 표시용. 워크스페이스 멤버 누구나 조회 가능."""
    workspace_id = _require_workspace(profile)
    workspace = db.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="워크스페이스를 찾을 수 없음")
    return WorkspaceOut(**workspace)


@app.get("/workspace/members", response_model=list[WorkspaceMemberOut])
def list_members(profile: dict = Depends(get_current_user)):
    """참여자 추가 UI가 "누구를 추가할지" 고를 목록으로 쓴다."""
    workspace_id = _require_workspace(profile)
    rows = db.list_workspace_members(workspace_id)
    return [
        WorkspaceMemberOut(
            user_id=r["user_id"], display_name=r.get("display_name"), email=r.get("email"), role=r.get("role"),
            has_avatar=r.get("has_avatar", False),
        )
        for r in rows
    ]


@app.delete("/workspace/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(user_id: str, profile: dict = Depends(get_current_user)):
    """워크스페이스에서 멤버를 방출한다 — 오너 전용, 본인은 방출 대상이 될 수 없다."""
    workspace_id = _require_workspace(profile)
    _require_owner(profile, workspace_id)
    if user_id == profile["id"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="오너 본인은 방출할 수 없음")

    db.remove_workspace_member(workspace_id, user_id)


@app.patch("/workspace/members/{user_id}/role", response_model=WorkspaceMemberOut)
def update_member_role(
    user_id: str, body: UpdateMemberRoleRequest, profile: dict = Depends(get_current_user)
):
    """멤버 역할을 팀장/팀원/게스트로 바꾼다 — 오너 전용, 본인 역할은 이 엔드포인트로
    바꿀 수 없다(실수로 자기 권한을 낮춰서 아무도 못 돌리는 상황 방지)."""
    workspace_id = _require_workspace(profile)
    _require_owner(profile, workspace_id)
    if user_id == profile["id"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="본인 역할은 이 방법으로 바꿀 수 없음")

    db.update_workspace_member_role(workspace_id, user_id, body.role)
    rows = db.list_workspace_members(workspace_id)
    updated = next((r for r in rows if r["user_id"] == user_id), None)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="워크스페이스 멤버가 아님")
    return WorkspaceMemberOut(
        user_id=updated["user_id"], display_name=updated.get("display_name"),
        email=updated.get("email"), role=updated.get("role"),
        has_avatar=updated.get("has_avatar", False),
    )


@app.get("/workspace/sessions", response_model=list[AdminSessionOut])
def list_admin_sessions(
    visibility: Literal["team", "private"] = Query(...), profile: dict = Depends(get_current_user)
):
    """오너가 워크스페이스의 모든 세션을 참여 여부/소유자 무관하게 열람한다."""
    workspace_id = _require_workspace(profile)
    _require_owner(profile, workspace_id)

    rows = db.list_workspace_sessions_for_admin(workspace_id, visibility)
    return [AdminSessionOut(**r) for r in rows]


@app.get("/workspace/sessions/{session_id}/messages", response_model=list[ChatMessageOut])
def get_admin_session_messages(session_id: str, profile: dict = Depends(get_current_user)):
    """오너가 세션 하나의 대화 내용을 읽기 전용으로 조회한다."""
    workspace_id = _require_workspace(profile)
    _require_owner(profile, workspace_id)

    session = db.get_chat_session_for_admin(session_id, workspace_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="세션을 찾을 수 없음")

    messages = db.list_chat_messages(session_id)
    return [_to_message_out(m) for m in messages]


@app.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(profile: dict = Depends(get_current_user)):
    """회원 탈퇴 — 본인 계정만 지울 수 있다(user_id를 URL/바디로 받지 않음).

    profiles/auth.users 둘 다 하드 삭제하지 않는다(이유는 db.py의 관련 함수 docstring
    참고) — 팀 공유 대화 등 다른 사람이 보는 콘텐츠가 이 사람의 탈퇴로 함께 사라지지
    않게 하기 위함이다. 대신 profiles.deleted_at을 남기고(get_current_user가 이후
    모든 요청을 막음) auth 사용자는 영구 ban을 걸어(ban_auth_user) 애초에 재로그인
    자체가 안 되게 한다.

    auth 사용자 ban(ban_auth_user)이 실패해도 요청 자체를 실패로 만들지 않는다 —
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
        db.ban_auth_user(user_id)
    except Exception:
        logger.exception("account_deletion_auth_user_ban_failed", extra={"user_id": user_id})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/teams", response_model=TeamOut)
def create_team(body: CreateTeamRequest, profile: dict = Depends(get_current_user)):
    """팀 생성 — 관리자(오너) 전용."""
    workspace_id = _require_workspace(profile)
    _require_owner(profile, workspace_id)
    try:
        team = db.create_team(workspace_id, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TeamOut(id=team["id"], name=team["name"], member_count=0)


@app.delete("/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team(team_id: str, profile: dict = Depends(get_current_user)):
    """팀 삭제 — 관리자(오너) 전용. 소속 인원이 있으면 400."""
    workspace_id = _require_workspace(profile)
    _require_owner(profile, workspace_id)
    try:
        db.delete_team(team_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.get("/teams", response_model=list[TeamOut])
def list_teams(profile: dict = Depends(get_current_user)):
    """팀 목록 + 인원수 — 워크스페이스 멤버 누구나 열람 가능."""
    workspace_id = _require_workspace(profile)
    rows = db.list_teams(workspace_id)
    return [TeamOut(**r) for r in rows]


@app.get("/teams/{team_id}/members", response_model=list[TeamMemberOut])
def list_team_members(team_id: str, profile: dict = Depends(get_current_user)):
    """팀별 멤버 명단 — 워크스페이스 멤버 누구나 열람 가능."""
    _require_workspace(profile)
    rows = db.list_team_members(team_id)
    return [
        TeamMemberOut(
            user_id=r["user_id"], display_name=r.get("display_name"), role=r.get("role"),
            has_avatar=r.get("has_avatar", False),
        )
        for r in rows
    ]


@app.get("/admin/users", response_model=list[AdminUserOut])
def list_all_users(profile: dict = Depends(get_current_user)):
    """전체 사용자 + 소속 팀 — 관리자(오너) 전용."""
    workspace_id = _require_workspace(profile)
    _require_owner(profile, workspace_id)
    rows = db.list_workspace_users_with_team(workspace_id)
    return [
        AdminUserOut(
            user_id=r["user_id"], display_name=r.get("display_name"), role=r.get("role"),
            team_id=r.get("team_id"), team_name=r.get("team_name"),
            has_avatar=r.get("has_avatar", False),
        )
        for r in rows
    ]


@app.patch("/admin/users/{user_id}/team", status_code=status.HTTP_204_NO_CONTENT)
def assign_user_team(user_id: str, body: AssignTeamRequest, profile: dict = Depends(get_current_user)):
    """사용자를 임의 팀에 배치/제외(team_id=null) — 관리자(오너) 전용, 자기 팀 범위 제한 없음."""
    workspace_id = _require_workspace(profile)
    _require_owner(profile, workspace_id)
    db.move_member_to_team(workspace_id, user_id, body.team_id)


@app.post("/teams/{team_id}/members", status_code=status.HTTP_204_NO_CONTENT)
def invite_team_member(team_id: str, body: AddParticipantRequest, profile: dict = Depends(get_current_user)):
    """팀원 초대 — 팀원/팀장 모두 자기 팀에만 가능. 대상은 미배치 사용자만(이미 배치된
    사용자는 팀장의 영입 엔드포인트를 써야 함)."""
    workspace_id = _require_workspace(profile)
    _require_team_scope(profile, workspace_id, team_id, {"admin", "editor"})

    target = db.get_workspace_member(workspace_id, body.user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="워크스페이스 멤버가 아님")
    if target.get("team_id") is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이미 배치된 사용자입니다. 팀장만 영입할 수 있음",
        )

    db.move_member_to_team(workspace_id, body.user_id, team_id)


@app.post("/teams/{team_id}/members/recruit", status_code=status.HTTP_204_NO_CONTENT)
def recruit_team_member(team_id: str, body: AddParticipantRequest, profile: dict = Depends(get_current_user)):
    """팀원 영입 — 팀장 전용, 자기 팀만. 대상이 다른 팀 소속이어도 데려올 수 있다."""
    workspace_id = _require_workspace(profile)
    _require_team_scope(profile, workspace_id, team_id, {"admin"})

    target = db.get_workspace_member(workspace_id, body.user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="워크스페이스 멤버가 아님")
    if target.get("team_id") == team_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="이미 같은 팀임")

    db.move_member_to_team(workspace_id, body.user_id, team_id)


@app.delete("/teams/{team_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_team_member(team_id: str, user_id: str, profile: dict = Depends(get_current_user)):
    """팀원 제외(팀에서만, 워크스페이스 방출 아님) — 팀장 전용, 자기 팀만. 본인은 대상 불가."""
    workspace_id = _require_workspace(profile)
    _require_team_scope(profile, workspace_id, team_id, {"admin"})
    if user_id == profile["id"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="본인은 제외할 수 없음")

    target = db.get_workspace_member(workspace_id, user_id)
    if target is None or target.get("team_id") != team_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="이 팀 소속이 아님")

    db.move_member_to_team(workspace_id, user_id, None)


def _to_profile_out(profile: dict) -> ProfileOut:
    return ProfileOut(
        id=profile["id"],
        display_name=profile.get("display_name"),
        has_avatar=bool(profile.get("avatar_object_key")),
    )


@app.get("/profile", response_model=ProfileOut)
def get_my_profile(profile: dict = Depends(get_current_user)):
    return _to_profile_out(profile)


@app.patch("/profile", response_model=ProfileOut)
def update_my_profile(body: UpdateProfileRequest, profile: dict = Depends(get_current_user)):
    updated = db.update_profile_display_name(profile["id"], body.display_name.strip())
    return _to_profile_out(updated)


def _avatar_response(object_key: Optional[str]) -> Response:
    if not object_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="프로필 사진이 없음")

    data = db.download_avatar_object(object_key)
    ext = object_key.rsplit(".", 1)[-1]
    content_type = AVATAR_CONTENT_TYPE_BY_EXT.get(ext, "application/octet-stream")
    return Response(content=data, media_type=content_type)


@app.get("/profile/avatar")
def get_my_avatar(profile: dict = Depends(get_current_user)):
    """설정 화면이 apiFetchBlob으로 인증 헤더와 함께 호출한다(다른 버킷들과 동일하게
    Storage URL을 프론트에 직접 넘기지 않음)."""
    return _avatar_response(profile.get("avatar_object_key"))


@app.get("/workspace/members/{user_id}/avatar")
def get_member_avatar(user_id: str, profile: dict = Depends(get_current_user)):
    """상단바·팀 로스터가 다른 워크스페이스 멤버의 프로필 사진을 보여줄 때 쓴다.
    GET /profile/avatar와 달리 대상이 호출자 본인이 아니어도 되지만, 같은
    워크스페이스 소속이어야 한다(db.get_member_avatar_object_key가 확인)."""
    workspace_id = _require_workspace(profile)
    object_key = db.get_member_avatar_object_key(workspace_id, user_id)
    return _avatar_response(object_key)


@app.post("/profile/avatar", response_model=ProfileOut)
async def upload_my_avatar(file: UploadFile = File(...), profile: dict = Depends(get_current_user)):
    ext = AVATAR_EXT_BY_CONTENT_TYPE.get(file.content_type)
    if ext is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="지원하지 않는 이미지 형식(jpeg/png/webp/gif만 가능)",
        )

    data = await file.read()
    if len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="이미지 용량이 너무 큼(최대 3MB)")

    object_key = f"{profile['id']}/avatar.{ext}"
    old_object_key = profile.get("avatar_object_key")
    if old_object_key and old_object_key != object_key:
        try:
            db.delete_avatar_object(old_object_key)
        except Exception:
            logger.exception("avatar_old_object_delete_failed", extra={"user_id": profile["id"]})

    db.upload_avatar_object(object_key, data, file.content_type)
    db.set_profile_avatar_object_key(profile["id"], object_key)

    return ProfileOut(id=profile["id"], display_name=profile.get("display_name"), has_avatar=True)


@app.delete("/profile/avatar", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_avatar(profile: dict = Depends(get_current_user)):
    object_key = profile.get("avatar_object_key")
    if object_key:
        db.delete_avatar_object(object_key)
        db.set_profile_avatar_object_key(profile["id"], None)

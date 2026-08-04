"""
Agent·API 담당 FastAPI 서버.
엔드포인트: 채팅 세션 생성/조회, 메시지 전송(Agent 호출 포함), 메시지 이력 조회.

실행:
    uvicorn src.api.main:app --reload
"""
from __future__ import annotations

from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .auth import get_current_user
from .schemas import (
    ChatMessageOut,
    ChatSessionOut,
    CitationOut,
    CreateSessionRequest,
    SaveToWikiResponse,
    SendMessageRequest,
    SendMessageResponse,
)
from .settings_router import router as settings_router
from .wiki_router import router as wiki_router
from ..agent.core import WikiAgent
from ..agent.wiki_tools import WikiTools
from ..wiki.interface import (
    WikiDraftInput,
    WikiSourceInput,
    create_wiki_version,
    publish_wiki_version,
    record_wiki_validation,
    review_wiki_version,
    upsert_wiki_page,
)

app = FastAPI(title="myWiki Agent API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://mywiki.pe.kr", "https://www.mywiki.pe.kr"],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(wiki_router)
app.include_router(settings_router)


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

    user_message = db.save_user_message(session_id, body.content)

    # 이전 대화 이력을 Agent에게 넘겨서 멀티턴 맥락을 유지한다.
    history = [
        {"role": "user" if m["role"] == "user" else "assistant", "content": m["content"]}
        for m in db.list_chat_messages(session_id)
        if m["id"] != user_message["id"]
    ]

    wiki_tools = WikiTools(workspace_id=workspace_id)
    agent = WikiAgent(wiki_tools)
    result = agent.answer(body.content, history=history)

    assistant_message = db.save_agent_message(session_id, result)

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
def share_message_to_team(session_id: str, message_id: str, profile: dict = Depends(get_current_user)):
    workspace_id = _require_workspace(profile)
    message = _get_owned_message(session_id, message_id, workspace_id, profile["id"])

    user_message = db.get_preceding_user_message(session_id, message["created_at"])
    if user_message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="짝이 되는 질문 메시지를 찾을 수 없음")

    team_session = db.get_or_create_team_session(workspace_id, profile["id"])
    db.copy_chat_message(team_session["id"], user_message)
    copied_assistant = db.copy_chat_message(team_session["id"], message)

    citations = db.list_message_citations(message_id)
    db.copy_message_citations(copied_assistant["id"], citations)

    return _to_message_out(copied_assistant)


@app.post("/chat/sessions/{session_id}/messages/{message_id}/save-to-wiki", response_model=SaveToWikiResponse)
def save_message_to_wiki(session_id: str, message_id: str, profile: dict = Depends(get_current_user)):
    workspace_id = _require_workspace(profile)
    message = _get_owned_message(session_id, message_id, workspace_id, profile["id"])

    citations = db.list_message_citations(message_id)
    if not citations:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="근거(citation)가 없는 답변은 위키에 저장할 수 없음"
        )

    user_message = db.get_preceding_user_message(session_id, message["created_at"])
    title = user_message["content"][:80] if user_message else "채팅에서 저장된 답변"
    slug = f"chat-{message_id[:8]}"

    page_id = upsert_wiki_page(workspace_id, slug, title, "issue")
    draft = WikiDraftInput(
        workspace_id=workspace_id,
        slug=slug,
        title=title,
        page_type="issue",
        markdown=message["content"],
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


@app.get("/health")
def health():
    return {"status": "ok"}

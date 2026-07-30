"""
Agent·API 담당 FastAPI 서버.
엔드포인트: 채팅 세션 생성/조회, 메시지 전송(Agent 호출 포함), 메시지 이력 조회.

실행:
    uvicorn src.api.main:app --reload
"""
from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, status

from . import db
from .auth import get_current_user
from .schemas import (
    ChatMessageOut,
    ChatSessionOut,
    CitationOut,
    CreateSessionRequest,
    SendMessageRequest,
    SendMessageResponse,
)
from ..agent.core import WikiAgent
from ..agent.wiki_tools import WikiTools

app = FastAPI(title="myWiki Agent API")


def _require_workspace(profile: dict) -> str:
    workspace_id = db.get_default_workspace_id(profile["id"])
    if not workspace_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="workspace 소속이 없음")
    return workspace_id


def _to_message_out(message: dict) -> ChatMessageOut:
    citations = db.list_message_citations(message["id"]) if message["role"] == "assistant" else []
    return ChatMessageOut(**message, citations=[CitationOut(**c) for c in citations])


@app.post("/chat/sessions", response_model=ChatSessionOut)
def create_session(body: CreateSessionRequest, profile: dict = Depends(get_current_user)):
    workspace_id = _require_workspace(profile)
    session = db.create_chat_session(workspace_id, profile["id"], body.title)
    return ChatSessionOut(**session)


@app.get("/chat/sessions/{session_id}/messages", response_model=list[ChatMessageOut])
def get_messages(session_id: str, profile: dict = Depends(get_current_user)):
    workspace_id = _require_workspace(profile)
    session = db.get_chat_session(session_id, workspace_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="세션을 찾을 수 없음")

    messages = db.list_chat_messages(session_id)
    return [_to_message_out(m) for m in messages]


@app.post("/chat/sessions/{session_id}/messages", response_model=SendMessageResponse)
def send_message(
    session_id: str, body: SendMessageRequest, profile: dict = Depends(get_current_user)
):
    workspace_id = _require_workspace(profile)
    session = db.get_chat_session(session_id, workspace_id)
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


@app.get("/health")
def health():
    return {"status": "ok"}

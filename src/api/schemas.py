from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class CreateSessionRequest(BaseModel):
    title: Optional[str] = None


class ChatSessionOut(BaseModel):
    id: str
    workspace_id: str
    user_id: str
    title: Optional[str]
    created_at: datetime
    updated_at: datetime


class SendMessageRequest(BaseModel):
    content: str


class CitationOut(BaseModel):
    id: str
    document_version_id: str
    quoted_text: Optional[str]
    relevance_score: Optional[float]
    citation_order: Optional[int]


class ChatMessageOut(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    model_name: Optional[str] = None
    prompt_version: Optional[str] = None
    created_at: datetime
    citations: list[CitationOut] = []


class SendMessageResponse(BaseModel):
    user_message: ChatMessageOut
    assistant_message: ChatMessageOut
    has_answer: bool

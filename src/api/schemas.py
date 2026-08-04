from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class CreateSessionRequest(BaseModel):
    title: Optional[str] = None
    visibility: Literal["private", "team"] = "private"


class ChatSessionOut(BaseModel):
    id: str
    workspace_id: str
    user_id: str
    title: Optional[str]
    visibility: str
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
    source_url: Optional[str] = None


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


class SaveToWikiResponse(BaseModel):
    page_id: str
    version_id: str
    slug: str


# ---------------------------------------------------------------------------
# Wiki 조회 — 프론트엔드 WikiPage 전용 (src/wiki/interface.py DTO를 그대로 반영)
# ---------------------------------------------------------------------------

class WikiPageSummaryOut(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    slug: str
    title: str
    page_type: str
    status: str
    parent_page_id: Optional[str]
    published_at: Optional[str]


class WikiVersionSummaryOut(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    version_no: int
    change_summary: Optional[str]
    created_at: str


class WikiSourceOut(BaseModel):
    model_config = {"from_attributes": True}

    document_version_id: str
    citation_order: Optional[int]
    claim_text: Optional[str]
    support_type: Optional[str]
    source_start_line: Optional[int]
    source_end_line: Optional[int]
    document_title: Optional[str] = None
    source_name: Optional[str] = None
    canonical_url: Optional[str] = None
    published_at: Optional[str] = None
    reliability_score: Optional[int] = None


class WikiPageContentOut(BaseModel):
    model_config = {"from_attributes": True}

    page_id: str
    slug: str
    title: str
    page_type: str
    published_at: Optional[str]
    version_id: str
    version_no: int
    markdown: str
    change_summary: Optional[str]
    confidence_score: Optional[float]
    validation_status: str
    review_status: str
    generated_by: str
    generator_model: Optional[str]
    created_at: str
    sources: list[WikiSourceOut]
    versions: list[WikiVersionSummaryOut]


# ---------------------------------------------------------------------------
# 워크스페이스 설정 — GET/PATCH /settings 전용
# ---------------------------------------------------------------------------

class WorkspaceSettingsOut(BaseModel):
    model_config = {"from_attributes": True}

    workspace_id: str
    wiki_update_cycle_minutes: int
    data_refresh_cycle_minutes: int
    chat_retention_days: Optional[int]
    last_wiki_refresh_at: Optional[str]
    last_data_refresh_at: Optional[str]
    updated_at: str


class UpdateWorkspaceSettingsRequest(BaseModel):
    wiki_update_cycle_minutes: Optional[Literal[30, 60, 180, 360, 720, 1440]] = None
    data_refresh_cycle_minutes: Optional[Literal[30, 60, 120, 180, 360, 720, 1440]] = None
    chat_retention_days: Optional[int] = None

from __future__ import annotations

from datetime import date as dt_date
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    title: Optional[str] = None
    visibility: Literal["private", "team"] = "private"


class ChatSessionOut(BaseModel):
    id: str
    workspace_id: str
    user_id: str
    title: Optional[str]
    visibility: str
    archived_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class SendMessageRequest(BaseModel):
    content: str


class RenameSessionRequest(BaseModel):
    title: str


class ShareToTeamRequest(BaseModel):
    target_session_id: Optional[str] = None


class ParticipantOut(BaseModel):
    user_id: str
    display_name: Optional[str] = None


class AddParticipantRequest(BaseModel):
    user_id: str


class WorkspaceMemberOut(BaseModel):
    user_id: str
    display_name: Optional[str] = None
    email: Optional[str] = None


class CitationOut(BaseModel):
    id: str
    document_version_id: str
    quoted_text: Optional[str]
    relevance_score: Optional[float]
    citation_order: Optional[int]
    source_url: Optional[str] = None
    document_title: Optional[str] = None
    source_name: Optional[str] = None
    published_at: Optional[str] = None
    reliability_score: Optional[int] = None


class ChatMessageOut(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    model_name: Optional[str] = None
    prompt_version: Optional[str] = None
    is_llm_fallback: bool = False
    author_name: Optional[str] = None
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
# Wiki ì¡°íšŒ ???„ë¡ ?¸ì—”??WikiPage ?„ìš© (src/wiki/interface.py DTOë¥?ê·¸ë?ë¡?ë°˜ì˜)
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


class WikiRelatedPageOut(BaseModel):
    model_config = {"from_attributes": True}

    page_id: str
    slug: str
    title: str
    page_type: str
    shared_source_count: int


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
    related_pages: list[WikiRelatedPageOut] = []


# ---------------------------------------------------------------------------
# ?Œí¬?¤í˜?´ìŠ¤ ?¤ì • ??GET/PATCH /settings ?„ìš©
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


# ---------------------------------------------------------------------------
# ë©”ì¸ ?€?œë³´??KPI ??GET /dashboard/summary ?„ìš©
# ---------------------------------------------------------------------------

class DashboardSummaryOut(BaseModel):
    model_config = {"from_attributes": True}

    collected_docs: int
    collected_docs_today: int
    generated_reports: int
    wiki_docs: int
    wiki_docs_new_today: int
    avg_reliability_label: str


# ---------------------------------------------------------------------------
# ?¼ë³„ ?˜ì§‘Â·ì±„íƒ ì¶”ì´ ??GET /dashboard/trend ?„ìš©
#
# DashboardSummaryOut??ë°°ì—´???¼ì›Œ?£ì? ?Šê³  ?°ë¡œ ëºë‹¤. ?€ìª½ì? ?¤ì¹¼??6ê°œë¡œ
# ?„ë¡ ?¸ì? ë°°ì„ ???ë‚œ ê³„ì•½?´ë¼ ëª¨ì–‘???”ë“¤ì§€ ?ŠëŠ”??
# ---------------------------------------------------------------------------

class TrendDayOut(BaseModel):
    model_config = {"from_attributes": True}

    # KST ê¸°ì? ? ì§œ. 'YYYY-MM-DD'ë¡?ì§ë ¬?”ëœ??
    date: dt_date
    collected: int
    # ê·¸ë‚  ?˜ì§‘ë¶?ì¤???‚¹???ë‚œ ë¬¸ì„œ ?? ë¶„ì„???˜ì§‘ë³´ë‹¤ ??²Œ ?Œì•„??
    # ?¤ëŠ˜ ê°’ì? ê±°ì˜ 0?¼ë¡œ ?˜ì˜¤??ê²??•ìƒ?´ë‹¤
    adopted: int
    # collected???˜ì§‘ ê²½ë¡œë³??´ì—­. ê·?ë°–ì˜ source_type???ê¸°ë©?
    # news + disclosure < collected ê°€ ?????ˆë‹¤
    news: int
    disclosure: int


class DashboardTrendOut(BaseModel):
    model_config = {"from_attributes": True}

    days: list[TrendDayOut]


# ---------------------------------------------------------------------------
# ì¹´í…Œê³ ë¦¬ ?„í™© ??GET /categories/stats ?„ìš©
# ---------------------------------------------------------------------------

class CategoryKeywordOut(BaseModel):
    model_config = {"from_attributes": True}

    word: str
    count: int


class CategoryDocumentOut(BaseModel):
    model_config = {"from_attributes": True}

    title: str
    quote: str
    source_label: str
    source_url: str
    # ?ë??œê°('1?œê°„ ??)?€ ?„ë¡ ?¸ê? ë§Œë“ ?? ?¬ê¸°??ISO ë¬¸ì??ê·¸ë?ë¡??´ë³´?¸ë‹¤.
    published_at: Optional[str]


class CategoryStatOut(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    name: str
    count: int
    top_issue: str
    tags: list[str]
    # ?„ë¡ ??CategoryCardê°€ ????ê°’ë§Œ ?¼ë²¨Â·?‰ìƒ?¼ë¡œ ë³€?˜í•œ?? ?¤ë¥¸ ê°’ì´ ê°€ë©?
    # ì¹´ë“œ??"? ë¢°??: "ë§??¨ê³  ê°’ì´ ë¹ ì?ë¯€ë¡??¬ê¸°??ë§‰ëŠ”??
    level: Literal["high", "mid", "low"]
    keywords: list[CategoryKeywordOut] = []
    recent_documents: list[CategoryDocumentOut] = []


class CategoryStatsOut(BaseModel):
    model_config = {"from_attributes": True}

    total_documents: int
    categories: list[CategoryStatOut]


# ---------------------------------------------------------------------------
# ?„í‚¤ ë°œí–‰ ë¸Œë¼?°ì? ?¸ì‹œ ?Œë¦¼ ??POST/DELETE /notifications/subscribe ?„ìš©
# ---------------------------------------------------------------------------

class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class SubscribeRequest(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeys


# ---------------------------------------------------------------------------
# Daily report - GET/POST /reports/daily
# ---------------------------------------------------------------------------

class DailyReportCitationOut(BaseModel):
    id: str
    section_id: str
    document_version_id: str
    source_start_line: Optional[int] = None
    source_end_line: Optional[int] = None
    quoted_text: Optional[str] = None
    relevance_score: Optional[float] = None
    citation_order: Optional[int] = None
    document_title: Optional[str] = None
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    published_at: Optional[str] = None


class DailyReportSectionOut(BaseModel):
    id: str
    report_id: str
    issue_key: str
    section_order: int
    title: str
    content: dict | str | None = None
    status: str
    model_name: Optional[str] = None
    prompt_version: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    citations: list[DailyReportCitationOut] = []


class DailyReportOut(BaseModel):
    report_id: str
    workspace_id: str
    report_key: str
    version: int
    title: str
    report_type: str
    status: str
    date: str
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    sections: list[DailyReportSectionOut] = []


class DailyReportGenerateRequest(BaseModel):
    date: dt_date
    max_sections: int = Field(default=15, ge=1)
    language: str = "ko"
    formats: Optional[list[str]] = None


class DailyReportArtifactOut(BaseModel):
    artifact_id: str
    report_id: str
    artifact_type: str
    object_key: str
    version: int
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    created_at: Optional[str] = None


class DailyReportGenerateResponse(BaseModel):
    report_id: str
    workspace_id: str
    report_key: str
    version: int
    title: Optional[str] = None
    report_type: str
    status: str
    date: str
    artifact_id: str
    artifact_type: str
    artifact_object_key: str
    artifacts: list[DailyReportArtifactOut]

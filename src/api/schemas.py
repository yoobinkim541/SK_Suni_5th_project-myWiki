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
# Wiki 조회 — 프론트엔드 WikiPage 전용 (src/wiki/interface.py DTO를 그대로 반영)
# ---------------------------------------------------------------------------

class WikiKeywordCatalogOut(BaseModel):
    word: str
    category: str


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


# ---------------------------------------------------------------------------
# 메인 대시보드 KPI — GET /dashboard/summary 전용
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
# 일별 수집·채택 추이 — GET /dashboard/trend 전용
#
# DashboardSummaryOut에 배열을 끼워넣지 않고 따로 뺐다. 저쪽은 스칼라 6개로
# 프론트와 배선이 끝난 계약이라 모양을 흔들지 않는다.
# ---------------------------------------------------------------------------

class TrendDayOut(BaseModel):
    model_config = {"from_attributes": True}

    # KST 기준 날짜. 'YYYY-MM-DD'로 직렬화된다
    date: dt_date
    collected: int
    # 그날 수집분 중 랭킹이 끝난 문서 수. 분석이 수집보다 늦게 돌아서
    # 오늘 값은 거의 0으로 나오는 게 정상이다
    adopted: int
    # collected의 수집 경로별 내역. 그 밖의 source_type이 생기면
    # news + disclosure < collected 가 될 수 있다
    news: int
    disclosure: int


class DashboardTrendOut(BaseModel):
    model_config = {"from_attributes": True}

    days: list[TrendDayOut]


# ---------------------------------------------------------------------------
# 카테고리 현황 — GET /categories/stats 전용
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
    # 상대시각('1시간 전')은 프론트가 만든다. 여기선 ISO 문자열 그대로 내보낸다.
    published_at: Optional[str]


class CategoryStatOut(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    name: str
    count: int
    top_issue: str
    tags: list[str]
    # 프론트 CategoryCard가 이 세 값만 라벨·색상으로 변환한다. 다른 값이 가면
    # 카드에 "신뢰도 : "만 남고 값이 빠지므로 여기서 막는다.
    level: Literal["high", "mid", "low"]
    keywords: list[CategoryKeywordOut] = []
    recent_documents: list[CategoryDocumentOut] = []


class CategoryStatsOut(BaseModel):
    model_config = {"from_attributes": True}

    total_documents: int
    categories: list[CategoryStatOut]


# ---------------------------------------------------------------------------
# 위키 발행 브라우저 푸시 알림 — POST/DELETE /notifications/subscribe 전용
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

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

from ..analysis.importance_models import ImpactDirection, TimeHorizon
from ..analysis.models import Category


class ReportType(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    COMPANY = "company"
    TECHNOLOGY = "technology"
    ISSUE_BRIEFING = "issue_briefing"


class ReportStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    RESEARCHING = "researching"
    DRAFTING = "drafting"
    VERIFYING = "verifying"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReportSectionStatus(str, Enum):
    PENDING = "pending"
    RESEARCHING = "researching"
    DRAFTING = "drafting"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"


class ArtifactType(str, Enum):
    MARKDOWN = "markdown"
    PDF = "pdf"
    PPTX = "pptx"
    DOCX = "docx"


class ReportGenerationRequest(BaseModel):
    workspace_id: str
    report_date: date
    max_sections: int = Field(default=15, ge=1)
    language: str = "ko"
    report_type: ReportType = ReportType.DAILY

    @field_validator("workspace_id", "language")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("required text fields must not be empty.")
        return value.strip()


class ReportCandidate(BaseModel):
    analysis_result_id: str
    workspace_id: str
    document_id: str
    document_version_id: str
    category: Category
    title: str
    summary: str | None = None
    reliability_score: int | None = None
    importance_score: int | None = None
    ranking_score: Decimal | None = None
    source_name: str | None = None
    source_type: str | None = None  # 'disclosure'면 selector.py가 근거 개수 요건을 면제한다.
    canonical_url: str | None = None
    published_at: datetime | None = None
    impact_direction: ImpactDirection | None = None
    time_horizon: TimeHorizon | None = None

    @field_validator("analysis_result_id", "workspace_id", "document_id", "document_version_id", "title")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("required identifier fields must not be empty.")
        return value.strip()

    @field_validator("summary", "source_name", "source_type", "canonical_url", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("published_at", mode="before")
    @classmethod
    def parse_datetime(cls, value: object) -> datetime | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    @field_validator("ranking_score", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal | None:
        if value is None or value == "":
            return None
        return Decimal(str(value))


class IssueGroup(BaseModel):
    issue_key: str
    category: Category
    candidates: list[ReportCandidate] = Field(min_length=1)
    representative_candidate: ReportCandidate | None = None
    representative_analysis_result_id: str | None = None

    @field_validator("issue_key")
    @classmethod
    def validate_issue_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("issue_key must not be empty.")
        return value.strip()

    @model_validator(mode="after")
    def validate_representative(self) -> "IssueGroup":
        candidate_ids = {candidate.analysis_result_id for candidate in self.candidates}
        if self.representative_candidate is not None:
            if self.representative_candidate.analysis_result_id not in candidate_ids:
                raise ValueError("representative_candidate must exist in candidates.")
            if self.representative_analysis_result_id is None:
                self.representative_analysis_result_id = self.representative_candidate.analysis_result_id
        if self.representative_analysis_result_id is not None and self.representative_analysis_result_id not in candidate_ids:
            raise ValueError("representative_analysis_result_id must exist in candidates.")
        if self.representative_candidate is None and self.representative_analysis_result_id is None:
            self.representative_analysis_result_id = self.candidates[0].analysis_result_id
        return self


class WikiContext(BaseModel):
    wiki_page_id: str
    wiki_version_id: str | None = None
    title: str
    content: str | None = None
    similarity_score: float | None = Field(default=None, ge=0.0, le=1.0)
    updated_at: datetime | None = None
    source_document_version_ids: list[str] = Field(default_factory=list)
    wiki_chunk_id: str | None = None

    @field_validator("wiki_page_id", "title")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("wiki_page_id and title must not be empty.")
        return value.strip()

    @field_validator("wiki_version_id", "content", "wiki_chunk_id", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("updated_at", mode="before")
    @classmethod
    def parse_wiki_datetime(cls, value: object) -> datetime | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


class EnrichedIssueGroup(BaseModel):
    issue_group: IssueGroup
    wiki_contexts: list[WikiContext] = Field(default_factory=list)


class ReportCitationDraft(BaseModel):
    analysis_result_id: str
    document_version_id: str
    citation_order: int = Field(ge=1)
    citation_role: str | None = None
    evidence_text: str | None = None
    source_start_line: int | None = None
    source_end_line: int | None = None
    relevance_score: float | None = Field(default=None, ge=0.0, le=1.0)
    # 표시용 메타데이터 — composer.py가 ComposerNewsSource(ReportCandidate 유래)에서
    # 채워 넣는다. 렌더러(markdown_renderer.py/pdf_renderer.py)가 document_version_id
    # 원문을 그대로 노출하지 않고 이 필드로 "제목 · 매체명 · 날짜"를 표시하는 데 쓴다.
    document_title: str | None = None
    source_name: str | None = None
    published_at: str | None = None

    @field_validator("analysis_result_id", "document_version_id")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("citation identifiers must not be empty.")
        return value.strip()

    @field_validator("citation_role", "evidence_text", "document_title", "source_name", "published_at", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class ReportWikiReferenceDraft(BaseModel):
    wiki_page_id: str
    wiki_version_id: str | None = None
    reference_order: int = Field(ge=1)
    reference_role: str | None = None
    similarity_score: float | None = Field(default=None, ge=0.0, le=1.0)
    wiki_chunk_id: str | None = None
    # 표시용 — composer.py가 ComposerWikiSource(WikiContext 유래)에서 채워 넣는다.
    # 렌더러가 wiki_page_id 원문 대신 이 제목을 표시하는 데 쓴다.
    wiki_title: str | None = None

    @field_validator("wiki_page_id")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("wiki_page_id must not be empty.")
        return value.strip()

    @field_validator("wiki_version_id", "reference_role", "wiki_chunk_id", "wiki_title", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class ReportSectionDraft(BaseModel):
    issue_key: str
    representative_analysis_result_id: str
    category: Category
    importance_score: int | None = Field(default=None, ge=0, le=100)
    impact_direction: ImpactDirection | None = None
    time_horizon: TimeHorizon | None = None
    title: str
    current_summary: str | None = None
    key_facts: list[str] = Field(default_factory=list)
    historical_context: list[str] = Field(default_factory=list)
    implications: list[str] = Field(default_factory=list)
    watch_points: list[str] = Field(default_factory=list)
    news_citations: list[ReportCitationDraft] = Field(default_factory=list)
    wiki_references: list[ReportWikiReferenceDraft] = Field(default_factory=list)
    status: ReportSectionStatus = ReportSectionStatus.DRAFTING

    @field_validator("issue_key", "representative_analysis_result_id", "title")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("required section fields must not be empty.")
        return value.strip()

    @field_validator("current_summary", mode="before")
    @classmethod
    def normalize_summary(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("key_facts", "historical_context", "implications", "watch_points", mode="before")
    @classmethod
    def normalize_string_lists(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("list fields must be lists.")
        normalized: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                normalized.append(text)
        return normalized


class ReportExecutiveSummary(BaseModel):
    issue_key: str
    title: str
    summary: str
    importance_score: int | None = Field(default=None, ge=0, le=100)
    impact_direction: ImpactDirection | None = None
    time_horizon: TimeHorizon | None = None

    @field_validator("issue_key", "title", "summary")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("executive summary fields must not be empty.")
        return value.strip()


class ReportIssueSummaryRow(BaseModel):
    issue_key: str
    category: Category
    title: str
    importance_score: int | None = Field(default=None, ge=0, le=100)
    impact_direction: ImpactDirection | None = None
    time_horizon: TimeHorizon | None = None

    @field_validator("issue_key", "title")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("issue summary row fields must not be empty.")
        return value.strip()


class ReportCategoryGroup(BaseModel):
    category: Category
    sections: list[ReportSectionDraft] = Field(default_factory=list)


class ReportOverallImplications(BaseModel):
    opportunities: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    monitoring_points: list[str] = Field(default_factory=list)

    @field_validator("opportunities", "risks", "monitoring_points", mode="before")
    @classmethod
    def normalize_string_lists(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("overall implication fields must be lists.")
        normalized: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                normalized.append(text)
        return normalized


class ReportNewsSource(BaseModel):
    document_version_id: str
    document_title: str | None = None
    source_name: str | None = None
    published_at: str | None = None

    @field_validator("document_version_id")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("document_version_id must not be empty.")
        return value.strip()

    @field_validator("document_title", "source_name", "published_at", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class ReportWikiSource(BaseModel):
    wiki_page_id: str
    wiki_version_id: str
    wiki_title: str | None = None

    @field_validator("wiki_page_id", "wiki_version_id")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("wiki source identifiers must not be empty.")
        return value.strip()

    @field_validator("wiki_title", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class GeneratedReport(BaseModel):
    report_id: str | None = None
    workspace_id: str
    report_date: date
    report_type: ReportType
    title: str | None = None
    language: str | None = None
    version: int | None = Field(default=None, ge=1)
    status: ReportStatus
    executive_summaries: list[ReportExecutiveSummary] = Field(default_factory=list)
    issue_summary_rows: list[ReportIssueSummaryRow] = Field(default_factory=list)
    sections: list[ReportSectionDraft] = Field(default_factory=list)
    category_groups: list[ReportCategoryGroup] = Field(default_factory=list)
    overall_implications: ReportOverallImplications | None = None
    news_sources: list[ReportNewsSource] = Field(default_factory=list)
    wiki_sources: list[ReportWikiSource] = Field(default_factory=list)
    artifact_id: str | None = None
    artifact_type: ArtifactType | None = None
    artifact_object_key: str | None = None
    created_at: datetime | None = None
    generated_at: datetime | None = None

    @field_validator("report_id", "workspace_id", "title", "language", "artifact_id", "artifact_object_key", mode="before")
    @classmethod
    def normalize_optional_identifiers(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("created_at", "generated_at", mode="before")
    @classmethod
    def parse_created_at(cls, value: object) -> datetime | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

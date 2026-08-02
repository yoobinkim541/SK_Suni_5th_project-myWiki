from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .importance_models import KeyNumber, SummaryEvidenceRef
from .importance_models import ImportanceLevel
from .reliability_models import ReliabilityLevel
from .models import Category

RANKING_FORMULA_VERSION = "ranking-v1"
IMPORTANCE_WEIGHT = Decimal("0.60")
RELIABILITY_WEIGHT = Decimal("0.30")
RECENCY_WEIGHT = Decimal("0.10")
DEFAULT_REPORT_LIMIT = 20
MAX_RANKING_DOCUMENTS = 20
DEFAULT_CATEGORY_LIMITS = {
    Category.PRODUCT_TECHNOLOGY.value: 5,
    Category.COMPETITOR.value: 4,
    Category.CUSTOMER_DEMAND.value: 4,
    Category.SUPPLY_PRODUCTION.value: 4,
    Category.POLICY_REGULATION.value: 4,
    Category.MARKET_MANAGEMENT.value: 4,
}

RankingStatus = Literal["pending", "completed", "excluded", "failed"]
SelectionReason = Literal["SELECTED", "LOW_RELIABILITY", "CATEGORY_LIMIT", "OUTSIDE_REPORT_LIMIT"]
RankingExclusionReason = Literal["LOW_RELIABILITY", "CATEGORY_LIMIT", "OUTSIDE_REPORT_LIMIT"]
RecencyBucket = Literal[
    "WITHIN_24_HOURS",
    "WITHIN_48_HOURS",
    "WITHIN_72_HOURS",
    "WITHIN_120_HOURS",
    "OLDER_THAN_120_HOURS",
    "MISSING_PUBLISHED_AT",
    "FUTURE_PUBLISHED_AT",
]


class RankingCandidate(BaseModel):
    analysis_result_id: str
    workspace_id: str
    document_version_id: str
    title: str
    primary_category: str
    secondary_categories: list[str] = Field(default_factory=list)
    canonical_url: str | None = None
    source_name: str | None = None
    published_at: datetime | None = None
    reliability_score: int
    reliability_level: ReliabilityLevel
    importance_score: int
    importance_level: ImportanceLevel
    core_summary: str
    key_points: list[str] = Field(default_factory=list)
    key_numbers: list[KeyNumber] = Field(default_factory=list)
    sk_hynix_implication: str
    opportunities: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    watch_points: list[str] = Field(default_factory=list)
    summary_evidence_refs: list[SummaryEvidenceRef] = Field(default_factory=list)
    existing_ranking_status: str | None = None
    existing_ranking_score: Decimal | None = None
    existing_recency_score: int | None = None
    existing_ranking_position: int | None = None
    existing_selected_for_report: bool = False
    existing_report_selection_position: int | None = None
    existing_selection_reason: str | None = None
    existing_ranking_exclusion_reason: str | None = None
    existing_ranking_formula_version: str | None = None
    existing_ranking_reference_time: datetime | None = None
    existing_ranking_batch_date: date | None = None
    existing_ranked_at: datetime | None = None
    existing_ranking_detail: dict = Field(default_factory=dict)
    existing_ranking_error_message: str | None = None

    @field_validator("published_at", "existing_ranking_reference_time", "existing_ranked_at", mode="before")
    @classmethod
    def parse_datetime(cls, value: object) -> datetime | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    @field_validator("existing_ranking_batch_date", mode="before")
    @classmethod
    def parse_date(cls, value: object) -> date | None:
        if value is None or value == "":
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        return date.fromisoformat(str(value))

    @field_validator("existing_ranking_score", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal | None:
        if value is None or value == "":
            return None
        return Decimal(str(value))


class RecencyScoreResult(BaseModel):
    score: int
    age_hours: Decimal | None = None
    bucket: RecencyBucket
    warnings: list[str] = Field(default_factory=list)


class RankedAnalysisResult(BaseModel):
    analysis_result_id: str
    workspace_id: str
    document_version_id: str
    title: str = ""
    primary_category: str = ""
    secondary_categories: list[str] = Field(default_factory=list)
    canonical_url: str | None = None
    source_name: str | None = None
    published_at: datetime | None = None
    reliability_score: int | None = None
    reliability_level: ReliabilityLevel | None = None
    importance_score: int | None = None
    importance_level: ImportanceLevel | None = None
    core_summary: str | None = None
    key_points: list[str] = Field(default_factory=list)
    key_numbers: list[KeyNumber] = Field(default_factory=list)
    sk_hynix_implication: str | None = None
    opportunities: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    watch_points: list[str] = Field(default_factory=list)
    summary_evidence_refs: list[SummaryEvidenceRef] = Field(default_factory=list)
    ranking_status: RankingStatus
    ranking_score: Decimal | None = None
    recency_score: int | None = None
    ranking_position: int | None = None
    selected_for_report: bool = False
    report_selection_position: int | None = None
    selection_reason: SelectionReason | None = None
    ranking_exclusion_reason: RankingExclusionReason | None = None
    ranking_formula_version: str | None = None
    ranking_reference_time: datetime | None = None
    ranking_batch_date: date | None = None
    ranked_at: datetime | None = None
    ranking_detail: dict = Field(default_factory=dict)
    ranking_error_message: str | None = None

    @field_validator("published_at", "ranking_reference_time", "ranked_at", mode="before")
    @classmethod
    def parse_datetime(cls, value: object) -> datetime | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    @field_validator("ranking_batch_date", mode="before")
    @classmethod
    def parse_date(cls, value: object) -> date | None:
        if value is None or value == "":
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        return date.fromisoformat(str(value))

    @field_validator("ranking_score", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal | None:
        if value is None or value == "":
            return None
        return Decimal(str(value))

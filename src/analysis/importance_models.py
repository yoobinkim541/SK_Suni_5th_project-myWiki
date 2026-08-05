from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

from .models import Category
from .reliability_models import ReliabilityLevel, StoredReliabilityResult


class ImportanceLevel(str, Enum):
    LOW = "낮음"
    MEDIUM = "보통"
    HIGH = "높음"


IMPORTANCE_LEVEL_LOW_MAX = 39
IMPORTANCE_LEVEL_MEDIUM_MAX = 69
DEFAULT_IMPORTANCE_PROMPT_VERSION = "importance-v2"
_ALLOWED_INFORMATION_TYPES = {"fact", "plan", "forecast", "estimate"}
_ALLOWED_SUMMARY_SUPPORTS = {"core_summary", "sk_hynix_implication"}


class ImpactDirection(str, Enum):
    OPPORTUNITY = "기회"
    RISK = "위험"
    MIXED = "혼합"
    NEUTRAL = "중립"


class TimeHorizon(str, Enum):
    IMMEDIATE = "즉시"
    SHORT_TERM = "단기"
    MID_TERM = "중기"
    LONG_TERM = "장기"


class KeyNumber(BaseModel):
    label: str
    value: str
    unit: str | None = None
    context: str
    information_type: str
    evidence_document_version_id: str
    quoted_text: str | None = None
    source_start_line: int | None = None
    source_end_line: int | None = None

    @field_validator("label", "value", "context", "information_type", "evidence_document_version_id")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("필수 key_numbers 필드는 비어 있을 수 없습니다.")
        return value.strip()

    @field_validator("unit", "quoted_text")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("information_type")
    @classmethod
    def validate_information_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_INFORMATION_TYPES:
            raise ValueError("허용되지 않은 information_type입니다.")
        return normalized


class SummaryEvidenceRef(BaseModel):
    document_version_id: str
    quoted_text: str
    source_start_line: int | None = None
    source_end_line: int | None = None
    supports: list[str] = Field(default_factory=list)

    @field_validator("document_version_id", "quoted_text")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary_evidence_refs 필수 필드는 비어 있을 수 없습니다.")
        normalized = value.strip()
        if len(normalized) > 500 and " " in normalized:
            raise ValueError("summary_evidence_refs 인용문은 500자를 초과할 수 없습니다.")
        return normalized

    @field_validator("supports")
    @classmethod
    def validate_supports(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            token = item.strip()
            if not token or token in seen:
                continue
            if token in _ALLOWED_SUMMARY_SUPPORTS or token.startswith("key_points[") or token.startswith("key_numbers["):
                normalized.append(token)
                seen.add(token)
                continue
            raise ValueError("허용되지 않은 supports 값입니다.")
        return normalized


class ImportanceDocument(BaseModel):
    document_version_id: str
    title: str
    source_name: str
    source_type: str | None = None
    canonical_url: str | None = None
    published_at: str | None = None
    markdown: str
    source_id: str | None = None

    @field_validator("title", "source_name", "markdown")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("필수 텍스트 필드는 비어 있을 수 없습니다.")
        return value.strip()


class ImportanceEvaluationRequest(BaseModel):
    workspace_id: str
    issue_id: str | None = None
    issue_title: str
    primary_category: str
    secondary_categories: list[str] = Field(default_factory=list)
    documents: list[ImportanceDocument] = Field(min_length=1)
    reliability_score: int | None = Field(default=None, ge=0, le=100)
    reliability_level: ReliabilityLevel | None = None
    independent_source_count: int = Field(default=1, ge=1)
    first_seen_at: str | None = None
    last_seen_at: str | None = None

    @field_validator("issue_title", "primary_category")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("issue_title과 primary_category는 비어 있을 수 없습니다.")
        return value.strip()


class ImportanceCriterionResult(BaseModel):
    score: int = Field(ge=0, le=25)
    reason: str
    evidence_document_ids: list[str]
    uncertainties: list[str] = Field(default_factory=list)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason은 비어 있을 수 없습니다.")
        return value.strip()


class ImportanceLLMResult(BaseModel):
    direct_relevance: ImportanceCriterionResult
    business_impact: ImportanceCriterionResult
    urgency: ImportanceCriterionResult
    industry_impact: ImportanceCriterionResult
    duration: ImportanceCriterionResult
    external_attention: ImportanceCriterionResult
    impact_direction: ImpactDirection
    time_horizon: TimeHorizon
    affected_areas: list[str]
    opportunities: list[str]
    risks: list[str]
    watch_points: list[str]
    missing_information: list[str] = Field(default_factory=list)
    core_summary: str
    key_points: list[str]
    key_numbers: list[KeyNumber] = Field(default_factory=list)
    sk_hynix_implication: str
    summary_evidence_refs: list[SummaryEvidenceRef] = Field(default_factory=list)

    @field_validator("core_summary", "sk_hynix_implication")
    @classmethod
    def validate_summary_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("요약 텍스트는 비어 있을 수 없습니다.")
        return value.strip()

    @field_validator(
        "affected_areas",
        "opportunities",
        "risks",
        "watch_points",
        "missing_information",
        "key_points",
        mode="before",
    )
    @classmethod
    def normalize_string_lists(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("배열 필드는 리스트여야 합니다.")
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item).strip()
            if not text or text in seen:
                continue
            normalized.append(text)
            seen.add(text)
        return normalized

    @model_validator(mode="after")
    def validate_score_ranges(self) -> "ImportanceLLMResult":
        if self.direct_relevance.score > 25:
            raise ValueError("direct_relevance 점수는 25를 초과할 수 없습니다.")
        if self.business_impact.score > 25:
            raise ValueError("business_impact 점수는 25를 초과할 수 없습니다.")
        if self.urgency.score > 15:
            raise ValueError("urgency 점수는 15를 초과할 수 없습니다.")
        if self.industry_impact.score > 15:
            raise ValueError("industry_impact 점수는 15를 초과할 수 없습니다.")
        if self.duration.score > 10:
            raise ValueError("duration 점수는 10을 초과할 수 없습니다.")
        if self.external_attention.score > 10:
            raise ValueError("external_attention 점수는 10을 초과할 수 없습니다.")
        return self


class ImportanceEvaluationResult(BaseModel):
    issue_id: str | None = None
    issue_title: str
    importance_score: int = Field(ge=0, le=100)
    importance_level: ImportanceLevel
    direct_relevance_score: int = Field(ge=0, le=25)
    business_impact_score: int = Field(ge=0, le=25)
    urgency_score: int = Field(ge=0, le=15)
    industry_impact_score: int = Field(ge=0, le=15)
    duration_score: int = Field(ge=0, le=10)
    external_attention_score: int = Field(ge=0, le=10)
    impact_direction: ImpactDirection
    time_horizon: TimeHorizon
    summary_reason: str
    criteria: dict[str, ImportanceCriterionResult] = Field(default_factory=dict)
    applied_caps: list[dict[str, object]] = Field(default_factory=list)
    code_signals: dict[str, object] = Field(default_factory=dict)
    core_summary: str
    key_points: list[str] = Field(default_factory=list)
    key_numbers: list[KeyNumber] = Field(default_factory=list)
    sk_hynix_implication: str
    summary_evidence_refs: list[SummaryEvidenceRef] = Field(default_factory=list)
    affected_areas: list[str]
    opportunities: list[str]
    risks: list[str]
    watch_points: list[str]
    missing_information: list[str]
    evaluated_document_version_ids: list[str]
    warnings: list[str] = Field(default_factory=list)


class ImportanceEvaluationFailure(BaseModel):
    issue_id: str | None = None
    issue_title: str
    status: str = "failed"
    error_code: str
    error_message: str
    evaluated_document_version_ids: list[str] = Field(default_factory=list)


class ImportanceMachineSignals(BaseModel):
    document_count: int
    unique_source_count: int
    unique_canonical_url_count: int
    independent_source_count: int
    has_official_source: bool
    duplicated_republish_detected: bool
    sk_hynix_explicitly_mentioned: bool
    core_business_mentioned: bool
    quantitative_impact_present: bool
    forecast_only: bool
    promotional_or_event_only: bool
    event_already_ended: bool
    warnings: list[str] = Field(default_factory=list)


class ImportanceCaps(BaseModel):
    direct_relevance_max: int = 25
    business_impact_max: int = 25
    urgency_max: int = 15
    industry_impact_max: int = 15
    duration_max: int = 10
    external_attention_max: int = 10
    final_level_cap: ImportanceLevel | None = None
    warnings: list[str] = Field(default_factory=list)
    applied_caps: list[dict[str, object]] = Field(default_factory=list)


class ImportanceCategory(str, Enum):
    PRODUCT_TECHNOLOGY = Category.PRODUCT_TECHNOLOGY.value
    COMPETITOR = Category.COMPETITOR.value
    CUSTOMER_DEMAND = Category.CUSTOMER_DEMAND.value
    SUPPLY_PRODUCTION = Category.SUPPLY_PRODUCTION.value
    POLICY_REGULATION = Category.POLICY_REGULATION.value
    MARKET_MANAGEMENT = Category.MARKET_MANAGEMENT.value


class ImportanceScoreBreakdown(BaseModel):
    direct_relevance_score: int = Field(ge=0, le=25)
    business_impact_score: int = Field(ge=0, le=25)
    urgency_score: int = Field(ge=0, le=15)
    industry_impact_score: int = Field(ge=0, le=15)
    duration_score: int = Field(ge=0, le=10)
    external_attention_score: int = Field(ge=0, le=10)
    total_score: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def validate_total(self) -> "ImportanceScoreBreakdown":
        computed_total = (
            self.direct_relevance_score
            + self.business_impact_score
            + self.urgency_score
            + self.industry_impact_score
            + self.duration_score
            + self.external_attention_score
        )
        if computed_total != self.total_score:
            raise ValueError("총점이 기준별 점수 합과 일치하지 않습니다.")
        return self


class StoredImportanceResult(StoredReliabilityResult):
    importance_status: str = "pending"
    importance_score: int | None = None
    importance_level: ImportanceLevel | None = None
    direct_relevance_score: int | None = None
    business_impact_score: int | None = None
    urgency_score: int | None = None
    industry_impact_score: int | None = None
    duration_score: int | None = None
    external_attention_score: int | None = None
    impact_direction: ImpactDirection | None = None
    time_horizon: TimeHorizon | None = None
    importance_summary_reason: str | None = None
    core_summary: str | None = None
    key_points: list[str] = Field(default_factory=list)
    key_numbers: list[KeyNumber] = Field(default_factory=list)
    sk_hynix_implication: str | None = None
    summary_evidence_refs: list[SummaryEvidenceRef] = Field(default_factory=list)
    affected_areas: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    watch_points: list[str] = Field(default_factory=list)
    importance_missing_information: list[str] = Field(default_factory=list)
    importance_detail: dict = Field(default_factory=dict)
    importance_model_name: str | None = None
    importance_prompt_version: str | None = None
    importance_evaluated_at: str | None = None
    importance_error_message: str | None = None

    @field_validator(
        "key_points",
        "affected_areas",
        "opportunities",
        "risks",
        "watch_points",
        "importance_missing_information",
        mode="before",
    )
    @classmethod
    def ensure_string_list(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value]
        raise ValueError("배열 컬럼은 리스트여야 합니다.")

    @field_validator("core_summary", "sk_hynix_implication", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("key_numbers", mode="before")
    @classmethod
    def ensure_key_numbers(cls, value: object) -> list[KeyNumber] | object:
        if value is None:
            return []
        return value

    @field_validator("summary_evidence_refs", mode="before")
    @classmethod
    def ensure_summary_evidence_refs(cls, value: object) -> list[SummaryEvidenceRef] | object:
        if value is None:
            return []
        return value

    @field_validator("importance_detail", mode="before")
    @classmethod
    def ensure_detail_object(cls, value: object) -> dict:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        raise ValueError("importance_detail은 객체여야 합니다.")


class AnalysisResultForReport(BaseModel):
    analysis_result_id: str
    workspace_id: str
    document_version_id: str
    ranking_position: int | None = None
    ranking_score: float | None = None
    report_selection_position: int | None = None
    title: str
    canonical_url: str | None = None
    source_name: str | None = None
    source_type: str | None = None  # 'disclosure'면 report/selector.py가 근거 개수 요건을 면제한다.
    published_at: str | None = None
    primary_category: str
    secondary_categories: list[str] = Field(default_factory=list)
    reliability_score: int
    reliability_level: ReliabilityLevel
    importance_score: int
    importance_level: ImportanceLevel
    impact_direction: ImpactDirection
    time_horizon: TimeHorizon
    core_summary: str
    key_points: list[str] = Field(default_factory=list)
    key_numbers: list[KeyNumber] = Field(default_factory=list)
    sk_hynix_implication: str
    opportunities: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    watch_points: list[str] = Field(default_factory=list)
    summary_evidence_refs: list[SummaryEvidenceRef] = Field(default_factory=list)

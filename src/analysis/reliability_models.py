from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

from .models import Category, StoredClassificationResult


class ReliabilityLevel(str, Enum):
    LOW = "낮음"
    MEDIUM = "보통"
    HIGH = "높음"


RELIABILITY_LEVELS = {
    ReliabilityLevel.LOW.value: (0, 39),
    ReliabilityLevel.MEDIUM.value: (40, 69),
    ReliabilityLevel.HIGH.value: (70, 100),
}

DEFAULT_RELIABILITY_PROMPT_VERSION = "reliability-v1"


class EvidenceDocument(BaseModel):
    document_version_id: str
    document_id: str | None = None
    title: str
    canonical_url: str | None = None
    source_name: str
    source_type: str | None = None
    source_reliability_score: float | None = None
    published_at: str | None = None
    markdown: str
    version_no: int | None = None
    source_id: str | None = None
    markdown_object_key: str | None = None

    @field_validator("title", "source_name", "markdown")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("필수 텍스트 필드는 비어 있을 수 없습니다.")
        return value.strip()


class ReliabilityEvaluationRequest(BaseModel):
    workspace_id: str
    issue_id: str | None = None
    issue_title: str
    category: str
    documents: list[EvidenceDocument] = Field(min_length=1)

    @field_validator("issue_title", "category")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("issue_title과 category는 비어 있을 수 없습니다.")
        return value.strip()


class ReliabilityCriterionResult(BaseModel):
    score: int = Field(ge=0, le=20)
    reason: str
    evidence_document_ids: list[str]
    warnings: list[str] = Field(default_factory=list)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason은 비어 있을 수 없습니다.")
        return value.strip()


class ReliabilityLLMResult(BaseModel):
    traceability: ReliabilityCriterionResult
    source_authority: ReliabilityCriterionResult
    current_validity: ReliabilityCriterionResult
    independent_evidence: ReliabilityCriterionResult
    factual_consistency: ReliabilityCriterionResult
    conflicting_claims: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)


class ReliabilityEvaluationResult(BaseModel):
    issue_id: str | None = None
    issue_title: str
    reliability_score: int = Field(ge=0, le=100)
    reliability_level: ReliabilityLevel
    traceability_score: int = Field(ge=0, le=20)
    source_authority_score: int = Field(ge=0, le=20)
    current_validity_score: int = Field(ge=0, le=20)
    independent_evidence_score: int = Field(ge=0, le=20)
    factual_consistency_score: int = Field(ge=0, le=20)
    summary_reason: str
    criteria: dict[str, ReliabilityCriterionResult] = Field(default_factory=dict)
    conflicting_claims: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    evaluated_document_version_ids: list[str]
    warnings: list[str] = Field(default_factory=list)

    @field_validator("summary_reason")
    @classmethod
    def validate_summary_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary_reason은 비어 있을 수 없습니다.")
        return value.strip()


class ReliabilityEvaluationFailure(BaseModel):
    issue_id: str | None = None
    issue_title: str
    status: str = "failed"
    error_code: str
    error_message: str
    evaluated_document_version_ids: list[str] = Field(default_factory=list)


class MachineSignals(BaseModel):
    has_any_url: bool
    has_any_markdown: bool
    has_complete_metadata: bool
    document_count: int
    unique_source_count: int
    unique_canonical_url_count: int
    has_official_source: bool
    single_source_only: bool
    duplicated_republish_detected: bool
    conflicting_claims_present: bool = False
    official_correction_detected: bool = False
    missing_markdown_documents: list[str] = Field(default_factory=list)
    missing_url_documents: list[str] = Field(default_factory=list)
    missing_metadata_documents: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CriterionCaps(BaseModel):
    traceability_max: int = 20
    source_authority_max: int = 20
    current_validity_max: int = 20
    independent_evidence_max: int = 20
    factual_consistency_max: int = 20
    final_level_cap: ReliabilityLevel | None = None
    warnings: list[str] = Field(default_factory=list)


class ReliabilityCategory(str, Enum):
    PRODUCT_TECHNOLOGY = Category.PRODUCT_TECHNOLOGY.value
    COMPETITOR = Category.COMPETITOR.value
    CUSTOMER_DEMAND = Category.CUSTOMER_DEMAND.value
    SUPPLY_PRODUCTION = Category.SUPPLY_PRODUCTION.value
    POLICY_REGULATION = Category.POLICY_REGULATION.value
    MARKET_MANAGEMENT = Category.MARKET_MANAGEMENT.value


class ReliabilityScoreBreakdown(BaseModel):
    traceability_score: int = Field(ge=0, le=20)
    source_authority_score: int = Field(ge=0, le=20)
    current_validity_score: int = Field(ge=0, le=20)
    independent_evidence_score: int = Field(ge=0, le=20)
    factual_consistency_score: int = Field(ge=0, le=20)
    total_score: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def validate_total(self) -> "ReliabilityScoreBreakdown":
        computed_total = (
            self.traceability_score
            + self.source_authority_score
            + self.current_validity_score
            + self.independent_evidence_score
            + self.factual_consistency_score
        )
        if computed_total != self.total_score:
            raise ValueError("총점이 기준별 점수 합과 일치하지 않습니다.")
        return self


class StoredReliabilityResult(StoredClassificationResult):
    analysis_result_id: str | None = None
    reliability_status: str = "pending"
    reliability_score: int | None = None
    reliability_level: ReliabilityLevel | None = None
    traceability_score: int | None = None
    source_authority_score: int | None = None
    current_validity_score: int | None = None
    independent_evidence_score: int | None = None
    factual_consistency_score: int | None = None
    reliability_summary_reason: str | None = None
    reliability_detail: dict = Field(default_factory=dict)
    reliability_model_name: str | None = None
    reliability_prompt_version: str | None = None
    reliability_evaluated_at: str | None = None
    reliability_error_message: str | None = None

    @field_validator("reliability_detail", mode="before")
    @classmethod
    def ensure_detail_object(cls, value: object) -> dict:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        raise ValueError("reliability_detail은 객체여야 합니다.")

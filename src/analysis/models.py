from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

DEFAULT_CLASSIFICATION_PROMPT_VERSION = "classification-v1"
DOCUMENT_ANALYSIS_RESULTS_TABLE = "document_analysis_results"


class Category(str, Enum):
    PRODUCT_TECHNOLOGY = "제품·기술"
    COMPETITOR = "경쟁사"
    CUSTOMER_DEMAND = "고객·수요산업"
    SUPPLY_PRODUCTION = "공급망·생산"
    POLICY_REGULATION = "정책·규제"
    MARKET_MANAGEMENT = "시장·경영"


ALLOWED_CATEGORIES = {category.value for category in Category}


class ClassificationResult(BaseModel):
    primary_category: Category
    secondary_categories: list[Category] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str

    @field_validator("secondary_categories")
    @classmethod
    def validate_secondary_categories(cls, value: list[Category]) -> list[Category]:
        if len(value) > 2:
            raise ValueError("secondary_categories는 최대 2개까지 허용됩니다.")
        if len(set(value)) != len(value):
            raise ValueError("secondary_categories에 중복된 카테고리를 넣을 수 없습니다.")
        return value

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason은 비어 있을 수 없습니다.")
        return value.strip()

    @model_validator(mode="after")
    def validate_primary_secondary_overlap(self) -> "ClassificationResult":
        if self.primary_category in self.secondary_categories:
            raise ValueError("primary_category와 secondary_categories는 중복될 수 없습니다.")
        return self


class StoredClassificationResult(BaseModel):
    id: str
    workspace_id: str
    document_version_id: str
    primary_category: Category | None = None
    secondary_categories: list[Category] = Field(default_factory=list)
    classification_confidence: float | None = None
    classification_reason: str | None = None
    status: Literal["pending", "completed", "failed"]
    error_message: str | None = None
    error_code: str | None = None
    model_name: str
    prompt_version: str
    classified_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @field_validator("classification_confidence", mode="before")
    @classmethod
    def coerce_confidence(cls, value: object) -> float | None:
        if value is None:
            return None
        return float(value)

    @field_validator("secondary_categories", mode="before")
    @classmethod
    def normalize_secondary_categories(cls, value: object) -> list[str] | object:
        if value is None:
            return []
        return value

    @model_validator(mode="after")
    def validate_completed_payload(self) -> "StoredClassificationResult":
        if self.status == "completed":
            if self.primary_category is None or self.classification_confidence is None or not self.classification_reason:
                raise ValueError("completed 상태에는 분류 결과가 모두 필요합니다.")
        return self

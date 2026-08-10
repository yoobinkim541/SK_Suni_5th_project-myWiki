from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ..analysis.reliability_models import RELIABILITY_LEVELS, ReliabilityLevel

TopicPageType = Literal[
    "industry", "company", "technology", "supply_chain", "policy", "market", "term"
]
WikiTopicAction = Literal["update_existing", "create_new", "skip"]


class PageReliabilityJudgment(BaseModel):
    """위키 LLM이 자기가 쓴 페이지를 놓고 스스로 매기는 신뢰도 판정.
    document_analysis_results의 원문 문서 판정과 별개로, 이 페이지 본문이 근거
    범위를 벗어나지 않았는지(grounding_fidelity)를 가장 중요하게 취급한다."""

    grounding_fidelity_score: int = Field(ge=0, le=40)
    grounding_fidelity_reason: str
    source_reliability_score: int = Field(ge=0, le=20)
    source_reliability_reason: str
    evidence_diversity_score: int = Field(ge=0, le=20)
    evidence_diversity_reason: str
    currency_score: int = Field(ge=0, le=20)
    currency_reason: str
    reliability_score: int = Field(ge=0, le=100)
    reliability_level: ReliabilityLevel

    @model_validator(mode="after")
    def validate_total_and_level(self) -> "PageReliabilityJudgment":
        computed = (
            self.grounding_fidelity_score + self.source_reliability_score
            + self.evidence_diversity_score + self.currency_score
        )
        if computed != self.reliability_score:
            raise ValueError("총점이 항목별 점수 합과 일치하지 않습니다.")
        low, high = RELIABILITY_LEVELS[self.reliability_level.value]
        if not (low <= self.reliability_score <= high):
            raise ValueError("reliability_level이 reliability_score 구간과 일치하지 않습니다.")
        return self


class WikiClaim(BaseModel):
    document_version_id: str
    claim_text: str
    citation_order: int = Field(ge=1)


class TopicPageCandidate(BaseModel):
    wiki_page_id: str
    title: str
    content: str | None = None
    similarity_score: float | None = Field(default=None, ge=0.0, le=1.0)


class TopLevelTopicPage(BaseModel):
    wiki_page_id: str
    title: str
    page_type: TopicPageType


class WikiTopicLLMResult(BaseModel):
    action: WikiTopicAction
    target_wiki_page_id: str | None = None
    slug: str | None = None
    title: str | None = None
    page_type: TopicPageType | None = None
    parent_page_id: str | None = None
    markdown: str | None = None
    change_summary: str | None = None
    claims: list[WikiClaim] = Field(default_factory=list)
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    reliability: PageReliabilityJudgment


class WikiDraftGenerationResult(BaseModel):
    issue_key: str
    issue_page_id: str
    issue_version_id: str
    topic_action: Literal["update_existing", "create_new", "skip", "failed"]
    topic_page_id: str | None = None
    topic_version_id: str | None = None
    error_message: str | None = None


class WikiPageIdentity(BaseModel):
    page_id: str
    slug: str
    title: str
    page_type: TopicPageType | Literal["issue"]
    parent_page_id: str | None = None


class IssuePageRewriteResult(BaseModel):
    current_summary: str = Field(min_length=1)
    key_facts: list[str] = Field(min_length=1)
    implications: list[str] = Field(min_length=1)
    watch_points: list[str] = Field(min_length=1)
    reliability: PageReliabilityJudgment | None = None

    @field_validator("current_summary")
    @classmethod
    def _nonblank_summary(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("current_summary must not be blank")
        return v.strip()

    @field_validator("key_facts", "implications", "watch_points")
    @classmethod
    def _nonblank_items(cls, v: list[str]) -> list[str]:
        items = [item.strip() for item in v if item.strip()]
        if not items:
            raise ValueError("list fields must contain at least one non-blank item")
        return items

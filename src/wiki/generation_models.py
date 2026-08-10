from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ..analysis.reliability_models import RELIABILITY_LEVELS, ReliabilityLevel

logger = logging.getLogger(__name__)

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

    @model_validator(mode="before")
    @classmethod
    def validate_total_and_level(cls, data: Any) -> Any:
        """reliability_score/reliability_level은 4개 세부 점수만으로 결정되는 순수
        파생값이다. LLM이 별도로 되돌려주는 값은 정보량이 없고, 4항 덧셈은 LLM이
        자주 틀리는 산술이므로 여기서 세부 점수로부터 다시 계산해 덮어쓴다 — LLM이
        보낸 값과 어긋나도 거부(ValidationError)하지 않고 파생값으로 대체한다."""
        if not isinstance(data, dict):
            return data

        sub_score_keys = (
            "grounding_fidelity_score",
            "source_reliability_score",
            "evidence_diversity_score",
            "currency_score",
        )
        if any(data.get(key) is None for key in sub_score_keys):
            # 세부 점수가 누락된 경우: 일반 필드 검증이 그에 맞는 에러를 내도록 그대로 둔다.
            return data
        try:
            sub_scores = [int(data[key]) for key in sub_score_keys]
        except (TypeError, ValueError):
            return data

        computed_score = sum(sub_scores)
        stated_score = data.get("reliability_score")
        if stated_score != computed_score:
            logger.warning(
                "wiki_reliability_score_derived_mismatch",
                extra={"stated_score": stated_score, "derived_score": computed_score},
            )

        derived_level = next(
            (
                level_value
                for level_value, (low, high) in RELIABILITY_LEVELS.items()
                if low <= computed_score <= high
            ),
            None,
        )
        stated_level = data.get("reliability_level")
        if derived_level is not None and stated_level != derived_level:
            logger.warning(
                "wiki_reliability_level_derived_mismatch",
                extra={"stated_level": stated_level, "derived_level": derived_level},
            )

        data = {**data, "reliability_score": computed_score}
        if derived_level is not None:
            data["reliability_level"] = derived_level
        return data


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

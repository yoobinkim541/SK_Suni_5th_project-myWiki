from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

TopicPageType = Literal["industry", "company", "technology", "term"]
WikiTopicAction = Literal["update_existing", "create_new", "skip"]


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

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

WikiDedupDecision = Literal["merge", "not_duplicate"]


class DedupPageInfo(BaseModel):
    page_id: str
    slug: str
    title: str
    page_type: str
    parent_page_id: str | None = None


class DedupCandidatePair(BaseModel):
    page_a: DedupPageInfo
    page_b: DedupPageInfo
    shared_source_count: int = Field(ge=0)
    title_similarity: float = Field(ge=0.0, le=1.0)


class WikiDedupClaim(BaseModel):
    document_version_id: str
    claim_text: str
    citation_order: int = Field(ge=1)


class WikiDedupLLMResult(BaseModel):
    decision: WikiDedupDecision
    representative_page_id: str | None = None
    title: str | None = None
    markdown: str | None = None
    change_summary: str | None = None
    claims: list[WikiDedupClaim] = Field(default_factory=list)


class DedupResult(BaseModel):
    page_a_id: str
    page_b_id: str
    decision: Literal["merged", "not_duplicate", "failed"]
    representative_page_id: str | None = None
    archived_page_id: str | None = None
    version_id: str | None = None
    error_message: str | None = None

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.wiki.generation_models import (
    TopicPageCandidate,
    TopLevelTopicPage,
    WikiClaim,
    WikiDraftGenerationResult,
    WikiPageIdentity,
    WikiTopicLLMResult,
)


def test_wiki_claim_requires_positive_citation_order():
    claim = WikiClaim(document_version_id="doc-1", claim_text="근거 문장", citation_order=1)
    assert claim.citation_order == 1
    with pytest.raises(ValidationError):
        WikiClaim(document_version_id="doc-1", claim_text="근거 문장", citation_order=0)


def test_topic_page_candidate_defaults():
    candidate = TopicPageCandidate(wiki_page_id="page-1", title="HBM4 수급현황")
    assert candidate.content is None
    assert candidate.similarity_score is None


def test_top_level_topic_page_rejects_issue_page_type():
    with pytest.raises(ValidationError):
        TopLevelTopicPage(wiki_page_id="page-1", title="이슈 페이지", page_type="issue")


def test_wiki_topic_llm_result_confidence_score_bounds():
    with pytest.raises(ValidationError):
        WikiTopicLLMResult(action="skip", confidence_score=1.5)
    result = WikiTopicLLMResult(action="skip", confidence_score=0.4)
    assert result.claims == []


def test_wiki_topic_llm_result_update_existing_with_claims():
    result = WikiTopicLLMResult(
        action="update_existing",
        target_wiki_page_id="page-1",
        markdown="# 갱신된 본문",
        change_summary="신규 근거 반영",
        claims=[WikiClaim(document_version_id="doc-1", claim_text="근거", citation_order=1)],
        confidence_score=0.8,
    )
    assert result.claims[0].document_version_id == "doc-1"


def test_wiki_draft_generation_result_defaults_topic_fields_to_none():
    result = WikiDraftGenerationResult(
        issue_key="issue-1",
        issue_page_id="page-1",
        issue_version_id="ver-1",
        topic_action="skip",
    )
    assert result.topic_page_id is None
    assert result.error_message is None


def test_wiki_page_identity_requires_page_type():
    identity = WikiPageIdentity(
        page_id="page-1", slug="hbm4-supply", title="HBM4_수급현황", page_type="technology", parent_page_id=None,
    )
    assert identity.slug == "hbm4-supply"
    with pytest.raises(ValidationError):
        WikiPageIdentity(page_id="page-1", slug="s", title="t", page_type="issue", parent_page_id=None)

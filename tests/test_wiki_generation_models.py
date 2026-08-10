from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.analysis.reliability_models import ReliabilityLevel
from src.wiki.generation_models import (
    IssuePageRewriteResult,
    PageReliabilityJudgment,
    TopicPageCandidate,
    TopLevelTopicPage,
    WikiClaim,
    WikiDraftGenerationResult,
    WikiPageIdentity,
    WikiTopicLLMResult,
)

_VALID_RELIABILITY = dict(
    grounding_fidelity_score=25, grounding_fidelity_reason="근거 범위 안에서 서술함",
    source_reliability_score=15, source_reliability_reason="원문 신뢰도 보통 수준",
    evidence_diversity_score=10, evidence_diversity_reason="출처 2건 확인",
    currency_score=10, currency_reason="최근 1주 이내 정보",
    reliability_score=60, reliability_level="보통",
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
        WikiTopicLLMResult(action="skip", confidence_score=1.5, reliability=PageReliabilityJudgment(**_VALID_RELIABILITY))
    result = WikiTopicLLMResult(action="skip", confidence_score=0.4, reliability=PageReliabilityJudgment(**_VALID_RELIABILITY))
    assert result.claims == []


def test_wiki_topic_llm_result_update_existing_with_claims():
    result = WikiTopicLLMResult(
        action="update_existing",
        target_wiki_page_id="page-1",
        markdown="# 갱신된 본문",
        change_summary="신규 근거 반영",
        claims=[WikiClaim(document_version_id="doc-1", claim_text="근거", citation_order=1)],
        confidence_score=0.8,
        reliability=PageReliabilityJudgment(**_VALID_RELIABILITY),
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
        WikiPageIdentity(page_id="page-1", slug="s", title="t", page_type="bogus", parent_page_id=None)


def test_wiki_page_identity_accepts_issue_page_type():
    """find_matching_issue_page()가 매칭된 이슈 페이지의 identity를 반환할 때 필요하다."""
    identity = WikiPageIdentity(
        page_id="page-1", slug="issue-hbm4-supply", title="HBM4 공급 부족", page_type="issue", parent_page_id=None,
    )
    assert identity.page_type == "issue"


def test_issue_page_rewrite_result_requires_nonempty_fields():
    with pytest.raises(ValidationError):
        IssuePageRewriteResult(current_summary="", key_facts=["a"], implications=["b"], watch_points=["c"])
    with pytest.raises(ValidationError):
        IssuePageRewriteResult(current_summary="요약", key_facts=[], implications=["b"], watch_points=["c"])


def test_issue_page_rewrite_result_accepts_valid_payload():
    result = IssuePageRewriteResult(
        current_summary="다듬어진 요약",
        key_facts=["사실 1"],
        implications=["시사점 1"],
        watch_points=["지점 1"],
    )
    assert result.current_summary == "다듬어진 요약"
    assert result.key_facts == ["사실 1"]


def test_issue_page_rewrite_result_rejects_whitespace_only_content():
    with pytest.raises(ValidationError):
        IssuePageRewriteResult(current_summary="   ", key_facts=["a"], implications=["b"], watch_points=["c"])
    with pytest.raises(ValidationError):
        IssuePageRewriteResult(current_summary="요약", key_facts=["  "], implications=["b"], watch_points=["c"])


def test_page_reliability_judgment_derives_total_from_sub_scores():
    """LLM이 잘못된 총점을 보내도(25+15+10+10=60과 불일치) 거부하지 않고,
    세부 점수 합으로 재계산한 값을 사용해야 한다."""
    judgment = PageReliabilityJudgment(
        grounding_fidelity_score=25, grounding_fidelity_reason="근거 범위 안에서 서술함",
        source_reliability_score=15, source_reliability_reason="원문 신뢰도 보통 수준",
        evidence_diversity_score=10, evidence_diversity_reason="출처 2건 확인",
        currency_score=10, currency_reason="최근 1주 이내 정보",
        reliability_score=99,  # 25+15+10+10=60 과 불일치 — 파생값(60)으로 대체되어야 함
        reliability_level="보통",
    )
    assert judgment.reliability_score == 60
    assert judgment.reliability_level == ReliabilityLevel.MEDIUM


def test_page_reliability_judgment_derives_level_from_computed_score():
    """LLM이 보낸 reliability_level이 실제 구간과 어긋나도(60점은 '보통' 구간인데
    '낮음'이라고 답해도) 거부하지 않고, 계산된 점수의 구간으로 재도출해야 한다."""
    judgment = PageReliabilityJudgment(
        grounding_fidelity_score=25, grounding_fidelity_reason="근거 범위 안에서 서술함",
        source_reliability_score=15, source_reliability_reason="원문 신뢰도 보통 수준",
        evidence_diversity_score=10, evidence_diversity_reason="출처 2건 확인",
        currency_score=10, currency_reason="최근 1주 이내 정보",
        reliability_score=60,
        reliability_level="낮음",  # 60점은 '보통' 구간(40-69)인데 '낮음'이라고 함 — 파생값으로 대체되어야 함
    )
    assert judgment.reliability_score == 60
    assert judgment.reliability_level == ReliabilityLevel.MEDIUM


def test_page_reliability_judgment_accepts_valid_payload():
    judgment = PageReliabilityJudgment(
        grounding_fidelity_score=25, grounding_fidelity_reason="근거 범위 안에서 서술함",
        source_reliability_score=15, source_reliability_reason="원문 신뢰도 보통 수준",
        evidence_diversity_score=10, evidence_diversity_reason="출처 2건 확인",
        currency_score=10, currency_reason="최근 1주 이내 정보",
        reliability_score=60,
        reliability_level="보통",
    )
    assert judgment.reliability_score == 60


def test_wiki_topic_llm_result_requires_reliability():
    with pytest.raises(ValidationError):
        WikiTopicLLMResult(action="skip", confidence_score=0.4)


def test_issue_page_rewrite_result_reliability_defaults_to_none():
    result = IssuePageRewriteResult(
        current_summary="다듬어진 요약", key_facts=["사실 1"],
        implications=["시사점 1"], watch_points=["지점 1"],
    )
    assert result.reliability is None

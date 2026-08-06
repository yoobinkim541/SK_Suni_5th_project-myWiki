from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.analysis.models import Category
from src.report.grouper import IssueGroupingConfig, group_report_candidates
from src.report.models import IssueGroup, ReportCandidate
from src.report.selector import select_report_candidates
from src.report.wiki_context import (
    build_wiki_query,
    build_wiki_query_terms,
    build_wiki_search_request,
    enrich_issue_group,
    enrich_issue_groups,
    to_wiki_context,
)
from src.wiki.models import WikiSearchResult
from src.wiki.repository import WikiSearchError


def make_candidate(
    *,
    analysis_result_id: str,
    workspace_id: str = "ws-1",
    category: Category = Category.PRODUCT_TECHNOLOGY,
    title: str = "SK hynix HBM3E roadmap",
    summary: str = "HBM3E demand rises with AI server shipments.",
    ranking_score: str = "90.0",
    reliability_score: int = 85,
    importance_score: int = 88,
    published_at: datetime | None = None,
) -> ReportCandidate:
    return ReportCandidate(
        analysis_result_id=analysis_result_id,
        workspace_id=workspace_id,
        document_id=f"doc-{analysis_result_id}",
        document_version_id=f"doc-ver-{analysis_result_id}",
        category=category,
        title=title,
        summary=summary,
        reliability_score=reliability_score,
        importance_score=importance_score,
        ranking_score=Decimal(ranking_score),
        source_name="source",
        canonical_url=f"https://example.com/{analysis_result_id}",
        published_at=published_at or datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc),
    )


def make_issue_group(candidates: list[ReportCandidate]) -> IssueGroup:
    return IssueGroup(
        issue_key="issue-1",
        category=candidates[0].category,
        candidates=candidates,
        representative_analysis_result_id=candidates[0].analysis_result_id,
    )


def test_build_wiki_query_terms_prioritizes_representative_and_repeated_tokens() -> None:
    issue_group = make_issue_group(
        [
            make_candidate(
                analysis_result_id="a",
                title="SK hynix HBM3E roadmap",
                summary="HBM3E demand grows in AI servers.",
            ),
            make_candidate(
                analysis_result_id="b",
                title="HBM3E roadmap for AI server memory",
                summary="AI server demand keeps growing for HBM3E.",
            ),
        ]
    )

    query_terms = build_wiki_query_terms(issue_group)

    assert query_terms[0:4] == ("sk", "hynix", "hbm3e", "roadmap")
    assert "ai" in query_terms
    assert "demand" in query_terms


def test_build_wiki_query_is_deterministic_for_same_group_members() -> None:
    candidate_a = make_candidate(analysis_result_id="a", title="HBM3E supply roadmap")
    candidate_b = make_candidate(analysis_result_id="b", title="HBM3E roadmap update")

    first = make_issue_group([candidate_a, candidate_b])
    second = IssueGroup(
        issue_key="issue-1",
        category=Category.PRODUCT_TECHNOLOGY,
        candidates=[candidate_b, candidate_a],
        representative_analysis_result_id="a",
    )

    assert build_wiki_query_terms(first) == build_wiki_query_terms(second)
    assert build_wiki_query(first) == build_wiki_query(second)


def test_build_wiki_search_request_keeps_workspace_category_and_limit() -> None:
    issue_group = make_issue_group([make_candidate(analysis_result_id="a")])

    request = build_wiki_search_request(issue_group, limit=3)

    assert request.workspace_id == "ws-1"
    assert request.category == Category.PRODUCT_TECHNOLOGY
    assert request.limit == 3
    assert request.query
    assert request.query_terms


def test_build_wiki_search_request_rejects_mixed_workspaces() -> None:
    issue_group = make_issue_group(
        [
            make_candidate(analysis_result_id="a", workspace_id="ws-1"),
            make_candidate(analysis_result_id="b", workspace_id="ws-2"),
        ]
    )

    with pytest.raises(ValueError, match="same workspace"):
        build_wiki_search_request(issue_group, limit=3)


def test_build_wiki_search_request_rejects_missing_representative_candidate() -> None:
    issue_group = IssueGroup.model_construct(
        issue_key="issue-1",
        category=Category.PRODUCT_TECHNOLOGY,
        candidates=[make_candidate(analysis_result_id="a")],
        representative_analysis_result_id="missing",
        representative_candidate=None,
    )

    with pytest.raises(ValueError, match="representative_analysis_result_id"):
        build_wiki_search_request(issue_group, limit=3)


def test_to_wiki_context_maps_result_fields() -> None:
    result = WikiSearchResult(
        wiki_page_id="page-1",
        wiki_version_id="ver-1",
        workspace_id="ws-1",
        title="HBM3E wiki",
        content="HBM3E background",
        score=0.75,
        updated_at="2026-08-02T01:00:00+00:00",
        source_document_version_ids=["doc-ver-1"],
    )

    context = to_wiki_context(result)

    assert context.wiki_page_id == "page-1"
    assert context.wiki_version_id == "ver-1"
    assert context.title == "HBM3E wiki"
    assert context.content == "HBM3E background"
    assert context.similarity_score == 0.75
    assert context.updated_at == datetime(2026, 8, 2, 1, 0, tzinfo=timezone.utc)
    assert context.source_document_version_ids == ["doc-ver-1"]


def test_enrich_issue_group_returns_contexts_when_wiki_exists() -> None:
    issue_group = make_issue_group([make_candidate(analysis_result_id="a")])

    def fake_search(_request):
        return [
            WikiSearchResult(
                wiki_page_id="page-1",
                wiki_version_id="ver-1",
                workspace_id="ws-1",
                title="HBM3E wiki",
                content="HBM3E background",
                score=0.8,
                updated_at="2026-08-02T01:00:00+00:00",
                source_document_version_ids=["doc-ver-1"],
            )
        ]

    enriched = enrich_issue_group(issue_group, wiki_search=fake_search, limit=3)

    assert enriched.issue_group is issue_group
    assert len(enriched.wiki_contexts) == 1
    assert enriched.wiki_contexts[0].wiki_page_id == "page-1"


def test_enrich_issue_group_returns_empty_contexts_when_no_wiki_exists() -> None:
    issue_group = make_issue_group([make_candidate(analysis_result_id="a")])

    enriched = enrich_issue_group(issue_group, wiki_search=lambda _request: [], limit=3)

    assert enriched.issue_group is issue_group
    assert enriched.wiki_contexts == []


def test_enrich_issue_group_is_fail_open_for_wiki_search_error() -> None:
    issue_group = make_issue_group([make_candidate(analysis_result_id="a")])

    def failing_search(_request):
        raise WikiSearchError("lookup failed")

    enriched = enrich_issue_group(issue_group, wiki_search=failing_search, limit=3)

    assert enriched.issue_group is issue_group
    assert enriched.wiki_contexts == []


def test_enrich_issue_group_propagates_programming_errors() -> None:
    issue_group = make_issue_group([make_candidate(analysis_result_id="a")])

    def broken_search(_request):
        raise RuntimeError("unexpected")

    with pytest.raises(RuntimeError, match="unexpected"):
        enrich_issue_group(issue_group, wiki_search=broken_search, limit=3)


def test_enrich_issue_groups_preserves_input_order() -> None:
    first = make_issue_group([make_candidate(analysis_result_id="a", title="HBM3E roadmap")])
    second = make_issue_group([make_candidate(analysis_result_id="b", title="DDR5 pricing")])
    second.issue_key = "issue-2"

    def fake_search(request):
        return [
            WikiSearchResult(
                wiki_page_id=f"page-{request.query_terms[0]}",
                wiki_version_id="ver-1",
                workspace_id=request.workspace_id,
                title=request.query,
                content="context",
                score=0.5,
                updated_at="2026-08-02T01:00:00+00:00",
                source_document_version_ids=[],
            )
        ]

    enriched = enrich_issue_groups([first, second], wiki_search=fake_search, limit_per_group=2)

    assert [item.issue_group.issue_key for item in enriched] == ["issue-1", "issue-2"]


def test_enrich_issue_groups_pipeline_integration() -> None:
    candidates = [
        make_candidate(
            analysis_result_id="a",
            title="HBM3E roadmap update",
            summary="HBM3E demand rises for AI servers.",
            ranking_score="95.0",
        ),
        make_candidate(
            analysis_result_id="b",
            title="HBM3E roadmap for AI server memory",
            summary="AI server demand keeps rising for HBM3E.",
            ranking_score="94.0",
        ),
        make_candidate(
            analysis_result_id="c",
            category=Category.COMPETITOR,
            title="NVIDIA demand update",
            summary="NVIDIA customer demand remains strong.",
            ranking_score="90.0",
        ),
    ]

    selected = select_report_candidates(
        candidates,
        max_candidates=3,
        min_reliability_score=70,
        min_importance_score=70,
    )
    groups = group_report_candidates(
        selected,
        config=IssueGroupingConfig(
            max_time_gap_hours=24,
            min_title_similarity=0.2,
            min_summary_similarity=0.2,
            min_shared_title_tokens=1,
        ),
    )

    def fake_search(request):
        if "hbm3e" in request.query_terms:
            return [
                WikiSearchResult(
                    wiki_page_id="page-hbm",
                    wiki_version_id="ver-hbm",
                    workspace_id=request.workspace_id,
                    title="HBM wiki",
                    content="HBM historical context",
                    score=0.9,
                    updated_at="2026-08-02T02:00:00+00:00",
                    source_document_version_ids=["doc-ver-hbm"],
                )
            ]
        return []

    enriched = enrich_issue_groups(groups, wiki_search=fake_search, limit_per_group=2)

    assert len(enriched) == 2
    assert enriched[0].issue_group.candidates[0].analysis_result_id in {"a", "b"}
    assert enriched[0].wiki_contexts
    assert enriched[1].wiki_contexts == []

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.analysis.importance_models import ImpactDirection, TimeHorizon
from src.analysis.models import Category
from src.report.models import (
    EnrichedIssueGroup,
    GeneratedReport,
    IssueGroup,
    ReportCandidate,
    ReportCategoryGroup,
    ReportCitationDraft,
    ReportExecutiveSummary,
    ReportGenerationRequest,
    ReportIssueSummaryRow,
    ReportNewsSource,
    ReportOverallImplications,
    ReportSectionDraft,
    ReportStatus,
    ReportType,
    ReportWikiReferenceDraft,
    ReportWikiSource,
    WikiContext,
)


def _candidate(document_version_id: str) -> ReportCandidate:
    return ReportCandidate(
        analysis_result_id=f"analysis-{document_version_id}",
        workspace_id="ws-1",
        document_id=f"document-{document_version_id}",
        document_version_id=document_version_id,
        category=Category.PRODUCT_TECHNOLOGY,
        title=f"title-{document_version_id}",
        summary="summary",
        reliability_score=80,
        importance_score=75,
        ranking_score=Decimal("88.50"),
        impact_direction=ImpactDirection.OPPORTUNITY,
        time_horizon=TimeHorizon.MID_TERM,
    )


def test_report_generation_request_defaults() -> None:
    request = ReportGenerationRequest(
        workspace_id="ws-1",
        report_date=date(2026, 8, 2),
    )

    assert request.max_sections == 15
    assert request.language == "ko"
    assert request.report_type == ReportType.DAILY


def test_report_generation_request_rejects_invalid_max_sections() -> None:
    with pytest.raises(ValueError):
        ReportGenerationRequest(
            workspace_id="ws-1",
            report_date=date(2026, 8, 2),
            max_sections=0,
        )


def test_report_candidate_keeps_identifiers() -> None:
    candidate = _candidate("doc-1")

    assert candidate.analysis_result_id == "analysis-doc-1"
    assert candidate.document_id == "document-doc-1"
    assert candidate.document_version_id == "doc-1"


def test_issue_group_holds_multiple_candidates() -> None:
    first = _candidate("doc-1")
    second = _candidate("doc-2")

    group = IssueGroup(
        issue_key="issue-1",
        category=Category.PRODUCT_TECHNOLOGY,
        candidates=[first, second],
    )

    assert len(group.candidates) == 2
    assert group.representative_analysis_result_id == "analysis-doc-1"


def test_wiki_context_allows_optional_fields() -> None:
    context = WikiContext(
        wiki_page_id="wiki-page-1",
        title="HBM",
    )

    assert context.wiki_version_id is None
    assert context.wiki_chunk_id is None
    assert context.similarity_score is None
    assert context.source_document_version_ids == []


def test_enriched_issue_group_allows_empty_wiki_contexts() -> None:
    enriched = EnrichedIssueGroup(
        issue_group=IssueGroup(
            issue_key="issue-1",
            category=Category.PRODUCT_TECHNOLOGY,
            candidates=[_candidate("doc-1")],
        ),
    )

    assert enriched.wiki_contexts == []


def test_report_section_draft_separates_news_and_wiki_references() -> None:
    section = ReportSectionDraft(
        issue_key="issue-1",
        representative_analysis_result_id="analysis-doc-1",
        category=Category.PRODUCT_TECHNOLOGY,
        importance_score=75,
        impact_direction=ImpactDirection.OPPORTUNITY,
        time_horizon=TimeHorizon.MID_TERM,
        title="HBM update",
        news_citations=[
            ReportCitationDraft(
                analysis_result_id="analysis-doc-1",
                document_version_id="doc-1",
                citation_order=1,
                evidence_text="quoted text",
            )
        ],
        wiki_references=[
            ReportWikiReferenceDraft(
                wiki_page_id="wiki-page-1",
                reference_order=1,
                similarity_score=0.8,
            )
        ],
    )

    assert section.issue_key == "issue-1"
    assert section.representative_analysis_result_id == "analysis-doc-1"
    assert len(section.news_citations) == 1
    assert len(section.wiki_references) == 1
    assert section.news_citations[0].document_version_id == "doc-1"
    assert section.wiki_references[0].wiki_page_id == "wiki-page-1"


def test_generated_report_allows_missing_artifact() -> None:
    report = GeneratedReport(
        workspace_id="ws-1",
        report_date=date(2026, 8, 2),
        report_type=ReportType.DAILY,
        status=ReportStatus.DRAFTING,
    )

    assert report.artifact_id is None
    assert report.artifact_object_key is None
    assert report.sections == []


def test_generated_report_extended_fields_accept_structured_content() -> None:
    section = ReportSectionDraft(
        issue_key="issue-1",
        representative_analysis_result_id="analysis-1",
        category=Category.PRODUCT_TECHNOLOGY,
        title="HBM update",
    )
    report = GeneratedReport(
        workspace_id="ws-1",
        report_date=date(2026, 8, 2),
        report_type=ReportType.DAILY,
        title="SK하이닉스 산업 동향 일일 보고서",
        language="ko",
        status=ReportStatus.DRAFTING,
        executive_summaries=[
            ReportExecutiveSummary(
                issue_key="issue-1",
                title="HBM update",
                summary="요약",
            )
        ],
        issue_summary_rows=[
            ReportIssueSummaryRow(
                issue_key="issue-1",
                category=Category.PRODUCT_TECHNOLOGY,
                title="HBM update",
            )
        ],
        sections=[section],
        category_groups=[ReportCategoryGroup(category=Category.PRODUCT_TECHNOLOGY, sections=[section])],
        overall_implications=ReportOverallImplications(
            opportunities=["기회"],
            risks=["위험"],
            monitoring_points=["모니터링"],
        ),
        news_sources=[ReportNewsSource(document_version_id="doc-1")],
        wiki_sources=[ReportWikiSource(wiki_page_id="wiki-page-1", wiki_version_id="wiki-ver-1")],
    )

    assert report.executive_summaries[0].summary == "요약"
    assert report.issue_summary_rows[0].issue_key == "issue-1"
    assert report.category_groups[0].sections[0].title == "HBM update"
    assert report.overall_implications is not None
    assert report.news_sources[0].document_version_id == "doc-1"
    assert report.wiki_sources[0].wiki_version_id == "wiki-ver-1"

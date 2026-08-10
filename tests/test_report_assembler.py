from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime

import pytest

from src.analysis.importance_models import ImpactDirection, TimeHorizon
from src.analysis.models import Category
from src.report.assembler import ReportAssemblyError, assemble_generated_report
from src.report.models import (
    ReportCitationDraft,
    ReportGenerationRequest,
    ReportSectionDraft,
    ReportType,
    ReportWikiReferenceDraft,
)


def make_section(
    issue_key: str,
    *,
    category: Category,
    importance_score: int,
    impact_direction: ImpactDirection,
    time_horizon: TimeHorizon = TimeHorizon.MID_TERM,
    title: str | None = None,
    current_summary: str | None = None,
    implications: list[str] | None = None,
    watch_points: list[str] | None = None,
    news_ids: list[str] | None = None,
    wiki_ids: list[tuple[str, str]] | None = None,
) -> ReportSectionDraft:
    return ReportSectionDraft(
        issue_key=issue_key,
        representative_analysis_result_id=f"analysis-{issue_key}",
        category=category,
        importance_score=importance_score,
        impact_direction=impact_direction,
        time_horizon=time_horizon,
        title=title or f"title-{issue_key}",
        current_summary=current_summary or f"summary-{issue_key}",
        key_facts=[f"fact-{issue_key}"],
        historical_context=[f"context-{issue_key}"],
        implications=implications or [f"implication-{issue_key}"],
        watch_points=watch_points or [f"watch-{issue_key}"],
        news_citations=[
            ReportCitationDraft(
                analysis_result_id=f"analysis-{issue_key}",
                document_version_id=document_version_id,
                citation_order=index,
                evidence_text=f"evidence-{document_version_id}",
            )
            for index, document_version_id in enumerate(news_ids or [f"doc-{issue_key}"], start=1)
        ],
        wiki_references=[
            ReportWikiReferenceDraft(
                wiki_page_id=wiki_page_id,
                wiki_version_id=wiki_version_id,
                reference_order=index,
                similarity_score=0.8,
            )
            for index, (wiki_page_id, wiki_version_id) in enumerate(
                wiki_ids or [(f"page-{issue_key}", f"wiki-{issue_key}")],
                start=1,
            )
        ],
    )


def make_request() -> ReportGenerationRequest:
    return ReportGenerationRequest(
        workspace_id="ws-1",
        report_date=date(2026, 8, 2),
        report_type=ReportType.DAILY,
    )


def test_assemble_generated_report_builds_expected_structure() -> None:
    generated_at = datetime(2026, 8, 2, 9, 0, 0)
    sections = [
        make_section(
            "issue-1",
            category=Category.PRODUCT_TECHNOLOGY,
            importance_score=90,
            impact_direction=ImpactDirection.OPPORTUNITY,
        ),
        make_section(
            "issue-2",
            category=Category.COMPETITOR,
            importance_score=80,
            impact_direction=ImpactDirection.RISK,
        ),
        make_section(
            "issue-3",
            category=Category.POLICY_REGULATION,
            importance_score=70,
            impact_direction=ImpactDirection.MIXED,
        ),
    ]

    report = assemble_generated_report(request=make_request(), sections=sections, generated_at=generated_at)

    assert report.title == "일일 산업 동향 보고서"
    assert report.report_date == date(2026, 8, 2)
    assert report.generated_at == generated_at
    assert report.created_at == generated_at
    assert report.language == "ko"
    assert report.sections == sections
    assert len(report.executive_summaries) == 3
    assert len(report.issue_summary_rows) == 3
    assert len(report.category_groups) == 3
    assert report.news_sources[0].document_version_id == "doc-issue-1"
    assert report.wiki_sources[0].wiki_version_id == "wiki-issue-1"


def test_assemble_generated_report_carries_display_attribution_into_aggregate_sources() -> None:
    """report.news_sources/wiki_sources는 렌더러가 document_version_id/wiki_page_id 원문을
    노출하지 않고 제목·매체명·날짜를 쓸 수 있도록 section의 표시용 메타데이터를 그대로 옮겨야 한다."""
    section = ReportSectionDraft(
        issue_key="issue-1",
        representative_analysis_result_id="analysis-issue-1",
        category=Category.PRODUCT_TECHNOLOGY,
        importance_score=90,
        impact_direction=ImpactDirection.OPPORTUNITY,
        time_horizon=TimeHorizon.MID_TERM,
        title="title-issue-1",
        current_summary="summary-issue-1",
        news_citations=[
            ReportCitationDraft(
                analysis_result_id="analysis-issue-1",
                document_version_id="doc-issue-1",
                citation_order=1,
                document_title="기사 제목 - 뉴시스",
                source_name="Google RSS - SK하이닉스",
                published_at="2026-08-02T07:23:01+00:00",
            )
        ],
        wiki_references=[
            ReportWikiReferenceDraft(
                wiki_page_id="page-issue-1",
                wiki_version_id="wiki-issue-1",
                reference_order=1,
                wiki_title="위키 문서 제목",
            )
        ],
    )

    report = assemble_generated_report(request=make_request(), sections=[section])

    assert report.news_sources[0].document_title == "기사 제목 - 뉴시스"
    assert report.news_sources[0].source_name == "Google RSS - SK하이닉스"
    assert report.news_sources[0].published_at == "2026-08-02T07:23:01+00:00"
    assert report.wiki_sources[0].wiki_title == "위키 문서 제목"


def test_assemble_generated_report_limits_executive_summaries_to_top_five() -> None:
    sections = [
        make_section(
            f"issue-{index}",
            category=Category.PRODUCT_TECHNOLOGY,
            importance_score=100 - index,
            impact_direction=ImpactDirection.OPPORTUNITY,
        )
        for index in range(7)
    ]

    report = assemble_generated_report(request=make_request(), sections=sections, generated_at=datetime(2026, 8, 2, 9, 0, 0))

    assert [item.issue_key for item in report.executive_summaries] == [
        "issue-0",
        "issue-1",
        "issue-2",
        "issue-3",
        "issue-4",
    ]


def test_assemble_generated_report_uses_all_sections_when_fewer_than_three() -> None:
    sections = [
        make_section(
            "issue-1",
            category=Category.PRODUCT_TECHNOLOGY,
            importance_score=70,
            impact_direction=ImpactDirection.OPPORTUNITY,
        ),
        make_section(
            "issue-2",
            category=Category.COMPETITOR,
            importance_score=60,
            impact_direction=ImpactDirection.RISK,
        ),
    ]

    report = assemble_generated_report(request=make_request(), sections=sections, generated_at=datetime(2026, 8, 2, 9, 0, 0))

    assert [item.issue_key for item in report.executive_summaries] == ["issue-1", "issue-2"]


def test_issue_summary_rows_keep_section_order_and_fields() -> None:
    sections = [
        make_section(
            "issue-b",
            category=Category.COMPETITOR,
            importance_score=50,
            impact_direction=ImpactDirection.RISK,
            time_horizon=TimeHorizon.SHORT_TERM,
        ),
        make_section(
            "issue-a",
            category=Category.PRODUCT_TECHNOLOGY,
            importance_score=90,
            impact_direction=ImpactDirection.OPPORTUNITY,
            time_horizon=TimeHorizon.LONG_TERM,
        ),
    ]

    report = assemble_generated_report(request=make_request(), sections=sections, generated_at=datetime(2026, 8, 2, 9, 0, 0))

    assert [row.issue_key for row in report.issue_summary_rows] == ["issue-b", "issue-a"]
    assert report.issue_summary_rows[0].category == Category.COMPETITOR
    assert report.issue_summary_rows[0].impact_direction == ImpactDirection.RISK
    assert report.issue_summary_rows[0].time_horizon == TimeHorizon.SHORT_TERM


def test_assemble_generated_report_preserves_section_content() -> None:
    section = make_section(
        "issue-1",
        category=Category.PRODUCT_TECHNOLOGY,
        importance_score=90,
        impact_direction=ImpactDirection.OPPORTUNITY,
        implications=["opportunity-1"],
        watch_points=["watch-1"],
    )

    report = assemble_generated_report(
        request=make_request(),
        sections=[section],
        generated_at=datetime(2026, 8, 2, 9, 0, 0),
    )

    assert report.sections[0].current_summary == section.current_summary
    assert report.sections[0].key_facts == section.key_facts
    assert report.sections[0].historical_context == section.historical_context
    assert report.sections[0].implications == section.implications
    assert report.sections[0].watch_points == section.watch_points
    assert report.sections[0].news_citations == section.news_citations
    assert report.sections[0].wiki_references == section.wiki_references


def test_category_groups_follow_business_order_and_omit_empty_categories() -> None:
    sections = [
        make_section(
            "issue-1",
            category=Category.MARKET_MANAGEMENT,
            importance_score=50,
            impact_direction=ImpactDirection.MIXED,
        ),
        make_section(
            "issue-2",
            category=Category.PRODUCT_TECHNOLOGY,
            importance_score=90,
            impact_direction=ImpactDirection.OPPORTUNITY,
        ),
        make_section(
            "issue-3",
            category=Category.POLICY_REGULATION,
            importance_score=70,
            impact_direction=ImpactDirection.RISK,
        ),
    ]

    report = assemble_generated_report(request=make_request(), sections=sections, generated_at=datetime(2026, 8, 2, 9, 0, 0))

    assert [group.category for group in report.category_groups] == [
        Category.PRODUCT_TECHNOLOGY,
        Category.POLICY_REGULATION,
        Category.MARKET_MANAGEMENT,
    ]


def test_overall_implications_split_opportunities_risks_and_monitoring() -> None:
    sections = [
        make_section(
            "issue-1",
            category=Category.PRODUCT_TECHNOLOGY,
            importance_score=90,
            impact_direction=ImpactDirection.OPPORTUNITY,
            implications=["expand hbm demand"],
            watch_points=["customer validation"],
        ),
        make_section(
            "issue-2",
            category=Category.COMPETITOR,
            importance_score=80,
            impact_direction=ImpactDirection.RISK,
            implications=["pricing pressure"],
            watch_points=["pricing pressure", "share loss"],
        ),
        make_section(
            "issue-3",
            category=Category.POLICY_REGULATION,
            importance_score=70,
            impact_direction=ImpactDirection.NEUTRAL,
            implications=["policy uncertainty"],
            watch_points=["policy guidance"],
        ),
    ]

    report = assemble_generated_report(request=make_request(), sections=sections, generated_at=datetime(2026, 8, 2, 9, 0, 0))

    assert report.overall_implications is not None
    assert report.overall_implications.opportunities == ["expand hbm demand"]
    assert report.overall_implications.risks == ["pricing pressure"]
    assert report.overall_implications.monitoring_points == [
        "customer validation",
        "pricing pressure",
        "share loss",
        "policy uncertainty",
        "policy guidance",
    ]


def test_source_lists_deduplicate_by_first_appearance() -> None:
    sections = [
        make_section(
            "issue-1",
            category=Category.PRODUCT_TECHNOLOGY,
            importance_score=90,
            impact_direction=ImpactDirection.OPPORTUNITY,
            news_ids=["doc-1", "doc-2"],
            wiki_ids=[("page-1", "wiki-1"), ("page-2", "wiki-2")],
        ),
        make_section(
            "issue-2",
            category=Category.COMPETITOR,
            importance_score=80,
            impact_direction=ImpactDirection.RISK,
            news_ids=["doc-2", "doc-3"],
            wiki_ids=[("page-9", "wiki-2"), ("page-3", "wiki-3")],
        ),
    ]

    report = assemble_generated_report(request=make_request(), sections=sections, generated_at=datetime(2026, 8, 2, 9, 0, 0))

    assert [item.document_version_id for item in report.news_sources] == ["doc-1", "doc-2", "doc-3"]
    assert [item.wiki_version_id for item in report.wiki_sources] == ["wiki-1", "wiki-2", "wiki-3"]


def test_duplicate_issue_key_raises_error() -> None:
    sections = [
        make_section(
            "issue-1",
            category=Category.PRODUCT_TECHNOLOGY,
            importance_score=90,
            impact_direction=ImpactDirection.OPPORTUNITY,
        ),
        make_section(
            "issue-1",
            category=Category.COMPETITOR,
            importance_score=80,
            impact_direction=ImpactDirection.RISK,
        ),
    ]

    with pytest.raises(ReportAssemblyError):
        assemble_generated_report(request=make_request(), sections=sections, generated_at=datetime(2026, 8, 2, 9, 0, 0))


def test_empty_sections_raise_error() -> None:
    with pytest.raises(ReportAssemblyError):
        assemble_generated_report(request=make_request(), sections=[], generated_at=datetime(2026, 8, 2, 9, 0, 0))


def test_input_is_not_mutated() -> None:
    sections = [
        make_section(
            "issue-1",
            category=Category.PRODUCT_TECHNOLOGY,
            importance_score=90,
            impact_direction=ImpactDirection.OPPORTUNITY,
        )
    ]
    original = deepcopy(sections)

    assemble_generated_report(request=make_request(), sections=sections, generated_at=datetime(2026, 8, 2, 9, 0, 0))

    assert sections == original


def test_same_input_produces_same_output() -> None:
    sections = [
        make_section(
            "issue-1",
            category=Category.PRODUCT_TECHNOLOGY,
            importance_score=90,
            impact_direction=ImpactDirection.OPPORTUNITY,
        ),
        make_section(
            "issue-2",
            category=Category.COMPETITOR,
            importance_score=80,
            impact_direction=ImpactDirection.RISK,
        ),
    ]
    generated_at = datetime(2026, 8, 2, 9, 0, 0)

    first = assemble_generated_report(request=make_request(), sections=sections, generated_at=generated_at)
    second = assemble_generated_report(request=make_request(), sections=sections, generated_at=generated_at)

    assert first == second

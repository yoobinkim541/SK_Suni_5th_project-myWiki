from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone

import pytest

from src.analysis.importance_models import ImpactDirection, TimeHorizon
from src.analysis.models import Category
from src.report.markdown_renderer import ReportRenderError, render_generated_report_markdown
from src.report.models import (
    GeneratedReport,
    ReportCategoryGroup,
    ReportCitationDraft,
    ReportExecutiveSummary,
    ReportIssueSummaryRow,
    ReportNewsSource,
    ReportOverallImplications,
    ReportSectionDraft,
    ReportStatus,
    ReportType,
    ReportWikiReferenceDraft,
    ReportWikiSource,
)


def make_section(issue_key: str, *, title: str, current_summary: str | None = None) -> ReportSectionDraft:
    return ReportSectionDraft(
        issue_key=issue_key,
        representative_analysis_result_id=f"analysis-{issue_key}",
        category=Category.PRODUCT_TECHNOLOGY,
        importance_score=92,
        impact_direction=ImpactDirection.RISK,
        time_horizon=TimeHorizon.MID_TERM,
        title=title,
        current_summary=current_summary,
        key_facts=[f"{issue_key} 첫 번째 사실", f"{issue_key} 두 번째 사실"],
        historical_context=[f"{issue_key} 과거 배경"],
        implications=[f"{issue_key} 시사점 한 줄"],
        watch_points=[f"{issue_key} 관찰 포인트"],
        news_citations=[
            ReportCitationDraft(
                analysis_result_id=f"analysis-{issue_key}",
                document_version_id=f"doc-ver-{issue_key}",
                citation_order=1,
                document_title=f"{issue_key} 관련 기사 제목 - 뉴시스",
                source_name="Google RSS - SK하이닉스",
                published_at="2026-08-02T07:23:01+00:00",
            )
        ],
        wiki_references=[
            ReportWikiReferenceDraft(
                wiki_page_id=f"wiki-page-{issue_key}",
                wiki_version_id=f"wiki-ver-{issue_key}",
                reference_order=1,
                wiki_title=f"{issue_key} 위키 문서 제목",
            )
        ],
    )


def make_report() -> GeneratedReport:
    sections = [
        make_section("issue-1", title="HBM4 | 생산 확대", current_summary="요약 줄 1"),
        make_section("issue-2", title="경쟁사 투자", current_summary="요약 줄 2"),
    ]
    return GeneratedReport(
        report_id="report-1",
        workspace_id="ws-1",
        report_date=date(2026, 8, 2),
        report_type=ReportType.DAILY,
        title="SK하이닉스 산업 동향 일일 보고서",
        language="ko",
        version=3,
        status=ReportStatus.COMPLETED,
        executive_summaries=[
            ReportExecutiveSummary(issue_key="issue-1", title="HBM4 | 생산 확대", summary="첫 번째 핵심 요약"),
            ReportExecutiveSummary(issue_key="issue-2", title="경쟁사 투자", summary="두 번째 핵심 요약"),
        ],
        issue_summary_rows=[
            ReportIssueSummaryRow(
                issue_key="issue-1",
                category=Category.PRODUCT_TECHNOLOGY,
                title="HBM4 | 생산 확대",
                importance_score=92,
                impact_direction=ImpactDirection.RISK,
                time_horizon=TimeHorizon.MID_TERM,
            )
        ],
        sections=sections,
        category_groups=[
            ReportCategoryGroup(category=Category.PRODUCT_TECHNOLOGY, sections=[sections[0]]),
            ReportCategoryGroup(category=Category.COMPETITOR, sections=[]),
        ],
        overall_implications=ReportOverallImplications(
            opportunities=["기회 요인"],
            risks=["위험 요인"],
            monitoring_points=["모니터링 포인트"],
        ),
        news_sources=[
            ReportNewsSource(
                document_version_id="doc-ver-issue-1",
                document_title="issue-1 관련 기사 제목 - 뉴시스",
                source_name="Google RSS - SK하이닉스",
                published_at="2026-08-02T07:23:01+00:00",
            ),
            ReportNewsSource(document_version_id="doc-ver-issue-2"),
        ],
        wiki_sources=[
            ReportWikiSource(
                wiki_page_id="wiki-page-issue-1", wiki_version_id="wiki-ver-issue-1",
                wiki_title="issue-1 위키 문서 제목",
            ),
            ReportWikiSource(wiki_page_id="wiki-page-issue-2", wiki_version_id="wiki-ver-issue-2"),
        ],
        created_at=datetime(2026, 8, 2, 8, 15, tzinfo=timezone.utc),
        generated_at=datetime(2026, 8, 2, 8, 15, tzinfo=timezone.utc),
    )


def test_render_generated_report_markdown_renders_all_sections() -> None:
    markdown = render_generated_report_markdown(make_report())

    assert "# SK하이닉스 산업 동향 일일 보고서" in markdown
    assert "## 오늘의 핵심 요약" in markdown
    assert "## 주요 이슈 요약표" in markdown
    assert "## 이슈별 상세 분석" in markdown
    assert "## 카테고리별 정리" in markdown
    assert "## 종합 시사점" in markdown
    assert "## 전체 출처" in markdown


def test_render_generated_report_markdown_renders_title_and_dates() -> None:
    markdown = render_generated_report_markdown(make_report())

    assert "- 기준일: 2026-08-02" in markdown
    assert "- 생성 시각: 2026-08-02 17:15 KST" in markdown


def test_render_generated_report_markdown_renders_numbered_executive_summary() -> None:
    markdown = render_generated_report_markdown(make_report())

    assert "1. 첫 번째 핵심 요약" in markdown
    assert "2. 두 번째 핵심 요약" in markdown


def test_render_generated_report_markdown_renders_issue_summary_table_and_escapes_pipe() -> None:
    markdown = render_generated_report_markdown(make_report())

    assert "| 카테고리 | 이슈 제목 | 중요도 | 영향 방향 | 시간 범위 |" in markdown
    assert "HBM4 \\| 생산 확대" in markdown


def test_render_generated_report_markdown_renders_detailed_structure() -> None:
    markdown = render_generated_report_markdown(make_report())

    assert "#### 현재 상황" in markdown
    assert "#### 핵심 사실" in markdown
    assert "#### 과거 배경" in markdown
    assert "#### SK하이닉스 시사점" in markdown
    assert "#### 관찰 포인트" in markdown
    assert "#### 출처" in markdown


def test_render_generated_report_markdown_renders_strings_and_lists() -> None:
    markdown = render_generated_report_markdown(make_report())

    assert "요약 줄 1" in markdown
    assert "- issue-1 첫 번째 사실" in markdown
    assert "- issue-1 두 번째 사실" in markdown


def test_render_generated_report_markdown_renders_section_refs_with_attribution_not_raw_ids() -> None:
    markdown = render_generated_report_markdown(make_report())

    assert "- [N1] issue-1 관련 기사 제목 - 뉴시스 · Google RSS - SK하이닉스 · 2026.08.02" in markdown
    assert "- [W1] issue-1 위키 문서 제목" in markdown
    assert "doc-ver-issue-1" not in markdown
    assert "wiki-page-issue-1" not in markdown


def test_render_generated_report_markdown_falls_back_when_attribution_missing() -> None:
    markdown = render_generated_report_markdown(make_report())

    assert "출처 정보 확인 안 됨" in markdown
    assert "doc-ver-issue-2" not in markdown
    assert "wiki-page-issue-2" not in markdown


def test_render_generated_report_markdown_rejects_duplicate_section_refs() -> None:
    report = make_report()
    report.sections[0].news_citations.append(
        ReportCitationDraft(
            analysis_result_id="analysis-dup",
            document_version_id="doc-ver-dup",
            citation_order=1,
        )
    )

    with pytest.raises(ReportRenderError):
        render_generated_report_markdown(report)


def test_render_generated_report_markdown_category_summary_does_not_repeat_full_body() -> None:
    markdown = render_generated_report_markdown(make_report())

    assert "### 제품·기술" in markdown
    assert "- **HBM4 | 생산 확대**" in markdown
    assert "  요약 줄 1" in markdown
    assert markdown.count("issue-1 첫 번째 사실") == 1


def test_render_generated_report_markdown_preserves_category_order_from_report() -> None:
    markdown = render_generated_report_markdown(make_report())

    assert markdown.index("### 제품·기술") < markdown.index("### 경쟁사")


def test_render_generated_report_markdown_renders_overall_implications() -> None:
    markdown = render_generated_report_markdown(make_report())

    assert "### 기회 요인" in markdown
    assert "- 기회 요인" in markdown
    assert "### 위험 요인" in markdown
    assert "- 위험 요인" in markdown
    assert "### 향후 모니터링 항목" in markdown
    assert "- 모니터링 포인트" in markdown


def test_render_generated_report_markdown_renders_all_sources() -> None:
    markdown = render_generated_report_markdown(make_report())

    assert "### 뉴스 기사" in markdown
    assert "1. issue-1 관련 기사 제목 - 뉴시스 · Google RSS - SK하이닉스 · 2026.08.02" in markdown
    assert "2. 출처 정보 확인 안 됨" in markdown
    assert "### 참고 Wiki" in markdown
    assert "1. issue-1 위키 문서 제목" in markdown
    assert "doc-ver-issue-1" not in markdown
    assert "wiki-page-issue-1" not in markdown


def test_render_generated_report_markdown_handles_empty_lists_without_python_repr() -> None:
    report = make_report()
    report.executive_summaries = []
    report.issue_summary_rows = []
    report.category_groups = []
    report.news_sources = []
    report.wiki_sources = []
    report.overall_implications = ReportOverallImplications()

    markdown = render_generated_report_markdown(report)

    assert "[]" not in markdown
    assert "None" not in markdown
    assert "- 요약된 핵심 이슈가 없습니다." in markdown
    assert "- 보고서에 포함된 주요 이슈가 없습니다." in markdown


def test_render_generated_report_markdown_does_not_mutate_input() -> None:
    report = make_report()
    original = deepcopy(report)

    render_generated_report_markdown(report)

    assert report == original


def test_render_generated_report_markdown_is_deterministic() -> None:
    report = make_report()

    first = render_generated_report_markdown(report)
    second = render_generated_report_markdown(report)

    assert first == second


def test_render_generated_report_markdown_ends_with_single_newline() -> None:
    markdown = render_generated_report_markdown(make_report())

    assert markdown.endswith("\n")
    assert not markdown.endswith("\n\n")

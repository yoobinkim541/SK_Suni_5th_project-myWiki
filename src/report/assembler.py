from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..analysis.importance_models import ImpactDirection
from ..analysis.models import Category
from .models import (
    GeneratedReport,
    ReportCategoryGroup,
    ReportExecutiveSummary,
    ReportGenerationRequest,
    ReportIssueSummaryRow,
    ReportNewsSource,
    ReportOverallImplications,
    ReportSectionDraft,
    ReportStatus,
    ReportWikiSource,
)

try:
    SEOUL_TZ = ZoneInfo("Asia/Seoul")
except ZoneInfoNotFoundError:
    SEOUL_TZ = timezone(timedelta(hours=9), name="Asia/Seoul")

DEFAULT_REPORT_TITLE = "일일 산업 동향 보고서"
CATEGORY_ORDER: tuple[Category, ...] = (
    Category.PRODUCT_TECHNOLOGY,
    Category.COMPETITOR,
    Category.CUSTOMER_DEMAND,
    Category.SUPPLY_PRODUCTION,
    Category.POLICY_REGULATION,
    Category.MARKET_MANAGEMENT,
)


class ReportAssemblyError(ValueError):
    """Raised when report sections cannot be assembled into a valid report."""


def assemble_generated_report(
    *,
    request: ReportGenerationRequest,
    sections: Sequence[ReportSectionDraft],
    generated_at: datetime | None = None,
) -> GeneratedReport:
    ordered_sections = list(sections)
    _validate_sections(ordered_sections)
    report_generated_at = generated_at or datetime.now(UTC).astimezone(SEOUL_TZ)

    return GeneratedReport(
        workspace_id=request.workspace_id,
        report_date=request.report_date,
        report_type=request.report_type,
        title=_build_report_title(),
        language=request.language,
        status=ReportStatus.DRAFTING,
        executive_summaries=_build_executive_summaries(ordered_sections),
        issue_summary_rows=_build_issue_summary_rows(ordered_sections),
        sections=ordered_sections,
        category_groups=_group_sections_by_category(ordered_sections),
        overall_implications=_build_overall_implications(ordered_sections),
        news_sources=_collect_news_sources(ordered_sections),
        wiki_sources=_collect_wiki_sources(ordered_sections),
        generated_at=report_generated_at,
        created_at=report_generated_at,
    )


def _validate_sections(sections: Sequence[ReportSectionDraft]) -> None:
    if not sections:
        raise ReportAssemblyError("at least one section is required to assemble a report.")

    seen_issue_keys: set[str] = set()
    for section in sections:
        if not section.issue_key.strip():
            raise ReportAssemblyError("section issue_key must not be empty.")
        if section.issue_key in seen_issue_keys:
            raise ReportAssemblyError(f"duplicate issue_key is not allowed: {section.issue_key}")
        seen_issue_keys.add(section.issue_key)

        if not section.title.strip():
            raise ReportAssemblyError(f"section title must not be empty: {section.issue_key}")
        if not isinstance(section.category, Category):
            raise ReportAssemblyError(f"invalid category on section: {section.issue_key}")
        if not section.representative_analysis_result_id.strip():
            raise ReportAssemblyError(f"representative_analysis_result_id is required: {section.issue_key}")

        for citation in section.news_citations:
            if not citation.document_version_id.strip():
                raise ReportAssemblyError(f"citation document_version_id is required: {section.issue_key}")

        for wiki_reference in section.wiki_references:
            if not wiki_reference.wiki_version_id or not wiki_reference.wiki_version_id.strip():
                raise ReportAssemblyError(f"wiki_version_id is required for wiki references: {section.issue_key}")


def _build_report_title() -> str:
    return DEFAULT_REPORT_TITLE


def _build_executive_summaries(sections: Sequence[ReportSectionDraft]) -> list[ReportExecutiveSummary]:
    sorted_sections = sorted(
        enumerate(sections),
        key=lambda item: (
            -(item[1].importance_score or -1),
            item[0],
            item[1].issue_key,
        ),
    )
    limit = min(max(len(sections), 3), 5)
    if len(sections) < 3:
        limit = len(sections)
    top_sections = [section for _, section in sorted_sections[:limit]]

    summaries: list[ReportExecutiveSummary] = []
    for section in top_sections:
        summaries.append(
            ReportExecutiveSummary(
                issue_key=section.issue_key,
                title=section.title,
                summary=section.current_summary or section.title,
                importance_score=section.importance_score,
                impact_direction=section.impact_direction,
                time_horizon=section.time_horizon,
            )
        )
    return summaries


def _build_issue_summary_rows(sections: Sequence[ReportSectionDraft]) -> list[ReportIssueSummaryRow]:
    return [
        ReportIssueSummaryRow(
            issue_key=section.issue_key,
            category=section.category,
            title=section.title,
            importance_score=section.importance_score,
            impact_direction=section.impact_direction,
            time_horizon=section.time_horizon,
        )
        for section in sections
    ]


def _group_sections_by_category(sections: Sequence[ReportSectionDraft]) -> list[ReportCategoryGroup]:
    groups: list[ReportCategoryGroup] = []
    for category in CATEGORY_ORDER:
        grouped_sections = [section for section in sections if section.category == category]
        if grouped_sections:
            groups.append(ReportCategoryGroup(category=category, sections=grouped_sections))
    return groups


def _build_overall_implications(sections: Sequence[ReportSectionDraft]) -> ReportOverallImplications:
    opportunities: list[str] = []
    risks: list[str] = []
    monitoring_points: list[str] = []
    seen_opportunities: set[str] = set()
    seen_risks: set[str] = set()
    seen_monitoring: set[str] = set()

    ordered_sections = sorted(
        enumerate(sections),
        key=lambda item: (
            -(item[1].importance_score or -1),
            item[0],
            item[1].issue_key,
        ),
    )

    for _, section in ordered_sections:
        if section.impact_direction == ImpactDirection.OPPORTUNITY:
            for implication in section.implications:
                _append_unique(opportunities, seen_opportunities, implication)
        elif section.impact_direction == ImpactDirection.RISK:
            for implication in section.implications:
                _append_unique(risks, seen_risks, implication)
        else:
            for implication in section.implications:
                _append_unique(monitoring_points, seen_monitoring, implication)

        for watch_point in section.watch_points:
            _append_unique(monitoring_points, seen_monitoring, watch_point)

    return ReportOverallImplications(
        opportunities=opportunities,
        risks=risks,
        monitoring_points=monitoring_points,
    )


def _collect_news_sources(sections: Sequence[ReportSectionDraft]) -> list[ReportNewsSource]:
    collected: list[ReportNewsSource] = []
    seen: set[str] = set()
    for section in sections:
        for citation in section.news_citations:
            document_version_id = citation.document_version_id.strip()
            if document_version_id in seen:
                continue
            seen.add(document_version_id)
            collected.append(ReportNewsSource(document_version_id=document_version_id))
    return collected


def _collect_wiki_sources(sections: Sequence[ReportSectionDraft]) -> list[ReportWikiSource]:
    collected: list[ReportWikiSource] = []
    seen: set[str] = set()
    for section in sections:
        for reference in section.wiki_references:
            wiki_version_id = (reference.wiki_version_id or "").strip()
            if not wiki_version_id or wiki_version_id in seen:
                continue
            seen.add(wiki_version_id)
            collected.append(
                ReportWikiSource(
                    wiki_page_id=reference.wiki_page_id,
                    wiki_version_id=wiki_version_id,
                )
            )
    return collected


def _append_unique(target: list[str], seen: set[str], value: str) -> None:
    normalized = " ".join(value.split())
    if not normalized or normalized in seen:
        return
    seen.add(normalized)
    target.append(normalized)

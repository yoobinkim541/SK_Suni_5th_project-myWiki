from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import GeneratedReport, ReportCategoryGroup, ReportSectionDraft

try:
    SEOUL_TZ = ZoneInfo("Asia/Seoul")
except ZoneInfoNotFoundError:
    SEOUL_TZ = timezone(timedelta(hours=9), name="Asia/Seoul")


class ReportRenderError(ValueError):
    """Raised when a GeneratedReport cannot be rendered safely."""


def render_generated_report_markdown(report: GeneratedReport) -> str:
    _validate_report_for_rendering(report)

    lines: list[str] = []
    _render_header(lines, report)
    _render_executive_summary(lines, report)
    _render_issue_summary_table(lines, report)
    _render_detailed_sections(lines, report)
    _render_category_summary(lines, report)
    _render_overall_implications(lines, report)
    _render_all_sources(lines, report)
    return "\n".join(lines).rstrip() + "\n"


def _validate_report_for_rendering(report: object) -> GeneratedReport:
    if not isinstance(report, GeneratedReport):
        raise ReportRenderError("report must be a GeneratedReport instance.")
    if not report.title:
        raise ReportRenderError("report title is required for rendering.")
    if report.report_date is None:
        raise ReportRenderError("report_date is required for rendering.")
    for section in report.sections:
        if not section.title:
            raise ReportRenderError("each section title is required for rendering.")
        _validate_section_source_refs(section)
    return report


def _validate_section_source_refs(section: ReportSectionDraft) -> None:
    seen_news: set[str] = set()
    for citation in section.news_citations:
        ref = f"N{citation.citation_order}"
        if ref in seen_news:
            raise ReportRenderError(f"duplicate section news ref detected: {ref}")
        seen_news.add(ref)

    seen_wiki: set[str] = set()
    for reference in section.wiki_references:
        ref = f"W{reference.reference_order}"
        if ref in seen_wiki:
            raise ReportRenderError(f"duplicate section wiki ref detected: {ref}")
        seen_wiki.add(ref)


def _render_header(lines: list[str], report: GeneratedReport) -> None:
    lines.append(f"# {_escape_inline_text(report.title or '')}")
    lines.append("")
    lines.append(f"- 기준일: {_format_date(report.report_date)}")
    if report.generated_at is not None:
        lines.append(f"- 생성 시각: {_format_datetime(report.generated_at)}")
    if report.report_type is not None:
        lines.append(f"- 보고서 유형: {report.report_type.value}")
    if report.language:
        lines.append(f"- 언어: {report.language}")
    if report.version is not None:
        lines.append(f"- 버전: {report.version}")
    lines.append("")


def _render_executive_summary(lines: list[str], report: GeneratedReport) -> None:
    lines.append("## 오늘의 핵심 요약")
    lines.append("")
    if not report.executive_summaries:
        lines.append("- 요약된 핵심 이슈가 없습니다.")
        lines.append("")
        return

    for index, item in enumerate(report.executive_summaries, start=1):
        summary = item.summary or item.title
        if not summary:
            continue
        lines.append(f"{index}. {_escape_inline_text(summary)}")
    lines.append("")


def _render_issue_summary_table(lines: list[str], report: GeneratedReport) -> None:
    lines.append("## 주요 이슈 요약표")
    lines.append("")
    if not report.issue_summary_rows:
        lines.append("- 보고서에 포함된 주요 이슈가 없습니다.")
        lines.append("")
        return

    lines.append("| 카테고리 | 이슈 제목 | 중요도 | 영향 방향 | 시간 범위 |")
    lines.append("|---|---|---:|---|---|")
    for row in report.issue_summary_rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    _escape_markdown_table_cell(row.category.value),
                    _escape_markdown_table_cell(row.title),
                    _escape_markdown_table_cell(_format_score(row.importance_score)),
                    _escape_markdown_table_cell(_format_enum_label(row.impact_direction)),
                    _escape_markdown_table_cell(_format_enum_label(row.time_horizon)),
                ]
            )
            + " |"
        )
    lines.append("")


def _render_detailed_sections(lines: list[str], report: GeneratedReport) -> None:
    lines.append("## 이슈별 상세 분석")
    lines.append("")
    for index, section in enumerate(report.sections, start=1):
        _render_section(lines, section, index=index)


def _render_section(lines: list[str], section: ReportSectionDraft, *, index: int) -> None:
    lines.append(f"### {index}. {_escape_inline_text(section.title)}")
    lines.append("")
    metadata = [
        ("카테고리", section.category.value),
        ("중요도", _format_score(section.importance_score)),
        ("영향 방향", _format_enum_label(section.impact_direction)),
        ("시간 범위", _format_enum_label(section.time_horizon)),
    ]
    for label, value in metadata:
        if value:
            lines.append(f"- {label}: {_escape_inline_text(value)}")
    if any(value for _, value in metadata):
        lines.append("")

    _render_text_block(lines, "현재 상황", section.current_summary, required_placeholder=True)
    _render_bullet_block(lines, "핵심 사실", section.key_facts)
    _render_bullet_block(lines, "과거 배경", section.historical_context)
    _render_bullet_block(lines, "SK하이닉스 시사점", section.implications)
    _render_bullet_block(lines, "관찰 포인트", section.watch_points)
    _render_section_sources(lines, section)


def _render_text_block(lines: list[str], title: str, value: str | None, *, required_placeholder: bool) -> None:
    text = (value or "").strip()
    if not text and not required_placeholder:
        return
    lines.append(f"#### {title}")
    lines.append("")
    if text:
        lines.append(_escape_inline_text(text))
    else:
        lines.append("- 제공된 내용이 없습니다.")
    lines.append("")


def _render_bullet_block(lines: list[str], title: str, values: Sequence[str]) -> None:
    normalized = [value.strip() for value in values if value and value.strip()]
    if not normalized:
        return
    lines.append(f"#### {title}")
    lines.append("")
    lines.extend(_render_bullet_list(normalized))
    lines.append("")


def _render_section_sources(lines: list[str], section: ReportSectionDraft) -> None:
    lines.append("#### 출처")
    lines.append("")
    if not section.news_citations and not section.wiki_references:
        lines.append("- 제공된 출처가 없습니다.")
        lines.append("")
        return

    if section.news_citations:
        lines.append("**뉴스**")
        lines.append("")
        for citation in sorted(section.news_citations, key=lambda item: item.citation_order):
            label = f"N{citation.citation_order}"
            body = _escape_inline_text(citation.document_version_id)
            lines.append(f"- [{label}] {body}")
        lines.append("")

    if section.wiki_references:
        lines.append("**Wiki**")
        lines.append("")
        for reference in sorted(section.wiki_references, key=lambda item: item.reference_order):
            label = f"W{reference.reference_order}"
            body = _escape_inline_text(reference.wiki_page_id)
            lines.append(f"- [{label}] {body}")
        lines.append("")


def _render_category_summary(lines: list[str], report: GeneratedReport) -> None:
    lines.append("## 카테고리별 정리")
    lines.append("")
    if not report.category_groups:
        lines.append("- 카테고리별로 정리할 주요 이슈가 없습니다.")
        lines.append("")
        return

    for group in report.category_groups:
        _render_category_group(lines, group)


def _render_category_group(lines: list[str], group: ReportCategoryGroup) -> None:
    lines.append(f"### {_escape_inline_text(group.category.value)}")
    lines.append("")
    if not group.sections:
        lines.append("- 해당 카테고리의 주요 이슈가 없습니다.")
        lines.append("")
        return
    for section in group.sections:
        lines.append(f"- **{_escape_inline_text(section.title)}**")
        summary = (section.current_summary or "").strip()
        if summary:
            lines.append(f"  {_escape_inline_text(summary)}")
    lines.append("")


def _render_overall_implications(lines: list[str], report: GeneratedReport) -> None:
    lines.append("## 종합 시사점")
    lines.append("")
    overall = report.overall_implications
    opportunities = overall.opportunities if overall is not None else []
    risks = overall.risks if overall is not None else []
    monitoring = overall.monitoring_points if overall is not None else []

    _render_named_bullets(lines, "기회 요인", opportunities)
    _render_named_bullets(lines, "위험 요인", risks)
    _render_named_bullets(lines, "향후 모니터링 항목", monitoring)


def _render_named_bullets(lines: list[str], title: str, values: Sequence[str]) -> None:
    lines.append(f"### {title}")
    lines.append("")
    normalized = [value.strip() for value in values if value and value.strip()]
    if not normalized:
        lines.append("- 해당 항목이 없습니다.")
        lines.append("")
        return
    lines.extend(_render_bullet_list(normalized))
    lines.append("")


def _render_all_sources(lines: list[str], report: GeneratedReport) -> None:
    lines.append("## 전체 출처")
    lines.append("")
    lines.append("### 뉴스 기사")
    lines.append("")
    if not report.news_sources:
        lines.append("- 제공된 뉴스 출처가 없습니다.")
        lines.append("")
    else:
        for index, source in enumerate(report.news_sources, start=1):
            lines.append(f"{index}. {_escape_inline_text(source.document_version_id)}")
        lines.append("")

    lines.append("### 참고 Wiki")
    lines.append("")
    if not report.wiki_sources:
        lines.append("- 제공된 Wiki 출처가 없습니다.")
        lines.append("")
        return
    for index, source in enumerate(report.wiki_sources, start=1):
        lines.append(f"{index}. {_escape_inline_text(source.wiki_page_id)}")
    lines.append("")


def _render_bullet_list(values: Sequence[str]) -> list[str]:
    return [f"- {_escape_inline_text(value)}" for value in values if value.strip()]


def _format_date(value: date) -> str:
    return value.isoformat()


def _format_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        localized = value.replace(tzinfo=SEOUL_TZ)
    else:
        localized = value.astimezone(SEOUL_TZ)
    return localized.strftime("%Y-%m-%d %H:%M KST")


def _format_score(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _format_enum_label(value: object) -> str:
    if value is None:
        return ""
    return str(getattr(value, "value", value))


def _escape_markdown_table_cell(value: object) -> str:
    text = _escape_inline_text("" if value is None else str(value))
    return text.replace("|", "\\|")


def _escape_inline_text(value: str) -> str:
    return " ".join(value.replace("\r", "\n").splitlines()).strip()

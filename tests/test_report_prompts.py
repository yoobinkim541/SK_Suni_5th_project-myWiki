from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from src.analysis.models import Category
from src.report.composer import ReportComposerConfig, build_composer_input
from src.report.models import EnrichedIssueGroup, IssueGroup, ReportCandidate, WikiContext
from src.report.prompts import SECTION_PROMPT_VERSION, build_report_section_messages


def _candidate(analysis_result_id: str, *, title: str, summary: str) -> ReportCandidate:
    return ReportCandidate(
        analysis_result_id=analysis_result_id,
        workspace_id="ws-1",
        document_id=f"doc-{analysis_result_id}",
        document_version_id=f"doc-ver-{analysis_result_id}",
        category=Category.PRODUCT_TECHNOLOGY,
        title=title,
        summary=summary,
        reliability_score=82,
        importance_score=89,
        ranking_score=Decimal("92.0"),
        source_name="news-source",
        canonical_url=f"https://example.com/{analysis_result_id}",
        published_at=datetime(2026, 8, 2, 1, 0, tzinfo=timezone.utc),
    )


def test_prompt_separates_news_and_wiki_sources() -> None:
    enriched = EnrichedIssueGroup(
        issue_group=IssueGroup(
            issue_key="issue-1",
            category=Category.PRODUCT_TECHNOLOGY,
            candidates=[
                _candidate("a", title="HBM3E roadmap", summary="HBM3E demand rises."),
                _candidate("b", title="HBM3E production", summary="Production ramps."),
            ],
            representative_analysis_result_id="a",
        ),
        wiki_contexts=[
            WikiContext(
                wiki_page_id="wiki-1",
                wiki_version_id="wiki-ver-1",
                title="HBM history",
                content="Historical HBM context.",
            )
        ],
    )

    composer_input = build_composer_input(enriched, config=ReportComposerConfig())
    system_prompt, user_prompt = build_report_section_messages(composer_input)

    assert SECTION_PROMPT_VERSION == "report-section-v1"
    assert "NEWS SOURCES" in user_prompt
    assert "WIKI SOURCES" in user_prompt
    assert "N1" in user_prompt and "N2" in user_prompt
    assert "W1" in user_prompt
    assert "current_summary: use NEWS SOURCES only" in system_prompt
    assert "historical_context: use WIKI SOURCES only" in system_prompt


def test_prompt_mentions_final_report_seven_part_structure() -> None:
    enriched = EnrichedIssueGroup(
        issue_group=IssueGroup(
            issue_key="issue-1",
            category=Category.PRODUCT_TECHNOLOGY,
            candidates=[_candidate("a", title="HBM3E roadmap", summary="HBM3E demand rises.")],
            representative_analysis_result_id="a",
        ),
        wiki_contexts=[],
    )

    composer_input = build_composer_input(enriched, config=ReportComposerConfig())
    system_prompt, _user_prompt = build_report_section_messages(composer_input)

    assert "1. Report title" in system_prompt
    assert "7. Full references" in system_prompt


def test_prompt_includes_expected_output_sections() -> None:
    enriched = EnrichedIssueGroup(
        issue_group=IssueGroup(
            issue_key="issue-1",
            category=Category.PRODUCT_TECHNOLOGY,
            candidates=[_candidate("a", title="HBM3E roadmap", summary="HBM3E demand rises.")],
            representative_analysis_result_id="a",
        ),
        wiki_contexts=[],
    )

    composer_input = build_composer_input(enriched, config=ReportComposerConfig())
    _system_prompt, user_prompt = build_report_section_messages(composer_input)

    assert '"current_summary"' in user_prompt
    assert '"key_facts"' in user_prompt
    assert '"historical_context"' in user_prompt
    assert '"implications"' in user_prompt
    assert '"watch_points"' in user_prompt

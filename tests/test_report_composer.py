from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.analysis.importance_models import ImpactDirection, TimeHorizon
from src.analysis.models import Category
from src.report.composer import (
    GeneratedReportSectionPayload,
    ReportComposerConfig,
    ReportComposerError,
    build_composer_input,
    build_report_citation_drafts,
    build_report_wiki_reference_drafts,
    collect_used_news_refs,
    collect_used_wiki_refs,
    compose_report_section,
    compose_report_sections,
)
from src.report.models import EnrichedIssueGroup, IssueGroup, ReportCandidate, WikiContext


def make_candidate(
    analysis_result_id: str,
    *,
    title: str,
    summary: str,
    importance_score: int = 88,
    impact_direction: ImpactDirection = ImpactDirection.OPPORTUNITY,
    time_horizon: TimeHorizon = TimeHorizon.MID_TERM,
) -> ReportCandidate:
    return ReportCandidate(
        analysis_result_id=analysis_result_id,
        workspace_id="ws-1",
        document_id=f"doc-{analysis_result_id}",
        document_version_id=f"doc-ver-{analysis_result_id}",
        category=Category.PRODUCT_TECHNOLOGY,
        title=title,
        summary=summary,
        reliability_score=85,
        importance_score=importance_score,
        ranking_score=Decimal("93.0"),
        source_name="source",
        canonical_url=f"https://example.com/{analysis_result_id}",
        published_at=datetime(2026, 8, 2, 1, 0, tzinfo=timezone.utc),
        impact_direction=impact_direction,
        time_horizon=time_horizon,
    )


def make_group(*, wiki_contexts: list[WikiContext] | None = None) -> EnrichedIssueGroup:
    return EnrichedIssueGroup(
        issue_group=IssueGroup(
            issue_key="issue-1",
            category=Category.PRODUCT_TECHNOLOGY,
            candidates=[
                make_candidate("a", title="HBM3E roadmap", summary="HBM3E demand rises for AI servers."),
                make_candidate("b", title="HBM3E production", summary="Production ramps for AI servers."),
            ],
            representative_analysis_result_id="a",
        ),
        wiki_contexts=wiki_contexts or [
            WikiContext(
                wiki_page_id="wiki-1",
                wiki_version_id="wiki-ver-1",
                title="HBM history",
                content="Historical HBM context.",
                similarity_score=0.8,
                updated_at=datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc),
                source_document_version_ids=["doc-ver-old"],
            )
        ],
    )


def valid_response() -> str:
    return json.dumps(
        {
            "title": "HBM3E roadmap update",
            "current_summary": {"text": "Current situation.", "news_refs": ["N1"]},
            "key_facts": [
                {"text": "Fact one.", "news_refs": ["N1"]},
                {"text": "Fact two.", "news_refs": ["N2"]},
            ],
            "historical_context": [
                {"text": "Background.", "wiki_refs": ["W1"]},
            ],
            "implications": [
                {"text": "Implication.", "news_refs": ["N1"], "wiki_refs": ["W1"], "is_inference": True},
            ],
            "watch_points": [
                {"text": "Watch this.", "news_refs": ["N2"], "wiki_refs": []},
            ],
        }
    )


def test_build_composer_input_assigns_deterministic_refs() -> None:
    composer_input = build_composer_input(make_group(), config=ReportComposerConfig())

    assert [item.source_ref for item in composer_input.news_sources] == ["N1", "N2"]
    assert composer_input.news_sources[0].is_representative is True
    assert [item.source_ref for item in composer_input.wiki_sources] == ["W1"]


def test_build_composer_input_truncates_wiki_without_mutating_original() -> None:
    original_content = "A" * 20
    group = make_group(
        wiki_contexts=[
            WikiContext(
                wiki_page_id="wiki-1",
                wiki_version_id="wiki-ver-1",
                title="HBM history",
                content=original_content,
            )
        ]
    )

    composer_input = build_composer_input(
        group,
        config=ReportComposerConfig(max_wiki_chars_per_context=5, max_total_wiki_chars=5),
    )

    assert composer_input.wiki_sources[0].content == "AAAAA"
    assert composer_input.wiki_sources[0].content_truncated is True
    assert group.wiki_contexts[0].content == original_content


def test_compose_report_section_maps_valid_output_to_section_draft() -> None:
    section = compose_report_section(
        make_group(),
        config=ReportComposerConfig(),
        llm_client=lambda _system, _user, _config: valid_response(),
    )

    assert section.issue_key == "issue-1"
    assert section.representative_analysis_result_id == "a"
    assert section.category == Category.PRODUCT_TECHNOLOGY
    assert section.importance_score == 88
    assert section.impact_direction == ImpactDirection.OPPORTUNITY
    assert section.time_horizon == TimeHorizon.MID_TERM
    assert section.news_citations[0].document_version_id == "doc-ver-a"
    assert section.wiki_references[0].wiki_version_id == "wiki-ver-1"
    # 렌더러가 document_version_id/wiki_page_id 원문을 그대로 노출하지 않도록,
    # 표시용 메타데이터(제목·매체명·게시일)가 여기서부터 채워져 있어야 한다.
    assert section.news_citations[0].document_title == "HBM3E roadmap"
    assert section.news_citations[0].source_name == "source"
    assert section.news_citations[0].published_at == "2026-08-02T01:00:00+00:00"
    assert section.wiki_references[0].wiki_title == "HBM history"


def test_build_report_citation_drafts_carries_display_attribution_from_candidate() -> None:
    composer_input = build_composer_input(make_group(), config=ReportComposerConfig())
    payload = GeneratedReportSectionPayload.model_validate(json.loads(valid_response()))

    drafts = build_report_citation_drafts(composer_input=composer_input, payload=payload)

    assert drafts[0].document_title == "HBM3E roadmap"
    assert drafts[0].source_name == "source"
    assert drafts[0].published_at == "2026-08-02T01:00:00+00:00"


def test_build_report_wiki_reference_drafts_carries_wiki_title() -> None:
    composer_input = build_composer_input(make_group(), config=ReportComposerConfig())
    payload = GeneratedReportSectionPayload.model_validate(json.loads(valid_response()))

    drafts = build_report_wiki_reference_drafts(composer_input=composer_input, payload=payload)

    assert drafts[0].wiki_title == "HBM history"


def test_compose_report_section_allows_empty_historical_context_when_no_wiki() -> None:
    response = json.dumps(
        {
            "title": "HBM3E roadmap update",
            "current_summary": {"text": "Current situation.", "news_refs": ["N1"]},
            "key_facts": [{"text": "Fact one.", "news_refs": ["N1"]}],
            "historical_context": [],
            "implications": [{"text": "Implication.", "news_refs": ["N1"], "wiki_refs": []}],
            "watch_points": [{"text": "Watch this.", "news_refs": ["N1"], "wiki_refs": []}],
        }
    )
    section = compose_report_section(
        make_group(wiki_contexts=[]),
        config=ReportComposerConfig(),
        llm_client=lambda _system, _user, _config: response,
    )

    assert section.historical_context == []


def test_compose_report_section_rejects_unknown_news_ref() -> None:
    response = json.dumps(
        {
            "title": "HBM3E roadmap update",
            "current_summary": {"text": "Current situation.", "news_refs": ["N3"]},
            "key_facts": [],
            "historical_context": [],
            "implications": [{"text": "Implication.", "news_refs": ["N1"], "wiki_refs": []}],
            "watch_points": [{"text": "Watch this.", "news_refs": ["N1"], "wiki_refs": []}],
        }
    )

    with pytest.raises(ReportComposerError):
        compose_report_section(
            make_group(wiki_contexts=[]),
            config=ReportComposerConfig(max_retries=0),
            llm_client=lambda _system, _user, _config: response,
        )


def test_compose_report_section_rejects_unknown_wiki_ref() -> None:
    response = json.dumps(
        {
            "title": "HBM3E roadmap update",
            "current_summary": {"text": "Current situation.", "news_refs": ["N1"]},
            "key_facts": [{"text": "Fact one.", "news_refs": ["N1"]}],
            "historical_context": [{"text": "Background.", "wiki_refs": ["W2"]}],
            "implications": [{"text": "Implication.", "news_refs": ["N1"], "wiki_refs": []}],
            "watch_points": [{"text": "Watch this.", "news_refs": ["N1"], "wiki_refs": []}],
        }
    )

    with pytest.raises(ReportComposerError):
        compose_report_section(
            make_group(),
            config=ReportComposerConfig(max_retries=0),
            llm_client=lambda _system, _user, _config: response,
        )


def test_compose_report_section_rejects_key_fact_without_news_ref() -> None:
    response = json.dumps(
        {
            "title": "HBM3E roadmap update",
            "current_summary": {"text": "Current situation.", "news_refs": ["N1"]},
            "key_facts": [{"text": "Fact one.", "news_refs": []}],
            "historical_context": [],
            "implications": [{"text": "Implication.", "news_refs": ["N1"], "wiki_refs": []}],
            "watch_points": [{"text": "Watch this.", "news_refs": ["N1"], "wiki_refs": []}],
        }
    )

    with pytest.raises(ReportComposerError):
        compose_report_section(
            make_group(wiki_contexts=[]),
            config=ReportComposerConfig(max_retries=0),
            llm_client=lambda _system, _user, _config: response,
        )


def test_compose_report_section_rejects_historical_context_without_wiki_ref() -> None:
    response = json.dumps(
        {
            "title": "HBM3E roadmap update",
            "current_summary": {"text": "Current situation.", "news_refs": ["N1"]},
            "key_facts": [{"text": "Fact one.", "news_refs": ["N1"]}],
            "historical_context": [{"text": "Background.", "wiki_refs": []}],
            "implications": [{"text": "Implication.", "news_refs": ["N1"], "wiki_refs": []}],
            "watch_points": [{"text": "Watch this.", "news_refs": ["N1"], "wiki_refs": []}],
        }
    )

    with pytest.raises(ReportComposerError):
        compose_report_section(
            make_group(),
            config=ReportComposerConfig(max_retries=0),
            llm_client=lambda _system, _user, _config: response,
        )


def test_compose_report_section_rejects_current_summary_using_wiki_only() -> None:
    response = json.dumps(
        {
            "title": "HBM3E roadmap update",
            "current_summary": {"text": "Current situation.", "news_refs": [], "wiki_refs": ["W1"]},
            "key_facts": [{"text": "Fact one.", "news_refs": ["N1"]}],
            "historical_context": [{"text": "Background.", "wiki_refs": ["W1"]}],
            "implications": [{"text": "Implication.", "news_refs": ["N1"], "wiki_refs": []}],
            "watch_points": [{"text": "Watch this.", "news_refs": ["N1"], "wiki_refs": []}],
        }
    )

    with pytest.raises(ReportComposerError):
        compose_report_section(
            make_group(),
            config=ReportComposerConfig(max_retries=0),
            llm_client=lambda _system, _user, _config: response,
        )


def test_collect_reference_drafts_only_uses_referenced_sources() -> None:
    composer_input = build_composer_input(make_group(), config=ReportComposerConfig())
    parsed = GeneratedReportSectionPayload.model_validate(json.loads(valid_response()))

    assert collect_used_news_refs(parsed) == ["N1", "N2"]
    assert collect_used_wiki_refs(parsed) == ["W1"]

    news_drafts = build_report_citation_drafts(composer_input=composer_input, payload=parsed)
    wiki_drafts = build_report_wiki_reference_drafts(composer_input=composer_input, payload=parsed)

    assert [item.document_version_id for item in news_drafts] == ["doc-ver-a", "doc-ver-b"]
    assert [item.wiki_version_id for item in wiki_drafts] == ["wiki-ver-1"]


def test_compose_report_section_retries_until_valid_response() -> None:
    responses = iter(
        [
            json.dumps(
                {
                    "title": "HBM3E roadmap update",
                    "current_summary": {"text": "Current situation.", "news_refs": ["N9"]},
                    "key_facts": [],
                    "historical_context": [],
                    "implications": [{"text": "Implication.", "news_refs": ["N1"], "wiki_refs": []}],
                    "watch_points": [{"text": "Watch this.", "news_refs": ["N1"], "wiki_refs": []}],
                }
            ),
            valid_response(),
        ]
    )

    section = compose_report_section(
        make_group(),
        config=ReportComposerConfig(max_retries=1),
        llm_client=lambda _system, _user, _config: next(responses),
    )

    assert section.title == "HBM3E roadmap update"


def test_compose_report_sections_preserves_input_order() -> None:
    first = make_group()
    second = EnrichedIssueGroup(
        issue_group=IssueGroup(
            issue_key="issue-2",
            category=Category.PRODUCT_TECHNOLOGY,
            candidates=[make_candidate("c", title="DDR5 pricing", summary="DDR5 prices move.")],
            representative_analysis_result_id="c",
        ),
        wiki_contexts=[],
    )

    sections = compose_report_sections(
        [first, second],
        config=ReportComposerConfig(),
        llm_client=lambda _system, _user, _config: json.dumps(
            {
                "title": "Section",
                "current_summary": {"text": "Current situation.", "news_refs": ["N1"]},
                "key_facts": [{"text": "Fact one.", "news_refs": ["N1"]}],
                "historical_context": [],
                "implications": [{"text": "Implication.", "news_refs": ["N1"], "wiki_refs": []}],
                "watch_points": [{"text": "Watch this.", "news_refs": ["N1"], "wiki_refs": []}],
            }
        ),
    )

    assert [section.issue_key for section in sections] == ["issue-1", "issue-2"]

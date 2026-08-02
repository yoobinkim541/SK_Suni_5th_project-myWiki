from __future__ import annotations

from datetime import date
from decimal import Decimal
from inspect import signature
from typing import get_type_hints

import pytest

from src.analysis.importance_models import ImpactDirection, TimeHorizon
from src.analysis.models import Category
from src.report.interface import DailyReportGenerationResult, ReportGenerationConfig, generate_daily_report
from src.report.models import (
    EnrichedIssueGroup,
    GeneratedReport,
    IssueGroup,
    ReportCandidate,
    ReportGenerationRequest,
    ReportSectionDraft,
    ReportStatus,
)
from src.report.repository import SavedReportArtifact


def test_generate_daily_report_signature_uses_report_models() -> None:
    hints = get_type_hints(generate_daily_report)
    params = signature(generate_daily_report).parameters

    assert list(params.keys()) == ["request", "supabase", "llm_client", "generated_at", "config"]
    assert hints["request"] is ReportGenerationRequest
    assert hints["return"] is DailyReportGenerationResult


def test_report_generation_config_has_component_configs() -> None:
    config = ReportGenerationConfig()

    assert config.selection.max_candidates is None
    assert config.selection.min_reliability_score == 70
    assert config.selection.min_importance_score == 70
    assert config.wiki.limit_per_group >= 0
    assert config.composer.prompt_version


def _make_request() -> ReportGenerationRequest:
    return ReportGenerationRequest(
        workspace_id="ws-1",
        report_date=date(2026, 8, 2),
        max_sections=5,
    )


def _make_candidate(analysis_result_id: str) -> ReportCandidate:
    return ReportCandidate(
        analysis_result_id=analysis_result_id,
        workspace_id="ws-1",
        document_id=f"doc-{analysis_result_id}",
        document_version_id=f"doc-ver-{analysis_result_id}",
        category=Category.PRODUCT_TECHNOLOGY,
        title=f"title-{analysis_result_id}",
        summary=f"summary-{analysis_result_id}",
        reliability_score=80,
        importance_score=85,
        ranking_score=Decimal("90"),
        published_at="2026-08-02T00:00:00+00:00",
        impact_direction=ImpactDirection.OPPORTUNITY,
        time_horizon=TimeHorizon.MID_TERM,
    )


def _make_issue_group(issue_key: str = "issue-1") -> IssueGroup:
    candidate = _make_candidate(f"candidate-{issue_key}")
    return IssueGroup(
        issue_key=issue_key,
        category=candidate.category,
        candidates=[candidate],
        representative_analysis_result_id=candidate.analysis_result_id,
    )


def _make_enriched_group(issue_key: str = "issue-1") -> EnrichedIssueGroup:
    return EnrichedIssueGroup(issue_group=_make_issue_group(issue_key))


def _make_section(issue_key: str = "issue-1") -> ReportSectionDraft:
    return ReportSectionDraft(
        issue_key=issue_key,
        representative_analysis_result_id=f"analysis-{issue_key}",
        category=Category.PRODUCT_TECHNOLOGY,
        importance_score=88,
        impact_direction=ImpactDirection.OPPORTUNITY,
        time_horizon=TimeHorizon.MID_TERM,
        title=f"title-{issue_key}",
        current_summary=f"summary-{issue_key}",
    )


def _make_created_report() -> GeneratedReport:
    return GeneratedReport(
        report_id="report-1",
        workspace_id="ws-1",
        report_date=date(2026, 8, 2),
        report_type="daily",
        version=1,
        status=ReportStatus.PENDING,
        created_at="2026-08-02T08:00:00+00:00",
    )


def _make_artifact() -> SavedReportArtifact:
    return SavedReportArtifact(
        artifact_id="artifact-1",
        report_id="report-1",
        artifact_type="markdown",
        object_key="ws-1/reports/report-1/markdown/v1.md",
        version=1,
        mime_type="text/markdown",
        file_size=123,
        content_hash="abc123",
        storage_bucket="reports",
    )


def _patch_pipeline_stages(monkeypatch: pytest.MonkeyPatch, sections: list[ReportSectionDraft]) -> None:
    monkeypatch.setattr("src.report.interface.create_report_version", lambda **kwargs: _make_created_report())
    monkeypatch.setattr("src.report.interface.get_report_candidates", lambda **kwargs: [_make_candidate("a")])
    monkeypatch.setattr("src.report.interface.select_report_candidates", lambda *args, **kwargs: [_make_candidate("a")])
    monkeypatch.setattr("src.report.interface.group_report_candidates", lambda *args, **kwargs: [_make_issue_group("issue-1")])
    monkeypatch.setattr("src.report.interface.enrich_issue_groups", lambda *args, **kwargs: [_make_enriched_group("issue-1")])
    monkeypatch.setattr("src.report.interface.compose_report_sections", lambda *args, **kwargs: sections)
    monkeypatch.setattr(
        "src.report.interface.assemble_generated_report",
        lambda **kwargs: GeneratedReport(
            workspace_id="ws-1",
            report_date=date(2026, 8, 2),
            report_type="daily",
            status=ReportStatus.DRAFTING,
            sections=sections,
        ),
    )
    monkeypatch.setattr("src.report.interface.save_report_sections", lambda **kwargs: [object()])
    monkeypatch.setattr("src.report.interface.create_and_save_markdown_artifact", lambda **kwargs: _make_artifact())
    monkeypatch.setattr("src.report.interface.mark_report_completed", lambda **kwargs: None)


def test_generate_daily_report_calls_wiki_draft_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, int, str]] = []
    sections = [_make_section("issue-1")]
    _patch_pipeline_stages(monkeypatch, sections)
    monkeypatch.setattr(
        "src.report.interface.generate_wiki_drafts_for_sections",
        lambda sections, enriched_groups, *, workspace_id, requested_by=None: calls.append(
            (len(sections), len(enriched_groups), workspace_id)
        )
        or [],
    )

    generate_daily_report(_make_request())

    assert len(calls) == 1
    assert calls[0] == (1, 1, "ws-1")


def test_generate_daily_report_survives_wiki_draft_generation_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    sections = [_make_section("issue-1")]
    _patch_pipeline_stages(monkeypatch, sections)
    monkeypatch.setattr(
        "src.report.interface.generate_wiki_drafts_for_sections",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("wiki 생성 실패")),
    )

    result = generate_daily_report(_make_request())

    assert result.report.status == ReportStatus.COMPLETED

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from src.analysis.importance_models import ImpactDirection, TimeHorizon
from src.analysis.models import Category
from src.report.interface import ReportGenerationConfig, generate_daily_report
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


def make_request() -> ReportGenerationRequest:
    return ReportGenerationRequest(
        workspace_id="ws-1",
        report_date=date(2026, 8, 2),
        max_sections=5,
    )


def make_candidate(analysis_result_id: str, *, category: Category = Category.PRODUCT_TECHNOLOGY) -> ReportCandidate:
    return ReportCandidate(
        analysis_result_id=analysis_result_id,
        workspace_id="ws-1",
        document_id=f"doc-{analysis_result_id}",
        document_version_id=f"doc-ver-{analysis_result_id}",
        category=category,
        title=f"title-{analysis_result_id}",
        summary=f"summary-{analysis_result_id}",
        reliability_score=80,
        importance_score=85,
        ranking_score=Decimal("90"),
        published_at="2026-08-02T00:00:00+00:00",
        impact_direction=ImpactDirection.OPPORTUNITY,
        time_horizon=TimeHorizon.MID_TERM,
    )


def make_issue_group(issue_key: str = "issue-1") -> IssueGroup:
    candidate = make_candidate(f"candidate-{issue_key}")
    return IssueGroup(
        issue_key=issue_key,
        category=candidate.category,
        candidates=[candidate],
        representative_analysis_result_id=candidate.analysis_result_id,
    )


def make_enriched_group(issue_key: str = "issue-1") -> EnrichedIssueGroup:
    return EnrichedIssueGroup(issue_group=make_issue_group(issue_key))


def make_section(issue_key: str = "issue-1") -> ReportSectionDraft:
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


def make_created_report() -> GeneratedReport:
    return GeneratedReport(
        report_id="report-1",
        workspace_id="ws-1",
        report_date=date(2026, 8, 2),
        report_type="daily",
        version=1,
        status=ReportStatus.PENDING,
        created_at="2026-08-02T08:00:00+00:00",
    )


def make_assembled_report(sections: list[ReportSectionDraft] | None = None) -> GeneratedReport:
    return GeneratedReport(
        workspace_id="ws-1",
        report_date=date(2026, 8, 2),
        report_type="daily",
        status=ReportStatus.DRAFTING,
        sections=sections or [],
    )


def make_artifact() -> SavedReportArtifact:
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


def test_generate_daily_report_runs_pipeline_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    candidates = [make_candidate("a")]
    selected = [make_candidate("a")]
    groups = [make_issue_group("issue-1")]
    enriched = [make_enriched_group("issue-1")]
    sections = [make_section("issue-1")]
    assembled = make_assembled_report(sections)
    artifact = make_artifact()

    def fake_create(**kwargs):
        calls.append("create")
        return make_created_report()

    def fake_candidates(**kwargs):
        calls.append("candidates")
        return candidates

    def fake_select(*args, **kwargs):
        calls.append("select")
        return selected

    def fake_group(*args, **kwargs):
        calls.append("group")
        return groups

    def fake_wiki(*args, **kwargs):
        calls.append("wiki")
        return enriched

    def fake_compose(*args, **kwargs):
        calls.append("compose")
        return sections

    def fake_assemble(**kwargs):
        calls.append("assemble")
        return assembled

    def fake_save(**kwargs):
        calls.append("save")
        return [object()]

    def fake_artifact(**kwargs):
        calls.append("artifact")
        return artifact

    def fake_complete(**kwargs):
        calls.append("complete")

    monkeypatch.setattr("src.report.interface.create_report_version", fake_create)
    monkeypatch.setattr("src.report.interface.get_report_candidates", fake_candidates)
    monkeypatch.setattr("src.report.interface.select_report_candidates", fake_select)
    monkeypatch.setattr("src.report.interface.group_report_candidates", fake_group)
    monkeypatch.setattr("src.report.interface.enrich_issue_groups", fake_wiki)
    monkeypatch.setattr("src.report.interface.compose_report_sections", fake_compose)
    monkeypatch.setattr("src.report.interface.assemble_generated_report", fake_assemble)
    monkeypatch.setattr("src.report.interface.save_report_sections", fake_save)
    monkeypatch.setattr("src.report.interface.create_and_save_markdown_artifact", fake_artifact)
    monkeypatch.setattr("src.report.interface.mark_report_completed", fake_complete)

    result = generate_daily_report(make_request(), generated_at=datetime(2026, 8, 2, 9, 0, 0))

    assert calls == ["create", "candidates", "select", "group", "wiki", "compose", "assemble", "save", "artifact", "complete"]
    assert result.report is assembled
    assert result.report.report_id == "report-1"
    assert result.report.version == 1
    assert result.report.status == ReportStatus.COMPLETED
    assert result.artifact == artifact


def test_generate_daily_report_returns_report_and_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    assembled = make_assembled_report()
    artifact = make_artifact()

    monkeypatch.setattr("src.report.interface.create_report_version", lambda **kwargs: make_created_report())
    monkeypatch.setattr("src.report.interface.get_report_candidates", lambda **kwargs: [make_candidate("a")])
    monkeypatch.setattr("src.report.interface.select_report_candidates", lambda *args, **kwargs: [make_candidate("a")])
    monkeypatch.setattr("src.report.interface.group_report_candidates", lambda *args, **kwargs: [make_issue_group("issue-1")])
    monkeypatch.setattr("src.report.interface.enrich_issue_groups", lambda *args, **kwargs: [make_enriched_group("issue-1")])
    monkeypatch.setattr("src.report.interface.compose_report_sections", lambda *args, **kwargs: [make_section("issue-1")])
    monkeypatch.setattr("src.report.interface.assemble_generated_report", lambda **kwargs: assembled)
    monkeypatch.setattr("src.report.interface.save_report_sections", lambda **kwargs: [object()])
    monkeypatch.setattr("src.report.interface.create_and_save_markdown_artifact", lambda **kwargs: artifact)
    monkeypatch.setattr("src.report.interface.mark_report_completed", lambda **kwargs: None)

    result = generate_daily_report(make_request())

    assert result.report is assembled
    assert result.artifact == artifact
    assert result.report.artifact_id == artifact.artifact_id
    assert result.report.artifact_object_key == artifact.object_key


def test_generate_daily_report_uses_same_section_drafts_for_assemble_and_persist(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}
    section_drafts = [make_section("issue-1")]

    def fake_assemble(**kwargs):
        seen["assembled_sections"] = kwargs["sections"]
        return make_assembled_report(section_drafts)

    def fake_save(**kwargs):
        seen["saved_sections"] = kwargs["sections"]
        return [object()]

    monkeypatch.setattr("src.report.interface.create_report_version", lambda **kwargs: make_created_report())
    monkeypatch.setattr("src.report.interface.get_report_candidates", lambda **kwargs: [make_candidate("a")])
    monkeypatch.setattr("src.report.interface.select_report_candidates", lambda *args, **kwargs: [make_candidate("a")])
    monkeypatch.setattr("src.report.interface.group_report_candidates", lambda *args, **kwargs: [make_issue_group("issue-1")])
    monkeypatch.setattr("src.report.interface.enrich_issue_groups", lambda *args, **kwargs: [make_enriched_group("issue-1")])
    monkeypatch.setattr("src.report.interface.compose_report_sections", lambda *args, **kwargs: section_drafts)
    monkeypatch.setattr("src.report.interface.assemble_generated_report", fake_assemble)
    monkeypatch.setattr("src.report.interface.save_report_sections", fake_save)
    monkeypatch.setattr("src.report.interface.create_and_save_markdown_artifact", lambda **kwargs: make_artifact())
    monkeypatch.setattr("src.report.interface.mark_report_completed", lambda **kwargs: None)

    generate_daily_report(make_request())

    assert seen["assembled_sections"] is section_drafts
    assert seen["saved_sections"] is section_drafts


def test_generate_daily_report_marks_failed_when_candidate_loading_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    marked: list[str] = []
    monkeypatch.setattr("src.report.interface.create_report_version", lambda **kwargs: make_created_report())
    monkeypatch.setattr("src.report.interface.get_report_candidates", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr("src.report.interface.mark_report_failed", lambda **kwargs: marked.append(kwargs["report_id"]))

    with pytest.raises(RuntimeError):
        generate_daily_report(make_request())

    assert marked == ["report-1"]


def test_generate_daily_report_stops_after_selector_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr("src.report.interface.create_report_version", lambda **kwargs: make_created_report())
    monkeypatch.setattr("src.report.interface.get_report_candidates", lambda **kwargs: [make_candidate("a")])
    monkeypatch.setattr("src.report.interface.select_report_candidates", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("bad select")))
    monkeypatch.setattr("src.report.interface.group_report_candidates", lambda *args, **kwargs: calls.append("group") or [])
    monkeypatch.setattr("src.report.interface.mark_report_failed", lambda **kwargs: calls.append("failed") or None)

    with pytest.raises(RuntimeError):
        generate_daily_report(make_request())

    assert calls == ["failed"]


def test_generate_daily_report_wiki_fail_open_is_delegated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.report.interface.create_report_version", lambda **kwargs: make_created_report())
    monkeypatch.setattr("src.report.interface.get_report_candidates", lambda **kwargs: [make_candidate("a")])
    monkeypatch.setattr("src.report.interface.select_report_candidates", lambda *args, **kwargs: [make_candidate("a")])
    monkeypatch.setattr("src.report.interface.group_report_candidates", lambda *args, **kwargs: [make_issue_group("issue-1")])
    monkeypatch.setattr("src.report.interface.enrich_issue_groups", lambda *args, **kwargs: [make_enriched_group("issue-1")])
    monkeypatch.setattr("src.report.interface.compose_report_sections", lambda *args, **kwargs: [make_section("issue-1")])
    monkeypatch.setattr("src.report.interface.assemble_generated_report", lambda **kwargs: make_assembled_report([make_section("issue-1")]))
    monkeypatch.setattr("src.report.interface.save_report_sections", lambda **kwargs: [object()])
    monkeypatch.setattr("src.report.interface.create_and_save_markdown_artifact", lambda **kwargs: make_artifact())
    monkeypatch.setattr("src.report.interface.mark_report_completed", lambda **kwargs: None)

    result = generate_daily_report(make_request())

    assert result.report.report_id == "report-1"


def test_generate_daily_report_marks_failed_when_composer_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    marked: list[str] = []
    monkeypatch.setattr("src.report.interface.create_report_version", lambda **kwargs: make_created_report())
    monkeypatch.setattr("src.report.interface.get_report_candidates", lambda **kwargs: [make_candidate("a")])
    monkeypatch.setattr("src.report.interface.select_report_candidates", lambda *args, **kwargs: [make_candidate("a")])
    monkeypatch.setattr("src.report.interface.group_report_candidates", lambda *args, **kwargs: [make_issue_group("issue-1")])
    monkeypatch.setattr("src.report.interface.enrich_issue_groups", lambda *args, **kwargs: [make_enriched_group("issue-1")])
    monkeypatch.setattr("src.report.interface.compose_report_sections", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("compose failed")))
    monkeypatch.setattr("src.report.interface.mark_report_failed", lambda **kwargs: marked.append(kwargs["report_id"]))

    with pytest.raises(RuntimeError):
        generate_daily_report(make_request())

    assert marked == ["report-1"]


def test_generate_daily_report_marks_failed_when_assembler_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    marked: list[str] = []
    monkeypatch.setattr("src.report.interface.create_report_version", lambda **kwargs: make_created_report())
    monkeypatch.setattr("src.report.interface.get_report_candidates", lambda **kwargs: [make_candidate("a")])
    monkeypatch.setattr("src.report.interface.select_report_candidates", lambda *args, **kwargs: [make_candidate("a")])
    monkeypatch.setattr("src.report.interface.group_report_candidates", lambda *args, **kwargs: [make_issue_group("issue-1")])
    monkeypatch.setattr("src.report.interface.enrich_issue_groups", lambda *args, **kwargs: [make_enriched_group("issue-1")])
    monkeypatch.setattr("src.report.interface.compose_report_sections", lambda *args, **kwargs: [make_section("issue-1")])
    monkeypatch.setattr("src.report.interface.assemble_generated_report", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("assemble failed")))
    monkeypatch.setattr("src.report.interface.mark_report_failed", lambda **kwargs: marked.append(kwargs["report_id"]))

    with pytest.raises(RuntimeError):
        generate_daily_report(make_request())

    assert marked == ["report-1"]


def test_generate_daily_report_marks_failed_when_section_save_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    marked: list[str] = []
    monkeypatch.setattr("src.report.interface.create_report_version", lambda **kwargs: make_created_report())
    monkeypatch.setattr("src.report.interface.get_report_candidates", lambda **kwargs: [make_candidate("a")])
    monkeypatch.setattr("src.report.interface.select_report_candidates", lambda *args, **kwargs: [make_candidate("a")])
    monkeypatch.setattr("src.report.interface.group_report_candidates", lambda *args, **kwargs: [make_issue_group("issue-1")])
    monkeypatch.setattr("src.report.interface.enrich_issue_groups", lambda *args, **kwargs: [make_enriched_group("issue-1")])
    monkeypatch.setattr("src.report.interface.compose_report_sections", lambda *args, **kwargs: [make_section("issue-1")])
    monkeypatch.setattr("src.report.interface.assemble_generated_report", lambda **kwargs: make_assembled_report([make_section("issue-1")]))
    monkeypatch.setattr("src.report.interface.save_report_sections", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("save failed")))
    monkeypatch.setattr("src.report.interface.mark_report_failed", lambda **kwargs: marked.append(kwargs["report_id"]))

    with pytest.raises(RuntimeError):
        generate_daily_report(make_request())

    assert marked == ["report-1"]


def test_generate_daily_report_marks_failed_when_artifact_save_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    marked: list[str] = []
    monkeypatch.setattr("src.report.interface.create_report_version", lambda **kwargs: make_created_report())
    monkeypatch.setattr("src.report.interface.get_report_candidates", lambda **kwargs: [make_candidate("a")])
    monkeypatch.setattr("src.report.interface.select_report_candidates", lambda *args, **kwargs: [make_candidate("a")])
    monkeypatch.setattr("src.report.interface.group_report_candidates", lambda *args, **kwargs: [make_issue_group("issue-1")])
    monkeypatch.setattr("src.report.interface.enrich_issue_groups", lambda *args, **kwargs: [make_enriched_group("issue-1")])
    monkeypatch.setattr("src.report.interface.compose_report_sections", lambda *args, **kwargs: [make_section("issue-1")])
    monkeypatch.setattr("src.report.interface.assemble_generated_report", lambda **kwargs: make_assembled_report([make_section("issue-1")]))
    monkeypatch.setattr("src.report.interface.save_report_sections", lambda **kwargs: [object()])
    monkeypatch.setattr("src.report.interface.create_and_save_markdown_artifact", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("artifact failed")))
    monkeypatch.setattr("src.report.interface.mark_report_failed", lambda **kwargs: marked.append(kwargs["report_id"]))
    monkeypatch.setattr("src.report.interface.mark_report_completed", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("should not complete")))

    with pytest.raises(RuntimeError):
        generate_daily_report(make_request())

    assert marked == ["report-1"]


def test_generate_daily_report_marks_failed_when_completion_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    marked: list[str] = []
    monkeypatch.setattr("src.report.interface.create_report_version", lambda **kwargs: make_created_report())
    monkeypatch.setattr("src.report.interface.get_report_candidates", lambda **kwargs: [make_candidate("a")])
    monkeypatch.setattr("src.report.interface.select_report_candidates", lambda *args, **kwargs: [make_candidate("a")])
    monkeypatch.setattr("src.report.interface.group_report_candidates", lambda *args, **kwargs: [make_issue_group("issue-1")])
    monkeypatch.setattr("src.report.interface.enrich_issue_groups", lambda *args, **kwargs: [make_enriched_group("issue-1")])
    monkeypatch.setattr("src.report.interface.compose_report_sections", lambda *args, **kwargs: [make_section("issue-1")])
    monkeypatch.setattr("src.report.interface.assemble_generated_report", lambda **kwargs: make_assembled_report([make_section("issue-1")]))
    monkeypatch.setattr("src.report.interface.save_report_sections", lambda **kwargs: [object()])
    monkeypatch.setattr("src.report.interface.create_and_save_markdown_artifact", lambda **kwargs: make_artifact())
    monkeypatch.setattr("src.report.interface.mark_report_completed", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("complete failed")))
    monkeypatch.setattr("src.report.interface.mark_report_failed", lambda **kwargs: marked.append(kwargs["report_id"]))

    with pytest.raises(RuntimeError):
        generate_daily_report(make_request())

    assert marked == ["report-1"]


def test_generate_daily_report_preserves_original_error_when_mark_failed_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.report.interface.create_report_version", lambda **kwargs: make_created_report())
    monkeypatch.setattr("src.report.interface.get_report_candidates", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("original")))
    monkeypatch.setattr("src.report.interface.mark_report_failed", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("mark failed")))

    with pytest.raises(RuntimeError, match="original"):
        generate_daily_report(make_request())


def test_generate_daily_report_handles_no_candidates_without_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    artifact = make_artifact()
    monkeypatch.setattr("src.report.interface.create_report_version", lambda **kwargs: make_created_report())
    monkeypatch.setattr("src.report.interface.get_report_candidates", lambda **kwargs: [])
    monkeypatch.setattr("src.report.interface.select_report_candidates", lambda *args, **kwargs: calls.append("select") or [])
    monkeypatch.setattr("src.report.interface.compose_report_sections", lambda *args, **kwargs: calls.append("compose") or [])
    monkeypatch.setattr("src.report.interface.create_and_save_markdown_artifact", lambda **kwargs: calls.append("artifact") or artifact)
    monkeypatch.setattr("src.report.interface.mark_report_completed", lambda **kwargs: calls.append("complete") or None)

    result = generate_daily_report(make_request(), generated_at=datetime(2026, 8, 2, 9, 0, 0))

    assert result.report.status == ReportStatus.COMPLETED
    assert result.report.sections == []
    assert result.artifact == artifact
    assert calls == ["select", "artifact", "complete"]


def test_generate_daily_report_passes_generated_at_to_assembler(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    generated_at = datetime(2026, 8, 2, 9, 0, 0)

    def fake_assemble(**kwargs):
        captured["generated_at"] = kwargs["generated_at"]
        return make_assembled_report([make_section("issue-1")])

    monkeypatch.setattr("src.report.interface.create_report_version", lambda **kwargs: make_created_report())
    monkeypatch.setattr("src.report.interface.get_report_candidates", lambda **kwargs: [make_candidate("a")])
    monkeypatch.setattr("src.report.interface.select_report_candidates", lambda *args, **kwargs: [make_candidate("a")])
    monkeypatch.setattr("src.report.interface.group_report_candidates", lambda *args, **kwargs: [make_issue_group("issue-1")])
    monkeypatch.setattr("src.report.interface.enrich_issue_groups", lambda *args, **kwargs: [make_enriched_group("issue-1")])
    monkeypatch.setattr("src.report.interface.compose_report_sections", lambda *args, **kwargs: [make_section("issue-1")])
    monkeypatch.setattr("src.report.interface.assemble_generated_report", fake_assemble)
    monkeypatch.setattr("src.report.interface.save_report_sections", lambda **kwargs: [object()])
    monkeypatch.setattr("src.report.interface.create_and_save_markdown_artifact", lambda **kwargs: make_artifact())
    monkeypatch.setattr("src.report.interface.mark_report_completed", lambda **kwargs: None)

    generate_daily_report(make_request(), generated_at=generated_at)

    assert captured["generated_at"] == generated_at


def test_generate_daily_report_passes_config_to_components(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    config = ReportGenerationConfig(
        selection={"max_candidates": 2, "min_reliability_score": 75, "min_importance_score": 80},
        grouping={"max_time_gap_hours": 12, "min_title_similarity": 0.3, "min_summary_similarity": 0.1, "min_shared_title_tokens": 1},
        wiki={"limit_per_group": 2},
        composer={"model": "test-model", "prompt_version": "report-section-v1"},
    )

    def fake_create(**kwargs):
        captured["request_config"] = kwargs["request_config"]
        return make_created_report()

    def fake_select(*args, **kwargs):
        captured["selection"] = kwargs
        return [make_candidate("a")]

    def fake_group(*args, **kwargs):
        captured["grouping"] = kwargs
        return [make_issue_group("issue-1")]

    def fake_wiki(*args, **kwargs):
        captured["wiki"] = kwargs
        return [make_enriched_group("issue-1")]

    def fake_compose(*args, **kwargs):
        captured["composer"] = kwargs
        return [make_section("issue-1")]

    def fake_save(**kwargs):
        captured["save"] = kwargs
        return [object()]

    def fake_artifact(**kwargs):
        captured["artifact"] = kwargs
        return make_artifact()

    monkeypatch.setattr("src.report.interface.create_report_version", fake_create)
    monkeypatch.setattr("src.report.interface.get_report_candidates", lambda **kwargs: [make_candidate("a")])
    monkeypatch.setattr("src.report.interface.select_report_candidates", fake_select)
    monkeypatch.setattr("src.report.interface.group_report_candidates", fake_group)
    monkeypatch.setattr("src.report.interface.enrich_issue_groups", fake_wiki)
    monkeypatch.setattr("src.report.interface.compose_report_sections", fake_compose)
    monkeypatch.setattr("src.report.interface.assemble_generated_report", lambda **kwargs: make_assembled_report([make_section("issue-1")]))
    monkeypatch.setattr("src.report.interface.save_report_sections", fake_save)
    monkeypatch.setattr("src.report.interface.create_and_save_markdown_artifact", fake_artifact)
    monkeypatch.setattr("src.report.interface.mark_report_completed", lambda **kwargs: None)

    generate_daily_report(make_request(), config=config)

    assert captured["selection"]["max_candidates"] == 2
    assert captured["selection"]["min_reliability_score"] == 75
    assert captured["grouping"]["config"].max_time_gap_hours == 12
    assert captured["wiki"]["limit_per_group"] == 2
    assert captured["composer"]["config"].model == "test-model"
    assert captured["save"]["model_name"] == "test-model"
    assert captured["save"]["prompt_version"] == "report-section-v1"
    assert captured["request_config"]["selection"]["min_importance_score"] == 80
    assert captured["artifact"]["created_by"] is None


def test_generate_daily_report_uses_injected_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    supabase = object()
    llm_client = object()

    def fake_create(**kwargs):
        captured["create"] = kwargs
        return make_created_report()

    def fake_candidates(**kwargs):
        captured["candidates"] = kwargs
        return [make_candidate("a")]

    def fake_compose(*args, **kwargs):
        captured["compose"] = kwargs
        return [make_section("issue-1")]

    def fake_save(**kwargs):
        captured["save"] = kwargs
        return [object()]

    def fake_artifact(**kwargs):
        captured["artifact"] = kwargs
        return make_artifact()

    monkeypatch.setattr("src.report.interface.create_report_version", fake_create)
    monkeypatch.setattr("src.report.interface.get_report_candidates", fake_candidates)
    monkeypatch.setattr("src.report.interface.select_report_candidates", lambda *args, **kwargs: [make_candidate("a")])
    monkeypatch.setattr("src.report.interface.group_report_candidates", lambda *args, **kwargs: [make_issue_group("issue-1")])
    monkeypatch.setattr("src.report.interface.enrich_issue_groups", lambda *args, **kwargs: [make_enriched_group("issue-1")])
    monkeypatch.setattr("src.report.interface.compose_report_sections", fake_compose)
    monkeypatch.setattr("src.report.interface.assemble_generated_report", lambda **kwargs: make_assembled_report([make_section("issue-1")]))
    monkeypatch.setattr("src.report.interface.save_report_sections", fake_save)
    monkeypatch.setattr("src.report.interface.create_and_save_markdown_artifact", fake_artifact)
    monkeypatch.setattr("src.report.interface.mark_report_completed", lambda **kwargs: None)

    generate_daily_report(make_request(), supabase=supabase, llm_client=llm_client)

    assert captured["create"]["supabase"] is supabase
    assert captured["candidates"]["supabase"] is supabase
    assert captured["compose"]["llm_client"] is llm_client
    assert captured["save"]["supabase"] is supabase
    assert captured["artifact"]["supabase"] is supabase


def test_generate_daily_report_passes_assembled_report_to_artifact_service(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    assembled = make_assembled_report([make_section("issue-1")])

    def fake_artifact(**kwargs):
        captured["report"] = kwargs["report"]
        return make_artifact()

    monkeypatch.setattr("src.report.interface.create_report_version", lambda **kwargs: make_created_report())
    monkeypatch.setattr("src.report.interface.get_report_candidates", lambda **kwargs: [make_candidate("a")])
    monkeypatch.setattr("src.report.interface.select_report_candidates", lambda *args, **kwargs: [make_candidate("a")])
    monkeypatch.setattr("src.report.interface.group_report_candidates", lambda *args, **kwargs: [make_issue_group("issue-1")])
    monkeypatch.setattr("src.report.interface.enrich_issue_groups", lambda *args, **kwargs: [make_enriched_group("issue-1")])
    monkeypatch.setattr("src.report.interface.compose_report_sections", lambda *args, **kwargs: [make_section("issue-1")])
    monkeypatch.setattr("src.report.interface.assemble_generated_report", lambda **kwargs: assembled)
    monkeypatch.setattr("src.report.interface.save_report_sections", lambda **kwargs: [object()])
    monkeypatch.setattr("src.report.interface.create_and_save_markdown_artifact", fake_artifact)
    monkeypatch.setattr("src.report.interface.mark_report_completed", lambda **kwargs: None)

    result = generate_daily_report(make_request())

    assert captured["report"] is assembled
    assert result.report is assembled


def test_generate_daily_report_does_not_complete_before_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr("src.report.interface.create_report_version", lambda **kwargs: make_created_report())
    monkeypatch.setattr("src.report.interface.get_report_candidates", lambda **kwargs: [make_candidate("a")])
    monkeypatch.setattr("src.report.interface.select_report_candidates", lambda *args, **kwargs: [make_candidate("a")])
    monkeypatch.setattr("src.report.interface.group_report_candidates", lambda *args, **kwargs: [make_issue_group("issue-1")])
    monkeypatch.setattr("src.report.interface.enrich_issue_groups", lambda *args, **kwargs: [make_enriched_group("issue-1")])
    monkeypatch.setattr("src.report.interface.compose_report_sections", lambda *args, **kwargs: [make_section("issue-1")])
    monkeypatch.setattr("src.report.interface.assemble_generated_report", lambda **kwargs: make_assembled_report([make_section("issue-1")]))
    monkeypatch.setattr("src.report.interface.save_report_sections", lambda **kwargs: [object()])
    monkeypatch.setattr("src.report.interface.create_and_save_markdown_artifact", lambda **kwargs: calls.append("artifact") or make_artifact())
    monkeypatch.setattr("src.report.interface.mark_report_completed", lambda **kwargs: calls.append("complete") or None)

    generate_daily_report(make_request())

    assert calls == ["artifact", "complete"]

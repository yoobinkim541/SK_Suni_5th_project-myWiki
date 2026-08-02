from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator
from supabase import Client

from .artifact_service import create_and_save_markdown_artifact
from .assembler import DEFAULT_REPORT_TITLE, assemble_generated_report
from .candidate_provider import get_report_candidates
from .composer import ReportComposerConfig, compose_report_sections
from .grouper import IssueGroupingConfig, group_report_candidates
from .models import GeneratedReport, ReportGenerationRequest, ReportStatus
from .repository import (
    SavedReportArtifact,
    create_report_version,
    mark_report_completed,
    mark_report_failed,
    save_report_sections,
)
from .selector import select_report_candidates
from .wiki_context import DEFAULT_WIKI_CONTEXT_LIMIT, enrich_issue_groups
from ..analysis.models import Category
from ..wiki.interface import search_wiki_contexts

logger = logging.getLogger(__name__)

try:
    SEOUL_TZ = ZoneInfo("Asia/Seoul")
except ZoneInfoNotFoundError:
    SEOUL_TZ = timezone(timedelta(hours=9), name="Asia/Seoul")


class ReportSelectionConfig(BaseModel):
    max_candidates: int | None = Field(default=None, ge=1)
    min_reliability_score: int = Field(default=70, ge=0, le=100)
    min_importance_score: int = Field(default=70, ge=0, le=100)
    min_ranking_score: Decimal | None = Field(default=None, ge=0, le=100)
    category_limits: dict[Category, int] | None = None

    @field_validator("min_ranking_score", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal | None:
        if value is None or value == "":
            return None
        return Decimal(str(value))


class WikiEnrichmentConfig(BaseModel):
    limit_per_group: int = Field(default=DEFAULT_WIKI_CONTEXT_LIMIT, ge=0)


class ReportGenerationConfig(BaseModel):
    requested_by: str | None = None
    selection: ReportSelectionConfig = Field(default_factory=ReportSelectionConfig)
    grouping: IssueGroupingConfig = Field(
        default_factory=lambda: IssueGroupingConfig(
            max_time_gap_hours=24,
            min_title_similarity=0.2,
            min_summary_similarity=0.2,
            min_shared_title_tokens=1,
            require_same_category=True,
        )
    )
    wiki: WikiEnrichmentConfig = Field(default_factory=WikiEnrichmentConfig)
    composer: ReportComposerConfig = Field(default_factory=ReportComposerConfig)
    explicit_group_keys: dict[str, str] | None = None

    @field_validator("requested_by", mode="before")
    @classmethod
    def normalize_requested_by(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class DailyReportGenerationResult(BaseModel):
    report: GeneratedReport
    artifact: SavedReportArtifact


def generate_daily_report(
    request: ReportGenerationRequest,
    *,
    supabase: Client | None = None,
    llm_client=None,
    generated_at: datetime | None = None,
    config: ReportGenerationConfig | None = None,
) -> DailyReportGenerationResult:
    pipeline_config = config or ReportGenerationConfig()
    stage = "create_report_version"
    report = create_report_version(
        workspace_id=request.workspace_id,
        report_key=_build_report_key(request),
        title=DEFAULT_REPORT_TITLE,
        report_type=request.report_type,
        request_config=_build_request_config(request, pipeline_config),
        requested_by=pipeline_config.requested_by,
        supabase=supabase,
    )

    try:
        stage = "load_candidates"
        candidates = get_report_candidates(
            workspace_id=request.workspace_id,
            report_date=request.report_date,
            supabase=supabase,
        )
        logger.info(
            "report_generation_stage",
            extra={
                "stage": stage,
                "report_id": report.report_id,
                "workspace_id": request.workspace_id,
                "candidate_count": len(candidates),
            },
        )

        stage = "select_candidates"
        selected_candidates = select_report_candidates(
            candidates,
            max_candidates=pipeline_config.selection.max_candidates or request.max_sections,
            min_reliability_score=pipeline_config.selection.min_reliability_score,
            min_importance_score=pipeline_config.selection.min_importance_score,
            min_ranking_score=pipeline_config.selection.min_ranking_score,
            category_limits=pipeline_config.selection.category_limits,
        )
        if len(selected_candidates) > len(candidates):
            raise ValueError("selected_candidates cannot exceed candidates.")

        if not selected_candidates:
            empty_report = _build_empty_generated_report(
                request=request,
                report=report,
                generated_at=generated_at,
            )
            artifact = _create_report_artifact(
                generated_report=empty_report,
                requested_by=pipeline_config.requested_by,
                supabase=supabase,
            )
            stage = "complete_report"
            mark_report_completed(report_id=report.report_id, supabase=supabase)
            _apply_completion_metadata(report=empty_report, artifact=artifact)
            return DailyReportGenerationResult(report=empty_report, artifact=artifact)

        stage = "group_candidates"
        issue_groups = group_report_candidates(
            selected_candidates,
            config=pipeline_config.grouping,
            explicit_group_keys=pipeline_config.explicit_group_keys,
        )
        if not issue_groups:
            raise ValueError("issue_groups must not be empty when candidates were selected.")

        stage = "enrich_wiki"
        enriched_groups = enrich_issue_groups(
            issue_groups,
            wiki_search=lambda wiki_request: search_wiki_contexts(wiki_request, supabase=supabase),
            limit_per_group=pipeline_config.wiki.limit_per_group,
        )
        if len(enriched_groups) != len(issue_groups):
            raise ValueError("enriched_groups count must match issue_groups count.")

        stage = "compose_sections"
        section_drafts = compose_report_sections(
            enriched_groups,
            config=pipeline_config.composer,
            llm_client=llm_client,
        )
        _validate_section_drafts(section_drafts, expected_count=len(issue_groups))

        stage = "assemble_report"
        assembled_report = assemble_generated_report(
            request=request,
            sections=section_drafts,
            generated_at=generated_at,
        )
        assembled_report.report_id = report.report_id
        assembled_report.version = report.version
        assembled_report.created_at = report.created_at

        stage = "save_sections"
        saved_sections = save_report_sections(
            report_id=report.report_id,
            sections=section_drafts,
            supabase=supabase,
            model_name=pipeline_config.composer.model,
            prompt_version=pipeline_config.composer.prompt_version,
        )
        if len(saved_sections) != len(section_drafts):
            raise ValueError("saved section count must match section_draft count.")

        stage = "save_artifact"
        artifact = _create_report_artifact(
            generated_report=assembled_report,
            requested_by=pipeline_config.requested_by,
            supabase=supabase,
        )

        stage = "complete_report"
        mark_report_completed(report_id=report.report_id, supabase=supabase)
        _apply_completion_metadata(report=assembled_report, artifact=artifact)
        return DailyReportGenerationResult(report=assembled_report, artifact=artifact)
    except Exception as exc:
        logger.exception(
            "report_generation_failed",
            extra={
                "stage": stage,
                "report_id": report.report_id,
                "workspace_id": request.workspace_id,
            },
        )
        try:
            mark_report_failed(report_id=report.report_id, supabase=supabase)
        except Exception:
            logger.exception(
                "report_generation_failed_to_mark_failed",
                extra={
                    "stage": stage,
                    "report_id": report.report_id,
                    "workspace_id": request.workspace_id,
                },
            )
        raise exc


def _build_report_key(request: ReportGenerationRequest) -> str:
    return f"{request.report_type.value}:{request.workspace_id}:{request.report_date.isoformat()}"


def _build_request_config(
    request: ReportGenerationRequest,
    config: ReportGenerationConfig,
) -> dict[str, object]:
    return {
        "report_date": request.report_date.isoformat(),
        "language": request.language,
        "max_sections": request.max_sections,
        "report_type": request.report_type.value,
        "selection": {
            "max_candidates": config.selection.max_candidates or request.max_sections,
            "min_reliability_score": config.selection.min_reliability_score,
            "min_importance_score": config.selection.min_importance_score,
            "min_ranking_score": str(config.selection.min_ranking_score)
            if config.selection.min_ranking_score is not None
            else None,
            "category_limits": _serialize_category_limits(config.selection.category_limits),
        },
        "grouping": config.grouping.model_dump(),
        "wiki": config.wiki.model_dump(),
        "composer": {
            "model": config.composer.model,
            "temperature": config.composer.temperature,
            "language": config.composer.language,
            "max_wiki_contexts": config.composer.max_wiki_contexts,
            "max_wiki_chars_per_context": config.composer.max_wiki_chars_per_context,
            "max_total_wiki_chars": config.composer.max_total_wiki_chars,
            "prompt_version": config.composer.prompt_version,
            "max_retries": config.composer.max_retries,
        },
        "explicit_group_keys": dict(config.explicit_group_keys or {}),
    }


def _serialize_category_limits(category_limits: Mapping[Category, int] | None) -> dict[str, int] | None:
    if category_limits is None:
        return None
    return {category.value: limit for category, limit in category_limits.items()}


def _build_empty_generated_report(
    *,
    request: ReportGenerationRequest,
    report: GeneratedReport,
    generated_at: datetime | None,
) -> GeneratedReport:
    report_generated_at = generated_at or datetime.now(UTC).astimezone(SEOUL_TZ)
    return GeneratedReport(
        report_id=report.report_id,
        workspace_id=request.workspace_id,
        report_date=request.report_date,
        report_type=request.report_type,
        title=DEFAULT_REPORT_TITLE,
        language=request.language,
        version=report.version,
        status=ReportStatus.COMPLETED,
        sections=[],
        executive_summaries=[],
        issue_summary_rows=[],
        category_groups=[],
        news_sources=[],
        wiki_sources=[],
        created_at=report.created_at,
        generated_at=report_generated_at,
    )


def _create_report_artifact(
    *,
    generated_report: GeneratedReport,
    requested_by: str | None,
    supabase: Client | None,
) -> SavedReportArtifact:
    return create_and_save_markdown_artifact(
        report=generated_report,
        supabase=supabase,
        created_by=requested_by,
    )


def _apply_completion_metadata(
    *,
    report: GeneratedReport,
    artifact: SavedReportArtifact,
) -> None:
    report.status = ReportStatus.COMPLETED
    report.artifact_id = artifact.artifact_id
    report.artifact_type = artifact.artifact_type
    report.artifact_object_key = artifact.object_key


def _validate_section_drafts(section_drafts, *, expected_count: int) -> None:
    if len(section_drafts) != expected_count:
        raise ValueError("section_draft count must match issue_group count.")
    issue_keys = [section.issue_key for section in section_drafts]
    if len(set(issue_keys)) != len(issue_keys):
        raise ValueError("section_draft issue_keys must be unique.")

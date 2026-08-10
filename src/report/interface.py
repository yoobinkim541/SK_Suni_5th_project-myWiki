from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator
from supabase import Client

from .artifact_service import (
    create_and_save_docx_artifact,
    create_and_save_markdown_artifact,
    create_and_save_pdf_artifact,
    create_and_save_pptx_artifact,
)
from .assembler import DEFAULT_REPORT_TITLE, assemble_generated_report
from .candidate_provider import get_report_candidates
from .composer import ReportComposerConfig, compose_report_sections
from .grouper import IssueGroupingConfig, group_report_candidates
from .models import ArtifactType, GeneratedReport, ReportGenerationRequest, ReportStatus
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
from ..wiki.generation import generate_wiki_drafts_for_sections
from ..wiki.interface import search_wiki_contexts

logger = logging.getLogger(__name__)

try:
    SEOUL_TZ = ZoneInfo("Asia/Seoul")
except ZoneInfoNotFoundError:
    SEOUL_TZ = timezone(timedelta(hours=9), name="Asia/Seoul")


class ReportSelectionConfig(BaseModel):
    max_candidates: int | None = Field(default=None, ge=1, le=20)
    # 2026-08-04 개정: 원래 70(= ReliabilityLevel.HIGH/ImportanceLevel.HIGH 하한, 둘 다
    # analysis/*_models.py의 LOW(0-39)/MEDIUM(40-69)/HIGH(70-100) 3단계 기준 공유)이었다.
    # 그런데 실제 수집되는 반도체 뉴스는 대부분 비공식·단일 출처라서
    # reliability_scoring.py의 source_authority_max/independent_evidence_max 상한 때문에
    # HIGH(70+)를 사실상 못 넘긴다 — 라이브 데이터 확인 결과 reliability_score가 70을 넘긴
    # 행이 하나도 없었고(최고 63), 그 결과 리포트·위키 후보 선정이 매번 0건이었다("HIGH만"
    # 요구하는 게 사실상 "전부 거부"와 같았음). 채점 로직 자체는 설계대로 정상 동작 중이므로,
    # 로직을 고치는 대신 기준을 MEDIUM 이상(40)으로 낮췄다 — LOW(명백히 부실한 단일신호/충돌
    # 정황 등으로 캡이 걸린 건)만 걸러내고 MEDIUM 이상은 통과시킨다.
    # 2026-08-07 재조정(#154): 40도 여전히 후보가 부족해 20으로 더 낮췄다. LOW 구간
    # (0-39) 하한 절반까지 허용하는 셈이라 위 문단의 "LOW만 거른다"는 더 이상 정확하지
    # 않다 — 지금은 "명백한 결측·모순 신호로 더 깊이 캡이 걸린 건"만 거른다.
    min_reliability_score: int = Field(default=20, ge=0, le=100)
    min_importance_score: int = Field(default=20, ge=0, le=100)
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


class ReportArtifactConfig(BaseModel):
    formats: list[ArtifactType] = Field(default_factory=lambda: [ArtifactType.PDF, ArtifactType.DOCX, ArtifactType.PPTX])

    @field_validator("formats", mode="before")
    @classmethod
    def normalize_formats(cls, value: object) -> list[ArtifactType] | object:
        if value is None:
            return [ArtifactType.PDF, ArtifactType.DOCX, ArtifactType.PPTX]
        if isinstance(value, (str, ArtifactType)):
            return [value]
        return value

    @model_validator(mode="after")
    def validate_formats(self) -> "ReportArtifactConfig":
        if not self.formats:
            raise ValueError("formats must not be empty.")
        deduped: list[ArtifactType] = []
        for item in self.formats:
            artifact_type = item if isinstance(item, ArtifactType) else ArtifactType(str(item))
            if artifact_type not in deduped:
                deduped.append(artifact_type)
        self.formats = deduped
        return self


class ReportGenerationConfig(BaseModel):
    requested_by: str | None = None
    selection: ReportSelectionConfig = Field(default_factory=ReportSelectionConfig)
    grouping: IssueGroupingConfig = Field(
        default_factory=lambda: IssueGroupingConfig(
            max_time_gap_hours=24,
            min_title_similarity=0.55,
            min_summary_similarity=0.55,
            min_shared_title_tokens=2,
            require_same_category=True,
        )
    )
    wiki: WikiEnrichmentConfig = Field(default_factory=WikiEnrichmentConfig)
    composer: ReportComposerConfig = Field(default_factory=ReportComposerConfig)
    artifacts: ReportArtifactConfig = Field(default_factory=ReportArtifactConfig)
    explicit_group_keys: dict[str, str] | None = None
    analysis_document_version_ids: list[str] | None = None

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
    artifacts: list[SavedReportArtifact] = Field(default_factory=list)


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
        candidate_kwargs = {
            "workspace_id": request.workspace_id,
            "report_date": request.report_date,
            "supabase": supabase,
        }
        if pipeline_config.analysis_document_version_ids is not None:
            candidate_kwargs["document_version_ids"] = pipeline_config.analysis_document_version_ids
        candidates = get_report_candidates(**candidate_kwargs)
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
            max_candidates=pipeline_config.selection.max_candidates or 20,
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
            artifacts = _create_report_artifacts(
                generated_report=empty_report,
                requested_by=pipeline_config.requested_by,
                supabase=supabase,
                artifact_config=pipeline_config.artifacts,
            )
            primary_artifact = artifacts[0]
            stage = "complete_report"
            mark_report_completed(report_id=report.report_id, supabase=supabase)
            _apply_completion_metadata(report=empty_report, artifact=primary_artifact)
            return DailyReportGenerationResult(report=empty_report, artifact=primary_artifact, artifacts=artifacts)

        stage = "group_candidates"
        issue_groups = group_report_candidates(
            selected_candidates,
            config=pipeline_config.grouping,
            explicit_group_keys=pipeline_config.explicit_group_keys,
        )
        issue_groups = issue_groups[:request.max_sections]
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

        stage = "generate_wiki_drafts"
        try:
            generate_wiki_drafts_for_sections(
                section_drafts,
                enriched_groups,
                workspace_id=request.workspace_id,
                requested_by=pipeline_config.requested_by,
                supabase=supabase,
                llm_client=llm_client,
            )
        except Exception:
            logger.exception(
                "wiki_draft_generation_failed",
                extra={
                    "stage": stage,
                    "report_id": report.report_id,
                    "workspace_id": request.workspace_id,
                },
            )

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
        artifacts = _create_report_artifacts(
            generated_report=assembled_report,
            requested_by=pipeline_config.requested_by,
            supabase=supabase,
            artifact_config=pipeline_config.artifacts,
        )
        primary_artifact = artifacts[0]

        stage = "complete_report"
        mark_report_completed(report_id=report.report_id, supabase=supabase)
        _apply_completion_metadata(report=assembled_report, artifact=primary_artifact)
        return DailyReportGenerationResult(report=assembled_report, artifact=primary_artifact, artifacts=artifacts)
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
            "max_candidates": config.selection.max_candidates or 20,
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
        "artifacts": {
            "formats": [artifact_type.value for artifact_type in config.artifacts.formats],
        },
        "explicit_group_keys": dict(config.explicit_group_keys or {}),
        "analysis_document_count": len(config.analysis_document_version_ids or []),
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


def _create_report_artifacts(
    *,
    generated_report: GeneratedReport,
    requested_by: str | None,
    supabase: Client | None,
    artifact_config: ReportArtifactConfig,
) -> list[SavedReportArtifact]:
    artifacts: list[SavedReportArtifact] = []
    for artifact_type in artifact_config.formats:
        if artifact_type == ArtifactType.MARKDOWN:
            artifacts.append(
                create_and_save_markdown_artifact(
                    report=generated_report,
                    supabase=supabase,
                    created_by=requested_by,
                )
            )
            continue
        if artifact_type == ArtifactType.DOCX:
            artifacts.append(
                create_and_save_docx_artifact(
                    report=generated_report,
                    supabase=supabase,
                    created_by=requested_by,
                )
            )
            continue
        if artifact_type == ArtifactType.PDF:
            artifacts.append(
                create_and_save_pdf_artifact(
                    report=generated_report,
                    supabase=supabase,
                    created_by=requested_by,
                )
            )
            continue
        if artifact_type == ArtifactType.PPTX:
            artifacts.append(
                create_and_save_pptx_artifact(
                    report=generated_report,
                    supabase=supabase,
                    created_by=requested_by,
                )
            )
            continue
        raise ValueError(f"Unsupported artifact type for report generation: {artifact_type.value}")
    return artifacts


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

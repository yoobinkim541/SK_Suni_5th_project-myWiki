from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from supabase import Client

from ..analysis.repository import get_supabase
from .artifact_service import resolve_report_artifact_bucket
from .interface import ReportArtifactConfig, ReportGenerationConfig, generate_daily_report
from .models import ArtifactType, ReportGenerationRequest, ReportStatus, ReportType
from .repository import (
    SavedReportArtifact,
    get_report_artifact,
    list_completed_daily_report_rows,
    list_report_artifacts_for_reports,
    list_report_sections_for_reports,
)


class ReportDownloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class DailyReportDownload:
    report_id: str
    version: int
    artifact_type: ArtifactType
    filename: str
    mime_type: str
    payload: bytes


ARTIFACT_FORMAT_ALIASES = {
    "markdown": ArtifactType.MARKDOWN,
    "md": ArtifactType.MARKDOWN,
    "pdf": ArtifactType.PDF,
    "ppt": ArtifactType.PPTX,
    "pptx": ArtifactType.PPTX,
    "word": ArtifactType.DOCX,
    "doc": ArtifactType.DOCX,
    "docx": ArtifactType.DOCX,
}

DEFAULT_ARTIFACT_MIME_TYPES = {
    ArtifactType.MARKDOWN: "text/markdown; charset=utf-8",
    ArtifactType.PDF: "application/pdf",
    ArtifactType.PPTX: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ArtifactType.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

ARTIFACT_EXTENSIONS = {
    ArtifactType.MARKDOWN: "md",
    ArtifactType.PDF: "pdf",
    ArtifactType.PPTX: "pptx",
    ArtifactType.DOCX: "docx",
}


def get_daily_report_history(
    workspace_id: str,
    *,
    limit: int = 30,
    supabase: Client | None = None,
) -> list[dict[str, Any]]:
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100.")

    db = supabase or get_supabase()
    report_rows = list_completed_daily_report_rows(workspace_id=workspace_id, supabase=db)

    latest_by_date: dict[date, dict[str, Any]] = {}
    for row in report_rows:
        report_date = _extract_daily_history_report_date(row)
        if report_date is None:
            continue
        existing = latest_by_date.get(report_date)
        if existing is None or _report_history_sort_key(row) > _report_history_sort_key(existing):
            latest_by_date[report_date] = row

    latest_reports = sorted(latest_by_date.items(), key=lambda item: item[0], reverse=True)[:limit]
    if not latest_reports:
        return []

    selected_report_rows = [row for _, row in latest_reports]
    report_ids = [str(row["id"]) for row in selected_report_rows]

    section_rows = list_report_sections_for_reports(report_ids=report_ids, supabase=db)
    issue_count_by_report: dict[str, int] = {report_id: 0 for report_id in report_ids}
    for section in section_rows:
        report_id = str(section.get("report_id"))
        if section.get("issue_key") is not None:
            issue_count_by_report[report_id] = issue_count_by_report.get(report_id, 0) + 1

    artifact_rows = list_report_artifacts_for_reports(report_ids=report_ids, supabase=db)
    artifact_types_by_report: dict[str, set[str]] = {report_id: set() for report_id in report_ids}
    for artifact in artifact_rows:
        report_id = str(artifact.get("report_id"))
        artifact_type = artifact.get("artifact_type")
        if artifact_type is not None:
            artifact_types_by_report.setdefault(report_id, set()).add(str(artifact_type))

    history: list[dict[str, Any]] = []
    date_by_report_id = {str(row["id"]): report_date for report_date, row in latest_reports}
    for row in selected_report_rows:
        report_id = str(row["id"])
        artifact_types = artifact_types_by_report.get(report_id, set())
        history.append(
            {
                "report_id": report_id,
                "date": date_by_report_id[report_id].isoformat(),
                "title": str(row.get("title") or ""),
                "version": int(row["version"]),
                "status": str(row["status"]),
                "completed_at": row.get("completed_at"),
                "issue_count": issue_count_by_report.get(report_id, 0),
                "has_pdf": ArtifactType.PDF.value in artifact_types,
                "has_docx": ArtifactType.DOCX.value in artifact_types,
                "has_pptx": ArtifactType.PPTX.value in artifact_types,
            }
        )
    return history


def get_daily_report(
    workspace_id: str,
    report_date: date,
    *,
    supabase: Client | None = None,
) -> dict[str, Any] | None:
    db = supabase or get_supabase()
    report_row = _get_latest_completed_daily_report_row(
        workspace_id=workspace_id,
        report_date=report_date,
        supabase=db,
    )
    if report_row is None:
        return None

    report_id = str(report_row["id"])

    section_rows = (
        db.table("report_sections")
        .select("id, report_id, issue_key, section_order, title, content, status, model_name, prompt_version, created_at, updated_at")
        .eq("report_id", report_id)
        .order("section_order")
        .execute()
        .data
    )

    section_ids = [str(row["id"]) for row in section_rows]
    citation_rows = []
    if section_ids:
        citation_rows = (
            db.table("report_citations")
            .select("id, section_id, document_version_id, source_start_line, source_end_line, quoted_text, relevance_score, citation_order")
            .in_("section_id", section_ids)
            .order("citation_order")
            .execute()
            .data
        )
        _enrich_report_citations(citation_rows, supabase=db)

    citations_by_section: dict[str, list[dict[str, Any]]] = {}
    for citation in citation_rows:
        section_id = str(citation["section_id"])
        citations_by_section.setdefault(section_id, []).append(
            {
                "id": str(citation["id"]),
                "section_id": section_id,
                "document_version_id": str(citation["document_version_id"]),
                "source_start_line": citation.get("source_start_line"),
                "source_end_line": citation.get("source_end_line"),
                "quoted_text": citation.get("quoted_text"),
                "relevance_score": citation.get("relevance_score"),
                "citation_order": citation.get("citation_order"),
                "document_title": citation.get("document_title"),
                "source_url": citation.get("source_url"),
                "source_name": citation.get("source_name"),
                "published_at": citation.get("published_at"),
            }
        )

    sections: list[dict[str, Any]] = []
    for row in section_rows:
        raw_content = row.get("content")
        content: dict[str, Any] | str | None = raw_content
        if isinstance(raw_content, str):
            try:
                content = json.loads(raw_content)
            except json.JSONDecodeError:
                content = raw_content
        section_id = str(row["id"])
        sections.append(
            {
                "id": section_id,
                "report_id": str(row["report_id"]),
                "issue_key": str(row["issue_key"]),
                "section_order": int(row["section_order"]),
                "title": str(row["title"]),
                "content": content,
                "status": str(row["status"]),
                "model_name": row.get("model_name"),
                "prompt_version": row.get("prompt_version"),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
                "citations": citations_by_section.get(section_id, []),
            }
        )

    return {
        "report_id": report_id,
        "workspace_id": str(report_row["workspace_id"]),
        "report_key": str(report_row["report_key"]),
        "version": int(report_row["version"]),
        "title": str(report_row.get("title") or "일일 산업 동향 보고서"),
        "report_type": str(report_row["report_type"]),
        "status": str(report_row["status"]),
        "date": report_date.isoformat(),
        "created_at": report_row.get("created_at"),
        "completed_at": report_row.get("completed_at"),
        "sections": sections,
    }


def _enrich_report_citations(
    rows: list[dict[str, Any]],
    *,
    supabase: Client,
) -> list[dict[str, Any]]:
    if not rows:
        return rows

    document_version_ids = list({str(row["document_version_id"]) for row in rows if row.get("document_version_id")})
    if not document_version_ids:
        return rows

    version_rows = (
        supabase.table("document_versions")
        .select("id, document_id")
        .in_("id", document_version_ids)
        .execute()
        .data
    )
    document_id_by_version = {
        str(row["id"]): row.get("document_id")
        for row in version_rows
        if row.get("id") is not None
    }

    document_ids = list({str(doc_id) for doc_id in document_id_by_version.values() if doc_id})
    documents_by_id: dict[str, dict[str, Any]] = {}
    if document_ids:
        document_rows = (
            supabase.table("documents")
            .select("id, title, canonical_url, published_at, source_id")
            .in_("id", document_ids)
            .execute()
            .data
        )
        documents_by_id = {
            str(row["id"]): row
            for row in document_rows
            if row.get("id") is not None
        }

    source_ids = list(
        {
            str(document["source_id"])
            for document in documents_by_id.values()
            if document.get("source_id") is not None
        }
    )
    source_name_by_id: dict[str, str] = {}
    if source_ids:
        source_rows = (
            supabase.table("sources")
            .select("id, name")
            .in_("id", source_ids)
            .execute()
            .data
        )
        source_name_by_id = {
            str(row["id"]): str(row["name"])
            for row in source_rows
            if row.get("id") is not None and row.get("name") is not None
        }

    for row in rows:
        document_version_id = str(row["document_version_id"])
        document_id = document_id_by_version.get(document_version_id)
        document = documents_by_id.get(str(document_id)) if document_id is not None else None
        row["document_title"] = document.get("title") if document else None
        row["source_url"] = document.get("canonical_url") if document else None
        row["published_at"] = document.get("published_at") if document else None
        source_id = document.get("source_id") if document else None
        row["source_name"] = source_name_by_id.get(str(source_id)) if source_id is not None else None

    return rows


def get_daily_report_download(
    workspace_id: str,
    report_date: date,
    artifact_format: str,
    *,
    supabase: Client | None = None,
) -> DailyReportDownload | None:
    db = supabase or get_supabase()
    artifact_type = normalize_report_artifact_format(artifact_format)
    report_row = _get_latest_completed_daily_report_row(
        workspace_id=workspace_id,
        report_date=report_date,
        supabase=db,
    )
    if report_row is None:
        return None

    report_id = str(report_row["id"])
    version = int(report_row["version"])
    artifact = get_report_artifact(
        report_id=report_id,
        artifact_type=artifact_type,
        version=version,
        supabase=db,
    )
    if artifact is None:
        return None

    payload = _download_report_artifact_payload(artifact=artifact, supabase=db)
    return DailyReportDownload(
        report_id=report_id,
        version=version,
        artifact_type=artifact_type,
        filename=build_daily_report_download_filename(
            report_date=report_date,
            artifact_type=artifact_type,
            version=version,
        ),
        mime_type=artifact.mime_type or DEFAULT_ARTIFACT_MIME_TYPES[artifact_type],
        payload=payload,
    )


def generate_daily_report_artifacts(
    *,
    workspace_id: str,
    report_date: date,
    max_sections: int = 15,
    language: str = "ko",
    requested_by: str | None = None,
    formats: list[str] | None = None,
    analysis_document_version_ids: list[str] | None = None,
    supabase: Client | None = None,
    llm_client=None,
) -> dict[str, Any]:
    artifact_config = None
    if formats is not None:
        artifact_config = ReportArtifactConfig(
            formats=[normalize_report_artifact_format(item) for item in formats],
        )


    config = ReportGenerationConfig(
        requested_by=requested_by,
        artifacts=artifact_config or ReportArtifactConfig(),
        analysis_document_version_ids=analysis_document_version_ids,
    )
    result = generate_daily_report(
        ReportGenerationRequest(
            workspace_id=workspace_id,
            report_date=report_date,
            max_sections=max_sections,
            language=language,
        ),
        supabase=supabase,
        llm_client=llm_client,
        config=config,
    )

    report = result.report
    artifact_type = report.artifact_type or result.artifact.artifact_type
    artifact_object_key = report.artifact_object_key or result.artifact.object_key
    return {
        "report_id": str(report.report_id),
        "workspace_id": report.workspace_id,
        "report_key": f"{report.report_type.value}:{report.workspace_id}:{report.report_date.isoformat()}",
        "version": int(report.version or 1),
        "title": report.title,
        "report_type": report.report_type.value,
        "status": report.status.value,
        "date": report.report_date.isoformat(),
        "artifact_id": str(report.artifact_id or result.artifact.artifact_id),
        "artifact_type": artifact_type.value,
        "artifact_object_key": artifact_object_key,
        "artifacts": [_serialize_artifact(artifact) for artifact in result.artifacts],
    }


def normalize_report_artifact_format(value: str) -> ArtifactType:
    normalized = str(value or "").strip().lower()
    if normalized not in ARTIFACT_FORMAT_ALIASES:
        supported = ", ".join(sorted(ARTIFACT_FORMAT_ALIASES))
        raise ValueError(f"Unsupported report format: {value}. Supported formats: {supported}.")
    return ARTIFACT_FORMAT_ALIASES[normalized]


def build_daily_report_download_filename(
    *,
    report_date: date,
    artifact_type: ArtifactType,
    version: int,
) -> str:
    extension = ARTIFACT_EXTENSIONS[artifact_type]
    return f"daily-report-{report_date.isoformat()}-v{version}.{extension}"


def _serialize_artifact(artifact: SavedReportArtifact) -> dict[str, Any]:
    return {
        "artifact_id": artifact.artifact_id,
        "report_id": artifact.report_id,
        "artifact_type": artifact.artifact_type.value,
        "object_key": artifact.object_key,
        "version": artifact.version,
        "mime_type": artifact.mime_type,
        "file_size": artifact.file_size,
        "created_at": artifact.created_at.isoformat() if artifact.created_at is not None else None,
    }


def _extract_daily_history_report_date(row: dict[str, Any]) -> date | None:
    request_config = row.get("request_config")
    if isinstance(request_config, str):
        try:
            request_config = json.loads(request_config)
        except json.JSONDecodeError:
            request_config = None
    if isinstance(request_config, dict):
        parsed = _parse_history_date(request_config.get("report_date"))
        if parsed is not None:
            return parsed

    report_key = str(row.get("report_key") or "")
    if report_key.startswith(f"{ReportType.DAILY.value}:"):
        return _parse_history_date(report_key.rsplit(":", 1)[-1])
    return None


def _parse_history_date(value: object) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _report_history_sort_key(row: dict[str, Any]) -> tuple[int, str, str]:
    return (
        int(row.get("version") or 0),
        str(row.get("completed_at") or ""),
        str(row.get("created_at") or ""),
    )


def _get_latest_completed_daily_report_row(
    *,
    workspace_id: str,
    report_date: date,
    supabase: Client,
) -> dict[str, Any] | None:
    report_key = f"{ReportType.DAILY.value}:{workspace_id}:{report_date.isoformat()}"
    report_rows = (
        supabase.table("reports")
        .select("id, workspace_id, report_key, version, title, report_type, status, created_at, completed_at, request_config")
        .eq("workspace_id", workspace_id)
        .eq("report_key", report_key)
        .eq("status", ReportStatus.COMPLETED.value)
        .order("version", desc=True)
        .limit(1)
        .execute()
        .data
    )
    if not report_rows:
        return None
    return report_rows[0]


def _download_report_artifact_payload(
    *,
    artifact: SavedReportArtifact,
    supabase: Client,
) -> bytes:
    storage_bucket = artifact.storage_bucket or resolve_report_artifact_bucket()
    try:
        payload = supabase.storage.from_(storage_bucket).download(artifact.object_key)
    except Exception as exc:
        raise ReportDownloadError(
            f"Failed to download report artifact object_key={artifact.object_key}."
        ) from exc
    if not isinstance(payload, (bytes, bytearray)) or not payload:
        raise ReportDownloadError(
            f"Downloaded report artifact is empty or invalid object_key={artifact.object_key}."
        )
    return bytes(payload)

from __future__ import annotations

import hashlib
import logging
import os
from datetime import date

from supabase import Client

from ..analysis.repository import get_supabase
from .markdown_renderer import render_generated_report_markdown
from .models import ArtifactType, GeneratedReport
from .repository import (
    ReportPersistenceError,
    SavedReportArtifact,
    get_report_artifact,
    save_report_artifact_metadata,
)

logger = logging.getLogger(__name__)

DEFAULT_REPORT_ARTIFACT_BUCKET = "myWiki"
MARKDOWN_CONTENT_TYPE = "text/markdown"


class ReportArtifactError(RuntimeError):
    pass


class ReportArtifactConflictError(ReportArtifactError):
    pass


class ReportArtifactUploadError(ReportArtifactError):
    pass


def build_report_artifact_object_key(
    *,
    workspace_id: str,
    report_id: str,
    report_version: int,
    artifact_type: ArtifactType | str = ArtifactType.MARKDOWN,
    extension: str = "md",
) -> str:
    resolved_artifact_type = artifact_type.value if isinstance(artifact_type, ArtifactType) else str(artifact_type).strip()
    normalized_workspace_id = _normalize_path_segment(workspace_id, field_name="workspace_id")
    normalized_report_id = _normalize_path_segment(report_id, field_name="report_id")
    normalized_extension = str(extension).strip().lstrip(".")
    if not normalized_extension:
        raise ReportArtifactError("extension must not be empty.")
    if report_version <= 0:
        raise ReportArtifactError("report_version must be greater than zero.")
    return f"{normalized_workspace_id}/reports/{normalized_report_id}/{resolved_artifact_type}/v{report_version}.{normalized_extension}"


def compute_markdown_content_hash(markdown: str) -> str:
    return hashlib.sha256(encode_markdown_payload(markdown)).hexdigest()


def encode_markdown_payload(markdown: str) -> bytes:
    normalized_markdown = _validate_markdown(markdown)
    return normalized_markdown.encode("utf-8")


def resolve_report_artifact_bucket() -> str:
    for env_name in ("REPORT_ARTIFACT_BUCKET", "SUPABASE_ARTIFACT_BUCKET"):
        value = os.getenv(env_name)
        if value and value.strip():
            return value.strip()
    return DEFAULT_REPORT_ARTIFACT_BUCKET


def save_markdown_report_artifact(
    *,
    report_id: str,
    workspace_id: str,
    report_version: int,
    report_date: date,
    markdown: str,
    supabase: Client | None = None,
    created_by: str | None = None,
) -> SavedReportArtifact:
    db = supabase or get_supabase()
    _validate_required_text(report_id, field_name="report_id")
    _validate_required_text(workspace_id, field_name="workspace_id")
    if report_version <= 0:
        raise ReportArtifactError("report_version must be greater than zero.")
    if not isinstance(report_date, date):
        raise ReportArtifactError("report_date must be a date.")

    payload = encode_markdown_payload(markdown)
    content_hash = hashlib.sha256(payload).hexdigest()
    file_size = len(payload)
    storage_bucket = resolve_report_artifact_bucket()
    object_key = build_report_artifact_object_key(
        workspace_id=workspace_id,
        report_id=report_id,
        report_version=report_version,
        artifact_type=ArtifactType.MARKDOWN,
        extension="md",
    )

    existing_artifact = get_report_artifact(
        report_id=report_id,
        artifact_type=ArtifactType.MARKDOWN,
        version=report_version,
        supabase=db,
    )
    if existing_artifact is not None:
        existing_bytes = _download_existing_artifact_bytes(
            supabase=db,
            storage_bucket=storage_bucket,
            object_key=existing_artifact.object_key,
        )
        existing_hash = hashlib.sha256(existing_bytes).hexdigest()
        if existing_hash != content_hash:
            raise ReportArtifactConflictError(
                "A markdown artifact already exists for this report version with different content."
            )
        existing_artifact.content_hash = existing_hash
        existing_artifact.storage_bucket = storage_bucket
        if existing_artifact.file_size is None:
            existing_artifact.file_size = len(existing_bytes)
        return existing_artifact

    uploaded = False
    try:
        _upload_markdown_payload(
            supabase=db,
            storage_bucket=storage_bucket,
            object_key=object_key,
            payload=payload,
        )
        uploaded = True
        saved_artifact = save_report_artifact_metadata(
            report_id=report_id,
            artifact_type=ArtifactType.MARKDOWN,
            object_key=object_key,
            version=report_version,
            mime_type=MARKDOWN_CONTENT_TYPE,
            file_size=file_size,
            created_by=created_by,
            supabase=db,
        )
    except ReportPersistenceError:
        if uploaded:
            _cleanup_uploaded_artifact(
                supabase=db,
                storage_bucket=storage_bucket,
                object_key=object_key,
            )
        raise
    except Exception as exc:
        if uploaded:
            _cleanup_uploaded_artifact(
                supabase=db,
                storage_bucket=storage_bucket,
                object_key=object_key,
            )
        raise ReportArtifactUploadError(
            f"Failed to upload markdown artifact for report_id={report_id} object_key={object_key}."
        ) from exc

    saved_artifact.content_hash = content_hash
    saved_artifact.storage_bucket = storage_bucket
    return saved_artifact


def create_and_save_markdown_artifact(
    *,
    report: GeneratedReport,
    markdown: str | None = None,
    supabase: Client | None = None,
    created_by: str | None = None,
) -> SavedReportArtifact:
    if report.report_id is None:
        raise ReportArtifactError("report.report_id must not be empty.")
    if report.version is None:
        raise ReportArtifactError("report.version must not be empty.")
    rendered_markdown = markdown if markdown is not None else render_generated_report_markdown(report)
    return save_markdown_report_artifact(
        report_id=report.report_id,
        workspace_id=report.workspace_id,
        report_version=report.version,
        report_date=report.report_date,
        markdown=rendered_markdown,
        supabase=supabase,
        created_by=created_by,
    )


def _upload_markdown_payload(
    *,
    supabase: Client,
    storage_bucket: str,
    object_key: str,
    payload: bytes,
) -> None:
    try:
        supabase.storage.from_(storage_bucket).upload(
            path=object_key,
            file=payload,
            file_options={
                "content-type": MARKDOWN_CONTENT_TYPE,
                "upsert": "false",
            },
        )
    except Exception as exc:
        raise ReportArtifactUploadError(
            f"Failed to upload markdown artifact for object_key={object_key}."
        ) from exc


def _download_existing_artifact_bytes(
    *,
    supabase: Client,
    storage_bucket: str,
    object_key: str,
) -> bytes:
    try:
        return supabase.storage.from_(storage_bucket).download(object_key)
    except Exception as exc:
        raise ReportArtifactError(
            f"Failed to download existing artifact for object_key={object_key}."
        ) from exc


def _cleanup_uploaded_artifact(
    *,
    supabase: Client,
    storage_bucket: str,
    object_key: str,
) -> None:
    try:
        supabase.storage.from_(storage_bucket).remove([object_key])
    except Exception:
        logger.exception(
            "report_artifact_cleanup_failed",
            extra={
                "bucket_name": storage_bucket,
                "object_key": object_key,
            },
        )


def _validate_markdown(markdown: str) -> str:
    if not isinstance(markdown, str):
        raise ReportArtifactError("markdown must be a string.")
    if not markdown.strip():
        raise ReportArtifactError("markdown must not be empty.")
    return markdown


def _validate_required_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReportArtifactError(f"{field_name} must not be empty.")
    return value.strip()


def _normalize_path_segment(value: str, *, field_name: str) -> str:
    normalized = _validate_required_text(value, field_name=field_name)
    sanitized = normalized.replace("\\", "-").replace("/", "-").replace(":", "-").strip()
    if not sanitized:
        raise ReportArtifactError(f"{field_name} must not be empty.")
    return sanitized

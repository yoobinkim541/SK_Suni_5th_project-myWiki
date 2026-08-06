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
from .pdf_renderer import PdfEvidenceLine, PdfReportDocument, PdfSection, normalize_pdf_text, render_daily_report_pdf
from .ppt_renderer import build_daily_report_ppt_document, render_daily_report_ppt
from .word_renderer import build_daily_report_word_document, render_daily_report_word

logger = logging.getLogger(__name__)

DEFAULT_REPORT_ARTIFACT_BUCKET = "reports"
MARKDOWN_CONTENT_TYPE = "text/markdown"
PDF_CONTENT_TYPE = "application/pdf"
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


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


def compute_content_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def compute_markdown_content_hash(markdown: str) -> str:
    return compute_content_hash(encode_markdown_payload(markdown))


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
    payload = encode_markdown_payload(markdown)
    return _save_binary_report_artifact(
        report_id=report_id,
        workspace_id=workspace_id,
        report_version=report_version,
        report_date=report_date,
        artifact_type=ArtifactType.MARKDOWN,
        extension="md",
        mime_type=MARKDOWN_CONTENT_TYPE,
        payload=payload,
        supabase=supabase,
        created_by=created_by,
    )


def save_pdf_report_artifact(
    *,
    report_id: str,
    workspace_id: str,
    report_version: int,
    report_date: date,
    pdf_bytes: bytes,
    supabase: Client | None = None,
    created_by: str | None = None,
) -> SavedReportArtifact:
    return _save_binary_report_artifact(
        report_id=report_id,
        workspace_id=workspace_id,
        report_version=report_version,
        report_date=report_date,
        artifact_type=ArtifactType.PDF,
        extension="pdf",
        mime_type=PDF_CONTENT_TYPE,
        payload=_validate_binary_payload(pdf_bytes, field_name="pdf_bytes"),
        supabase=supabase,
        created_by=created_by,
    )


def save_docx_report_artifact(
    *,
    report_id: str,
    workspace_id: str,
    report_version: int,
    report_date: date,
    docx_bytes: bytes,
    supabase: Client | None = None,
    created_by: str | None = None,
) -> SavedReportArtifact:
    return _save_binary_report_artifact(
        report_id=report_id,
        workspace_id=workspace_id,
        report_version=report_version,
        report_date=report_date,
        artifact_type=ArtifactType.DOCX,
        extension="docx",
        mime_type=DOCX_CONTENT_TYPE,
        payload=_validate_binary_payload(docx_bytes, field_name="docx_bytes"),
        supabase=supabase,
        created_by=created_by,
    )


def save_pptx_report_artifact(
    *,
    report_id: str,
    workspace_id: str,
    report_version: int,
    report_date: date,
    pptx_bytes: bytes,
    supabase: Client | None = None,
    created_by: str | None = None,
) -> SavedReportArtifact:
    return _save_binary_report_artifact(
        report_id=report_id,
        workspace_id=workspace_id,
        report_version=report_version,
        report_date=report_date,
        artifact_type=ArtifactType.PPTX,
        extension="pptx",
        mime_type=PPTX_CONTENT_TYPE,
        payload=_validate_binary_payload(pptx_bytes, field_name="pptx_bytes"),
        supabase=supabase,
        created_by=created_by,
    )


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


def create_and_save_pdf_artifact(
    *,
    report: GeneratedReport,
    pdf_bytes: bytes | None = None,
    supabase: Client | None = None,
    created_by: str | None = None,
) -> SavedReportArtifact:
    if report.report_id is None:
        raise ReportArtifactError("report.report_id must not be empty.")
    if report.version is None:
        raise ReportArtifactError("report.version must not be empty.")

    rendered_pdf = pdf_bytes
    if rendered_pdf is None:
        rendered_pdf = _render_generated_report_pdf(report)

    return save_pdf_report_artifact(
        report_id=report.report_id,
        workspace_id=report.workspace_id,
        report_version=report.version,
        report_date=report.report_date,
        pdf_bytes=rendered_pdf,
        supabase=supabase,
        created_by=created_by,
    )


def create_and_save_docx_artifact(
    *,
    report: GeneratedReport,
    docx_bytes: bytes | None = None,
    supabase: Client | None = None,
    created_by: str | None = None,
) -> SavedReportArtifact:
    if report.report_id is None:
        raise ReportArtifactError("report.report_id must not be empty.")
    if report.version is None:
        raise ReportArtifactError("report.version must not be empty.")

    rendered_docx = docx_bytes
    if rendered_docx is None:
        report_key = _build_report_key_from_report(report)
        generated_at = report.generated_at.isoformat() if report.generated_at is not None else None
        word_document = build_daily_report_word_document(
            report_key=report_key,
            version=report.version,
            sections=report.sections,
            generated_at=generated_at,
            report_date=report.report_date,
            title=report.title,
        )
        rendered_docx = render_daily_report_word(word_document)

    return save_docx_report_artifact(
        report_id=report.report_id,
        workspace_id=report.workspace_id,
        report_version=report.version,
        report_date=report.report_date,
        docx_bytes=rendered_docx,
        supabase=supabase,
        created_by=created_by,
    )


def create_and_save_pptx_artifact(
    *,
    report: GeneratedReport,
    pptx_bytes: bytes | None = None,
    supabase: Client | None = None,
    created_by: str | None = None,
) -> SavedReportArtifact:
    if report.report_id is None:
        raise ReportArtifactError("report.report_id must not be empty.")
    if report.version is None:
        raise ReportArtifactError("report.version must not be empty.")

    rendered_pptx = pptx_bytes
    if rendered_pptx is None:
        report_key = _build_report_key_from_report(report)
        generated_at = report.generated_at.isoformat() if report.generated_at is not None else None
        ppt_document = build_daily_report_ppt_document(
            report_key=report_key,
            version=report.version,
            sections=report.sections,
            generated_at=generated_at,
            report_date=report.report_date,
            title=report.title,
        )
        rendered_pptx = render_daily_report_ppt(ppt_document)

    return save_pptx_report_artifact(
        report_id=report.report_id,
        workspace_id=report.workspace_id,
        report_version=report.version,
        report_date=report.report_date,
        pptx_bytes=rendered_pptx,
        supabase=supabase,
        created_by=created_by,
    )


def _save_binary_report_artifact(
    *,
    report_id: str,
    workspace_id: str,
    report_version: int,
    report_date: date,
    artifact_type: ArtifactType,
    extension: str,
    mime_type: str,
    payload: bytes,
    supabase: Client | None,
    created_by: str | None,
) -> SavedReportArtifact:
    db = supabase or get_supabase()
    _validate_required_text(report_id, field_name="report_id")
    _validate_required_text(workspace_id, field_name="workspace_id")
    if report_version <= 0:
        raise ReportArtifactError("report_version must be greater than zero.")
    if not isinstance(report_date, date):
        raise ReportArtifactError("report_date must be a date.")

    content_hash = compute_content_hash(payload)
    file_size = len(payload)
    storage_bucket = resolve_report_artifact_bucket()
    object_key = build_report_artifact_object_key(
        workspace_id=workspace_id,
        report_id=report_id,
        report_version=report_version,
        artifact_type=artifact_type,
        extension=extension,
    )

    existing_artifact = get_report_artifact(
        report_id=report_id,
        artifact_type=artifact_type,
        version=report_version,
        supabase=db,
    )
    if existing_artifact is not None:
        existing_bytes = _download_existing_artifact_bytes(
            supabase=db,
            storage_bucket=storage_bucket,
            object_key=existing_artifact.object_key,
        )
        existing_hash = compute_content_hash(existing_bytes)
        if existing_hash != content_hash:
            raise ReportArtifactConflictError(
                f"An artifact already exists for report version with different content: {artifact_type.value}."
            )
        existing_artifact.content_hash = existing_hash
        existing_artifact.storage_bucket = storage_bucket
        if existing_artifact.file_size is None:
            existing_artifact.file_size = len(existing_bytes)
        return existing_artifact

    uploaded = False
    try:
        _upload_payload(
            supabase=db,
            storage_bucket=storage_bucket,
            object_key=object_key,
            payload=payload,
            mime_type=mime_type,
        )
        uploaded = True
        saved_artifact = save_report_artifact_metadata(
            report_id=report_id,
            artifact_type=artifact_type,
            object_key=object_key,
            version=report_version,
            mime_type=mime_type,
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
            f"Failed to upload report artifact for report_id={report_id} object_key={object_key}."
        ) from exc

    saved_artifact.content_hash = content_hash
    saved_artifact.storage_bucket = storage_bucket
    return saved_artifact


def _upload_payload(
    *,
    supabase: Client,
    storage_bucket: str,
    object_key: str,
    payload: bytes,
    mime_type: str,
) -> None:
    try:
        supabase.storage.from_(storage_bucket).upload(
            path=object_key,
            file=payload,
            file_options={
                "content-type": mime_type,
                "upsert": "false",
            },
        )
    except Exception as exc:
        raise ReportArtifactUploadError(
            f"Failed to upload report artifact for object_key={object_key}."
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


def _build_report_key_from_report(report: GeneratedReport) -> str:
    return f"{report.report_type.value}:{report.workspace_id}:{report.report_date.isoformat()}"


def _validate_binary_payload(payload: bytes, *, field_name: str) -> bytes:
    if not isinstance(payload, (bytes, bytearray)):
        raise ReportArtifactError(f"{field_name} must be bytes.")
    raw = bytes(payload)
    if not raw:
        raise ReportArtifactError(f"{field_name} must not be empty.")
    return raw


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


def _render_generated_report_pdf(report: GeneratedReport) -> bytes:
    generated_at = report.generated_at.isoformat() if report.generated_at is not None else report.report_date.isoformat()
    title = normalize_pdf_text(report.title or "일일 산업 동향 보고서")
    subtitle = normalize_pdf_text(f"{report.report_type.value}:{report.workspace_id}:{report.report_date.isoformat()}")
    sections = tuple(
        PdfSection(
            category=normalize_pdf_text(section.category.value),
            title=normalize_pdf_text(section.title),
            body=normalize_pdf_text(_build_pdf_section_body(section)),
            confidence_label=normalize_pdf_text(_build_pdf_confidence_label(section)),
            evidences=tuple(
                PdfEvidenceLine(
                    document_version_id=normalize_pdf_text(citation.document_title or citation.document_version_id),
                    quoted_text=normalize_pdf_text(_build_pdf_citation_text(citation)),
                    relevance_score=citation.relevance_score,
                )
                for citation in section.news_citations[:3]
            ),
        )
        for section in report.sections
        if getattr(section.status, "value", section.status) == "completed"
    )
    document = PdfReportDocument(
        title=title,
        subtitle=subtitle,
        generated_at=generated_at,
        version=report.version,
        sections=sections,
    )
    return render_daily_report_pdf(document)


def _build_pdf_section_body(section) -> str:
    parts = [(section.current_summary or "").strip()]
    for heading, values in (
        ("\ud575\uc2ec \uc0ac\uc2e4", section.key_facts),
        ("SK\ud558\uc774\ub2c9\uc2a4 \uc2dc\uc0ac\uc810", section.implications),
        ("\uad00\ucc30 \ud3ec\uc778\ud2b8", section.watch_points),
    ):
        normalized = [str(value).strip() for value in values if str(value).strip()]
        if normalized:
            parts.append(heading)
            parts.extend(f"\u2022 {value}" for value in normalized)
    return "\n\n".join(part for part in parts if part) or "\ub0b4\uc6a9 \uc5c6\uc74c"


def _build_pdf_citation_text(citation) -> str:
    evidence_text = (citation.evidence_text or "").strip()
    if evidence_text:
        return evidence_text
    attribution = [
        value.strip()
        for value in (citation.document_title, citation.source_name, citation.published_at)
        if value and value.strip()
    ]
    return " | ".join(attribution) or "\ucd9c\ucc98 \uc815\ubcf4 \uc5c6\uc74c"


def _build_pdf_confidence_label(section) -> str:
    if section.importance_score is not None:
        if section.importance_score >= 85:
            return "high"
        if section.importance_score >= 70:
            return "medium"
    return "pending"

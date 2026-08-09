from __future__ import annotations

import hashlib
import logging
import os
from datetime import date

from supabase import Client

from ..analysis.repository import get_supabase
from .markdown_renderer import render_generated_report_markdown
from .models import ArtifactType, GeneratedReport, ReportSectionStatus
from .repository import (
    ReportPersistenceError,
    SavedReportArtifact,
    get_report_artifact,
    save_report_artifact_metadata,
)
from .pdf_renderer import PdfEvidenceLine, PdfExecutiveSummaryLine, PdfReportDocument, PdfSection, PdfSourceLine, normalize_pdf_text, render_daily_report_pdf
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
        rendered_pdf = _render_generated_report_pdf(_build_artifact_render_report(report))

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
        render_report = _build_artifact_render_report(report)
        report_key = _build_report_key_from_report(render_report)
        generated_at = render_report.generated_at.isoformat() if render_report.generated_at is not None else None
        word_document = build_daily_report_word_document(
            report_key=report_key,
            version=render_report.version,
            sections=render_report.sections,
            generated_at=generated_at,
            report_date=render_report.report_date,
            title=render_report.title,
            executive_summaries=render_report.executive_summaries,
            issue_summary_rows=render_report.issue_summary_rows,
            category_groups=render_report.category_groups,
            overall_implications=render_report.overall_implications,
            news_sources=render_report.news_sources,
            wiki_sources=render_report.wiki_sources,
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
        render_report = _build_artifact_render_report(report)
        report_key = _build_report_key_from_report(render_report)
        generated_at = render_report.generated_at.isoformat() if render_report.generated_at is not None else None
        ppt_document = build_daily_report_ppt_document(
            report_key=report_key,
            version=render_report.version,
            sections=render_report.sections,
            generated_at=generated_at,
            report_date=render_report.report_date,
            title=render_report.title,
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


def _build_artifact_render_report(report: GeneratedReport) -> GeneratedReport:
    render_report = report.model_copy(deep=True)
    for section in render_report.sections:
        if section.status == ReportSectionStatus.DRAFTING and _section_has_renderable_content(section):
            section.status = ReportSectionStatus.COMPLETED
    return render_report


def _section_has_renderable_content(section) -> bool:
    return bool(
        section.current_summary
        or section.key_facts
        or section.historical_context
        or section.implications
        or section.watch_points
        or section.news_citations
    )

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
    title = normalize_pdf_text(report.title or "\uc77c\uc77c \uc0b0\uc5c5 \ub3d9\ud5a5 \ubcf4\uace0\uc11c")
    sections = [
        PdfSection(
            category="",
            title="\uc624\ub298\uc758 \ud575\uc2ec \uc694\uc57d",
            body=_build_pdf_executive_summary(report),
            confidence_label="",
            section_type="executive",
            executive_items=_build_pdf_executive_items(report),
        ),
        PdfSection(category="", title="\uc774\uc288\ubcc4 \ubd84\uc11d", body="", confidence_label="", section_type="issues_heading"),
    ]
    sections.extend(
        PdfSection(
            category=section.category.value,
            title=f"ISSUE {index:02d}. {section.title}",
            body=_build_pdf_issue_body(section),
            confidence_label="",
            evidences=_build_pdf_evidences(section),
            section_type="issue",
            importance_score=section.importance_score,
            reliability_score=section.reliability_score,
            impact_direction=_enum_value(section.impact_direction),
            time_horizon=_enum_value(section.time_horizon),
        )
        for index, section in enumerate(report.sections, start=1)
        if getattr(section.status, "value", section.status) == "completed"
    )
    sections.extend(
        [
            PdfSection(category="", title="\uce74\ud14c\uace0\ub9ac\ubcc4 \uc815\ub9ac", body=_build_pdf_category_summary(report), confidence_label="", section_type="categories"),
            PdfSection(category="", title="\uc885\ud569 \uc2dc\uc0ac\uc810", body=_build_pdf_overall_implications(report), confidence_label="", section_type="implications"),
            PdfSection(category="", title="\uc804\uccb4 \ucd9c\ucc98 \ubaa9\ub85d", body="", confidence_label="", section_type="sources", source_rows=_build_pdf_source_rows(report)),
        ]
    )
    return render_daily_report_pdf(
        PdfReportDocument(
            title=title,
            subtitle=normalize_pdf_text(report.report_date.isoformat()),
            generated_at=generated_at,
            version=report.version,
            sections=tuple(sections),
        )
    )


def _build_pdf_executive_summary(report: GeneratedReport) -> str:
    summaries = [item.summary for item in report.executive_summaries if item.summary][:5]
    if not summaries:
        return f"- \uc8fc\uc694 \uc774\uc288 \uc815\ubcf4 \uc5c6\uc74c"
    return "\n".join(f"{index}. {summary}" for index, summary in enumerate(summaries, start=1))


def _build_pdf_executive_items(report: GeneratedReport) -> tuple[PdfExecutiveSummaryLine, ...]:
    category_by_issue = {row.issue_key: row.category.value for row in report.issue_summary_rows}
    return tuple(
        PdfExecutiveSummaryLine(
            title=item.title,
            summary=item.summary,
            category=category_by_issue.get(item.issue_key, ""),
            importance_score=item.importance_score,
            impact_direction=_enum_value(item.impact_direction),
            time_horizon=_enum_value(item.time_horizon),
        )
        for item in report.executive_summaries[:5]
    )


def _build_pdf_issue_body(section) -> str:
    facts = [item for item in section.key_facts if item] or ["- \uc815\ubcf4 \uc5c6\uc74c"]
    implications = [item for item in section.implications if item] or ["- \uc815\ubcf4 \uc5c6\uc74c"]
    watch_points = [item for item in section.watch_points if item] or ["- \uc815\ubcf4 \uc5c6\uc74c"]
    lines = ["\uc0ac\uc2e4", *[f"- {item}" for item in facts], "", "\uc758\ubbf8", section.current_summary or "\uc815\ubcf4 \uc5c6\uc74c", "", "SK\ud558\uc774\ub2c9\uc2a4 \uc601\ud5a5", *[f"- {item}" for item in implications], "", "\ub2e4\uc74c \ud655\uc778 \uc0ac\ud56d", *[f"- {item}" for item in watch_points]]
    return "\n".join(lines)


def _build_pdf_evidences(section) -> tuple[PdfEvidenceLine, ...]:
    return tuple(
        PdfEvidenceLine(
            document_version_id=normalize_pdf_text(_format_pdf_citation_label(citation)),
            quoted_text=normalize_pdf_text((citation.evidence_text or citation.document_title or "\ucd9c\ucc98 \uc815\ubcf4 \uc5c6\uc74c").strip()),
            relevance_score=citation.relevance_score,
        )
        for citation in section.news_citations
    )


def _format_pdf_citation_label(citation) -> str:
    parts = [part for part in (citation.source_name, citation.published_at) if part]
    return " | ".join(parts) or "\ub274\uc2a4 \ucd9c\ucc98"


def _build_pdf_category_summary(report: GeneratedReport) -> str:
    category_order = ("\uc81c\ud488\u00b7\uae30\uc220", "\uacbd\uc7c1\uc0ac", "\uace0\uac1d\u00b7\uc218\uc694\uc0b0\uc5c5", "\uacf5\uae09\ub9dd\u00b7\uc0dd\uc0b0", "\uc815\ucc45\u00b7\uaddc\uc81c", "\uc2dc\uc7a5\u00b7\uacbd\uc601")
    groups = {group.category.value: group.sections for group in report.category_groups}
    lines: list[str] = []
    for category in category_order:
        lines.append(category)
        sections = groups.get(category, [])
        if not sections:
            lines.append(f"- \uc8fc\uc694 \ub3d9\ud5a5 \uc5c6\uc74c")
        else:
            lines.extend(f"- {item.title}: {item.current_summary or '\uc815\ubcf4 \uc5c6\uc74c'}" for item in sections[:3])
    return "\n".join(lines)


def _build_pdf_overall_implications(report: GeneratedReport) -> str:
    overall = report.overall_implications
    opportunities = [f"- {item}" for item in (overall.opportunities if overall is not None else [])] or ["- \uc815\ubcf4 \uc5c6\uc74c"]
    risks = [f"- {item}" for item in (overall.risks if overall is not None else [])] or ["- \uc815\ubcf4 \uc5c6\uc74c"]
    monitoring = [f"- {item}" for item in (overall.monitoring_points if overall is not None else [])] or ["- \uc815\ubcf4 \uc5c6\uc74c"]
    return "\n".join([
        "\uae30\ud68c", *opportunities,
        "", "\uc704\ud5d8", *risks,
        "", "\uc9c0\uc18d \uad00\ucc30", *monitoring,
    ])


def _format_pdf_source_date(value: str | None) -> str:
    if not value:
        return ""
    return value[:10].replace("-", ".")


def _build_pdf_source_rows(report: GeneratedReport) -> tuple[PdfSourceLine, ...]:
    rows: list[PdfSourceLine] = []
    seen: set[tuple[str, str, str]] = set()
    for source in report.news_sources:
        key = ("\ub274\uc2a4", source.source_name or "", source.document_title or "")
        if key in seen:
            continue
        seen.add(key)
        rows.append(PdfSourceLine(source_type="\ub274\uc2a4", source_name=source.source_name or "", title=source.document_title or "", published_at=_format_pdf_source_date(source.published_at), url=source.source_url))
    for source in report.wiki_sources:
        key = ("\ub0b4\ubd80 Wiki", source.wiki_page_id, source.wiki_title or "")
        if key in seen:
            continue
        seen.add(key)
        rows.append(PdfSourceLine(source_type="\ub0b4\ubd80 Wiki", source_name="", title=source.wiki_title or "", published_at=""))
    return tuple(rows)


def _build_pdf_confidence_label(section) -> str:
    if section.importance_score is not None:
        if section.importance_score >= 85:
            return "high"
        if section.importance_score >= 70:
            return "medium"
    return "pending"


def _enum_value(value) -> str:
    if value is None:
        return ""
    return normalize_pdf_text(getattr(value, "value", str(value)))

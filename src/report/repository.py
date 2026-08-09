from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone

from pydantic import BaseModel
from supabase import Client

from ..analysis.repository import get_supabase
from .models import ArtifactType, GeneratedReport, ReportSectionDraft, ReportStatus, ReportType


class ReportPersistenceError(Exception):
    pass


class SavedReportSection(BaseModel):
    section_id: str
    report_id: str
    section_order: int
    issue_key: str
    title: str


class SavedReportArtifact(BaseModel):
    artifact_id: str
    report_id: str
    artifact_type: ArtifactType
    object_key: str
    version: int
    mime_type: str | None = None
    file_size: int | None = None
    created_at: datetime | None = None
    content_hash: str | None = None
    storage_bucket: str | None = None


def list_completed_daily_report_rows(
    *,
    workspace_id: str,
    supabase: Client | None = None,
) -> list[dict[str, object]]:
    db = supabase or get_supabase()
    return (
        db.table("reports")
        .select("id, workspace_id, report_key, version, title, report_type, status, request_config, created_at, completed_at")
        .eq("workspace_id", workspace_id)
        .eq("report_type", ReportType.DAILY.value)
        .eq("status", ReportStatus.COMPLETED.value)
        .execute()
        .data
    )


def list_report_sections_for_reports(
    *,
    report_ids: Sequence[str],
    supabase: Client | None = None,
) -> list[dict[str, object]]:
    if not report_ids:
        return []
    db = supabase or get_supabase()
    return (
        db.table("report_sections")
        .select("id, report_id, issue_key")
        .in_("report_id", list(report_ids))
        .execute()
        .data
    )


def list_report_artifacts_for_reports(
    *,
    report_ids: Sequence[str],
    supabase: Client | None = None,
) -> list[dict[str, object]]:
    if not report_ids:
        return []
    db = supabase or get_supabase()
    return (
        db.table("artifacts")
        .select("id, report_id, artifact_type, version")
        .in_("report_id", list(report_ids))
        .execute()
        .data
    )


def create_report_version(
    *,
    workspace_id: str,
    report_key: str,
    title: str,
    report_type: ReportType | str,
    request_config: dict[str, object],
    requested_by: str | None = None,
    supabase: Client | None = None,
) -> GeneratedReport:
    db = supabase or get_supabase()
    next_version = _get_next_report_version(
        workspace_id=workspace_id,
        report_key=report_key,
        supabase=db,
    )
    row = {
        "workspace_id": workspace_id,
        "report_key": report_key,
        "version": next_version,
        "requested_by": requested_by,
        "title": title,
        "report_type": report_type.value if isinstance(report_type, ReportType) else str(report_type),
        "status": ReportStatus.PENDING.value,
        "request_config": request_config,
    }
    try:
        inserted = db.table("reports").insert(row).execute().data[0]
    except Exception as exc:  # pragma: no cover
        raise ReportPersistenceError("Failed to create a new report version.") from exc

    return GeneratedReport(
        report_id=str(inserted["id"]),
        workspace_id=str(inserted["workspace_id"]),
        report_date=_extract_report_date(inserted.get("request_config")),
        report_type=ReportType(str(inserted["report_type"])),
        version=int(inserted["version"]),
        status=ReportStatus(str(inserted["status"])),
        created_at=inserted.get("created_at"),
    )


def get_latest_completed_report(
    *,
    workspace_id: str,
    report_key: str,
    supabase: Client | None = None,
) -> GeneratedReport | None:
    db = supabase or get_supabase()
    rows = (
        db.table("reports")
        .select("id, workspace_id, report_key, version, title, report_type, status, request_config, created_at")
        .eq("workspace_id", workspace_id)
        .eq("report_key", report_key)
        .eq("status", ReportStatus.COMPLETED.value)
        .execute()
        .data
    )
    if not rows:
        return None
    latest = max(rows, key=lambda row: int(row["version"]))
    return GeneratedReport(
        report_id=str(latest["id"]),
        workspace_id=str(latest["workspace_id"]),
        report_date=_extract_report_date(latest.get("request_config")),
        report_type=ReportType(str(latest["report_type"])),
        version=int(latest["version"]),
        status=ReportStatus(str(latest["status"])),
        created_at=latest.get("created_at"),
    )


def get_report_artifact(
    *,
    report_id: str,
    artifact_type: ArtifactType | str,
    version: int,
    supabase: Client | None = None,
) -> SavedReportArtifact | None:
    db = supabase or get_supabase()
    resolved_artifact_type = artifact_type.value if isinstance(artifact_type, ArtifactType) else str(artifact_type)
    rows = (
        db.table("artifacts")
        .select("id, report_id, artifact_type, object_key, version, mime_type, file_size, created_at")
        .eq("report_id", report_id)
        .eq("artifact_type", resolved_artifact_type)
        .eq("version", version)
        .execute()
        .data
    )
    if not rows:
        return None
    return _build_saved_report_artifact(rows[0])


def save_report_artifact_metadata(
    *,
    report_id: str,
    artifact_type: ArtifactType | str,
    object_key: str,
    version: int,
    mime_type: str | None = None,
    file_size: int | None = None,
    created_by: str | None = None,
    supabase: Client | None = None,
) -> SavedReportArtifact:
    db = supabase or get_supabase()
    resolved_artifact_type = artifact_type.value if isinstance(artifact_type, ArtifactType) else str(artifact_type)
    row = {
        "report_id": report_id,
        "artifact_type": resolved_artifact_type,
        "object_key": object_key,
        "version": version,
        "mime_type": mime_type,
        "file_size": file_size,
        "created_by": created_by,
    }
    try:
        inserted = db.table("artifacts").insert(row).execute().data[0]
    except Exception as exc:
        raise ReportPersistenceError("Failed to persist report artifact metadata.") from exc
    return _build_saved_report_artifact(inserted)


def mark_report_completed(
    *,
    report_id: str,
    supabase: Client | None = None,
) -> None:
    db = supabase or get_supabase()
    db.table("reports").update(
        {
            "status": ReportStatus.COMPLETED.value,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", report_id).execute()


def mark_report_failed(
    *,
    report_id: str,
    supabase: Client | None = None,
) -> None:
    db = supabase or get_supabase()
    db.table("reports").update({"status": ReportStatus.FAILED.value}).eq("id", report_id).execute()


def save_report_sections(
    *,
    report_id: str,
    sections: Sequence[ReportSectionDraft],
    supabase: Client | None = None,
    model_name: str | None = None,
    prompt_version: str | None = None,
) -> list[SavedReportSection]:
    db = supabase or get_supabase()
    existing_by_issue_key = _get_existing_sections_by_issue_key(
        report_id=report_id,
        supabase=db,
    )

    rows_to_insert: list[dict[str, object]] = []
    rows_to_update: list[tuple[str, dict[str, object]]] = []
    section_by_issue_key: dict[str, ReportSectionDraft] = {}

    for order, section in enumerate(sections, start=1):
        payload = _build_section_row_payload(
            report_id=report_id,
            section=section,
            section_order=order,
            model_name=model_name,
            prompt_version=prompt_version,
        )
        section_by_issue_key[section.issue_key] = section
        existing = existing_by_issue_key.get(section.issue_key)
        if existing is None:
            rows_to_insert.append(payload)
            continue
        rows_to_update.append((str(existing["id"]), payload))

    saved_sections: list[SavedReportSection] = []
    for section_id, payload in rows_to_update:
        updated = (
            db.table("report_sections")
            .update(payload)
            .eq("id", section_id)
            .execute()
            .data[0]
        )
        saved_sections.append(
            SavedReportSection(
                section_id=str(updated["id"]),
                report_id=report_id,
                section_order=int(updated["section_order"]),
                issue_key=str(updated["issue_key"]),
                title=str(updated["title"]),
            )
        )

    inserted_sections: list[SavedReportSection] = []
    if rows_to_insert:
        inserted_rows = db.table("report_sections").insert(rows_to_insert).execute().data
        for row in inserted_rows:
            inserted_sections.append(
                SavedReportSection(
                    section_id=str(row["id"]),
                    report_id=report_id,
                    section_order=int(row["section_order"]),
                    issue_key=str(row["issue_key"]),
                    title=str(row["title"]),
                )
            )

    all_saved = sorted(saved_sections + inserted_sections, key=lambda item: item.section_order)

    try:
        save_report_citations(
            section_map=all_saved,
            sections=sections,
            supabase=db,
        )
        save_report_wiki_references(
            section_map=all_saved,
            sections=sections,
            supabase=db,
        )
    except Exception as exc:
        mark_report_failed(report_id=report_id, supabase=db)
        inserted_section_ids = [section.section_id for section in inserted_sections]
        if inserted_section_ids:
            db.table("report_sections").update({"status": "failed"}).in_("id", inserted_section_ids).execute()
        raise ReportPersistenceError("Failed to persist report citations or wiki references.") from exc

    return all_saved


def save_report_citations(
    *,
    section_map: Sequence[SavedReportSection],
    sections: Sequence[ReportSectionDraft],
    supabase: Client | None = None,
) -> None:
    db = supabase or get_supabase()
    section_by_issue_key = {section.issue_key: section for section in section_map}
    section_ids = [item.section_id for item in section_map]
    existing_rows = (
        db.table("report_citations")
        .select("id, section_id, document_version_id, citation_order")
        .in_("section_id", section_ids)
        .execute()
        .data
    )
    # citation_order도 키에 포함한다 - 같은 문서를 두 번 인용하면
    # (section_id, document_version_id)만으로는 두 번째 인용이 조용히 드롭된다.
    existing_by_key = {
        (str(row["section_id"]), str(row["document_version_id"]), row.get("citation_order")): row["id"]
        for row in existing_rows
    }
    seen_keys: set[tuple[str, str, object]] = set()

    rows_to_insert: list[dict[str, object]] = []
    for section in sections:
        saved_section = section_by_issue_key[section.issue_key]
        for citation in section.news_citations:
            key = (saved_section.section_id, citation.document_version_id, citation.citation_order)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            if key in existing_by_key:
                continue
            rows_to_insert.append(
                {
                    "section_id": saved_section.section_id,
                    "document_version_id": citation.document_version_id,
                    "source_start_line": citation.source_start_line,
                    "source_end_line": citation.source_end_line,
                    "quoted_text": citation.evidence_text,
                    "relevance_score": citation.relevance_score,
                    "citation_order": citation.citation_order,
                }
            )

    # 이번 실행에서 더 이상 근거로 쓰이지 않는 기존 citation은 삭제한다.
    # (재생성 시 빠진 근거가 테이블에 영구 잔존하는 것을 방지)
    stale_ids = [row_id for key, row_id in existing_by_key.items() if key not in seen_keys]
    if stale_ids:
        db.table("report_citations").delete().in_("id", stale_ids).execute()

    if rows_to_insert:
        db.table("report_citations").insert(rows_to_insert).execute()


def save_report_wiki_references(
    *,
    section_map: Sequence[SavedReportSection],
    sections: Sequence[ReportSectionDraft],
    supabase: Client | None = None,
) -> None:
    db = supabase or get_supabase()
    section_by_issue_key = {section.issue_key: section for section in section_map}
    section_ids = [item.section_id for item in section_map]
    existing_rows = (
        db.table("report_wiki_references")
        .select("id, section_id, wiki_version_id")
        .in_("section_id", section_ids)
        .execute()
        .data
    )
    existing_by_key = {
        (str(row["section_id"]), str(row["wiki_version_id"])): row["id"]
        for row in existing_rows
        if row.get("wiki_version_id") is not None
    }
    seen_keys: set[tuple[str, str]] = set()

    rows_to_insert: list[dict[str, object]] = []
    for section in sections:
        saved_section = section_by_issue_key[section.issue_key]
        for reference in section.wiki_references:
            if reference.wiki_version_id is None:
                raise ReportPersistenceError("wiki_version_id is required to persist a wiki reference.")
            key = (saved_section.section_id, reference.wiki_version_id)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            if key in existing_by_key:
                continue
            rows_to_insert.append(
                {
                    "section_id": saved_section.section_id,
                    "wiki_page_id": reference.wiki_page_id,
                    "wiki_version_id": reference.wiki_version_id,
                    "reference_order": reference.reference_order,
                    "relevance_score": reference.similarity_score,
                }
            )

    # 이번 실행에서 더 이상 근거로 쓰이지 않는 기존 wiki reference는 삭제한다.
    stale_ids = [row_id for key, row_id in existing_by_key.items() if key not in seen_keys]
    if stale_ids:
        db.table("report_wiki_references").delete().in_("id", stale_ids).execute()

    if rows_to_insert:
        db.table("report_wiki_references").insert(rows_to_insert).execute()


def _get_next_report_version(
    *,
    workspace_id: str,
    report_key: str,
    supabase: Client | None = None,
) -> int:
    db = supabase or get_supabase()
    rows = (
        db.table("reports")
        .select("version")
        .eq("workspace_id", workspace_id)
        .eq("report_key", report_key)
        .execute()
        .data
    )
    if not rows:
        return 1
    return max(int(row["version"]) for row in rows) + 1


def _get_existing_sections_by_issue_key(
    *,
    report_id: str,
    supabase: Client | None = None,
) -> dict[str, dict[str, object]]:
    db = supabase or get_supabase()
    rows = (
        db.table("report_sections")
        .select("id, report_id, issue_key, section_order, title")
        .eq("report_id", report_id)
        .execute()
        .data
    )
    return {
        str(row["issue_key"]): row
        for row in rows
        if row.get("issue_key")
    }


def _build_section_row_payload(
    *,
    report_id: str,
    section: ReportSectionDraft,
    section_order: int,
    model_name: str | None,
    prompt_version: str | None,
) -> dict[str, object]:
    return {
        "report_id": report_id,
        "issue_key": section.issue_key,
        "section_order": section_order,
        "title": section.title,
        "content": json.dumps(_build_section_content_payload(section), ensure_ascii=False),
        "status": section.status.value,
        "model_name": model_name,
        "prompt_version": prompt_version,
    }


def _build_section_content_payload(section: ReportSectionDraft) -> dict[str, object]:
    return {
        "issue_key": section.issue_key,
        "representative_analysis_result_id": section.representative_analysis_result_id,
        "category": section.category.value,
        "importance_score": section.importance_score,
        "impact_direction": section.impact_direction.value if section.impact_direction is not None else None,
        "time_horizon": section.time_horizon.value if section.time_horizon is not None else None,
        "current_summary": section.current_summary,
        "key_facts": list(section.key_facts),
        "historical_context": list(section.historical_context),
        "implications": list(section.implications),
        "watch_points": list(section.watch_points),
    }


def _build_saved_report_artifact(row: dict[str, object]) -> SavedReportArtifact:
    return SavedReportArtifact(
        artifact_id=str(row["id"]),
        report_id=str(row["report_id"]),
        artifact_type=ArtifactType(str(row["artifact_type"])),
        object_key=str(row["object_key"]),
        version=int(row["version"]),
        mime_type=str(row["mime_type"]) if row.get("mime_type") is not None else None,
        file_size=int(row["file_size"]) if row.get("file_size") is not None else None,
        created_at=row.get("created_at"),
    )


def _extract_report_date(request_config: object) -> datetime.date:
    if not isinstance(request_config, dict):
        raise ReportPersistenceError("request_config must include report_date.")
    report_date = request_config.get("report_date")
    if not report_date:
        raise ReportPersistenceError("request_config must include report_date.")
    return datetime.fromisoformat(str(report_date)).date()

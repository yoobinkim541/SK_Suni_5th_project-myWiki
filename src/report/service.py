from __future__ import annotations

import json
from datetime import date
from typing import Any

from supabase import Client

from ..analysis.repository import get_supabase
from .models import ReportType


def get_daily_report(
    workspace_id: str,
    report_date: date,
    *,
    supabase: Client | None = None,
) -> dict[str, Any] | None:
    """Load the latest completed daily report for a workspace and date."""
    db = supabase or get_supabase()
    report_key = _build_daily_report_key(workspace_id, report_date)

    report_rows = (
        db.table("reports")
        .select("id, workspace_id, report_key, version, title, report_type, status, created_at, completed_at")
        .eq("workspace_id", workspace_id)
        .eq("report_key", report_key)
        .eq("report_type", ReportType.DAILY.value)
        .eq("status", "completed")
        .execute()
        .data
    )
    if not report_rows:
        return None

    latest_report = max(report_rows, key=lambda row: int(row["version"]))
    report_id = str(latest_report["id"])

    section_rows = (
        db.table("report_sections")
        .select(
            "id, report_id, issue_key, section_order, title, content, status, model_name, prompt_version, created_at, updated_at"
        )
        .eq("report_id", report_id)
        .order("section_order")
        .execute()
        .data
    )
    section_ids = [str(row["id"]) for row in section_rows]

    citation_rows: list[dict[str, Any]] = []
    if section_ids:
        citation_rows = (
            db.table("report_citations")
            .select(
                "id, section_id, document_version_id, source_start_line, source_end_line, quoted_text, relevance_score, citation_order"
            )
            .in_("section_id", section_ids)
            .order("citation_order")
            .execute()
            .data
        )

    enriched_citations = _enrich_citations(db, citation_rows)
    citations_by_section: dict[str, list[dict[str, Any]]] = {}
    for citation in enriched_citations:
        citations_by_section.setdefault(str(citation["section_id"]), []).append(citation)

    sections: list[dict[str, Any]] = []
    for row in section_rows:
        section_id = str(row["id"])
        sections.append(
            {
                "id": section_id,
                "report_id": str(row["report_id"]),
                "issue_key": str(row.get("issue_key") or ""),
                "section_order": int(row["section_order"]),
                "title": str(row["title"]),
                "content": _parse_section_content(row.get("content")),
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
        "workspace_id": str(latest_report["workspace_id"]),
        "report_key": str(latest_report["report_key"]),
        "version": int(latest_report["version"]),
        "title": str(latest_report["title"]),
        "report_type": str(latest_report["report_type"]),
        "status": str(latest_report["status"]),
        "date": report_date.isoformat(),
        "created_at": latest_report.get("created_at"),
        "completed_at": latest_report.get("completed_at"),
        "sections": sections,
    }


def _build_daily_report_key(workspace_id: str, report_date: date) -> str:
    return f"{ReportType.DAILY.value}:{workspace_id}:{report_date.isoformat()}"


def _parse_section_content(content: Any) -> dict[str, Any] | str | None:
    if content is None:
        return None
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        stripped = content.strip()
        if not stripped:
            return None
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return stripped
        return parsed if isinstance(parsed, dict) else stripped
    return str(content)


def _enrich_citations(db: Client, citation_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not citation_rows:
        return []

    version_ids = list({str(row["document_version_id"]) for row in citation_rows})
    version_rows = (
        db.table("document_versions")
        .select("id, document_id")
        .in_("id", version_ids)
        .execute()
        .data
    )
    document_id_by_version = {str(row["id"]): str(row["document_id"]) for row in version_rows}

    document_ids = list({doc_id for doc_id in document_id_by_version.values()})
    documents_by_id: dict[str, dict[str, Any]] = {}
    if document_ids:
        document_rows = (
            db.table("documents")
            .select("id, title, canonical_url, published_at, source_id")
            .in_("id", document_ids)
            .execute()
            .data
        )
        documents_by_id = {str(row["id"]): row for row in document_rows}

    source_ids = list(
        {
            str(row["source_id"])
            for row in documents_by_id.values()
            if row.get("source_id") is not None
        }
    )
    source_name_by_id: dict[str, str] = {}
    if source_ids:
        source_rows = db.table("sources").select("id, name").in_("id", source_ids).execute().data
        source_name_by_id = {str(row["id"]): str(row["name"]) for row in source_rows}

    enriched_rows: list[dict[str, Any]] = []
    for row in citation_rows:
        document_version_id = str(row["document_version_id"])
        document_id = document_id_by_version.get(document_version_id)
        document = documents_by_id.get(document_id, {}) if document_id else {}
        source_id = document.get("source_id")
        enriched_rows.append(
            {
                "id": str(row["id"]),
                "section_id": str(row["section_id"]),
                "document_version_id": document_version_id,
                "source_start_line": row.get("source_start_line"),
                "source_end_line": row.get("source_end_line"),
                "quoted_text": row.get("quoted_text"),
                "relevance_score": row.get("relevance_score"),
                "citation_order": row.get("citation_order"),
                "document_title": document.get("title"),
                "source_url": document.get("canonical_url"),
                "source_name": source_name_by_id.get(str(source_id)) if source_id is not None else None,
                "published_at": document.get("published_at"),
            }
        )
    return enriched_rows

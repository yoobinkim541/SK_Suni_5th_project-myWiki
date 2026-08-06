from __future__ import annotations

import json
from datetime import date
from typing import Any

from supabase import Client

from ..analysis.repository import get_supabase
from .models import ReportStatus, ReportType


def get_daily_report(
    workspace_id: str,
    report_date: date,
    *,
    supabase: Client | None = None,
) -> dict[str, Any] | None:
    db = supabase or get_supabase()
    report_key = f"{ReportType.DAILY.value}:{workspace_id}:{report_date.isoformat()}"

    report_rows = (
        db.table("reports")
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

    report_row = report_rows[0]
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

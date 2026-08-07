"""Persist the exact analysis input used by the scheduled daily report."""
from __future__ import annotations

from datetime import date, datetime
from typing import Sequence

from src.pipeline_common.db import get_client

DAILY_REPORT_ANALYSIS_BATCHES_TABLE = "daily_report_analysis_batches"


def save_analysis_batch(
    *,
    workspace_id: str,
    report_date: date,
    document_version_ids: Sequence[str],
    started_at: datetime,
) -> None:
    """Create or replace the one scheduled analysis batch for a report date."""
    get_client().table(DAILY_REPORT_ANALYSIS_BATCHES_TABLE).upsert(
        {
            "workspace_id": workspace_id,
            "report_date": report_date.isoformat(),
            "document_version_ids": list(dict.fromkeys(str(value) for value in document_version_ids)),
            "status": "running",
            "started_at": started_at.isoformat(),
            "completed_at": None,
        },
        on_conflict="workspace_id,report_date",
    ).execute()


def mark_analysis_batch_completed(*, workspace_id: str, report_date: date, completed_at: datetime) -> None:
    get_client().table(DAILY_REPORT_ANALYSIS_BATCHES_TABLE).update(
        {"status": "completed", "completed_at": completed_at.isoformat()}
    ).eq("workspace_id", workspace_id).eq("report_date", report_date.isoformat()).execute()


def get_completed_analysis_batch_document_ids(*, workspace_id: str, report_date: date) -> list[str]:
    rows = (
        get_client().table(DAILY_REPORT_ANALYSIS_BATCHES_TABLE)
        .select("document_version_ids")
        .eq("workspace_id", workspace_id)
        .eq("report_date", report_date.isoformat())
        .eq("status", "completed")
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        raise LookupError(f"No completed daily-report analysis batch exists for {report_date.isoformat()}.")
    return [str(value) for value in rows[0].get("document_version_ids") or []]

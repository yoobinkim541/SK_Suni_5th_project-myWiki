"""Generate the daily report at a fixed scheduled time.

GitHub Actions invokes this script at 23:00 UTC, which is 08:00 in Asia/Seoul.
The report date is resolved in Korea Standard Time so reports remain correctly
dated even though GitHub Actions cron schedules are expressed in UTC.

Usage:
    python scripts/generate_daily_report_scheduled.py
"""

from __future__ import annotations

import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.pipeline_common.db import get_client
from src.analysis.daily_report_batch import get_completed_analysis_batch_document_ids
from src.report.candidate_provider import get_report_candidates
from src.report.service import generate_daily_report_artifacts

SEOUL_TZ = timezone(timedelta(hours=9))


def log(message: str) -> None:
    print(f"[generate_daily_report_scheduled] {message}", flush=True)


def get_workspace_id() -> str:
    rows = get_client().table("workspaces").select("id, name").limit(2).execute().data
    if len(rows) != 1:
        raise SystemExit(f"workspace_id could not be resolved automatically (workspaces={len(rows)}).")
    return str(rows[0]["id"])


def get_daily_report_window(now: datetime) -> tuple[datetime, datetime]:
    """Return the completed 08:00-to-08:00 Korea Standard Time window."""
    seoul_now = now.astimezone(SEOUL_TZ)
    window_end = datetime.combine(seoul_now.date(), time(hour=8), tzinfo=SEOUL_TZ)
    window_start = window_end - timedelta(days=1)
    return window_start.astimezone(timezone.utc), window_end.astimezone(timezone.utc)


def run_scheduled_daily_report(*, now: datetime | None = None) -> dict[str, object]:
    current_time = now or datetime.now(timezone.utc)
    report_date = current_time.astimezone(SEOUL_TZ).date()
    workspace_id = get_workspace_id()
    window_start, window_end = get_daily_report_window(current_time)
    try:
        batch_document_version_ids = get_completed_analysis_batch_document_ids(workspace_id=workspace_id, report_date=report_date)
        candidates = get_report_candidates(
            workspace_id=workspace_id,
            report_date=report_date,
            published_from=window_start,
            document_version_ids=batch_document_version_ids,
            published_to=window_end,
        )
    except LookupError:
        candidates = get_report_candidates(
            workspace_id=workspace_id,
            report_date=report_date,
            published_from=window_start,
            published_to=window_end,
        )
    analysis_document_version_ids = [candidate.document_version_id for candidate in candidates]

    log(
        "daily report generation started "
        f"(date={report_date.isoformat()} window={window_start.isoformat()}..{window_end.isoformat()} "
        f"candidates={len(analysis_document_version_ids)})"
    )
    result = generate_daily_report_artifacts(
        workspace_id=workspace_id,
        report_date=report_date,
        requested_by=None,
        analysis_document_version_ids=analysis_document_version_ids,
    )
    log(
        "daily report generation complete: "
        f"report_id={result['report_id']} version={result['version']} status={result['status']}"
    )
    return result


if __name__ == "__main__":
    run_scheduled_daily_report()

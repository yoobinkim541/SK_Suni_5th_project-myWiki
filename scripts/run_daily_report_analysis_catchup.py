"""Run and record the adaptive 07:00 KST analysis batch for the daily report."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from scripts.run_analysis_pipeline import (
    get_adaptive_analysis_limit,
    get_workspace_id,
    run_analysis_pipeline,
    select_analysis_candidates,
)
from src.analysis.daily_report_batch import mark_analysis_batch_completed, save_analysis_batch

SEOUL_TZ = timezone(timedelta(hours=9))


def run_daily_report_analysis_catchup(*, now: datetime | None = None) -> list[str] | None:
    current_time = now or datetime.now(timezone.utc)
    workspace_id = get_workspace_id()
    limit = get_adaptive_analysis_limit(workspace_id)
    candidate_ids = select_analysis_candidates(workspace_id, limit=limit)
    report_date = current_time.astimezone(SEOUL_TZ).date()

    save_analysis_batch(
        workspace_id=workspace_id,
        report_date=report_date,
        document_version_ids=candidate_ids,
        started_at=current_time,
    )
    if not candidate_ids:
        mark_analysis_batch_completed(
            workspace_id=workspace_id,
            report_date=report_date,
            completed_at=datetime.now(timezone.utc),
        )
        return []

    completed_ids = run_analysis_pipeline(
        workspace_id,
        limit=limit,
        document_version_ids=candidate_ids,
    )
    if completed_ids is not None:
        mark_analysis_batch_completed(
            workspace_id=workspace_id,
            report_date=report_date,
            completed_at=datetime.now(timezone.utc),
        )
    return completed_ids


if __name__ == "__main__":
    sys.exit(0 if run_daily_report_analysis_catchup() is not None else 1)

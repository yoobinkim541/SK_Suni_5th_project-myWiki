from __future__ import annotations

import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from scripts.run_analysis_pipeline import get_adaptive_analysis_limit, run_analysis_pipeline
from scripts.run_pipeline import run_collect, run_preprocess

from src.pipeline_common.db import get_client
from src.settings.service import get_workspace_settings, mark_data_refreshed

GRACE_MINUTES = 15
KST = timezone(timedelta(hours=9))
NIGHTLY_ANALYSIS_WINDOW_KST = (time(0, 0), time(6, 0))


def is_within_nightly_analysis_window(now_utc: datetime) -> bool:
    """Return whether the dedicated nightly analysis job owns this time window."""
    now_kst_time = now_utc.astimezone(KST).time()
    start, end = NIGHTLY_ANALYSIS_WINDOW_KST
    return start <= now_kst_time < end


def log(msg: str) -> None:
    print(f"[refresh_data_scheduled] {msg}", flush=True)


def is_refresh_due(last_data_refresh_at: str | None, cycle_minutes: int, *, now: datetime) -> bool:
    if last_data_refresh_at is None:
        return True
    last = datetime.fromisoformat(last_data_refresh_at.replace("Z", "+00:00"))
    elapsed_minutes = (now - last).total_seconds() / 60
    return elapsed_minutes >= cycle_minutes - GRACE_MINUTES


def get_workspace_id() -> str:
    rows = get_client().table("workspaces").select("id, name").limit(2).execute().data
    if len(rows) != 1:
        raise SystemExit(f"workspace_id could not be resolved automatically (workspaces={len(rows)}).")
    return str(rows[0]["id"])


def run_scheduled_refresh(*, now: datetime | None = None) -> bool:
    workspace_id = get_workspace_id()
    settings = get_workspace_settings(workspace_id)

    current_time = now or datetime.now(timezone.utc)
    if not is_refresh_due(settings.last_data_refresh_at, settings.data_refresh_cycle_minutes, now=current_time):
        log(
            f"refresh skipped (cycle={settings.data_refresh_cycle_minutes}m last={settings.last_data_refresh_at})"
        )
        return False

    gate_now = current_time
    log(f"refresh started (cycle={settings.data_refresh_cycle_minutes}m)")

    collect_summary = run_collect(UUID(workspace_id), limit=None, source_id=None)
    log(f"collect complete: {collect_summary}")

    preprocess_summary = run_preprocess(UUID(workspace_id))
    log(f"preprocess complete: {preprocess_summary}")

    if is_within_nightly_analysis_window(current_time):
        log("analysis skipped: dedicated nightly analysis job owns this time window")
    else:
        analysis_limit = get_adaptive_analysis_limit(workspace_id)
        log(f"analysis pipeline started (limit={analysis_limit})")
        if run_analysis_pipeline(workspace_id, limit=analysis_limit) is None:
            log("analysis did not complete; daily report will wait for its 08:00 schedule")

    mark_data_refreshed(workspace_id, at=gate_now)
    log("refresh complete (daily report is generated separately at 08:00 KST)")
    return True


if __name__ == "__main__":
    sys.exit(0 if run_scheduled_refresh() is not None else 1)

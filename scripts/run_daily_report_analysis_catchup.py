"""Run the adaptive analysis batch that feeds the 07:30 KST daily report.

The success criterion is the same candidate set used by the scheduled report:
selected_for_report=True documents whose published_at is inside the report's
08:00 KST to 08:00 KST publication window. Ranking-batch selected totals are
logged for observability, but they are not used to decide completion.
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from scripts.generate_daily_report_scheduled import get_daily_report_window
from scripts.run_analysis_pipeline import (
    get_adaptive_analysis_limit,
    get_workspace_id,
    run_analysis_pipeline,
    select_analysis_candidates,
)
from src.analysis.daily_report_batch import (
    mark_analysis_batch_completed,
    mark_analysis_batch_insufficient,
    save_analysis_batch,
)
from src.analysis.exceptions import RankingLoadFailedError
from src.analysis.repository import (
    get_documents_ready_for_classification,
    get_documents_ready_for_importance,
    get_documents_ready_for_ranking,
    get_documents_ready_for_reliability,
    get_ranked_results_for_report,
)
from src.pipeline_common.db import get_client
from src.report.candidate_provider import get_report_candidates
from src.report.models import ReportCandidate

SEOUL_TZ = timezone(timedelta(hours=9))
DEFAULT_MIN_CANDIDATES = 6
REPORT_SELECTION_LIMIT = 200
ROUND_BUDGET = timedelta(minutes=30)
QUERY_CHUNK_SIZE = 100


@dataclass(frozen=True)
class CandidateSnapshot:
    ranking_selected_total: int
    window_candidates: list[ReportCandidate]

    @property
    def window_selected(self) -> int:
        return len(self.window_candidates)

    @property
    def window_document_version_ids(self) -> list[str]:
        return [candidate.document_version_id for candidate in self.window_candidates]


def log(message: str) -> None:
    print(f"[run_daily_report_analysis_catchup] {message}", flush=True)


def _default_deadline(report_date: date) -> datetime:
    deadline_kst = datetime.combine(report_date, time(hour=7, minute=15), tzinfo=SEOUL_TZ)
    return deadline_kst.astimezone(timezone.utc)


def get_selected_results(workspace_id: str, ranking_batch_date: date) -> list:
    return get_ranked_results_for_report(
        workspace_id=workspace_id,
        ranking_batch_date=ranking_batch_date,
        limit=REPORT_SELECTION_LIMIT,
    )


def _try_get_selected_results(workspace_id: str, ranking_batch_date: date) -> list | None:
    try:
        return get_selected_results(workspace_id, ranking_batch_date)
    except RankingLoadFailedError:
        log("selected_for_report lookup failed; stopping with the last known state")
        return None


def get_window_report_candidates(
    *,
    workspace_id: str,
    report_date: date,
    window_start: datetime,
    window_end: datetime,
) -> list[ReportCandidate]:
    return get_report_candidates(
        workspace_id=workspace_id,
        report_date=report_date,
        published_from=window_start,
        published_to=window_end,
    )


def _load_candidate_snapshot(
    *,
    workspace_id: str,
    report_date: date,
    ranking_batch_date: date,
    window_start: datetime,
    window_end: datetime,
) -> CandidateSnapshot | None:
    ranking_selected = _try_get_selected_results(workspace_id, ranking_batch_date)
    if ranking_selected is None:
        return None
    return CandidateSnapshot(
        ranking_selected_total=len(ranking_selected),
        window_candidates=get_window_report_candidates(
            workspace_id=workspace_id,
            report_date=report_date,
            window_start=window_start,
            window_end=window_end,
        ),
    )


def _log_snapshot(
    *,
    prefix: str,
    report_date: date,
    window_start: datetime,
    window_end: datetime,
    snapshot: CandidateSnapshot,
    min_candidates: int,
) -> None:
    missing = max(0, min_candidates - snapshot.window_selected)
    log(
        f"{prefix} report_date={report_date.isoformat()} "
        f"window_start={window_start.isoformat()} window_end={window_end.isoformat()} "
        f"ranking_selected_total={snapshot.ranking_selected_total} "
        f"window_selected={snapshot.window_selected} "
        f"target_candidates={min_candidates} missing_candidates={missing}"
    )


def _chunked(values: Sequence[str], size: int = QUERY_CHUNK_SIZE):
    for index in range(0, len(values), size):
        yield list(values[index : index + size])


def get_report_window_document_version_ids(
    *,
    workspace_id: str,
    window_start: datetime,
    window_end: datetime,
) -> tuple[list[str], list[str]]:
    db = get_client()
    document_rows: list[dict[str, Any]] = []
    start = 0
    page_size = 1000
    while True:
        rows = (
            db.table("documents")
            .select("id")
            .eq("workspace_id", workspace_id)
            .eq("status", "active")
            .gte("published_at", window_start.isoformat())
            .lt("published_at", window_end.isoformat())
            .range(start, start + page_size - 1)
            .execute()
            .data
        )
        document_rows.extend(rows)
        if len(rows) < page_size:
            break
        start += page_size

    document_ids = [str(row["id"]) for row in document_rows]
    if not document_ids:
        return [], []

    version_ids: list[str] = []
    for chunk in _chunked(document_ids):
        rows = db.table("document_versions").select("id").in_("document_id", chunk).execute().data
        version_ids.extend(str(row["id"]) for row in rows)
    return document_ids, list(dict.fromkeys(version_ids))


def select_window_analysis_candidates(
    *,
    workspace_id: str,
    limit: int,
    window_start: datetime,
    window_end: datetime,
) -> list[str]:
    window_document_ids, window_version_ids = get_report_window_document_version_ids(
        workspace_id=workspace_id,
        window_start=window_start,
        window_end=window_end,
    )
    if not window_version_ids:
        return []

    cap = max(0, limit)
    if cap == 0:
        return []

    window_version_set = set(window_version_ids)
    selected: list[str] = []
    for document_version_id in select_analysis_candidates(workspace_id, limit=cap):
        if document_version_id in window_version_set and document_version_id not in selected:
            selected.append(document_version_id)

    if len(selected) < cap:
        ready_groups = (
            get_documents_ready_for_ranking(
                workspace_id=workspace_id,
                limit=cap * 5,
                restrict_to_version_ids=window_version_ids,
            ),
            get_documents_ready_for_importance(
                workspace_id=workspace_id,
                limit=cap * 5,
                restrict_to_version_ids=window_version_ids,
            ),
            get_documents_ready_for_reliability(
                workspace_id=workspace_id,
                limit=cap * 5,
                restrict_to_version_ids=window_version_ids,
            ),
            get_documents_ready_for_classification(
                workspace_id=workspace_id,
                limit=cap * 5,
                restrict_to_document_ids=window_document_ids,
            ),
        )
        for ready_ids in ready_groups:
            for document_version_id in ready_ids:
                if document_version_id in window_version_set and document_version_id not in selected:
                    selected.append(document_version_id)
                    if len(selected) >= cap:
                        return selected[:cap]

    return selected[:cap]


def run_daily_report_analysis_catchup(
    *,
    now: datetime | None = None,
    deadline: datetime | None = None,
    min_candidates: int = DEFAULT_MIN_CANDIDATES,
    clock: Callable[[], datetime] | None = None,
) -> list[str]:
    current_time = now or datetime.now(timezone.utc)
    _clock = clock or (lambda: datetime.now(timezone.utc))
    workspace_id = get_workspace_id()
    report_date = current_time.astimezone(SEOUL_TZ).date()
    window_start, window_end = get_daily_report_window(current_time)
    effective_deadline = deadline or _default_deadline(report_date)

    log(
        f"start report_date={report_date.isoformat()} "
        f"window_start={window_start.isoformat()} window_end={window_end.isoformat()} "
        f"target_candidates={min_candidates} deadline={effective_deadline.isoformat()}"
    )
    save_analysis_batch(
        workspace_id=workspace_id,
        report_date=report_date,
        document_version_ids=[],
        started_at=current_time,
    )

    previous_candidate_ids: list[str] | None = None
    last_snapshot: CandidateSnapshot | None = None
    stop_reason = "deadline"

    while _clock() < effective_deadline:
        ranking_batch_date = _clock().astimezone(timezone.utc).date()
        snapshot = _load_candidate_snapshot(
            workspace_id=workspace_id,
            report_date=report_date,
            ranking_batch_date=ranking_batch_date,
            window_start=window_start,
            window_end=window_end,
        )
        if snapshot is None:
            stop_reason = "selected_lookup_failed"
            break
        last_snapshot = snapshot
        _log_snapshot(
            prefix="checkpoint",
            report_date=report_date,
            window_start=window_start,
            window_end=window_end,
            snapshot=snapshot,
            min_candidates=min_candidates,
        )
        if snapshot.window_selected >= min_candidates:
            stop_reason = "target_reached"
            break

        limit = get_adaptive_analysis_limit(workspace_id)
        candidate_ids = select_window_analysis_candidates(
            workspace_id=workspace_id,
            limit=limit,
            window_start=window_start,
            window_end=window_end,
        )
        if not candidate_ids:
            stop_reason = "no_window_analysis_candidates"
            log("no analysis candidates inside report publication window; stopping")
            break
        if previous_candidate_ids is not None and set(candidate_ids) == set(previous_candidate_ids):
            stop_reason = "same_window_candidate_ids"
            log("same report-window candidate set as previous round; stopping")
            break
        if _clock() + ROUND_BUDGET > effective_deadline:
            stop_reason = "round_budget_exceeds_deadline"
            log(
                f"remaining time is below round budget ({int(ROUND_BUDGET.total_seconds() // 60)}m); "
                "stopping before a new analysis round"
            )
            break

        log(
            f"window_selected={snapshot.window_selected} target_candidates={min_candidates} "
            f"missing_candidates={min_candidates - snapshot.window_selected} "
            f"analyzing_window_candidates={len(candidate_ids)}"
        )
        try:
            run_analysis_pipeline(workspace_id, limit=limit, document_version_ids=candidate_ids)
        except Exception as exc:
            stop_reason = "run_analysis_pipeline_exception"
            log(f"run_analysis_pipeline raised; stopping with current state: {exc!r}")
            break
        previous_candidate_ids = candidate_ids
    else:
        stop_reason = "deadline"

    final_ranking_batch_date = _clock().astimezone(timezone.utc).date()
    final_snapshot = _load_candidate_snapshot(
        workspace_id=workspace_id,
        report_date=report_date,
        ranking_batch_date=final_ranking_batch_date,
        window_start=window_start,
        window_end=window_end,
    ) or last_snapshot or CandidateSnapshot(ranking_selected_total=0, window_candidates=[])
    final_ids = final_snapshot.window_document_version_ids
    final_status = "completed" if final_snapshot.window_selected >= min_candidates else "insufficient"

    save_analysis_batch(
        workspace_id=workspace_id,
        report_date=report_date,
        document_version_ids=final_ids,
        started_at=current_time,
    )
    completed_at = datetime.now(timezone.utc)
    if final_status == "completed":
        mark_analysis_batch_completed(
            workspace_id=workspace_id,
            report_date=report_date,
            completed_at=completed_at,
        )
    else:
        mark_analysis_batch_insufficient(
            workspace_id=workspace_id,
            report_date=report_date,
            completed_at=completed_at,
        )

    log(
        f"finish report_date={report_date.isoformat()} "
        f"window_start={window_start.isoformat()} window_end={window_end.isoformat()} "
        f"ranking_selected_total={final_snapshot.ranking_selected_total} "
        f"final_window_candidates={final_snapshot.window_selected} "
        f"target_candidates={min_candidates} "
        f"missing_candidates={max(0, min_candidates - final_snapshot.window_selected)} "
        f"status={final_status} stop_reason={stop_reason}"
    )
    return final_ids


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily report analysis catch-up")
    parser.add_argument("--min-candidates", type=int, default=DEFAULT_MIN_CANDIDATES)
    args = parser.parse_args()

    run_daily_report_analysis_catchup(min_candidates=args.min_candidates)
    return 0


if __name__ == "__main__":
    sys.exit(main())

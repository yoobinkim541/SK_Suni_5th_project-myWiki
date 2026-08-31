"""Nightly analysis batch for the next scheduled Daily Report.

The scheduled report uses an operational publication window of 08:00 KST to
08:00 KST, not the KST calendar day. This job spends each stage's capacity on
that report window first, then fills any remaining capacity with the existing
backlog. Backlog processing is intentionally preserved.

Usage:
    python scripts/run_nightly_analysis.py
    python scripts/run_nightly_analysis.py --budget-minutes 60
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from scripts.generate_daily_report_scheduled import get_daily_report_window
from src.analysis.importance import evaluate_and_save_importances
from src.analysis.interface import classify_document_versions, evaluate_reliability_for_documents
from src.analysis.ranking import rank_analysis_results
from src.analysis.repository import (
    _chunked,
    get_documents_ready_for_classification,
    get_documents_ready_for_importance,
    get_documents_ready_for_ranking,
    get_documents_ready_for_reliability,
    get_supabase,
)

STAGE_LIMIT = 50
# GitHub-hosted runners hard-stop jobs at roughly six hours. Keep the existing
# safety budget and stage-by-stage deadline checks; this change only changes
# which candidates get the budget first.
DEFAULT_BUDGET_MINUTES = 335
LOG_CANDIDATE_LIMIT = 1000
KST = timezone(timedelta(hours=9))


@dataclass
class StageRunStats:
    report_window_version_ids: set[str] = field(default_factory=set)
    backlog_version_ids: set[str] = field(default_factory=set)
    classification_attempts: int = 0
    reliability_attempts: int = 0
    importance_attempts: int = 0
    ranking_attempts: int = 0
    deadline_reached: bool = False

    @property
    def processed_report_window(self) -> int:
        return len(self.report_window_version_ids)

    @property
    def processed_backlog(self) -> int:
        return len(self.backlog_version_ids)


def log(msg: str) -> None:
    print(f"[run_nightly_analysis] {msg}", flush=True)


def get_workspace_id() -> str:
    rows = get_supabase().table("workspaces").select("id, name").limit(2).execute().data
    if len(rows) != 1:
        raise SystemExit(f"workspace_id could not be resolved automatically (workspaces={len(rows)}).")
    return str(rows[0]["id"])


def get_report_window_document_ids(
    workspace_id: str,
    *,
    window_start: datetime,
    window_end: datetime,
) -> list[str]:
    """Return active document ids inside the Daily Report publication window."""
    db = get_supabase()
    rows: list[dict] = []
    start = 0
    page_size = 1000
    while True:
        page = (
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
        rows.extend(page)
        if len(page) < page_size:
            break
        start += page_size
    return [str(row["id"]) for row in rows]


def get_version_ids_for_documents(document_ids: list[str]) -> list[str]:
    """Return all document_versions.id values for the supplied documents."""
    if not document_ids:
        return []
    db = get_supabase()
    version_ids: list[str] = []
    for chunk in _chunked(document_ids):
        rows = db.table("document_versions").select("id").in_("document_id", chunk).execute().data
        version_ids.extend(str(row["id"]) for row in rows)
    return version_ids


def _merge_priority_candidates(priority_ids: list[str], backlog_ids: list[str], *, limit: int) -> list[str]:
    """Return up to limit ids, always placing report-window ids first."""
    selected: list[str] = []
    seen: set[str] = set()
    for document_version_id in [*priority_ids, *backlog_ids]:
        if document_version_id in seen:
            continue
        selected.append(document_version_id)
        seen.add(document_version_id)
        if len(selected) >= limit:
            break
    return selected


def _split_report_window_and_backlog(
    document_version_ids: list[str],
    *,
    report_window_version_ids: set[str],
) -> tuple[list[str], list[str]]:
    report_window = [item for item in document_version_ids if item in report_window_version_ids]
    backlog = [item for item in document_version_ids if item not in report_window_version_ids]
    return report_window, backlog


def _collect_ready_version_ids(
    *,
    workspace_id: str,
    limit: int,
    restrict_to_document_ids: list[str] | None = None,
    restrict_to_version_ids: list[str] | None = None,
) -> set[str]:
    ready: set[str] = set()
    ready.update(
        get_documents_ready_for_classification(
            workspace_id=workspace_id,
            limit=limit,
            restrict_to_document_ids=restrict_to_document_ids,
        )
    )
    ready.update(
        get_documents_ready_for_reliability(
            workspace_id=workspace_id,
            limit=limit,
            restrict_to_version_ids=restrict_to_version_ids,
        )
    )
    ready.update(
        get_documents_ready_for_importance(
            workspace_id=workspace_id,
            limit=limit,
            restrict_to_version_ids=restrict_to_version_ids,
        )
    )
    ready.update(
        get_documents_ready_for_ranking(
            workspace_id=workspace_id,
            limit=limit,
            restrict_to_version_ids=restrict_to_version_ids,
        )
    )
    return ready


def summarize_initial_candidates(
    *,
    workspace_id: str,
    report_window_document_ids: list[str],
    report_window_version_ids: list[str],
) -> tuple[int, int, int]:
    window_limit = max(LOG_CANDIDATE_LIMIT, len(report_window_version_ids))
    report_window_ready = _collect_ready_version_ids(
        workspace_id=workspace_id,
        limit=window_limit,
        restrict_to_document_ids=report_window_document_ids,
        restrict_to_version_ids=report_window_version_ids,
    )
    report_window_resumable: set[str] = set()
    for ready_ids in (
        get_documents_ready_for_reliability(
            workspace_id=workspace_id,
            limit=window_limit,
            restrict_to_version_ids=report_window_version_ids,
        ),
        get_documents_ready_for_importance(
            workspace_id=workspace_id,
            limit=window_limit,
            restrict_to_version_ids=report_window_version_ids,
        ),
        get_documents_ready_for_ranking(
            workspace_id=workspace_id,
            limit=window_limit,
            restrict_to_version_ids=report_window_version_ids,
        ),
    ):
        report_window_resumable.update(ready_ids)

    backlog_ready = _collect_ready_version_ids(workspace_id=workspace_id, limit=LOG_CANDIDATE_LIMIT)
    backlog_ready.difference_update(report_window_ready)
    return len(report_window_ready), len(report_window_resumable), len(backlog_ready)


def _record_stage_stats(
    stats: StageRunStats,
    *,
    stage_name: str,
    document_version_ids: list[str],
    report_window_version_ids: set[str],
) -> tuple[int, int]:
    report_window, backlog = _split_report_window_and_backlog(
        document_version_ids,
        report_window_version_ids=report_window_version_ids,
    )
    if stage_name == "classification":
        stats.classification_attempts += len(document_version_ids)
    elif stage_name == "reliability":
        stats.reliability_attempts += len(document_version_ids)
    elif stage_name == "importance":
        stats.importance_attempts += len(document_version_ids)
    elif stage_name == "ranking":
        stats.ranking_attempts += len(document_version_ids)
    stats.report_window_version_ids.update(report_window)
    stats.backlog_version_ids.update(backlog)
    return len(report_window), len(backlog)


def run_prioritized_stages_until_exhausted(
    workspace_id: str,
    deadline: datetime,
    *,
    report_window_document_ids: list[str],
    report_window_version_ids: list[str],
) -> StageRunStats:
    """Run stages until no candidates remain or the existing deadline is reached."""
    report_window_version_set = set(report_window_version_ids)
    stats = StageRunStats()
    round_no = 0
    previous_pending_ids: frozenset[str] | None = None
    while datetime.now(timezone.utc) < deadline:
        round_no += 1
        made_progress = False
        round_pending_ids: set[str] = set()

        if datetime.now(timezone.utc) >= deadline:
            break
        report_window_classify = get_documents_ready_for_classification(
            workspace_id=workspace_id,
            limit=STAGE_LIMIT,
            restrict_to_document_ids=report_window_document_ids,
        )
        backlog_classify = (
            get_documents_ready_for_classification(workspace_id=workspace_id, limit=STAGE_LIMIT)
            if len(report_window_classify) < STAGE_LIMIT
            else []
        )
        pending_classify = _merge_priority_candidates(report_window_classify, backlog_classify, limit=STAGE_LIMIT)
        if pending_classify:
            round_pending_ids.update(f"classification:{item}" for item in pending_classify)
            report_count, backlog_count = _record_stage_stats(
                stats,
                stage_name="classification",
                document_version_ids=pending_classify,
                report_window_version_ids=report_window_version_set,
            )
            log(
                f"[priority] round {round_no} classification "
                f"report_window={report_count} backlog={backlog_count} total={len(pending_classify)}"
            )
            classify_document_versions(workspace_id=workspace_id, document_version_ids=pending_classify)
            made_progress = True

        if datetime.now(timezone.utc) >= deadline:
            break
        report_window_reliability = get_documents_ready_for_reliability(
            workspace_id=workspace_id,
            limit=STAGE_LIMIT,
            restrict_to_version_ids=report_window_version_ids,
        )
        backlog_reliability = (
            get_documents_ready_for_reliability(workspace_id=workspace_id, limit=STAGE_LIMIT)
            if len(report_window_reliability) < STAGE_LIMIT
            else []
        )
        pending_reliability = _merge_priority_candidates(report_window_reliability, backlog_reliability, limit=STAGE_LIMIT)
        if pending_reliability:
            round_pending_ids.update(f"reliability:{item}" for item in pending_reliability)
            report_count, backlog_count = _record_stage_stats(
                stats,
                stage_name="reliability",
                document_version_ids=pending_reliability,
                report_window_version_ids=report_window_version_set,
            )
            log(
                f"[priority] round {round_no} reliability "
                f"report_window={report_count} backlog={backlog_count} total={len(pending_reliability)}"
            )
            evaluate_reliability_for_documents(workspace_id=workspace_id, document_version_ids=pending_reliability)
            made_progress = True

        if datetime.now(timezone.utc) >= deadline:
            break
        report_window_importance = get_documents_ready_for_importance(
            workspace_id=workspace_id,
            limit=STAGE_LIMIT,
            restrict_to_version_ids=report_window_version_ids,
        )
        backlog_importance = (
            get_documents_ready_for_importance(workspace_id=workspace_id, limit=STAGE_LIMIT)
            if len(report_window_importance) < STAGE_LIMIT
            else []
        )
        pending_importance = _merge_priority_candidates(report_window_importance, backlog_importance, limit=STAGE_LIMIT)
        if pending_importance:
            round_pending_ids.update(f"importance:{item}" for item in pending_importance)
            report_count, backlog_count = _record_stage_stats(
                stats,
                stage_name="importance",
                document_version_ids=pending_importance,
                report_window_version_ids=report_window_version_set,
            )
            log(
                f"[priority] round {round_no} importance "
                f"report_window={report_count} backlog={backlog_count} total={len(pending_importance)}"
            )
            evaluate_and_save_importances(workspace_id=workspace_id, document_version_ids=pending_importance)
            made_progress = True

        if datetime.now(timezone.utc) >= deadline:
            break
        report_window_ranking = get_documents_ready_for_ranking(
            workspace_id=workspace_id,
            limit=STAGE_LIMIT,
            restrict_to_version_ids=report_window_version_ids,
        )
        backlog_ranking = (
            get_documents_ready_for_ranking(workspace_id=workspace_id, limit=STAGE_LIMIT)
            if len(report_window_ranking) < STAGE_LIMIT
            else []
        )
        pending_ranking = _merge_priority_candidates(report_window_ranking, backlog_ranking, limit=STAGE_LIMIT)
        if pending_ranking:
            round_pending_ids.update(f"ranking:{item}" for item in pending_ranking)
            report_count, backlog_count = _record_stage_stats(
                stats,
                stage_name="ranking",
                document_version_ids=pending_ranking,
                report_window_version_ids=report_window_version_set,
            )
            log(
                f"[priority] round {round_no} ranking "
                f"report_window={report_count} backlog={backlog_count} total={len(pending_ranking)}"
            )
            rank_analysis_results(workspace_id=workspace_id, document_version_ids=pending_ranking)
            made_progress = True

        current_pending_ids = frozenset(round_pending_ids)
        if previous_pending_ids is not None and current_pending_ids == previous_pending_ids:
            log(f"[priority] round {round_no} no state change; stopping to avoid retrying the same failures")
            return stats
        previous_pending_ids = current_pending_ids

        if not made_progress:
            log(f"[priority] round {round_no} no candidates left; stopping")
            return stats

    stats.deadline_reached = datetime.now(timezone.utc) >= deadline
    log(f"[priority] stopping after round {round_no}; deadline_reached={stats.deadline_reached}")
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Nightly analysis batch for Daily Report priority and backlog")
    parser.add_argument("--budget-minutes", type=int, default=DEFAULT_BUDGET_MINUTES)
    args = parser.parse_args()

    workspace_id = get_workspace_id()
    start = datetime.now(timezone.utc)
    deadline = start + timedelta(minutes=args.budget_minutes)
    report_window_start, report_window_end = get_daily_report_window(start)
    log(f"start budget_minutes={args.budget_minutes} deadline={deadline.isoformat()}")
    log(
        f"report_window_start={report_window_start.isoformat()} "
        f"report_window_end={report_window_end.isoformat()}"
    )

    report_window_document_ids = get_report_window_document_ids(
        workspace_id,
        window_start=report_window_start,
        window_end=report_window_end,
    )
    report_window_version_ids = get_version_ids_for_documents(report_window_document_ids)
    report_window_candidates, report_window_resumable, backlog_candidates = summarize_initial_candidates(
        workspace_id=workspace_id,
        report_window_document_ids=report_window_document_ids,
        report_window_version_ids=report_window_version_ids,
    )
    log(
        "[Nightly Analysis] "
        f"report_window_documents={len(report_window_document_ids)} "
        f"report_window_versions={len(report_window_version_ids)} "
        f"report_window_candidates={report_window_candidates} "
        f"report_window_resumable={report_window_resumable} "
        f"backlog_candidates={backlog_candidates} "
        "processing_priority=report_window->backlog"
    )

    stats = run_prioritized_stages_until_exhausted(
        workspace_id,
        deadline,
        report_window_document_ids=report_window_document_ids,
        report_window_version_ids=report_window_version_ids,
    )
    log(
        "[Nightly Analysis] "
        f"processed_report_window={stats.processed_report_window} "
        f"processed_backlog={stats.processed_backlog} "
        f"classification_attempts={stats.classification_attempts} "
        f"reliability_attempts={stats.reliability_attempts} "
        f"importance_attempts={stats.importance_attempts} "
        f"ranking_attempts={stats.ranking_attempts} "
        f"deadline_reached={stats.deadline_reached}"
    )
    log("complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())

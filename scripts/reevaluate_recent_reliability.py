from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.analysis.reliability import evaluate_and_save_reliability
from src.pipeline_common.db import get_client


QUERY_CHUNK_SIZE = 200
PAGE_SIZE = 1000


def chunked(values: Sequence[str], size: int = QUERY_CHUNK_SIZE) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield list(values[index : index + size])


def get_workspace_id() -> str:
    rows = get_client().table("workspaces").select("id, name").limit(2).execute().data
    if len(rows) != 1:
        raise SystemExit(f"Unable to choose one workspace automatically. workspace_count={len(rows)}")
    return str(rows[0]["id"])


def _paged_documents(*, workspace_id: str, since: datetime, date_column: str) -> list[dict[str, Any]]:
    db = get_client()
    rows: list[dict[str, Any]] = []
    start = 0
    since_iso = since.isoformat()
    while True:
        page = (
            db.table("documents")
            .select("id,title,published_at,created_at")
            .eq("workspace_id", workspace_id)
            .eq("status", "active")
            .gte(date_column, since_iso)
            .order(date_column, desc=True)
            .range(start, start + PAGE_SIZE - 1)
            .execute()
            .data
        )
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        start += PAGE_SIZE
    return rows


def get_recent_document_ids(*, workspace_id: str, days: int) -> list[str]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    by_id: dict[str, dict[str, Any]] = {}
    for date_column in ("published_at", "created_at"):
        for row in _paged_documents(workspace_id=workspace_id, since=since, date_column=date_column):
            by_id[str(row["id"])] = row
    return list(by_id.keys())


def get_document_version_ids(*, document_ids: list[str]) -> list[str]:
    if not document_ids:
        return []
    db = get_client()
    version_rows: list[dict[str, Any]] = []
    for chunk in chunked(document_ids):
        version_rows.extend(
            db.table("document_versions")
            .select("id,document_id,created_at")
            .in_("document_id", chunk)
            .order("created_at", desc=True)
            .execute()
            .data
        )
    version_rows.sort(key=lambda row: row.get("created_at") or "", reverse=True)
    return list(dict.fromkeys(str(row["id"]) for row in version_rows))


def get_classified_version_ids(*, workspace_id: str, version_ids: list[str]) -> list[str]:
    if not version_ids:
        return []
    db = get_client()
    classified: set[str] = set()
    for chunk in chunked(version_ids):
        rows = (
            db.table("document_analysis_results")
            .select("document_version_id,status")
            .eq("workspace_id", workspace_id)
            .eq("status", "completed")
            .in_("document_version_id", chunk)
            .execute()
            .data
        )
        classified.update(str(row["document_version_id"]) for row in rows)
    return [version_id for version_id in version_ids if version_id in classified]


def reevaluate_recent_reliability(*, workspace_id: str, days: int, limit: int | None, dry_run: bool) -> int:
    document_ids = get_recent_document_ids(workspace_id=workspace_id, days=days)
    version_ids = get_document_version_ids(document_ids=document_ids)
    target_ids = get_classified_version_ids(workspace_id=workspace_id, version_ids=version_ids)
    if limit is not None:
        target_ids = target_ids[:limit]

    print(f"workspace_id: {workspace_id}")
    print(f"days: {days}")
    print(f"recent_documents: {len(document_ids)}")
    print(f"recent_versions: {len(version_ids)}")
    print(f"classified_targets: {len(target_ids)}")

    if dry_run:
        print("dry_run: true")
        for document_version_id in target_ids[:20]:
            print(f"target: {document_version_id}")
        return 0

    counts: Counter[str] = Counter()
    for index, document_version_id in enumerate(target_ids, start=1):
        print(f"[{index}/{len(target_ids)}] reevaluating {document_version_id}", flush=True)
        result = evaluate_and_save_reliability(
            workspace_id=workspace_id,
            document_version_id=document_version_id,
            force=True,
        )
        status = result.reliability_status
        counts[status] += 1
        if status == "completed":
            level = result.reliability_level.value if result.reliability_level else ""
            print(f"  completed score={result.reliability_score} level={level}", flush=True)
        else:
            print(f"  failed error={result.error_code or result.reliability_error_message}", flush=True)

    print("summary:")
    for status, count in sorted(counts.items()):
        print(f"  {status}: {count}")
    return 1 if counts.get("failed") else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Force-reevaluate reliability for recently collected documents.")
    parser.add_argument("--workspace-id", default=None)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.days <= 0:
        parser.error("--days must be greater than 0")
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be greater than 0")

    workspace_id = args.workspace_id or get_workspace_id()
    return reevaluate_recent_reliability(
        workspace_id=workspace_id,
        days=args.days,
        limit=args.limit,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())

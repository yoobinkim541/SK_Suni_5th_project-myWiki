"""Backfill DART disclosure type metadata into documents.

OpenDART list.json does not return pblntf_ty in each response item. The type is a
request filter, so this script queries each disclosure type separately and writes
the type used for that request to the matching DART viewer document.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from dotenv import load_dotenv

from src.analysis.repository import get_supabase
from src.collectors.fetchers import (
    DART_DISCLOSURE_TYPE_NAMES,
    DART_LIST_URL,
    DART_VIEWER_URL,
)
from src.pipeline_common.urls import normalize_url


DEFAULT_DAYS = 14


def _date(value: datetime) -> str:
    return value.strftime("%Y%m%d")


def _workspace_id(db, explicit: str | None) -> str:
    if explicit:
        return explicit
    rows = db.table("workspaces").select("id").limit(2).execute().data
    if len(rows) != 1:
        raise SystemExit(f"workspace_id를 자동 결정할 수 없습니다(workspaces={len(rows)}). --workspace-id를 지정하세요.")
    return str(rows[0]["id"])


def _disclosure_sources(db, workspace_id: str) -> list[dict[str, Any]]:
    return (
        db.table("sources")
        .select("id, name, config")
        .eq("workspace_id", workspace_id)
        .eq("source_type", "disclosure")
        .eq("enabled", True)
        .execute()
        .data
    ) or []


def _fetch_list(*, api_key: str, corp_code: str, days: int, disclosure_type_code: str) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bgn_de": _date(now - timedelta(days=days)),
        "end_de": _date(now),
        "pblntf_ty": disclosure_type_code,
        "page_count": 100,
        "sort": "date",
        "sort_mth": "desc",
    }
    response = httpx.get(DART_LIST_URL, params=params, timeout=15.0)
    payload = response.json()
    status = payload.get("status")
    if status == "013":
        return []
    if status != "000":
        raise RuntimeError(f"DART list.json 오류 corp_code={corp_code} type={disclosure_type_code} status={status}: {payload.get('message')}")
    return payload.get("list") or []


def backfill(*, workspace_id: str | None, days: int, dry_run: bool) -> dict[str, int]:
    load_dotenv()
    api_key = os.environ.get("DART_API_KEY")
    if not api_key:
        raise SystemExit("DART_API_KEY 환경변수가 없습니다.")

    db = get_supabase()
    resolved_workspace_id = _workspace_id(db, workspace_id)
    sources = _disclosure_sources(db, resolved_workspace_id)

    stats = {"sources": len(sources), "matched": 0, "updated": 0, "unchanged": 0, "missing": 0}
    for source in sources:
        corp_code = ((source.get("config") or {}).get("corp_code") or "").strip()
        if not corp_code:
            continue
        for disclosure_type_code, disclosure_type_name in DART_DISCLOSURE_TYPE_NAMES.items():
            for entry in _fetch_list(api_key=api_key, corp_code=corp_code, days=days, disclosure_type_code=disclosure_type_code):
                rcept_no = (entry.get("rcept_no") or "").strip()
                if not rcept_no:
                    continue
                canonical_url = normalize_url(f"{DART_VIEWER_URL}?rcpNo={rcept_no}")
                rows = (
                    db.table("documents")
                    .select("id, disclosure_type_code, disclosure_type_name")
                    .eq("workspace_id", resolved_workspace_id)
                    .eq("source_id", source["id"])
                    .eq("canonical_url", canonical_url)
                    .limit(1)
                    .execute()
                    .data
                ) or []
                if not rows:
                    stats["missing"] += 1
                    continue
                stats["matched"] += 1
                row = rows[0]
                if (
                    row.get("disclosure_type_code") == disclosure_type_code
                    and row.get("disclosure_type_name") == disclosure_type_name
                ):
                    stats["unchanged"] += 1
                    continue
                if not dry_run:
                    (
                        db.table("documents")
                        .update({
                            "disclosure_type_code": disclosure_type_code,
                            "disclosure_type_name": disclosure_type_name,
                        })
                        .eq("id", row["id"])
                        .eq("workspace_id", resolved_workspace_id)
                        .execute()
                    )
                stats["updated"] += 1
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill DART disclosure pblntf_ty metadata into documents.")
    parser.add_argument("--workspace-id")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    stats = backfill(workspace_id=args.workspace_id, days=args.days, dry_run=args.dry_run)
    print(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""90일 이상 갱신 없는 published Wiki 페이지를 archived로 전환하는 배치.

리포트/위키 생성 파이프라인과 완전히 독립된 스케줄로 돌린다.

사용법:
    python scripts/archive_stale_wiki_pages.py
    python scripts/archive_stale_wiki_pages.py --staleness-days 30
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.pipeline_common.db import get_client
from src.wiki.generation import archive_stale_wiki_pages


def get_workspace_id() -> str:
    rows = get_client().table("workspaces").select("id, name").limit(2).execute().data
    if len(rows) != 1:
        raise SystemExit(f"workspace_id를 자동으로 하나로 못 정했다 (workspaces 행 {len(rows)}개).")
    return str(rows[0]["id"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staleness-days", type=int, default=90)
    args = parser.parse_args()

    workspace_id = get_workspace_id()
    archived_ids = archive_stale_wiki_pages(workspace_id, staleness_days=args.staleness_days)
    print(f"[archive] {len(archived_ids)}개 페이지 아카이빙: {archived_ids}")

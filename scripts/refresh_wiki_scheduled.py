"""Wiki 업데이트 주기(workspace_settings.wiki_update_cycle_minutes)를 지킨 채
refresh_wiki_from_recent_analysis()를 돌리는 게이트.

GitHub Actions는 30분(가장 촘촘한 주기 옵션)마다 이 스크립트를 호출하지만,
실제로 갱신을 실행하는 건 설정된 주기가 지났을 때뿐이다. refresh_wiki.py는
상태 없이(stateless) 항상 "최근 N시간 분석분"만 처리하므로, 게이트를 통과할
때마다 넉넉한 고정 lookback(24시간)으로 불러도 안전하다 — 이슈 페이지
중복방지 로직(find_matching_issue_page)이 겹쳐 호출되는 경우를 막아준다.

사용법:
    python scripts/refresh_wiki_scheduled.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.pipeline_common.db import get_client
from src.settings.service import get_workspace_settings, mark_wiki_refreshed
from src.wiki.generation import refresh_wiki_from_recent_analysis
from src.wiki.generation_models import WikiDraftGenerationResult

SINCE_HOURS_LOOKBACK = 24


def log(msg: str) -> None:
    print(f"[refresh_wiki_scheduled] {msg}", flush=True)


def is_refresh_due(last_wiki_refresh_at: str | None, cycle_minutes: int, *, now: datetime) -> bool:
    """last_wiki_refresh_at이 없으면(한 번도 안 돌았으면) 무조건 실행."""
    if last_wiki_refresh_at is None:
        return True
    last = datetime.fromisoformat(last_wiki_refresh_at.replace("Z", "+00:00"))
    elapsed_minutes = (now - last).total_seconds() / 60
    return elapsed_minutes >= cycle_minutes


def get_workspace_id() -> str:
    rows = get_client().table("workspaces").select("id, name").limit(2).execute().data
    if len(rows) != 1:
        raise SystemExit(f"workspace_id를 자동으로 하나로 못 정했다 (workspaces 행 {len(rows)}개).")
    return str(rows[0]["id"])


def report_results(results: list[WikiDraftGenerationResult]) -> int:
    log(f"{len(results)}개 이슈 처리:")
    for r in results:
        log(f"  - {r.issue_key}: issue_page={r.issue_page_id} topic_action={r.topic_action}")
        if r.error_message:
            log(f"    error: {r.error_message}")
    if results and all(r.error_message is not None for r in results):
        return 1
    return 0


if __name__ == "__main__":
    workspace_id = get_workspace_id()
    settings = get_workspace_settings(workspace_id)

    now = datetime.now(timezone.utc)
    if not is_refresh_due(settings.last_wiki_refresh_at, settings.wiki_update_cycle_minutes, now=now):
        log(
            f"아직 주기 안 됨 (주기={settings.wiki_update_cycle_minutes}분, "
            f"마지막 갱신={settings.last_wiki_refresh_at})"
        )
        sys.exit(0)

    log(f"주기 도달 — 갱신 시작 (주기={settings.wiki_update_cycle_minutes}분)")
    results = refresh_wiki_from_recent_analysis(workspace_id, since_hours=SINCE_HOURS_LOOKBACK)
    exit_code = report_results(results)
    mark_wiki_refreshed(workspace_id)

    if exit_code != 0:
        raise SystemExit(exit_code)

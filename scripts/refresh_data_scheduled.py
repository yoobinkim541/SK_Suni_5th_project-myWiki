"""데이터 갱신 주기(workspace_settings.data_refresh_cycle_minutes)를 지킨 채
수집 -> 정제 -> 분류 -> 신뢰도 -> 중요도 -> 랭킹을 순서대로 도는 게이트.

refresh_wiki_scheduled.py와 같은 구조다 — GitHub Actions는 30분(가장 촘촘한 주기 옵션)마다
이 스크립트를 부르지만, 실제로 도는 건 설정된 주기가 지났을 때뿐이다.

수집·분석을 원래 scheduled-collection.yml/scheduled-analysis.yml 두 워크플로우로 따로
돌렸었는데, 그러면 둘 다 "이 주기 값"만 보고 각자 게이트를 통과하다 보니 분석이 그 직전
수집 결과를 못 받고 그 이전 수집분으로 도는 레이스가 생길 수 있었다. 이 스크립트는
한 실행 안에서 수집 -> 분석을 순서대로 실행해 그 레이스를 없앤다.

사용법:
    python scripts/refresh_data_scheduled.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from scripts.run_analysis_pipeline import run_analysis_pipeline
from scripts.run_pipeline import run_collect, run_preprocess

from src.pipeline_common.db import get_client
from src.settings.service import get_workspace_settings, mark_data_refreshed

GRACE_MINUTES = 15


def log(msg: str) -> None:
    print(f"[refresh_data_scheduled] {msg}", flush=True)


def is_refresh_due(last_data_refresh_at: str | None, cycle_minutes: int, *, now: datetime) -> bool:
    """refresh_wiki_scheduled.is_refresh_due와 동일한 로직 — 주기가 안 지났으면 스킵한다.
    GRACE_MINUTES만큼 조기 허용해서 cron 지연으로 주기가 한 사이클 통째로 밀리는 걸 막는다."""
    if last_data_refresh_at is None:
        return True
    last = datetime.fromisoformat(last_data_refresh_at.replace("Z", "+00:00"))
    elapsed_minutes = (now - last).total_seconds() / 60
    return elapsed_minutes >= cycle_minutes - GRACE_MINUTES


def get_workspace_id() -> str:
    rows = get_client().table("workspaces").select("id, name").limit(2).execute().data
    if len(rows) != 1:
        raise SystemExit(f"workspace_id를 자동으로 하나로 못 정했다 (workspaces 행 {len(rows)}개).")
    return str(rows[0]["id"])


if __name__ == "__main__":
    workspace_id = get_workspace_id()
    settings = get_workspace_settings(workspace_id)

    now = datetime.now(timezone.utc)
    if not is_refresh_due(settings.last_data_refresh_at, settings.data_refresh_cycle_minutes, now=now):
        log(
            f"아직 주기 안 됨 (주기={settings.data_refresh_cycle_minutes}분, "
            f"마지막 갱신={settings.last_data_refresh_at})"
        )
        sys.exit(0)

    gate_now = now  # 게이트 통과 시각 — 수집+분석 완료 후가 아니라 이 시각으로 찍는다
    log(f"주기 도달 — 수집 시작 (주기={settings.data_refresh_cycle_minutes}분)")

    collect_summary = run_collect(UUID(workspace_id), limit=None, source_id=None)
    log(f"수집 완료: {collect_summary}")

    preprocess_summary = run_preprocess(UUID(workspace_id))
    log(f"정제 완료: {preprocess_summary}")

    log("분석 단계 시작 (분류->신뢰도->중요도->랭킹)")
    run_analysis_pipeline(workspace_id, limit=50)

    mark_data_refreshed(workspace_id, at=gate_now)
    log("완료")

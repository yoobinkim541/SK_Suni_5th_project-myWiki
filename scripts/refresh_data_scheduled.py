from __future__ import annotations

import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Callable
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from scripts.run_analysis_pipeline import get_adaptive_analysis_limit, get_analysis_backlog_count, run_analysis_pipeline
from scripts.run_pipeline import run_collect, run_preprocess

from src.pipeline_common.db import get_client
from src.settings.service import get_workspace_settings, mark_data_refreshed

GRACE_MINUTES = 15

SELF_BUDGET_MINUTES = 40
"""job timeout(scheduled-data-refresh.yml, 55분) 대비 15분 여유를 둔 자체 시간 예산.
refresh_wiki_scheduled.py/run_nightly_analysis.py와 같은 self-budget 패턴 — collect()가
이미 20-24분을 쓰므로(워크플로 주석 참고), 분석 단계가 나머지 시간을 데드라인까지
반복 소비하다가 하드 타임아웃으로 배치 중간에 잘리는 대신 스스로 멈춘다.

데드라인은 잡 시작 시각(collect() 호출 전)에 고정한다 — collect+preprocess가 이미 써버린
시간을 분석 단계 예산에서 자연히 제외하기 위함이다. 여유를 5분이 아니라 15분으로 넉넉히
잡은 이유는, 데드라인이 while 루프 "회차 사이"에서만 재확인되고(run_analysis_pipeline()
한 번 호출 안쪽에서는 체크되지 않음) 최대 50건짜리 한 회차가 데드라인을 넘겨서까지 계속
돌 수 있기 때문 — 그 한 회차의 초과분을 흡수할 여유가 필요하다.

now 파라미터(게이트 판정용, 고정된 과거 날짜로 테스트하는 경우가 많음)와는 별개로,
데드라인 계산·체크는 항상 run_scheduled_refresh()의 clock 파라미터(기본값: 실제 벽시계)만
쓴다 — 두 "시각" 개념이 섞이면 게이트 테스트용 고정 날짜가 데드라인을 항상 "이미 지남"으로
오판하게 만든다."""

KST = timezone(timedelta(hours=9))
NIGHTLY_ANALYSIS_WINDOW_KST = (time(0, 0), time(7, 15))
"""scripts/run_nightly_analysis.py(00:00 KST 시작)와 daily-report-analysis-catchup.yml
(06:00 KST 시작, 내부 마감 07:15 KST)이 이 구간 동안 분석을 전담한다. 예전에는 06:00에
끝났는데, catchup이 07:00 KST에서 06:00 KST로 앞당겨지면서(2026-08-09) 그 사이(06:00~
07:15)에 이 스크립트가 같은 문서를 동시에 분석해 LLM 호출을 낭비할 위험이 생겨 넓혔다."""


def is_within_nightly_analysis_window(now_utc: datetime) -> bool:
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


def run_scheduled_refresh(*, now: datetime | None = None, clock: Callable[[], datetime] | None = None) -> bool:
    workspace_id = get_workspace_id()
    settings = get_workspace_settings(workspace_id)

    get_current_time = clock or (lambda: datetime.now(timezone.utc))

    current_time = now or datetime.now(timezone.utc)
    if not is_refresh_due(settings.last_data_refresh_at, settings.data_refresh_cycle_minutes, now=current_time):
        log(
            f"refresh skipped (cycle={settings.data_refresh_cycle_minutes}m last={settings.last_data_refresh_at})"
        )
        return False

    gate_now = current_time
    log(f"refresh started (cycle={settings.data_refresh_cycle_minutes}m)")
    # 데드라인은 잡 시작 시각(collect() 호출 전) 기준으로 고정한다 — collect()/preprocess()가
    # 이미 소비한 시간이 분석 단계 예산에서 그대로 빠지도록 하기 위함. collect()/preprocess()는
    # 이 데드라인과 무관하게 항상 무조건 실행된다(게이트 대상이 아님).
    deadline = get_current_time() + timedelta(minutes=SELF_BUDGET_MINUTES)

    collect_summary = run_collect(UUID(workspace_id), limit=None, source_id=None)
    log(f"collect complete: {collect_summary}")

    preprocess_summary = run_preprocess(UUID(workspace_id))
    log(f"preprocess complete: {preprocess_summary}")

    if is_within_nightly_analysis_window(current_time):
        log("analysis skipped during nightly analysis window (00:00-07:15 KST)")
    else:
        previous_backlog_count: int | None = None
        round_number = 0
        while get_current_time() < deadline:
            backlog_count = get_analysis_backlog_count(workspace_id)
            if backlog_count == 0 or backlog_count == previous_backlog_count:
                # 백로그가 없거나(0), 지난 회차와 똑같은 값이면(진척 없음 = 영구 실패
                # 후보 재시도 루프) 예산이 남아있어도 멈춘다.
                break
            previous_backlog_count = backlog_count
            round_number += 1
            analysis_limit = get_adaptive_analysis_limit(workspace_id)
            log(f"analysis round {round_number}: backlog={backlog_count} limit={analysis_limit}")
            run_analysis_pipeline(workspace_id, limit=analysis_limit)

    mark_data_refreshed(workspace_id, at=gate_now)
    log("refresh complete (daily report is generated separately at 08:00 KST)")
    return True


if __name__ == "__main__":
    sys.exit(0 if run_scheduled_refresh() is not None else 1)

"""Wiki 업데이트 주기(workspace_settings.wiki_update_cycle_minutes)를 지킨 채
refresh_wiki_from_recent_analysis()를 돌리는 게이트.

GitHub Actions는 30분(가장 촘촘한 주기 옵션)마다 이 스크립트를 호출하지만,
실제로 갱신을 실행하는 건 설정된 주기가 지났을 때뿐이다. refresh_wiki.py는
상태 없이(stateless) 항상 "최근 N시간 분석분"만 처리하므로, since_hours은
매번 고정값이 아니라 실제 경과 시간 기준으로 계산한다(중복 재생성 비용 방지).

LLM 생성 자체가 시간이 걸리고 GitHub Actions cron도 늦게 도는 경우가 있어서,
"주기 통과" 시각(now)을 갱신 작업 시작 전에 미리 찍어두고 그 시각을 last_wiki_refresh_at
갱신에 쓴다(완료 시각을 찍으면 실제 주기가 계속 늘어난다). is_refresh_due()에도
GRACE_MINUTES만큼 여유를 둬서 cron 지연으로 주기가 한 사이클 통째로 밀리는 걸 막는다.

사용법:
    python scripts/refresh_wiki_scheduled.py
"""
from __future__ import annotations

import math
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.pipeline_common.db import get_client
from src.settings.service import get_workspace_settings
from src.wiki.generation import refresh_wiki_from_recent_analysis
from src.wiki.generation_models import WikiDraftGenerationResult

SINCE_HOURS_LOOKBACK = 24
GRACE_MINUTES = 15
SELF_BUDGET_MINUTES = 80
"""wiki-refresh-gate.yml의 GH Actions job timeout(90분)보다 여유 있게 잡은 자체 시간 예산.
run_daily_report_analysis_catchup.py/run_nightly_analysis.py와 같은 self-budget 패턴 —
큰 백로그로 처리 시간이 늘어나도 GH Actions에 강제 종료되기 전에 스스로 멈춰서
(refresh_wiki_from_recent_analysis의 deadline 인자), last_wiki_refresh_at 갱신이
아예 누락되는 걸 막는다. 남은 10분은 checkout/pip install 등 스크립트 실행 전후 오버헤드 여유분."""

KST = timezone(timedelta(hours=9))
REPORT_CRITICAL_WINDOW_KST = (time(6, 0), time(8, 30))
"""이 구간(KST 06:00~08:30) 동안은 위키 갱신을 아예 건너뛴다. daily-report-analysis-catchup.yml
(06:00 KST 시작)과 scheduled-daily-report.yml(07:30 KST 시작, 08:30 KST 마감)이 도는 시간대라,
위키 갱신이 같은 OpenRouter 호출 자원을 나눠 쓰면 리포트 완료가 늦어질 위험이 있다.
wiki-refresh-gate.yml의 job 타임아웃을 넉넉하게 늘려도(예: 90분) 이 구간을 건드리지 않게,
구간 시작 전 마지막 실행(05:30 KST 틱)이 최대치로 돌아도 07:00 KST에는 끝나 있어 안전 마진이 크다."""


def log(msg: str) -> None:
    print(f"[refresh_wiki_scheduled] {msg}", flush=True)


def is_within_report_critical_window(now_utc: datetime) -> bool:
    now_kst_time = now_utc.astimezone(KST).time()
    start, end = REPORT_CRITICAL_WINDOW_KST
    return start <= now_kst_time < end


def is_refresh_due(last_wiki_refresh_at: str | None, cycle_minutes: int, *, now: datetime) -> bool:
    """last_wiki_refresh_at이 없으면(한 번도 안 돌았으면) 무조건 실행.

    GRACE_MINUTES만큼 조기 허용한다 — LLM 생성 시간 + cron 지연 때문에 완료 시각
    기준으로 다음 주기를 재면 실제 간격이 매번 설정값보다 길어지는 걸 보정한다.
    """
    if last_wiki_refresh_at is None:
        return True
    last = datetime.fromisoformat(last_wiki_refresh_at.replace("Z", "+00:00"))
    elapsed_minutes = (now - last).total_seconds() / 60
    return elapsed_minutes >= cycle_minutes - GRACE_MINUTES


def _compute_since_hours(last_wiki_refresh_at: str | None, *, now: datetime) -> int:
    """실제 경과 시간 기준으로 lookback을 계산한다 — 최소 2시간, 최대(기존 안전 상한) 24시간.
    last_wiki_refresh_at이 없으면(첫 실행) 기존과 동일하게 24시간 그대로 쓴다."""
    if last_wiki_refresh_at is None:
        return SINCE_HOURS_LOOKBACK
    last = datetime.fromisoformat(last_wiki_refresh_at.replace("Z", "+00:00"))
    elapsed_minutes = (now - last).total_seconds() / 60
    return min(SINCE_HOURS_LOOKBACK, max(2, math.ceil(elapsed_minutes / 60) + 1))


def _mark_wiki_refreshed_at(workspace_id: str, at: datetime) -> None:
    """last_wiki_refresh_at을 지정한 시각으로 갱신한다.

    src/settings/service.py의 mark_wiki_refreshed()는 자기 내부에서 now()를 찍기 때문에
    "게이트 통과 시각"이 아니라 "갱신 작업 완료 시각"이 찍힌다 — LLM 생성이 오래 걸리면
    그만큼 다음 주기가 매번 밀린다. 이 스크립트는 게이트를 통과한 시각(gate_now)을 직접
    넘겨서 찍어야 하므로, workspace_settings를 여기서 바로 업데이트한다.
    """
    get_client().table("workspace_settings").update(
        {"last_wiki_refresh_at": at.isoformat()}
    ).eq("workspace_id", workspace_id).execute()


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
    if is_within_report_critical_window(now):
        log("리포트 준비 구간(KST 06:00~08:30)이라 위키 갱신을 건너뜀")
        sys.exit(0)
    if not is_refresh_due(settings.last_wiki_refresh_at, settings.wiki_update_cycle_minutes, now=now):
        log(
            f"아직 주기 안 됨 (주기={settings.wiki_update_cycle_minutes}분, "
            f"마지막 갱신={settings.last_wiki_refresh_at})"
        )
        sys.exit(0)

    gate_now = now  # 게이트 통과 시각 — 갱신 완료 후가 아니라 이 시각으로 last_wiki_refresh_at을 찍는다
    since_hours = _compute_since_hours(settings.last_wiki_refresh_at, now=gate_now)
    deadline = gate_now + timedelta(minutes=SELF_BUDGET_MINUTES)
    log(f"주기 도달 — 갱신 시작 (주기={settings.wiki_update_cycle_minutes}분, since_hours={since_hours})")
    results = refresh_wiki_from_recent_analysis(workspace_id, since_hours=since_hours, deadline=deadline)
    exit_code = report_results(results)
    _mark_wiki_refreshed_at(workspace_id, gate_now)

    if exit_code != 0:
        raise SystemExit(exit_code)

"""Run the adaptive analysis batch that feeds the 07:30 KST daily report.

목표: 07:30 KST 리포트 생성 전까지 최소 min_candidates(기본 6)건의
report-ready(selected_for_report=True) 문서를 확보한다. 이미 충분하면(주로
nightly-analysis.yml이 00:00 KST부터 밤새 처리해 둔 결과만으로) LLM 호출 없이
바로 끝나고, 부족하면 07:15 KST 내부 마감까지 백로그를 이어서 처리한다.

구조적 문제와 그 수정: 예전 버전은 "이번 실행이 직접 고른 후보"만
daily_report_analysis_batches에 기록했다. generate_daily_report_scheduled.py는
그 기록에 있는 document_version_ids로만 리포트 후보를 제한하는데
(candidate_provider.get_report_candidates), 이미 랭킹까지 끝난 문서는
select_analysis_candidates의 "재개 대상" 조회에 더 이상 안 걸리므로
nightly-analysis.yml이 처리한 결과가 리포트에서 아예 누락됐다. 이제는 매
실행 끝에 daily_report_analysis_batches를 "그 시점에 실제로
selected_for_report=True인 문서 전체"로 다시 채운다 — 이 실행이 직접
처리했는지 여부와 무관하게.

날짜 변환: rank_analysis_results가 기록하는 ranking_batch_date는 UTC 캘린더
날짜다(src/analysis/ranking.py: batch_date = reference_time_utc.date()).
selected_for_report 조회는 매번 그 순간의 UTC 캘린더 날짜(_clock().date())로
수행한다 — report_date(KST)에서 하루를 빼는 방식은 이 배치가 KST 00:00~07:15
구간에서 실행된다는 가정에서만 성립하고, workflow_dispatch로 그 구간 밖에
수동 실행하면 틀린 날짜를 조회하게 된다.

에러 처리:
- selected_for_report 조회 자체가 실패하면(RankingLoadFailedError) 그 시점까지
  알고 있던 상태로 루프를 멈춘다.
- 한 라운드(run_analysis_pipeline)가 예외를 던지면(분류/신뢰도/중요도는 문서
  단위 실패를 내부에서 흡수하지만, 랭킹 단계는 AMBIGUOUS_ANALYSIS_RESULT 등으로
  예외를 던질 수 있다) 그 예외를 삼키고 루프를 멈춘다 — 그래야 이전 라운드까지
  쌓인 진행 상황이 마지막 저장 단계에서 유실되지 않는다.
- 라운드 하나(run_analysis_pipeline)는 실측 30분+ 걸릴 수 있으므로(50건까지,
  4단계 LLM 호출), 남은 시간이 라운드 예산(30분)보다 적으면 아예 새 라운드를
  시작하지 않는다 — scheduled-daily-report.yml과 concurrency group을 공유하므로
  07:30 KST 전에 반드시 끝나야 한다.

사용법:
    python scripts/run_daily_report_analysis_catchup.py
    python scripts/run_daily_report_analysis_catchup.py --min-candidates 10
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from scripts.run_analysis_pipeline import (
    get_adaptive_analysis_limit,
    get_workspace_id,
    run_analysis_pipeline,
    select_analysis_candidates,
)
from src.analysis.daily_report_batch import mark_analysis_batch_completed, save_analysis_batch
from src.analysis.exceptions import RankingLoadFailedError
from src.analysis.repository import get_ranked_results_for_report

SEOUL_TZ = timezone(timedelta(hours=9))
DEFAULT_MIN_CANDIDATES = 6
# get_ranked_results_for_report 기본 limit(20)보다 넉넉히 잡아서, 이미 선정된 게 많아도
# 배치 기록에서 누락되는 일이 없게 한다(MAX_ANALYSIS_CANDIDATES=50보다 큼).
REPORT_SELECTION_LIMIT = 200
# 한 라운드(run_analysis_pipeline, 최대 50건 x 4단계 LLM 호출)는 실측 30분+ 걸릴 수
# 있다(run_nightly_analysis.py에서 관측). 마감까지 이 시간도 안 남았으면 아예 새
# 라운드를 시작하지 않는다 — scheduled-daily-report.yml과 공유하는 concurrency
# group(cancel-in-progress: false)을 07:30 KST 전에 비워야 한다.
ROUND_BUDGET = timedelta(minutes=30)


def log(message: str) -> None:
    print(f"[run_daily_report_analysis_catchup] {message}", flush=True)


def _default_deadline(report_date: date) -> datetime:
    """KST 07:15 — scheduled-daily-report.yml(07:30 KST)이 시작하기 전에
    concurrency group(daily-report-schedule)을 반드시 비워야 한다."""
    deadline_kst = datetime.combine(report_date, time(hour=7, minute=15), tzinfo=SEOUL_TZ)
    return deadline_kst.astimezone(timezone.utc)


def get_selected_results(workspace_id: str, ranking_batch_date: date) -> list:
    """ranking_batch_date(UTC 캘린더 날짜)에 이미 선정된(selected_for_report=True)
    분석 결과 전체. 호출부가 조회 시점의 실제 UTC 날짜를 넘겨야 한다(모듈 docstring
    "날짜 변환" 참고) — 이 함수 자체는 KST/report_date를 알지 못한다."""
    return get_ranked_results_for_report(
        workspace_id=workspace_id,
        ranking_batch_date=ranking_batch_date,
        limit=REPORT_SELECTION_LIMIT,
    )


def _try_get_selected_results(workspace_id: str, ranking_batch_date: date) -> list | None:
    """조회 자체가 실패하면(RankingLoadFailedError) None을 반환한다 — 호출부가 무한
    재시도하지 않고 그 시점까지 알고 있던 상태로 우아하게 멈출 수 있게 한다."""
    try:
        return get_selected_results(workspace_id, ranking_batch_date)
    except RankingLoadFailedError:
        log("selected_for_report 조회 실패 — 그 시점까지의 상태로 종료")
        return None


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
    effective_deadline = deadline or _default_deadline(report_date)

    # "시작함" 마커 — 아직 몇 건이 될지 모르니 빈 목록으로 남긴다.
    save_analysis_batch(
        workspace_id=workspace_id,
        report_date=report_date,
        document_version_ids=[],
        started_at=current_time,
    )

    previous_candidate_ids: list[str] | None = None
    last_known_selected: list = []
    while _clock() < effective_deadline:
        ranking_batch_date = _clock().astimezone(timezone.utc).date()
        selected = _try_get_selected_results(workspace_id, ranking_batch_date)
        if selected is None:
            break
        last_known_selected = selected
        if len(selected) >= min_candidates:
            log(f"이미 {len(selected)}건 선정됨(목표 {min_candidates}) — 종료")
            break

        limit = get_adaptive_analysis_limit(workspace_id)
        candidate_ids = select_analysis_candidates(workspace_id, limit=limit)
        if not candidate_ids:
            log("처리할 후보 없음 — 종료")
            break
        if previous_candidate_ids is not None and set(candidate_ids) == set(previous_candidate_ids):
            log("직전과 동일한 후보 집합 — 진행 없음, 종료")
            break

        if _clock() + ROUND_BUDGET > effective_deadline:
            log(
                f"남은 시간이 라운드 예산({int(ROUND_BUDGET.total_seconds() // 60)}분)보다 적음 "
                f"— 새 라운드를 시작하지 않고 종료"
            )
            break

        log(f"선정 {len(selected)}건(목표 {min_candidates}) — 후보 {len(candidate_ids)}건 추가 분석")
        try:
            run_analysis_pipeline(workspace_id, limit=limit, document_version_ids=candidate_ids)
        except Exception as exc:
            log(f"run_analysis_pipeline 예외 발생 — 이전 라운드까지의 진행 상황으로 종료: {exc!r}")
            break
        previous_candidate_ids = candidate_ids
    else:
        log("마감 도달 — 종료")

    final_ranking_batch_date = _clock().astimezone(timezone.utc).date()
    final_selected = _try_get_selected_results(workspace_id, final_ranking_batch_date)
    if final_selected is None:
        final_selected = last_known_selected
    final_ids = [result.document_version_id for result in final_selected]
    save_analysis_batch(
        workspace_id=workspace_id,
        report_date=report_date,
        document_version_ids=final_ids,
        started_at=current_time,
    )
    if final_ids:
        mark_analysis_batch_completed(
            workspace_id=workspace_id,
            report_date=report_date,
            completed_at=datetime.now(timezone.utc),
        )
    else:
        log(
            "최종 후보 0건 — 배치를 completed로 표시하지 않음"
            "(generate_daily_report_scheduled.py의 LookupError 폴백 경로가 대신 작동하도록)"
        )
    log(f"완료 — 최종 {len(final_ids)}건")
    return final_ids


def main() -> int:
    parser = argparse.ArgumentParser(description="일일 리포트용 분석 catchup — 최소 후보 수 확보")
    parser.add_argument("--min-candidates", type=int, default=DEFAULT_MIN_CANDIDATES)
    args = parser.parse_args()

    run_daily_report_analysis_catchup(min_candidates=args.min_candidates)
    return 0


if __name__ == "__main__":
    sys.exit(main())

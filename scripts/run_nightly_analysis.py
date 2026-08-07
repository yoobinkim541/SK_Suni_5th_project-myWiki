"""매일 자정(KST)부터 도는 분석 전용 배치 — 아침 리포트 마감(오전 8시) 전에
분류->신뢰도->중요도->랭킹을 최대한 끝내는 게 목적이다.

배경: refresh_data_scheduled.py(30분 주기, collect->preprocess->analyze를 한 실행
안에서 순서대로 돎)는 백로그가 크면 각 실행의 55분(현재 워크플로우 설정) 안에
분류까지만 가고 신뢰도·중요도·랭킹은 시작도 못 하는 경우가 잦다(2026-08-07 확인,
run 31135258583 — 분류 끝나고 신뢰도 도중 타임아웃). 리포트는 importance_score·
reliability_score가 둘 다 있어야 후보로 뽑히므로, 뒷단계가 밀리면 "오늘 발행된
기사인데 리포트엔 하나도 안 뜨는" 상태가 된다.

이 스크립트는 그 문제를 두 가지로 푼다:
    1. 오늘(KST) 발행된 문서부터 4단계를 전부 먼저 끝낸다
       (restrict_to_document_ids/restrict_to_version_ids로 좁혀서 — 안 그러면
       재정제된 오래된 문서가 "최근 처리 시각" 정렬에서 오늘 기사보다 앞에 서서
       계속 순서를 뺏는다).
    2. 남은 시간 동안 일반 백로그를 이어서 처리한다.

GitHub Actions 호스팅 러너는 job 하나가 최대 6시간까지만 돈다(플랫폼 한도,
timeout-minutes를 그 이상으로 잡아도 강제 종료된다) — 그래서 자정 시작 기준
6시간(=오전 6시 KST)이 아니라 그보다 살짝 못 미치는 350분을 안전 마진으로 잡는다.

collect·preprocess는 이 스크립트가 건드리지 않는다 — 낮 동안의 scheduled-data-
refresh.yml이 계속 30분 주기로 새 기사를 모아온다. 그 워크플로우가 오늘의 분석
단계는 이 스크립트와 겹치지 않도록, 이 스크립트가 도는 시간대(KST 00:00~06:00)에는
자기 쪽 분석 단계를 건너뛴다 (refresh_data_scheduled.py의 야간 창 체크 참조) — 같은
문서를 두 프로세스가 동시에 분석하면 LLM 호출이 낭비된다.

사용법:
    python scripts/run_nightly_analysis.py
    python scripts/run_nightly_analysis.py --budget-minutes 60  # 로컬 테스트용
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

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
# GitHub Actions 호스팅 러너의 job 최대 실행 시간(6시간)에서 로그·정리 시간을
# 뺀 안전 마진. 워크플로우의 timeout-minutes도 이보다 여유 있게(360에 근접)
# 잡되, 실제 종료 판단은 이 값으로 한다 — 강제 kill보다 스스로 멈추는 게
# 마지막에 처리 중이던 문서가 어중간한 상태로 안 남는다.
DEFAULT_BUDGET_MINUTES = 350
KST = timezone(timedelta(hours=9))
"""한국은 DST가 없어 UTC+9 고정 오프셋으로 충분하다 (zoneinfo의 IANA tzdata
의존성을 피한다 — 일부 환경엔 tzdata 패키지가 없어 zoneinfo가 바로 깨진다)."""


def log(msg: str) -> None:
    print(f"[run_nightly_analysis] {msg}", flush=True)


def get_workspace_id() -> str:
    rows = get_supabase().table("workspaces").select("id, name").limit(2).execute().data
    if len(rows) != 1:
        raise SystemExit(f"workspace_id를 자동으로 하나로 못 정했다 (workspaces 행 {len(rows)}개).")
    return str(rows[0]["id"])


def _kst_today_bounds_utc(now_utc: datetime) -> tuple[str, str]:
    """지금(UTC) 기준 KST 오늘 하루의 [00:00, 24:00) 경계를 UTC ISO 문자열로."""
    now_kst = now_utc.astimezone(KST)
    start_kst = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
    end_kst = start_kst + timedelta(days=1)
    return start_kst.astimezone(timezone.utc).isoformat(), end_kst.astimezone(timezone.utc).isoformat()


def get_today_document_ids(workspace_id: str, *, now_utc: datetime) -> list[str]:
    """KST 기준 오늘 발행된 active 문서 id. 없으면 빈 리스트."""
    start_iso, end_iso = _kst_today_bounds_utc(now_utc)
    db = get_supabase()
    rows = (
        db.table("documents")
        .select("id")
        .eq("workspace_id", workspace_id)
        .eq("status", "active")
        .gte("published_at", start_iso)
        .lt("published_at", end_iso)
        .execute()
        .data
    )
    return [row["id"] for row in rows]


def get_version_ids_for_documents(document_ids: list[str]) -> list[str]:
    """document_id 목록에 딸린 document_versions.id 전부. 정제(preprocess)가 아직
    안 된 문서는 버전이 없어 결과에서 자연히 빠진다."""
    if not document_ids:
        return []
    db = get_supabase()
    version_ids: list[str] = []
    for chunk in _chunked(document_ids):
        rows = db.table("document_versions").select("id").in_("document_id", chunk).execute().data
        version_ids.extend(row["id"] for row in rows)
    return version_ids


def run_stages_until_exhausted(
    workspace_id: str,
    deadline: datetime,
    *,
    restrict_to_document_ids: list[str] | None,
    restrict_to_version_ids: list[str] | None,
    label: str,
) -> None:
    """네 단계를 반복 호출해서, 이번 restrict 범위 안에서 더 할 게 없어지거나
    deadline을 넘길 때까지 돈다. restrict가 None이면 일반 백로그 전체가 대상이다.

    collect()·preprocess()·run_analysis_pipeline()과 같은 계약 — 문서 1건 실패는
    각 evaluate_*/classify_* 함수 내부에서 실패로 기록되고 여기서는 예외를 던지지
    않는다. 그래야 1건 실패로 이 배치 전체가 멈추지 않는다.
    """
    round_no = 0
    while datetime.now(timezone.utc) < deadline:
        round_no += 1
        made_progress = False

        pending_classify = get_documents_ready_for_classification(
            workspace_id=workspace_id, limit=STAGE_LIMIT, restrict_to_document_ids=restrict_to_document_ids
        )
        if pending_classify:
            log(f"[{label}] round {round_no} 분류 대상 {len(pending_classify)}건")
            classify_document_versions(workspace_id=workspace_id, document_version_ids=pending_classify)
            made_progress = True

        pending_reliability = get_documents_ready_for_reliability(
            workspace_id=workspace_id, limit=STAGE_LIMIT, restrict_to_version_ids=restrict_to_version_ids
        )
        if pending_reliability:
            log(f"[{label}] round {round_no} 신뢰도 대상 {len(pending_reliability)}건")
            evaluate_reliability_for_documents(workspace_id=workspace_id, document_version_ids=pending_reliability)
            made_progress = True

        pending_importance = get_documents_ready_for_importance(
            workspace_id=workspace_id, limit=STAGE_LIMIT, restrict_to_version_ids=restrict_to_version_ids
        )
        if pending_importance:
            log(f"[{label}] round {round_no} 중요도 대상 {len(pending_importance)}건")
            evaluate_and_save_importances(workspace_id=workspace_id, document_version_ids=pending_importance)
            made_progress = True

        pending_ranking = get_documents_ready_for_ranking(
            workspace_id=workspace_id, limit=STAGE_LIMIT, restrict_to_version_ids=restrict_to_version_ids
        )
        if pending_ranking:
            log(f"[{label}] round {round_no} 랭킹 대상 {len(pending_ranking)}건")
            rank_analysis_results(workspace_id=workspace_id, document_version_ids=pending_ranking)
            made_progress = True

        if not made_progress:
            log(f"[{label}] round {round_no} — 더 처리할 게 없음, 종료")
            return
    log(f"[{label}] 시간 예산 소진으로 종료 (round {round_no})")


def main() -> int:
    parser = argparse.ArgumentParser(description="야간 분석 배치 — 오늘자 문서 우선, 이후 백로그")
    parser.add_argument("--budget-minutes", type=int, default=DEFAULT_BUDGET_MINUTES)
    args = parser.parse_args()

    workspace_id = get_workspace_id()
    start = datetime.now(timezone.utc)
    deadline = start + timedelta(minutes=args.budget_minutes)
    log(f"시작 (예산 {args.budget_minutes}분, 마감 {deadline.isoformat()})")

    today_document_ids = get_today_document_ids(workspace_id, now_utc=start)
    log(f"오늘(KST) 발행 문서 {len(today_document_ids)}건")
    if today_document_ids:
        today_version_ids = get_version_ids_for_documents(today_document_ids)
        run_stages_until_exhausted(
            workspace_id,
            deadline,
            restrict_to_document_ids=today_document_ids,
            restrict_to_version_ids=today_version_ids,
            label="오늘자 우선",
        )

    if datetime.now(timezone.utc) >= deadline:
        log("오늘자 처리만으로 시간 예산 소진 — 백로그 단계 생략")
        return 0

    run_stages_until_exhausted(
        workspace_id, deadline, restrict_to_document_ids=None, restrict_to_version_ids=None, label="백로그"
    )
    log("완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())

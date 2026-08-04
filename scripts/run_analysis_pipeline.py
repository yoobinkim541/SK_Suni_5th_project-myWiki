"""분류 -> 신뢰도 -> 중요도 -> 랭킹 4단계를 순서대로 도는 배치 진입점.

scripts/run_pipeline.py(수집·정제)와 짝을 이룬다 — 그동안 이 4단계는 각 단계별
스크립트(classify_document.py 등)로 문서 1건씩만 수동 호출할 수 있었고, 이걸 도는
스케줄 배치가 없어서 수집만 계속 쌓이고 분석은 멈춰 있었다(위키/리포트 후보가
0건으로 나오던 원인 중 하나 — 2026-08-04 wiki-page-type-expansion 검증 중 발견).

각 단계는 앞 단계가 끝난 결과를 보고 "아직 이 단계를 안 거친 문서"만 찾아서 처리한다
(get_documents_ready_for_*). 한 번 실행에서 뒷 단계까지 이어지도록 순서대로 돈다 —
분류가 막 끝난 문서가 같은 실행 안에서 신뢰도까지 갈 수 있다.

사용법:
    python scripts/run_analysis_pipeline.py
    python scripts/run_analysis_pipeline.py --limit 10
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.analysis.interface import classify_document_versions, evaluate_reliability_for_documents
from src.analysis.importance import evaluate_and_save_importances
from src.analysis.ranking import rank_analysis_results
from src.analysis.repository import (
    get_documents_ready_for_classification,
    get_documents_ready_for_importance,
    get_documents_ready_for_ranking,
    get_documents_ready_for_reliability,
)
from src.pipeline_common.db import get_client

DEFAULT_LIMIT = 20


def get_workspace_id() -> str:
    rows = get_client().table("workspaces").select("id, name").limit(2).execute().data
    if len(rows) != 1:
        raise SystemExit(f"workspace_id를 자동으로 하나로 못 정했다 (workspaces 행 {len(rows)}개).")
    return str(rows[0]["id"])


def log(msg: str) -> None:
    print(f"[run_analysis_pipeline] {msg}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="분류/신뢰도/중요도/랭킹 배치 실행")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="단계별 최대 처리 건수")
    args = parser.parse_args()

    # collect()·preprocess()와 같은 계약: 문서 1건 실패는 로그로만 남기고 배치 자체는
    # 항상 성공(0)으로 끝낸다 — run_pipeline.py/refresh_wiki_scheduled.py와 동일한 관례.
    # 그렇지 않으면 10건 중 1건만 실패해도 매번 CI가 빨간불이 되어 신호가 무뎌진다.
    workspace_id = get_workspace_id()

    pending_classify = get_documents_ready_for_classification(workspace_id=workspace_id, limit=args.limit)
    log(f"분류 대상 {len(pending_classify)}건")
    if pending_classify:
        results = classify_document_versions(workspace_id=workspace_id, document_version_ids=pending_classify)
        failed = [r for r in results if r.status != "completed"]
        log(f"분류 완료 {len(results) - len(failed)}건, 실패 {len(failed)}건")

    pending_reliability = get_documents_ready_for_reliability(workspace_id=workspace_id, limit=args.limit)
    log(f"신뢰도 평가 대상 {len(pending_reliability)}건")
    if pending_reliability:
        results = evaluate_reliability_for_documents(workspace_id=workspace_id, document_version_ids=pending_reliability)
        failed = [r for r in results if r.reliability_status != "completed"]
        log(f"신뢰도 평가 완료 {len(results) - len(failed)}건, 실패 {len(failed)}건")

    pending_importance = get_documents_ready_for_importance(workspace_id=workspace_id, limit=args.limit)
    log(f"중요도 평가 대상 {len(pending_importance)}건")
    if pending_importance:
        results = evaluate_and_save_importances(workspace_id=workspace_id, document_version_ids=pending_importance)
        failed = [r for r in results if r.importance_status != "completed"]
        log(f"중요도 평가 완료 {len(results) - len(failed)}건, 실패 {len(failed)}건")

    pending_ranking = get_documents_ready_for_ranking(workspace_id=workspace_id, limit=args.limit)
    log(f"랭킹 대상 {len(pending_ranking)}건")
    if pending_ranking:
        results = rank_analysis_results(workspace_id=workspace_id, document_version_ids=pending_ranking)
        selected = [r for r in results if r.selected_for_report]
        log(f"랭킹 완료 {len(results)}건, 리포트 선정 {len(selected)}건")

    return 0


if __name__ == "__main__":
    sys.exit(main())

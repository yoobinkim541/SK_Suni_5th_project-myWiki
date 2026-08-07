"""분류 -> 신뢰도 -> 중요도 -> 랭킹 4단계를 순차 실행하는 배치 진입점.

scripts/run_pipeline.py(수집·정제) 다음에 붙여 돌릴 수 있도록 만든 분석 배치다.
중요도/랭킹 backlog가 길어지면 새 문서 유입보다 리포트 후보 복구가 우선이므로,
하류 단계를 먼저 한 번 처리한 뒤 새 문서를 분류하고 마지막에 다시 하류 단계를
재시도하는 방식으로 구성한다.

사용법:
    python scripts/run_analysis_pipeline.py
    python scripts/run_analysis_pipeline.py --limit 10
"""
from __future__ import annotations

from datetime import datetime, timezone
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.analysis.interface import get_document_refs
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

MAX_ANALYSIS_CANDIDATES = 50


def select_analysis_candidates(workspace_id: str, *, limit: int) -> list[str]:
    """Choose one bounded set of documents for this analysis run."""
    cap = min(max(limit, 0), MAX_ANALYSIS_CANDIDATES)
    if cap == 0:
        return []

    # Finish documents already near report readiness before adding newly
    # collected documents. The selected list is reused for every stage in
    # this single run.
    resumable_ids = list(
        dict.fromkeys(
            document_id
            for ready in (
                get_documents_ready_for_ranking(workspace_id=workspace_id, limit=cap * 5),
                get_documents_ready_for_importance(workspace_id=workspace_id, limit=cap * 5),
                get_documents_ready_for_reliability(workspace_id=workspace_id, limit=cap * 5),
            )
            for document_id in ready
        )
    )
    new_ids = get_documents_ready_for_classification(workspace_id=workspace_id, limit=cap)
    ready_ids = list(dict.fromkeys([*resumable_ids, *new_ids]))
    if not ready_ids:
        return []
    try:
        refs = get_document_refs(workspace_id=workspace_id, document_version_ids=ready_ids)
    except Exception:
        return ready_ids[:cap]
    scores = {ref.document_version_id: _analysis_candidate_score(ref) for ref in refs}
    # A retry must not be pushed out by newly collected articles. Within each
    # class, use the same freshness/source/relevance ranking.
    resumable_set = set(resumable_ids)
    return sorted(
        ready_ids,
        key=lambda document_id: (
            document_id not in resumable_set,
            -scores.get(document_id, 0),
            document_id,
        ),
    )[:cap]
def _analysis_candidate_score(ref) -> float:
    text = (ref.title or "").lower()
    relevance = 25.0 if any(token in text for token in ("sk????", "sk hynix", "????")) else 0.0
    if not relevance and any(token in text for token in ("hbm", "dram", "nand", "semiconductor", "???")):
        relevance = 12.0
    source_value = ref.source_reliability_score
    if source_value is None:
        source_value = {
            "disclosure": 100,
            "official_press": 85,
            "news": 60,
            "rss": 60,
        }.get((ref.source_type or "").lower(), 40)
    source_score = min(max(float(source_value), 0.0), 100.0) * 0.30
    return _recency_candidate_score(ref.published_at) + source_score + relevance


def _recency_candidate_score(published_at: str | None) -> float:
    if not published_at:
        return 0.0
    try:
        published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (datetime.now(timezone.utc) - published.astimezone(timezone.utc)).total_seconds() / 3600)
    return max(0.0, 45.0 - min(45.0, age_hours / 8.0))


DEFAULT_LIMIT = 20


def get_analysis_backlog_count(workspace_id: str) -> int:
    """Return the number of runnable analysis items, capped at one burst."""
    ready_ids = {
        document_id
        for ready in (
            get_documents_ready_for_ranking(workspace_id=workspace_id, limit=MAX_ANALYSIS_CANDIDATES),
            get_documents_ready_for_importance(workspace_id=workspace_id, limit=MAX_ANALYSIS_CANDIDATES),
            get_documents_ready_for_reliability(workspace_id=workspace_id, limit=MAX_ANALYSIS_CANDIDATES),
            get_documents_ready_for_classification(workspace_id=workspace_id, limit=MAX_ANALYSIS_CANDIDATES),
        )
        for document_id in ready
    }
    return min(len(ready_ids), MAX_ANALYSIS_CANDIDATES)


def get_adaptive_analysis_limit(workspace_id: str) -> int:
    """Keep normal runs small, then drain a growing backlog in one burst."""
    backlog_count = get_analysis_backlog_count(workspace_id)
    return DEFAULT_LIMIT if backlog_count <= DEFAULT_LIMIT else backlog_count


def get_workspace_id() -> str:
    rows = get_client().table("workspaces").select("id, name").limit(2).execute().data
    if len(rows) != 1:
        raise SystemExit(f"workspace_id를 자동으로 하나로 정할 수 없음(workspaces 총 {len(rows)}개).")
    return str(rows[0]["id"])


def log(msg: str) -> None:
    print(f"[run_analysis_pipeline] {msg}", flush=True)


def _run_ranking_stage(*, workspace_id: str, document_version_ids: list[str]) -> list:
    pending_ranking = document_version_ids
    log(f"랭킹 대상 {len(pending_ranking)}건")
    if pending_ranking:
        results = rank_analysis_results(workspace_id=workspace_id, document_version_ids=pending_ranking)
        selected = [r for r in results if r.selected_for_report]
        log(f"랭킹 완료 {len(results)}건 리포트 선정 {len(selected)}건")
        return results
    return []


def _run_importance_stage(*, workspace_id: str, document_version_ids: list[str]) -> list:
    pending_importance = document_version_ids
    log(f"중요도 평가 대상 {len(pending_importance)}건")
    if pending_importance:
        results = evaluate_and_save_importances(workspace_id=workspace_id, document_version_ids=pending_importance)
        failed = [r for r in results if r.importance_status != "completed"]
        log(f"중요도 평가 완료 {len(results) - len(failed)}건 실패 {len(failed)}건")
        return results
    return []


def _run_reliability_stage(*, workspace_id: str, document_version_ids: list[str]) -> list:
    pending_reliability = document_version_ids
    log(f"신뢰도 평가 대상 {len(pending_reliability)}건")
    if pending_reliability:
        results = evaluate_reliability_for_documents(workspace_id=workspace_id, document_version_ids=pending_reliability)
        failed = [r for r in results if r.reliability_status != "completed"]
        log(f"신뢰도 평가 완료 {len(results) - len(failed)}건 실패 {len(failed)}건")
        return results
    return []


def _run_classification_stage(*, workspace_id: str, document_version_ids: list[str]) -> list:
    pending_classify = document_version_ids
    log(f"분류 대상 {len(pending_classify)}건")
    if pending_classify:
        results = classify_document_versions(workspace_id=workspace_id, document_version_ids=pending_classify)
        failed = [r for r in results if r.status != "completed"]
        log(f"분류 완료 {len(results) - len(failed)}건 실패 {len(failed)}건")
        return results
    return []


def _has_failed_results(results: list, status_field: str) -> bool:
    return any(getattr(result, status_field, "completed") == "failed" for result in results)


def run_analysis_pipeline(
    workspace_id: str,
    *,
    limit: int = DEFAULT_LIMIT,
    document_version_ids: list[str] | None = None,
) -> list[str] | None:
    """분류->신뢰도->중요도->랭킹 4단계를 실행한다.

    스케줄 배치에서는 실행 시간 예산이 빠듯하므로, 이미 중요도/랭킹 직전까지 온 문서가
    새 유입 문서 뒤로 밀려 리포트가 비는 현상을 막기 위해 다음 순서를 사용한다.

    1. 하류 backlog 우선 처리: 랭킹 -> 중요도 -> 신뢰도
    2. 신규 문서 진입: 분류
    3. 같은 실행 안에서 한 번 더 하류 단계 재시도: 신뢰도 -> 중요도 -> 랭킹
    """
    effective_limit = min(max(limit, 0), MAX_ANALYSIS_CANDIDATES)
    candidate_ids = (
        list(dict.fromkeys(document_version_ids))[:effective_limit]
        if document_version_ids is not None
        else select_analysis_candidates(workspace_id, limit=effective_limit)
    )
    if not candidate_ids:
        log("analysis candidates selected: 0")
        return None
    log(f"analysis candidates selected: {len(candidate_ids)}")
    try:
        classification_results = _run_classification_stage(
            workspace_id=workspace_id, document_version_ids=candidate_ids
        )
        reliability_results = _run_reliability_stage(
            workspace_id=workspace_id, document_version_ids=candidate_ids
        )
        importance_results = _run_importance_stage(
            workspace_id=workspace_id, document_version_ids=candidate_ids
        )
        ranking_results = _run_ranking_stage(
            workspace_id=workspace_id, document_version_ids=candidate_ids
        )
    except Exception:
        raise
    if any((
        _has_failed_results(classification_results, "status"),
        _has_failed_results(reliability_results, "reliability_status"),
        _has_failed_results(importance_results, "importance_status"),
        _has_failed_results(ranking_results, "ranking_status"),
    )):
        log("analysis did not complete for every selected candidate")
        return None
    log("analysis completed")
    return candidate_ids


def main() -> int:
    parser = argparse.ArgumentParser(description="분류/신뢰도/중요도/랭킹 배치 실행")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="단계별 최대 처리 건수")
    args = parser.parse_args()

    run_analysis_pipeline(get_workspace_id(), limit=args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from .importance_models import AnalysisResultForReport
from .ranking_models import (
    DEFAULT_CATEGORY_LIMITS,
    DEFAULT_REPORT_LIMIT,
    MAX_RANKING_DOCUMENTS,
    RANKING_FORMULA_VERSION,
    RankingCandidate,
    RankedAnalysisResult,
)
from .ranking_scoring import calculate_ranking_score, calculate_recency_score
from .repository import get_ranked_results_for_report, get_ranking_candidates, save_ranking_results


def rank_analysis_results(
    *,
    workspace_id: str,
    document_version_ids: list[str],
    ranking_reference_time: datetime | None = None,
    report_limit: int = DEFAULT_REPORT_LIMIT,
    category_limits: dict[str, int] | None = None,
    force: bool = False,
) -> list[RankedAnalysisResult]:
    unique_document_ids = _dedupe_document_ids(document_version_ids)[:MAX_RANKING_DOCUMENTS]
    if not unique_document_ids:
        return []

    reference_time = ranking_reference_time or datetime.now(timezone.utc)
    if reference_time.tzinfo is None or reference_time.utcoffset() is None:
        raise ValueError("ranking_reference_time must be timezone-aware")
    reference_time_utc = reference_time.astimezone(timezone.utc)
    batch_date = reference_time_utc.date()
    normalized_category_limits = dict(DEFAULT_CATEGORY_LIMITS)
    if category_limits:
        normalized_category_limits.update(category_limits)

    candidates = get_ranking_candidates(
        workspace_id=workspace_id,
        document_version_ids=unique_document_ids,
    )
    if not candidates:
        return []

    if not force and _can_reuse_existing_ranking(
        candidates=candidates,
        requested_document_ids=unique_document_ids,
        reference_time=reference_time_utc,
        batch_date=batch_date,
    ):
        return _build_results_from_existing(candidates)

    provisional_results: list[RankedAnalysisResult] = []
    for candidate in candidates:
        recency = calculate_recency_score(
            published_at=candidate.published_at,
            reference_time=reference_time_utc,
        )
        ranking_score = calculate_ranking_score(
            importance_score=candidate.importance_score,
            reliability_score=candidate.reliability_score,
            recency_score=recency.score,
        )
        warnings = list(recency.warnings)
        ranking_status = "completed"
        ranking_exclusion_reason = None
        ranking_position = None
        selection_reason = None
        if candidate.reliability_score < 40:
            ranking_status = "excluded"
            ranking_exclusion_reason = "LOW_RELIABILITY"
            selection_reason = "LOW_RELIABILITY"
        elif candidate.reliability_score < 70:
            warnings.append("REVIEW_RECOMMENDED")

        provisional_results.append(
            RankedAnalysisResult(
                analysis_result_id=candidate.analysis_result_id,
                workspace_id=candidate.workspace_id,
                document_version_id=candidate.document_version_id,
                title=candidate.title,
                primary_category=candidate.primary_category,
                secondary_categories=list(candidate.secondary_categories),
                canonical_url=candidate.canonical_url,
                source_name=candidate.source_name,
                published_at=candidate.published_at,
                reliability_score=candidate.reliability_score,
                reliability_level=candidate.reliability_level,
                importance_score=candidate.importance_score,
                importance_level=candidate.importance_level,
                core_summary=candidate.core_summary,
                key_points=list(candidate.key_points),
                key_numbers=list(candidate.key_numbers),
                sk_hynix_implication=candidate.sk_hynix_implication,
                opportunities=list(candidate.opportunities),
                risks=list(candidate.risks),
                watch_points=list(candidate.watch_points),
                summary_evidence_refs=list(candidate.summary_evidence_refs),
                ranking_status=ranking_status,
                ranking_score=ranking_score,
                recency_score=recency.score,
                ranking_position=ranking_position,
                selected_for_report=False,
                report_selection_position=None,
                selection_reason=selection_reason,
                ranking_exclusion_reason=ranking_exclusion_reason,
                ranking_formula_version=RANKING_FORMULA_VERSION,
                ranking_reference_time=reference_time_utc,
                ranking_batch_date=batch_date,
                ranked_at=reference_time_utc,
                ranking_detail={
                    "formula_version": RANKING_FORMULA_VERSION,
                    "weights": {
                        "importance": 0.6,
                        "reliability": 0.3,
                        "recency": 0.1,
                    },
                    "components": {
                        "importance_score": candidate.importance_score,
                        "reliability_score": candidate.reliability_score,
                        "recency_score": recency.score,
                    },
                    "published_at": candidate.published_at.isoformat() if candidate.published_at else None,
                    "reference_time": reference_time.isoformat(),
                    "age_hours": float(recency.age_hours) if recency.age_hours is not None else None,
                    "recency_bucket": recency.bucket,
                    "warnings": warnings,
                    "batch_document_version_ids": list(unique_document_ids),
                    "selection": {
                        "selected_for_report": False,
                        "report_selection_position": None,
                        "reason": selection_reason,
                    },
                },
            )
        )

    completed = [item for item in provisional_results if item.ranking_status == "completed"]
    completed.sort(key=_completed_sort_key)
    for position, item in enumerate(completed, start=1):
        item.ranking_position = position

    _apply_report_selection(
        results=completed,
        report_limit=report_limit,
        category_limits=normalized_category_limits,
    )

    final_results = completed + [item for item in provisional_results if item.ranking_status != "completed"]
    for item in final_results:
        item.ranking_detail["selection"] = {
            "selected_for_report": item.selected_for_report,
            "report_selection_position": item.report_selection_position,
            "reason": item.selection_reason,
        }
    return save_ranking_results(workspace_id=workspace_id, results=final_results)


def get_ranked_results_for_report_data(*, workspace_id: str, ranking_batch_date: date, limit: int = DEFAULT_REPORT_LIMIT) -> list[AnalysisResultForReport]:
    return get_ranked_results_for_report(
        workspace_id=workspace_id,
        ranking_batch_date=ranking_batch_date,
        limit=limit,
    )


def _dedupe_document_ids(document_version_ids: list[str]) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()
    for document_version_id in document_version_ids:
        normalized = str(document_version_id).strip()
        if not normalized or normalized in seen:
            continue
        results.append(normalized)
        seen.add(normalized)
    return results


def _can_reuse_existing_ranking(*, candidates: list[RankingCandidate], requested_document_ids: list[str], reference_time: datetime, batch_date: date) -> bool:
    if len(candidates) != len(requested_document_ids):
        return False
    for candidate in candidates:
        if candidate.existing_ranking_status not in {"completed", "excluded"}:
            return False
        if candidate.existing_ranking_formula_version != RANKING_FORMULA_VERSION:
            return False
        if candidate.existing_ranking_batch_date != batch_date:
            return False
        if candidate.existing_ranking_reference_time != reference_time:
            return False
        detail = candidate.existing_ranking_detail or {}
        if detail.get("batch_document_version_ids") != requested_document_ids:
            return False
        components = detail.get("components") or {}
        if components.get("importance_score") != candidate.importance_score:
            return False
        if components.get("reliability_score") != candidate.reliability_score:
            return False
        published_at = candidate.published_at.isoformat() if candidate.published_at else None
        if detail.get("published_at") != published_at:
            return False
    return True


def _build_results_from_existing(candidates: list[RankingCandidate]) -> list[RankedAnalysisResult]:
    results: list[RankedAnalysisResult] = []
    for candidate in candidates:
        results.append(
            RankedAnalysisResult(
                analysis_result_id=candidate.analysis_result_id,
                workspace_id=candidate.workspace_id,
                document_version_id=candidate.document_version_id,
                title=candidate.title,
                primary_category=candidate.primary_category,
                secondary_categories=list(candidate.secondary_categories),
                canonical_url=candidate.canonical_url,
                source_name=candidate.source_name,
                published_at=candidate.published_at,
                reliability_score=candidate.reliability_score,
                reliability_level=candidate.reliability_level,
                importance_score=candidate.importance_score,
                importance_level=candidate.importance_level,
                core_summary=candidate.core_summary,
                key_points=list(candidate.key_points),
                key_numbers=list(candidate.key_numbers),
                sk_hynix_implication=candidate.sk_hynix_implication,
                opportunities=list(candidate.opportunities),
                risks=list(candidate.risks),
                watch_points=list(candidate.watch_points),
                summary_evidence_refs=list(candidate.summary_evidence_refs),
                ranking_status=candidate.existing_ranking_status,
                ranking_score=candidate.existing_ranking_score,
                recency_score=candidate.existing_recency_score,
                ranking_position=candidate.existing_ranking_position,
                selected_for_report=candidate.existing_selected_for_report,
                report_selection_position=candidate.existing_report_selection_position,
                selection_reason=candidate.existing_selection_reason,
                ranking_exclusion_reason=candidate.existing_ranking_exclusion_reason,
                ranking_formula_version=candidate.existing_ranking_formula_version,
                ranking_reference_time=candidate.existing_ranking_reference_time,
                ranking_batch_date=candidate.existing_ranking_batch_date,
                ranked_at=candidate.existing_ranked_at,
                ranking_detail=dict(candidate.existing_ranking_detail or {}),
                ranking_error_message=candidate.existing_ranking_error_message,
            )
        )
    return sorted(results, key=lambda item: (item.ranking_position is None, item.ranking_position or 10**9, item.document_version_id))


def _completed_sort_key(item: RankedAnalysisResult) -> tuple[Decimal, int, int, int, int, str]:
    published_timestamp = item.published_at.astimezone(timezone.utc).timestamp() if item.published_at else float("-inf")
    return (
        -(item.ranking_score or Decimal("0.00")),
        -(item.importance_score or 0),
        -(item.reliability_score or 0),
        -(item.recency_score or 0),
        -int(published_timestamp) if item.published_at else 10**18,
        item.document_version_id,
    )


def _apply_report_selection(*, results: list[RankedAnalysisResult], report_limit: int, category_limits: dict[str, int]) -> None:
    selected_count = 0
    category_counts: dict[str, int] = {}
    report_position = 1
    for item in results:
        category_limit = category_limits.get(item.primary_category, report_limit)
        if category_counts.get(item.primary_category, 0) >= category_limit:
            item.selected_for_report = False
            item.selection_reason = "CATEGORY_LIMIT"
            item.report_selection_position = None
            continue
        if selected_count >= report_limit:
            item.selected_for_report = False
            item.selection_reason = "OUTSIDE_REPORT_LIMIT"
            item.report_selection_position = None
            continue
        item.selected_for_report = True
        item.selection_reason = "SELECTED"
        item.report_selection_position = report_position
        report_position += 1
        selected_count += 1
        category_counts[item.primary_category] = category_counts.get(item.primary_category, 0) + 1

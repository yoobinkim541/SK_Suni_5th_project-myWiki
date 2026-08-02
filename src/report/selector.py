from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal

from ..analysis.models import Category
from .models import ReportCandidate

MIN_SCORE = 0
MAX_SCORE = 100


def select_report_candidates(
    candidates: Sequence[ReportCandidate],
    *,
    max_candidates: int,
    min_reliability_score: int,
    min_importance_score: int,
    min_ranking_score: Decimal | None = None,
    category_limits: Mapping[Category, int] | None = None,
) -> list[ReportCandidate]:
    _validate_selection_config(
        max_candidates=max_candidates,
        min_reliability_score=min_reliability_score,
        min_importance_score=min_importance_score,
        min_ranking_score=min_ranking_score,
        category_limits=category_limits,
    )

    eligible = [
        candidate
        for candidate in candidates
        if _is_eligible_candidate(
            candidate,
            min_reliability_score=min_reliability_score,
            min_importance_score=min_importance_score,
            min_ranking_score=min_ranking_score,
        )
    ]
    ordered = sort_report_candidates(eligible)

    selected: list[ReportCandidate] = []
    category_counts: defaultdict[Category, int] = defaultdict(int)
    for candidate in ordered:
        if category_limits is not None:
            category_limit = category_limits.get(candidate.category)
            if category_limit is not None and category_counts[candidate.category] >= category_limit:
                continue

        selected.append(candidate)
        category_counts[candidate.category] += 1
        if len(selected) >= max_candidates:
            break

    return selected


def sort_report_candidates(candidates: Sequence[ReportCandidate]) -> list[ReportCandidate]:
    ordered = list(candidates)
    ordered.sort(key=lambda item: item.analysis_result_id)
    ordered.sort(
        key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    ordered.sort(key=lambda item: item.reliability_score or MIN_SCORE, reverse=True)
    ordered.sort(key=lambda item: item.importance_score or MIN_SCORE, reverse=True)
    ordered.sort(
        key=lambda item: item.ranking_score if item.ranking_score is not None else Decimal("-1"),
        reverse=True,
    )
    return ordered


def _is_eligible_candidate(
    candidate: ReportCandidate,
    *,
    min_reliability_score: int,
    min_importance_score: int,
    min_ranking_score: Decimal | None,
) -> bool:
    if candidate.reliability_score is None or candidate.reliability_score < min_reliability_score:
        return False
    if candidate.importance_score is None or candidate.importance_score < min_importance_score:
        return False
    if min_ranking_score is not None:
        if candidate.ranking_score is None or candidate.ranking_score < min_ranking_score:
            return False
    return True


def _validate_selection_config(
    *,
    max_candidates: int,
    min_reliability_score: int,
    min_importance_score: int,
    min_ranking_score: Decimal | None,
    category_limits: Mapping[Category, int] | None,
) -> None:
    if max_candidates < 1:
        raise ValueError("max_candidates는 1 이상이어야 합니다.")
    _validate_score("min_reliability_score", min_reliability_score)
    _validate_score("min_importance_score", min_importance_score)
    if min_ranking_score is not None:
        _validate_score("min_ranking_score", min_ranking_score)
    if category_limits is None:
        return
    for category, limit in category_limits.items():
        if not isinstance(category, Category):
            raise ValueError("category_limits의 key는 Category여야 합니다.")
        if limit < 0:
            raise ValueError("category limit은 0 이상이어야 합니다.")


def _validate_score(name: str, value: int | Decimal) -> None:
    if value < MIN_SCORE or value > MAX_SCORE:
        raise ValueError(f"{name}는 {MIN_SCORE} 이상 {MAX_SCORE} 이하여야 합니다.")

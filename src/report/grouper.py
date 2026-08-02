from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from pydantic import BaseModel, Field

from ..analysis.models import Category
from .models import IssueGroup, ReportCandidate

_URL_PATTERN = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_NON_WORD_PATTERN = re.compile(r"[\W_]+", re.UNICODE)


class IssueGroupingConfig(BaseModel):
    max_time_gap_hours: int = Field(ge=0)
    min_title_similarity: float = Field(ge=0.0, le=1.0)
    min_summary_similarity: float = Field(ge=0.0, le=1.0)
    min_shared_title_tokens: int = Field(ge=0)
    require_same_category: bool = True


def group_report_candidates(
    candidates: Sequence[ReportCandidate],
    *,
    config: IssueGroupingConfig,
    explicit_group_keys: Mapping[str, str] | None = None,
) -> list[IssueGroup]:
    _validate_candidate_input(candidates)
    if not candidates:
        return []

    ordered_candidates = _sort_candidates_for_grouping(candidates)
    working_groups: list[dict[str, object]] = []

    for candidate in ordered_candidates:
        explicit_group_key = explicit_group_keys.get(candidate.document_id) if explicit_group_keys is not None else None
        if explicit_group_key is not None:
            matching_group = _find_explicit_group(
                groups=working_groups,
                candidate=candidate,
                explicit_group_key=explicit_group_key,
            )
            if matching_group is None:
                working_groups.append(
                    _build_group_state(
                        candidate=candidate,
                        explicit_group_key=explicit_group_key,
                    )
                )
            else:
                _append_candidate_to_group(matching_group, candidate)
            continue

        best_match = _find_best_heuristic_group(
            groups=working_groups,
            candidate=candidate,
            config=config,
        )
        if best_match is None:
            working_groups.append(_build_group_state(candidate=candidate, explicit_group_key=None))
            continue
        _append_candidate_to_group(best_match, candidate)

    issue_groups = [_finalize_issue_group(group, config=config) for group in working_groups]
    return _sort_issue_groups(issue_groups)


def _validate_candidate_input(candidates: Sequence[ReportCandidate]) -> None:
    if not candidates:
        return
    workspace_ids = {candidate.workspace_id for candidate in candidates}
    if len(workspace_ids) != 1:
        raise ValueError("All candidates must belong to the same workspace.")
    analysis_result_ids = [candidate.analysis_result_id for candidate in candidates]
    if len(set(analysis_result_ids)) != len(analysis_result_ids):
        raise ValueError("Duplicate analysis_result_id values are not allowed.")


def _sort_candidates_for_grouping(candidates: Sequence[ReportCandidate]) -> list[ReportCandidate]:
    ordered = list(candidates)
    ordered.sort(key=lambda item: item.analysis_result_id)
    ordered.sort(
        key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    ordered.sort(key=lambda item: _candidate_ranking_score(item), reverse=True)
    ordered.sort(key=lambda item: _candidate_importance_score(item), reverse=True)
    ordered.sort(key=lambda item: _candidate_reliability_score(item), reverse=True)
    return ordered


def _find_explicit_group(
    *,
    groups: list[dict[str, object]],
    candidate: ReportCandidate,
    explicit_group_key: str,
) -> dict[str, object] | None:
    for group in groups:
        if group["explicit_group_key"] != explicit_group_key:
            continue
        representative = group["representative_candidate"]
        if representative.workspace_id != candidate.workspace_id:
            continue
        if representative.category != candidate.category:
            continue
        return group
    return None


def _find_best_heuristic_group(
    *,
    groups: list[dict[str, object]],
    candidate: ReportCandidate,
    config: IssueGroupingConfig,
) -> dict[str, object] | None:
    best_group: dict[str, object] | None = None
    best_score: tuple[float, float, int, str] | None = None
    for group in groups:
        representative = group["representative_candidate"]
        comparison = _calculate_issue_similarity(
            candidate=candidate,
            representative=representative,
            config=config,
        )
        if comparison is None:
            continue
        score = (
            comparison["title_similarity"],
            comparison["summary_similarity"],
            comparison["shared_title_tokens"],
            representative.analysis_result_id,
        )
        if best_score is None or score > best_score:
            best_group = group
            best_score = score
    return best_group


def _calculate_issue_similarity(
    *,
    candidate: ReportCandidate,
    representative: ReportCandidate,
    config: IssueGroupingConfig,
) -> dict[str, float | int] | None:
    if candidate.workspace_id != representative.workspace_id:
        return None
    if config.require_same_category and candidate.category != representative.category:
        return None
    if not _is_within_time_window(candidate.published_at, representative.published_at, config.max_time_gap_hours):
        return None

    title_tokens_candidate = _tokenize_issue_text(candidate.title)
    title_tokens_representative = _tokenize_issue_text(representative.title)
    summary_tokens_candidate = _tokenize_issue_text(candidate.summary)
    summary_tokens_representative = _tokenize_issue_text(representative.summary)
    if not title_tokens_candidate or not title_tokens_representative:
        return None
    if not summary_tokens_candidate or not summary_tokens_representative:
        return None

    shared_title_tokens = len(title_tokens_candidate & title_tokens_representative)
    if shared_title_tokens < config.min_shared_title_tokens:
        return None

    title_similarity = _token_jaccard_similarity(title_tokens_candidate, title_tokens_representative)
    if title_similarity < config.min_title_similarity:
        return None

    summary_similarity = _token_jaccard_similarity(summary_tokens_candidate, summary_tokens_representative)
    if summary_similarity < config.min_summary_similarity:
        return None

    return {
        "title_similarity": title_similarity,
        "summary_similarity": summary_similarity,
        "shared_title_tokens": shared_title_tokens,
    }


def _is_within_time_window(
    first: datetime | None,
    second: datetime | None,
    max_time_gap_hours: int,
) -> bool:
    if first is None or second is None:
        return False
    if first.tzinfo is None or second.tzinfo is None:
        return False
    return abs(first - second) <= timedelta(hours=max_time_gap_hours)


def _normalize_issue_text(value: str | None) -> str:
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", value).lower()
    normalized = _URL_PATTERN.sub(" ", normalized)
    normalized = _NON_WORD_PATTERN.sub(" ", normalized)
    normalized = " ".join(normalized.split())
    return normalized.strip()


def _tokenize_issue_text(value: str | None) -> set[str]:
    normalized = _normalize_issue_text(value)
    if not normalized:
        return set()
    tokens: set[str] = set()
    for token in normalized.split():
        if len(token) > 1 or any(character.isdigit() for character in token):
            tokens.add(token)
    return tokens


def _token_jaccard_similarity(tokens_a: set[str], tokens_b: set[str]) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    union = tokens_a | tokens_b
    if not union:
        return 0.0
    return len(tokens_a & tokens_b) / len(union)


def _build_group_state(
    *,
    candidate: ReportCandidate,
    explicit_group_key: str | None,
) -> dict[str, object]:
    return {
        "candidates": [candidate],
        "representative_candidate": candidate,
        "explicit_group_key": explicit_group_key,
    }


def _append_candidate_to_group(group: dict[str, object], candidate: ReportCandidate) -> None:
    group["candidates"].append(candidate)
    ordered_candidates = _sort_group_candidates(group["candidates"])
    group["candidates"] = ordered_candidates
    group["representative_candidate"] = ordered_candidates[0]


def _finalize_issue_group(group: dict[str, object], *, config: IssueGroupingConfig) -> IssueGroup:
    candidates = _sort_group_candidates(group["candidates"])
    representative = candidates[0]
    explicit_group_key = group["explicit_group_key"]
    issue_key = _build_issue_key(
        workspace_id=representative.workspace_id,
        category=representative.category,
        candidates=candidates,
        explicit_group_key=explicit_group_key,
    )
    return IssueGroup(
        issue_key=issue_key,
        category=representative.category,
        candidates=candidates,
        representative_candidate=representative,
        representative_analysis_result_id=representative.analysis_result_id,
    )


def _build_issue_key(
    *,
    workspace_id: str,
    category: Category,
    candidates: Sequence[ReportCandidate],
    explicit_group_key: str | None,
) -> str:
    if explicit_group_key is not None:
        return f"explicit:{workspace_id}:{category.value}:{explicit_group_key}"

    analysis_ids = "|".join(sorted(candidate.analysis_result_id for candidate in candidates))
    digest = hashlib.sha256(analysis_ids.encode("utf-8")).hexdigest()[:16]
    return f"heuristic:{category.value}:{digest}"


def _sort_group_candidates(candidates: Sequence[ReportCandidate]) -> list[ReportCandidate]:
    ordered = list(candidates)
    ordered.sort(key=lambda item: item.analysis_result_id)
    ordered.sort(
        key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    ordered.sort(key=lambda item: _candidate_ranking_score(item), reverse=True)
    ordered.sort(key=lambda item: _candidate_importance_score(item), reverse=True)
    ordered.sort(key=lambda item: _candidate_reliability_score(item), reverse=True)
    return ordered


def _sort_issue_groups(groups: Sequence[IssueGroup]) -> list[IssueGroup]:
    ordered = list(groups)
    ordered.sort(key=lambda group: group.issue_key)
    ordered.sort(
        key=lambda group: group.representative_candidate.published_at
        if group.representative_candidate is not None and group.representative_candidate.published_at is not None
        else datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    ordered.sort(
        key=lambda group: _candidate_ranking_score(group.representative_candidate),
        reverse=True,
    )
    ordered.sort(
        key=lambda group: _candidate_importance_score(group.representative_candidate),
        reverse=True,
    )
    ordered.sort(
        key=lambda group: _candidate_reliability_score(group.representative_candidate),
        reverse=True,
    )
    return ordered


def _candidate_reliability_score(candidate: ReportCandidate | None) -> int:
    if candidate is None or candidate.reliability_score is None:
        return -1
    return candidate.reliability_score


def _candidate_importance_score(candidate: ReportCandidate | None) -> int:
    if candidate is None or candidate.importance_score is None:
        return -1
    return candidate.importance_score


def _candidate_ranking_score(candidate: ReportCandidate | None) -> Decimal:
    if candidate is None or candidate.ranking_score is None:
        return Decimal("-1")
    return candidate.ranking_score

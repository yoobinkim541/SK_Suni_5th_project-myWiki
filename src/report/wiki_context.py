from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Sequence

from pydantic import ValidationError

from ..wiki.models import WikiSearchRequest, WikiSearchResult
from ..wiki.repository import WikiSearchError
from .models import EnrichedIssueGroup, IssueGroup, ReportCandidate, WikiContext

DEFAULT_WIKI_CONTEXT_LIMIT = 3
DEFAULT_MAX_QUERY_TERMS = 10

_URL_PATTERN = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_NON_WORD_PATTERN = re.compile(r"[\W_]+", re.UNICODE)
_STOPWORDS = {
    "발표",
    "관련",
    "시장",
    "기업",
    "기술",
    "정보",
    "추진",
    "계획",
    "소식",
}


def build_wiki_search_request(
    issue_group: IssueGroup,
    *,
    limit: int,
) -> WikiSearchRequest:
    workspace_id = _get_single_workspace_id(issue_group)
    query_terms = build_wiki_query_terms(issue_group)
    return WikiSearchRequest(
        workspace_id=workspace_id,
        query=build_wiki_query(issue_group),
        query_terms=query_terms,
        category=issue_group.category,
        limit=limit,
    )


def build_wiki_query(issue_group: IssueGroup) -> str:
    return " ".join(build_wiki_query_terms(issue_group))


def build_wiki_query_terms(
    issue_group: IssueGroup,
    *,
    max_terms: int = DEFAULT_MAX_QUERY_TERMS,
) -> tuple[str, ...]:
    if max_terms < 1:
        raise ValueError("max_terms must be at least 1.")

    workspace_id = _get_single_workspace_id(issue_group)
    representative = _get_representative_candidate(issue_group)

    representative_title_tokens = _ordered_tokens(representative.title)
    representative_summary_tokens = _ordered_tokens(representative.summary)
    repeated_title_tokens = _repeated_tokens(candidate.title for candidate in issue_group.candidates)
    repeated_summary_tokens = _repeated_tokens(candidate.summary for candidate in issue_group.candidates)
    category_tokens = _ordered_tokens(issue_group.category.value)

    ordered_groups = (
        representative_title_tokens,
        repeated_title_tokens,
        representative_summary_tokens,
        repeated_summary_tokens,
        category_tokens,
    )

    terms: list[str] = []
    seen: set[str] = set()
    for token_group in ordered_groups:
        for token in token_group:
            if token in seen:
                continue
            terms.append(token)
            seen.add(token)
            if len(terms) >= max_terms:
                return tuple(terms)

    if not terms:
        raise ValueError(f"Issue group for workspace {workspace_id} did not produce any wiki query terms.")
    return tuple(terms)


def to_wiki_context(result: WikiSearchResult) -> WikiContext:
    return WikiContext(
        wiki_page_id=result.wiki_page_id,
        wiki_version_id=result.wiki_version_id,
        title=result.title,
        content=result.content,
        similarity_score=result.score,
        updated_at=result.updated_at,
        source_document_version_ids=list(result.source_document_version_ids),
    )


def enrich_issue_group(
    issue_group: IssueGroup,
    *,
    wiki_search: Callable[[WikiSearchRequest], Sequence[WikiSearchResult]],
    limit: int,
) -> EnrichedIssueGroup:
    request = build_wiki_search_request(issue_group, limit=limit)
    try:
        results = wiki_search(request)
    except WikiSearchError:
        return EnrichedIssueGroup(issue_group=issue_group, wiki_contexts=[])

    wiki_contexts = [to_wiki_context(result) for result in results]
    return EnrichedIssueGroup(issue_group=issue_group, wiki_contexts=wiki_contexts)


def enrich_issue_groups(
    issue_groups: Sequence[IssueGroup],
    *,
    wiki_search: Callable[[WikiSearchRequest], Sequence[WikiSearchResult]],
    limit_per_group: int,
) -> list[EnrichedIssueGroup]:
    return [
        enrich_issue_group(
            issue_group,
            wiki_search=wiki_search,
            limit=limit_per_group,
        )
        for issue_group in issue_groups
    ]


def _get_single_workspace_id(issue_group: IssueGroup) -> str:
    workspace_ids = {candidate.workspace_id for candidate in issue_group.candidates}
    if len(workspace_ids) != 1:
        raise ValueError("All candidates in an issue group must belong to the same workspace.")
    return next(iter(workspace_ids))


def _get_representative_candidate(issue_group: IssueGroup) -> ReportCandidate:
    representative_id = issue_group.representative_analysis_result_id
    if representative_id is None:
        raise ValueError("Issue group is missing representative_analysis_result_id.")
    for candidate in issue_group.candidates:
        if candidate.analysis_result_id == representative_id:
            return candidate
    raise ValueError("representative_analysis_result_id does not exist in issue_group.candidates.")


def _repeated_tokens(values: Sequence[str | None]) -> tuple[str, ...]:
    counter: Counter[str] = Counter()
    first_seen: dict[str, int] = {}
    for index, value in enumerate(values):
        tokens = _ordered_tokens(value)
        for token in dict.fromkeys(tokens):
            counter[token] += 1
            first_seen.setdefault(token, index)

    repeated = [token for token, count in counter.items() if count >= 2]
    repeated.sort(key=lambda token: (first_seen[token], token))
    return tuple(repeated)


def _ordered_tokens(value: str | None) -> tuple[str, ...]:
    normalized = _normalize_search_text(value)
    if not normalized:
        return ()

    ordered: list[str] = []
    seen: set[str] = set()
    for token in normalized.split():
        if token in _STOPWORDS:
            continue
        if len(token) <= 1 and not any(character.isdigit() for character in token):
            continue
        if token in seen:
            continue
        ordered.append(token)
        seen.add(token)
    return tuple(ordered)


def _normalize_search_text(value: str | None) -> str:
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", value).lower()
    normalized = _URL_PATTERN.sub(" ", normalized)
    normalized = _NON_WORD_PATTERN.sub(" ", normalized)
    normalized = " ".join(normalized.split())
    return normalized.strip()

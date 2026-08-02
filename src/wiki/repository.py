from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from supabase import Client

from ..analysis.repository import get_supabase
from .models import WikiSearchRequest, WikiSearchResult

DEFAULT_STORAGE_BUCKET = "myWiki"
DEFAULT_CANDIDATE_LIMIT_MULTIPLIER = 10
DEFAULT_MAX_PAGE_SCAN = 30

_URL_PATTERN = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_NON_WORD_PATTERN = re.compile(r"[\W_]+", re.UNICODE)


class WikiSearchError(Exception):
    pass


def search_wiki_contexts(
    request: WikiSearchRequest,
    *,
    supabase: Client | None = None,
    storage_bucket: str = DEFAULT_STORAGE_BUCKET,
    candidate_limit_multiplier: int = DEFAULT_CANDIDATE_LIMIT_MULTIPLIER,
    max_page_scan: int = DEFAULT_MAX_PAGE_SCAN,
) -> list[WikiSearchResult]:
    db = supabase or get_supabase()
    page_limit = max(
        request.limit,
        min(max_page_scan, request.limit * max(1, candidate_limit_multiplier)),
    )

    try:
        page_rows = (
            db.table("wiki_pages")
            .select("id, workspace_id, title, status, current_version_id, updated_at")
            .eq("workspace_id", request.workspace_id)
            .eq("status", "published")
            .order("updated_at", desc=True)
            .limit(page_limit)
            .execute()
            .data
        )
    except Exception as exc:  # pragma: no cover - defensive wrapper
        raise WikiSearchError("Failed to load wiki pages.") from exc

    current_version_ids = [
        str(row["current_version_id"])
        for row in page_rows
        if row.get("current_version_id")
    ]
    if not current_version_ids:
        return []

    try:
        version_rows = (
            db.table("wiki_page_versions")
            .select("id, page_id, version_no, markdown_object_key, created_at")
            .in_("id", current_version_ids)
            .execute()
            .data
        )
        source_rows = (
            db.table("wiki_page_sources")
            .select("wiki_version_id, document_version_id, citation_order")
            .in_("wiki_version_id", current_version_ids)
            .order("citation_order")
            .execute()
            .data
        )
    except Exception as exc:  # pragma: no cover - defensive wrapper
        raise WikiSearchError("Failed to load wiki versions or sources.") from exc

    versions_by_id = {str(row["id"]): dict(row) for row in version_rows}
    source_ids_by_version = _group_source_document_version_ids(source_rows)
    query_terms = _prepare_query_terms(request)
    if not query_terms:
        return []

    results: list[WikiSearchResult] = []
    for page_row in page_rows:
        page_id = str(page_row["id"])
        version_id = page_row.get("current_version_id")
        if version_id is None:
            continue
        version = versions_by_id.get(str(version_id))
        if version is None:
            continue

        try:
            markdown_bytes = db.storage.from_(storage_bucket).download(version["markdown_object_key"])
        except Exception as exc:  # pragma: no cover - defensive wrapper
            raise WikiSearchError(f"Failed to download wiki markdown for page {page_id}.") from exc

        content = markdown_bytes.decode("utf-8")
        score_card = _score_page(
            title=str(page_row["title"]),
            content=content,
            query_terms=query_terms,
        )
        if score_card is None:
            continue

        results.append(
            WikiSearchResult(
                wiki_page_id=page_id,
                wiki_version_id=str(version["id"]),
                workspace_id=str(page_row["workspace_id"]),
                title=str(page_row["title"]),
                content=content,
                score=score_card["score"],
                updated_at=page_row.get("updated_at") or version.get("created_at"),
                source_document_version_ids=source_ids_by_version.get(str(version["id"]), []),
            )
        )

    results.sort(key=lambda item: item.wiki_page_id)
    results.sort(
        key=lambda item: item.updated_at.isoformat() if item.updated_at is not None else "",
        reverse=True,
    )
    results.sort(
        key=lambda item: _overlap_count(_tokenize_search_text(item.title), set(query_terms)),
        reverse=True,
    )
    results.sort(key=lambda item: item.score, reverse=True)
    return results[: request.limit]


def _prepare_query_terms(request: WikiSearchRequest) -> tuple[str, ...]:
    prepared: list[str] = []
    seen: set[str] = set()
    for term in request.query_terms:
        normalized_term = _normalize_search_text(term)
        if not normalized_term:
            continue
        if normalized_term in seen:
            continue
        prepared.append(normalized_term)
        seen.add(normalized_term)

    if prepared:
        return tuple(prepared)

    if request.query is None:
        return ()

    return tuple(_tokenize_search_text(request.query))


def _group_source_document_version_ids(rows: Iterable[dict[str, object]]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
    for row in rows:
        version_id = str(row["wiki_version_id"])
        document_version_id = str(row["document_version_id"])
        if version_id not in grouped:
            grouped[version_id] = []
            seen[version_id] = set()
        if document_version_id in seen[version_id]:
            continue
        grouped[version_id].append(document_version_id)
        seen[version_id].add(document_version_id)
    return grouped


def _score_page(
    *,
    title: str,
    content: str,
    query_terms: tuple[str, ...],
) -> dict[str, float] | None:
    title_tokens = _tokenize_search_text(title)
    body_tokens = _tokenize_search_text(content)
    query_token_set = set(query_terms)
    if not query_token_set:
        return None

    title_overlap = _overlap_count(title_tokens, query_token_set)
    body_overlap = _overlap_count(body_tokens, query_token_set)
    total_overlap = len((title_tokens | body_tokens) & query_token_set)
    if total_overlap == 0:
        return None

    query_size = len(query_token_set)
    title_overlap_score = title_overlap / query_size
    body_overlap_score = body_overlap / query_size
    query_coverage_score = total_overlap / query_size
    score = min(
        1.0,
        (title_overlap_score * 0.6)
        + (body_overlap_score * 0.3)
        + (query_coverage_score * 0.1),
    )
    return {
        "score": score,
    }


def _normalize_search_text(value: str | None) -> str:
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", value).lower()
    normalized = _URL_PATTERN.sub(" ", normalized)
    normalized = _NON_WORD_PATTERN.sub(" ", normalized)
    normalized = " ".join(normalized.split())
    return normalized.strip()


def _tokenize_search_text(value: str | None) -> set[str]:
    normalized = _normalize_search_text(value)
    if not normalized:
        return set()

    tokens: set[str] = set()
    for token in normalized.split():
        if len(token) > 1 or any(character.isdigit() for character in token):
            tokens.add(token)
    return tokens


def _overlap_count(tokens: set[str], query_terms: set[str]) -> int:
    return len(tokens & query_terms)

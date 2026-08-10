"""
Public Wiki contracts shared by Agent and Report layers.

The command functions are implemented in `service.py`.
The query functions are implemented in `query.py`.
The report-side search port is implemented in `repository.py`.

Keep the existing DTO field names stable because other modules consume them
directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from supabase import Client

from .models import WikiSearchRequest, WikiSearchResult
from .repository import search_wiki_contexts as _search_wiki_contexts

PageType = Literal[
    "industry", "company", "technology", "supply_chain", "policy", "market", "issue", "term"
]
SupportType = Literal["supports", "contradicts", "context"]
ValidationStatus = Literal["pending", "passed", "failed"]
ReviewDecision = Literal["approved", "rejected"]


@dataclass(frozen=True)
class WikiSourceInput:
    """Input row for `wiki_page_sources`."""

    claim_text: str
    document_version_id: Optional[str] = None
    source_url: Optional[str] = None
    source_title: Optional[str] = None
    published_at: Optional[str] = None
    source_start_line: Optional[int] = None
    source_end_line: Optional[int] = None
    support_type: SupportType = "supports"
    citation_order: Optional[int] = None


@dataclass(frozen=True)
class WikiDraftInput:
    """Single input DTO for creating a wiki version draft."""

    workspace_id: str
    slug: str
    title: str
    page_type: PageType
    markdown: str
    sources: list[WikiSourceInput]
    change_summary: Optional[str] = None
    parent_page_id: Optional[str] = None
    created_by: Optional[str] = None
    generated_by: Literal["human", "llm"] = "llm"
    generator_model: Optional[str] = None
    generator_prompt_version: Optional[str] = None
    generation_run_id: Optional[str] = None
    page_reliability_score: Optional[int] = None
    page_reliability_level: Optional[str] = None
    page_reliability_detail: Optional[dict] = None


@dataclass(frozen=True)
class WikiPageSummary:
    """Item returned from `list_published_wiki_pages()`."""

    id: str
    slug: str
    title: str
    page_type: str
    status: str
    parent_page_id: Optional[str]
    published_at: Optional[str]


@dataclass(frozen=True)
class WikiVersionSummary:
    """Item returned from the wiki version history list."""

    id: str
    version_no: int
    change_summary: Optional[str]
    created_at: str


@dataclass(frozen=True)
class WikiSource:
    """Traceable source attached to a wiki claim."""

    document_version_id: Optional[str]
    citation_order: Optional[int]
    claim_text: Optional[str]
    support_type: Optional[str]
    source_start_line: Optional[int]
    source_end_line: Optional[int]
    document_title: Optional[str] = None
    source_name: Optional[str] = None
    canonical_url: Optional[str] = None
    published_at: Optional[str] = None
    reliability_score: Optional[int] = None


@dataclass(frozen=True)
class WikiRelatedPage:
    """Another published wiki page that shares evidence with the current one."""

    page_id: str
    slug: str
    title: str
    page_type: str
    shared_source_count: int


@dataclass(frozen=True)
class WikiPageContent:
    """Published wiki page detail payload."""

    page_id: str
    slug: str
    title: str
    page_type: str
    published_at: Optional[str]
    version_id: str
    version_no: int
    markdown: str
    change_summary: Optional[str]
    confidence_score: Optional[float]
    validation_status: str
    review_status: str
    generated_by: str
    generator_model: Optional[str]
    created_at: str
    sources: tuple[WikiSource, ...]
    versions: tuple[WikiVersionSummary, ...]
    related_pages: tuple[WikiRelatedPage, ...] = ()


def upsert_wiki_page(
    workspace_id: str,
    slug: str,
    title: str,
    page_type: PageType,
    parent_page_id: Optional[str] = None,
    *,
    supabase: Client | None = None,
) -> str:
    """Find or create a wiki page by slug and return its id."""

    from .service import upsert_wiki_page as _impl

    return _impl(workspace_id, slug, title, page_type, parent_page_id, supabase=supabase)


def update_wiki_page_title(page_id: str, title: str, *, supabase: Client | None = None) -> None:
    """Overwrite an existing page's title (upsert_wiki_page never does, by design)."""

    from .service import update_wiki_page_title as _impl

    return _impl(page_id, title, supabase=supabase)


def create_wiki_version(draft: WikiDraftInput, *, supabase: Client | None = None) -> str:
    """
    Create a new wiki version draft.

    This must not mutate `current_version_id`.
    """

    from .service import create_wiki_version as _impl

    return _impl(draft, supabase=supabase)


def add_wiki_version(
    page_id: str,
    markdown: str,
    change_summary: str,
    sources: list[WikiSourceInput],
    created_by: Optional[str] = None,
) -> str:
    """
    Backward-compatible write entry point expected by existing Agent and tests.

    The newer write contract uses `create_wiki_version()` with `WikiDraftInput`.
    This legacy function remains exported so older callers fail predictably
    instead of breaking at import time.
    """

    raise NotImplementedError


def record_wiki_validation(
    version_id: str,
    validation_status: ValidationStatus,
    confidence_score: Optional[float],
    *,
    supabase: Client | None = None,
) -> None:
    """Record validation status and confidence score."""

    from .service import record_wiki_validation as _impl

    return _impl(version_id, validation_status, confidence_score, supabase=supabase)


def review_wiki_version(
    version_id: str,
    reviewer_id: Optional[str],
    decision: ReviewDecision,
    *,
    supabase: Client | None = None,
) -> None:
    """Record the review result without publishing the version.

    reviewer_id=None means an automated (non-human) approval — used by the
    wiki auto-generation pipeline. reviewed_by is stored as NULL in that case.
    """

    from .service import review_wiki_version as _impl

    return _impl(version_id, reviewer_id, decision, supabase=supabase)


def publish_wiki_version(page_id: str, version_id: str, *, supabase: Client | None = None) -> None:
    """Publish an approved and validated wiki version."""

    from .service import publish_wiki_version as _impl

    return _impl(page_id, version_id, supabase=supabase)


def request_wiki_index(
    wiki_version_id: str,
    collection_name: str,
    requested_by: Optional[str] = None,
) -> str:
    """Create a QMD indexing job and return the job id."""

    from .service import request_wiki_index as _impl

    return _impl(wiki_version_id, collection_name, requested_by)


def list_published_wiki_pages(
    workspace_id: str,
    page_type: Optional[PageType] = None,
    query: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[WikiPageSummary]:
    """Return published wiki pages for a workspace."""

    from .query import list_published_wiki_pages as _impl

    return _impl(workspace_id, page_type=page_type, query=query, limit=limit, offset=offset)


def get_published_wiki_page(
    workspace_id: str,
    slug: str,
) -> Optional[WikiPageContent]:
    """Return a published wiki page detail payload."""

    from .query import get_published_wiki_page as _impl

    return _impl(workspace_id, slug)


def list_wiki_versions(
    workspace_id: str,
    page_id: str,
) -> list[WikiVersionSummary]:
    """Return wiki version history for a page."""

    from .query import list_wiki_versions as _impl

    return _impl(workspace_id, page_id)


def search_wiki_contexts(
    request: WikiSearchRequest,
    *,
    supabase: Client | None = None,
) -> list[WikiSearchResult]:
    """Return report-side wiki search results."""

    return _search_wiki_contexts(request, supabase=supabase)

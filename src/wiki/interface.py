"""
`src/agent/wiki_tools.py` consumes this module's write-side contract directly.
Keep the existing dataclass field names and write function signatures stable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from supabase import Client

from .models import WikiSearchRequest, WikiSearchResult
from .repository import search_wiki_contexts as _search_wiki_contexts


@dataclass
class WikiSourceInput:
    document_version_id: str
    claim_text: str
    source_start_line: Optional[int] = None
    source_end_line: Optional[int] = None
    support_type: str = "supports"


def upsert_wiki_page(
    workspace_id: str, slug: str, title: str, page_type: str
) -> str:
    """Find or create a wiki page by slug and return its id."""
    raise NotImplementedError


def add_wiki_version(
    page_id: str,
    markdown: str,
    change_summary: str,
    sources: list[WikiSourceInput],
    created_by: Optional[str] = None,
) -> str:
    """
    Add a new wiki_page_versions row without mutating historical versions.
    - Upload markdown to Storage and persist markdown_object_key
    - Persist sources to wiki_page_sources
    - Update wiki_pages.current_version_id to the new version
    Return the new wiki_page_versions.id.
    """
    raise NotImplementedError


def search_wiki_contexts(
    request: WikiSearchRequest,
    *,
    supabase: Client | None = None,
) -> list[WikiSearchResult]:
    return _search_wiki_contexts(request, supabase=supabase)

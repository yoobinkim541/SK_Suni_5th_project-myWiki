"""
게시된 Wiki 조회 모듈 — Agent·Report 공용.

조회 조건:
  wiki_pages.status = 'published'
  wiki_page_versions.validation_status = 'passed'
  wiki_page_versions.review_status = 'approved'

SERVICE_ROLE_KEY 를 사용하며, 모든 쿼리에 workspace_id 필터를 명시한다.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from supabase import Client, create_client

from .interface import (
    PageType,
    WikiPageContent,
    WikiPageSummary,
    WikiSource,
    WikiVersionSummary,
)

WIKI_BUCKET = "wiki"


@lru_cache(maxsize=1)
def _get_client() -> Client:
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )


def list_published_wiki_pages(
    workspace_id: str,
    page_type: Optional[PageType] = None,
    query: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[WikiPageSummary]:
    db = _get_client()
    q = (
        db.table("wiki_pages")
        .select("id, slug, title, page_type, status, parent_page_id, published_at")
        .eq("workspace_id", workspace_id)
        .eq("status", "published")
    )
    if page_type:
        q = q.eq("page_type", page_type)
    if query:
        q = q.ilike("title", f"%{query}%")
    res = q.limit(limit).offset(offset).execute()
    return [WikiPageSummary(**row) for row in res.data]


def get_published_wiki_page(
    workspace_id: str,
    slug: str,
) -> Optional[WikiPageContent]:
    db = _get_client()

    page_res = (
        db.table("wiki_pages")
        .select("id, slug, title, page_type, status, current_version_id, published_at")
        .eq("workspace_id", workspace_id)
        .eq("slug", slug)
        .eq("status", "published")
        .maybe_single()
        .execute()
    )
    if not page_res.data or not page_res.data.get("current_version_id"):
        return None

    page = page_res.data
    version_id = page["current_version_id"]

    version_res = (
        db.table("wiki_page_versions")
        .select(
            "id, version_no, markdown_object_key, change_summary, confidence_score,"
            " validation_status, review_status, generated_by, generator_model, created_at"
        )
        .eq("id", version_id)
        .eq("validation_status", "passed")
        .eq("review_status", "approved")
        .maybe_single()
        .execute()
    )
    if not version_res.data:
        return None

    version = version_res.data
    markdown_bytes = db.storage.from_(WIKI_BUCKET).download(version["markdown_object_key"])
    markdown = markdown_bytes.decode("utf-8")

    sources_res = (
        db.table("wiki_page_sources")
        .select(
            "document_version_id, citation_order, claim_text,"
            " support_type, source_start_line, source_end_line"
        )
        .eq("wiki_version_id", version_id)
        .order("citation_order")
        .execute()
    )
    sources = tuple(WikiSource(**row) for row in sources_res.data)

    versions_res = (
        db.table("wiki_page_versions")
        .select("id, version_no, change_summary, created_at")
        .eq("page_id", page["id"])
        .order("version_no", desc=True)
        .execute()
    )
    versions = tuple(WikiVersionSummary(**row) for row in versions_res.data)

    return WikiPageContent(
        page_id=page["id"],
        slug=page["slug"],
        title=page["title"],
        page_type=page["page_type"],
        published_at=page.get("published_at"),
        version_id=version["id"],
        version_no=version["version_no"],
        markdown=markdown,
        change_summary=version.get("change_summary"),
        confidence_score=version.get("confidence_score"),
        validation_status=version["validation_status"],
        review_status=version["review_status"],
        generated_by=version["generated_by"],
        generator_model=version.get("generator_model"),
        created_at=version["created_at"],
        sources=sources,
        versions=versions,
    )


def list_wiki_versions(
    workspace_id: str,
    page_id: str,
) -> list[WikiVersionSummary]:
    db = _get_client()
    page_check = (
        db.table("wiki_pages")
        .select("id")
        .eq("id", page_id)
        .eq("workspace_id", workspace_id)
        .maybe_single()
        .execute()
    )
    if not page_check.data:
        return []

    res = (
        db.table("wiki_page_versions")
        .select("id, version_no, change_summary, created_at")
        .eq("page_id", page_id)
        .order("version_no", desc=True)
        .execute()
    )
    return [WikiVersionSummary(**row) for row in res.data]

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

from ..categories.keywords import CATEGORY_KEYWORDS
from .interface import (
    PageType,
    WikiPageContent,
    WikiPageSummary,
    WikiRelatedPage,
    WikiSource,
    WikiVersionSummary,
)

WIKI_BUCKET = "wiki"
RELATED_PAGES_LIMIT = 5


@lru_cache(maxsize=1)
def _get_client() -> Client:
    # SUPABASE_SERVICE_ROLE_KEY(구 명명) 또는 SUPABASE_SECRET_KEY(신 명명) 둘 다 지원
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ["SUPABASE_SECRET_KEY"]
    return create_client(os.environ["SUPABASE_URL"], key)


def list_published_wiki_pages(
    workspace_id: str,
    page_type: Optional[PageType] = None,
    query: Optional[str] = None,
    keyword: Optional[str] = None,
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
    if keyword:
        keyword_res = db.table("wiki_page_keywords").select("page_id").eq("keyword", keyword).execute()
        matching_page_ids = [row["page_id"] for row in keyword_res.data]
        if not matching_page_ids:
            return []
        q = q.in_("id", matching_page_ids)
    res = q.order("published_at", desc=True).limit(limit).offset(offset).execute()
    return [WikiPageSummary(**row) for row in res.data]


def list_keyword_catalog() -> list[dict]:
    """카테고리 키워드 사전 전체를 {word, category} 형태로 평탄화한다.

    실사용 여부와 무관한 고정 카탈로그 — 프론트가 본문 키워드 하이라이트/집계에 쓴다.
    DB 조회 없음(워크스페이스 무관, 항상 같은 값).
    """
    return [
        {"word": word, "category": category}
        for category, words in CATEGORY_KEYWORDS.items()
        for word in words
    ]


def _enrich_sources(db: Client, workspace_id: str, rows: list[dict]) -> tuple[WikiSource, ...]:
    """
    wiki_page_sources 원본 행에 문서 제목·매체명·게시일·개별 신뢰도를 붙인다.

    PostgREST embedded join 대신 순차 조회를 쓴다(이 모듈·generation_repository.py의
    기존 관례) — document_version_id -> document_versions.document_id -> documents
    (title/canonical_url/published_at/source_id) -> sources.name, 그리고 별도로
    document_analysis_results.reliability_score. 화면의 "평균 신뢰도"는 여기서
    평균 내지 않고 개별 점수만 내려준다 — "근거 문서 건수"처럼 프론트에서
    배열 기준으로 계산하게 둔다(집계 로직이 백엔드/프론트 두 곳에 흩어지지 않게).
    """
    if not rows:
        return tuple()

    document_version_ids = list({row["document_version_id"] for row in rows})

    versions_res = (
        db.table("document_versions")
        .select("id, document_id")
        .in_("id", document_version_ids)
        .execute()
    )
    document_id_by_version = {row["id"]: row["document_id"] for row in versions_res.data}

    document_ids = list({doc_id for doc_id in document_id_by_version.values() if doc_id})
    documents_by_id: dict[str, dict] = {}
    if document_ids:
        documents_res = (
            db.table("documents")
            .select("id, title, canonical_url, published_at, source_id")
            .eq("workspace_id", workspace_id)
            .in_("id", document_ids)
            .execute()
        )
        documents_by_id = {row["id"]: row for row in documents_res.data}

    source_ids = list({row["source_id"] for row in documents_by_id.values() if row.get("source_id")})
    source_name_by_id: dict[str, str] = {}
    if source_ids:
        sources_res = (
            db.table("sources")
            .select("id, name")
            .eq("workspace_id", workspace_id)
            .in_("id", source_ids)
            .execute()
        )
        source_name_by_id = {row["id"]: row["name"] for row in sources_res.data}

    analysis_res = (
        db.table("document_analysis_results")
        .select("document_version_id, reliability_score")
        .eq("workspace_id", workspace_id)
        .in_("document_version_id", document_version_ids)
        .execute()
    )
    reliability_by_version = {
        row["document_version_id"]: row["reliability_score"]
        for row in analysis_res.data
        if row.get("reliability_score") is not None
    }

    enriched = []
    for row in rows:
        document_id = document_id_by_version.get(row["document_version_id"])
        document = documents_by_id.get(document_id) if document_id else None
        enriched.append(
            WikiSource(
                document_version_id=row["document_version_id"],
                citation_order=row.get("citation_order"),
                claim_text=row.get("claim_text"),
                support_type=row.get("support_type"),
                source_start_line=row.get("source_start_line"),
                source_end_line=row.get("source_end_line"),
                document_title=document.get("title") if document else None,
                canonical_url=document.get("canonical_url") if document else None,
                published_at=document.get("published_at") if document else None,
                source_name=source_name_by_id.get(document.get("source_id")) if document else None,
                reliability_score=reliability_by_version.get(row["document_version_id"]),
            )
        )
    return tuple(enriched)


def _get_related_pages(
    db: Client,
    workspace_id: str,
    current_page_id: str,
    current_version_id: str,
    document_version_ids: list[str],
    limit: int = RELATED_PAGES_LIMIT,
) -> tuple[WikiRelatedPage, ...]:
    """
    같은 원문(document_version_id)을 근거로 인용하는 다른 위키를 찾는다.

    별도 관계 테이블 없이 wiki_page_sources만으로 조회 시점에 계산한다:
    1) 이 문서들을 인용하는 다른 wiki_version_id를 찾고
    2) wiki_version_id별 공유 document_version_id를 집합으로 모아 중복 인용을 1건으로 셈
    3) 그 wiki_version_id가 실제로 어떤 위키의 "현재 게시 버전"인지 확인한다
       (수정으로 밀려난 구버전은 여기서 자연히 제외됨)
    4) 공유 건수 내림차순으로 상위 limit개만 반환
    """
    if not document_version_ids:
        return tuple()

    shared_res = (
        db.table("wiki_page_sources")
        .select("wiki_version_id, document_version_id")
        .in_("document_version_id", document_version_ids)
        .neq("wiki_version_id", current_version_id)
        .execute()
    )
    shared_docs_by_version: dict[str, set[str]] = {}
    for row in shared_res.data:
        shared_docs_by_version.setdefault(row["wiki_version_id"], set()).add(
            row["document_version_id"]
        )
    if not shared_docs_by_version:
        return tuple()

    pages_res = (
        db.table("wiki_pages")
        .select("id, slug, title, page_type, current_version_id")
        .eq("workspace_id", workspace_id)
        .eq("status", "published")
        .neq("id", current_page_id)
        .in_("current_version_id", list(shared_docs_by_version.keys()))
        .execute()
    )

    related = [
        WikiRelatedPage(
            page_id=row["id"],
            slug=row["slug"],
            title=row["title"],
            page_type=row["page_type"],
            shared_source_count=len(shared_docs_by_version[row["current_version_id"]]),
        )
        for row in pages_res.data
    ]
    related.sort(key=lambda r: r.shared_source_count, reverse=True)
    return tuple(related[:limit])


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
    page = page_res.data if page_res else None
    if not page or not page.get("current_version_id"):
        return None

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
    version = version_res.data if version_res else None
    if not version:
        return None

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
    sources = _enrich_sources(db, workspace_id, sources_res.data)

    versions_res = (
        db.table("wiki_page_versions")
        .select("id, version_no, change_summary, created_at")
        .eq("page_id", page["id"])
        .order("version_no", desc=True)
        .execute()
    )
    versions = tuple(WikiVersionSummary(**row) for row in versions_res.data)

    related_pages = _get_related_pages(
        db,
        workspace_id,
        page["id"],
        version_id,
        [s.document_version_id for s in sources],
    )

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
        related_pages=related_pages,
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
    if not page_check or not page_check.data:
        return []

    res = (
        db.table("wiki_page_versions")
        .select("id, version_no, change_summary, created_at")
        .eq("page_id", page_id)
        .order("version_no", desc=True)
        .execute()
    )
    return [WikiVersionSummary(**row) for row in res.data]

from __future__ import annotations

import logging

from supabase import Client

from ..analysis.repository import get_supabase
from .citation_text import strip_orphaned_citation_markers
from .interface import (
    WikiDraftInput,
    WikiSourceInput,
    create_wiki_version,
    publish_wiki_version,
    record_wiki_validation,
    review_wiki_version,
)
from .query import get_published_wiki_page

logger = logging.getLogger(__name__)


def clean_orphaned_citations_for_workspace(
    workspace_id: str,
    *,
    supabase: Client | None = None,
) -> list[str]:
    """워크스페이스의 published 위키 페이지를 훑어, 본문의 [N] 각주가 실제 근거
    개수보다 많은 페이지를 찾아 죽은 각주를 제거한 새 버전으로 정리한다.

    이미 저장된 문서에 이 문제가 있었던 이유(agent/core.py의 submit_answer가
    본문 각주 개수와 citations 개수 대응을 강제하지 않았던 것)는 코드 가드로
    막았지만(strip_orphaned_citation_markers), 그 전에 이미 저장된 문서는 소급
    적용되지 않으므로 이 배치로 한 번 정리한다.

    실제로 정리된 페이지의 slug 목록을 반환한다(변경 없으면 빈 리스트).
    """
    db = supabase or get_supabase()
    pages = (
        db.table("wiki_pages")
        .select("slug, parent_page_id")
        .eq("workspace_id", workspace_id)
        .eq("status", "published")
        .execute()
        .data
    )

    cleaned_slugs: list[str] = []
    for row in pages:
        slug = row["slug"]
        parent_page_id = str(row["parent_page_id"]) if row.get("parent_page_id") else None

        content = get_published_wiki_page(workspace_id, slug)
        if content is None:
            continue

        cleaned_markdown = strip_orphaned_citation_markers(content.markdown, len(content.sources))
        if cleaned_markdown == content.markdown:
            continue

        draft = WikiDraftInput(
            workspace_id=workspace_id,
            slug=content.slug,
            title=content.title,
            page_type=content.page_type,
            parent_page_id=parent_page_id,
            markdown=cleaned_markdown,
            sources=[
                WikiSourceInput(
                    document_version_id=source.document_version_id,
                    source_url=source.canonical_url,
                    source_title=source.document_title,
                    published_at=source.published_at,
                    claim_text=source.claim_text or "",
                    source_start_line=source.source_start_line,
                    source_end_line=source.source_end_line,
                    support_type=source.support_type or "supports",
                    citation_order=source.citation_order,
                )
                for source in content.sources
            ],
            change_summary="본문의 죽은 각주(실제 근거 없는 [N]) 정리",
            generated_by="llm",
        )
        version_id = create_wiki_version(draft, supabase=db)
        record_wiki_validation(version_id, "passed", None, supabase=db)
        review_wiki_version(version_id, None, "approved", supabase=db)
        publish_wiki_version(content.page_id, version_id, supabase=db)

        cleaned_slugs.append(slug)
        logger.info("wiki_citation_cleanup_applied", extra={"slug": slug})

    return cleaned_slugs

from __future__ import annotations

import logging

from supabase import Client

from ..analysis.repository import get_supabase
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


def _has_duplicate_document(sources) -> bool:
    document_ids = [source.document_version_id for source in sources]
    return len(document_ids) != len(set(document_ids))


def clean_duplicate_sources_for_workspace(
    workspace_id: str,
    *,
    supabase: Client | None = None,
) -> list[str]:
    """워크스페이스의 published 위키 페이지를 훑어, 같은 document_version_id가
    wiki_page_sources에 여러 행으로 중복 저장된 페이지를 찾아 재발행으로 정리한다.

    원인(수정 완료): service.py의 _build_source_rows()가 완전히 같은 행만 중복으로
    간주해서, 같은 문서를 근거로 삼는 서로 다른 claim(예: 위키 중복 병합 배치가 두
    원본 페이지의 claim을 그대로 이어붙이는 경우)이 각각 별도 행으로 쌓였다 —
    프론트 "근거 문서" 목록에 같은 출처가 여러 장 뜨는 문제로 나타났다. 코드는
    문서당 한 행으로 합치도록 고쳤지만, 이미 발행된 문서에는 소급 적용되지 않으므로
    이 배치로 한 번 정리한다: 기존 content.sources를 그대로 다시 create_wiki_version()에
    넣으면(고쳐진) _build_source_rows()가 자동으로 문서당 한 행으로 합친다.

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

        if not _has_duplicate_document(content.sources):
            continue

        draft = WikiDraftInput(
            workspace_id=workspace_id,
            slug=content.slug,
            title=content.title,
            page_type=content.page_type,
            parent_page_id=parent_page_id,
            markdown=content.markdown,
            sources=[
                WikiSourceInput(
                    document_version_id=source.document_version_id,
                    claim_text=source.claim_text or "",
                    source_start_line=source.source_start_line,
                    source_end_line=source.source_end_line,
                    support_type=source.support_type or "supports",
                    citation_order=source.citation_order,
                )
                for source in content.sources
            ],
            change_summary="같은 문서를 중복 참조하던 출처 행을 문서당 한 행으로 정리",
            generated_by="llm",
        )
        version_id = create_wiki_version(draft, supabase=db)
        record_wiki_validation(version_id, "passed", None, supabase=db)
        review_wiki_version(version_id, None, "approved", supabase=db)
        publish_wiki_version(content.page_id, version_id, supabase=db)

        cleaned_slugs.append(slug)
        logger.info("wiki_duplicate_source_cleanup_applied", extra={"slug": slug})

    return cleaned_slugs

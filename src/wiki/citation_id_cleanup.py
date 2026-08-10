from __future__ import annotations

import logging
import re
from datetime import datetime

from supabase import Client

from ..analysis.repository import get_supabase
from .interface import (
    WikiDraftInput,
    WikiSource,
    WikiSourceInput,
    create_wiki_version,
    publish_wiki_version,
    record_wiki_validation,
    review_wiki_version,
)
from .query import get_published_wiki_page

logger = logging.getLogger(__name__)

# 발행된 페이지에서 실제로 관찰된 형태가 제각각이다(결정론적 이슈 페이지 생성 코드의
# "- {evidence} (document_version_id=X)"뿐 아니라, LLM이 자유 형식으로 쓴 토픽·dedup
# 병합 페이지의 "N. document_version_id=X: {evidence} (citation_order=N)",
# "- [N] document_version_id=X" 등) — 그래서 줄 전체를 고정된 틀로 파싱하는 대신,
# "document_version_id=<id>"라는 토큰 자체만 찾아 사람이 읽을 수 있는 표기로 치환한다.
# 바로 뒤에 ", citation_order=N" 또는 " citation_order=N"이 붙어 있으면 같이 지운다.
_RAW_CITATION_TOKEN = re.compile(
    r"document_version_id=(?P<doc_id>[^\s,\)\]:]+)(?:,?\s*citation_order=\d+)?"
)
# 위 치환 후에도 document_version_id에 안 붙어 있던 독립된 "(citation_order=N)"이
# 남을 수 있어(예: "... (document_version_id=X: 텍스트 (citation_order=N)") 별도로 정리한다.
_TRAILING_CITATION_ORDER = re.compile(r"\s*\(\s*citation_order=\d+\s*\)")
_EMPTY_PARENS = re.compile(r"\(\s*\)")


def _format_citation_date(published_at: str | None) -> str:
    if not published_at:
        return ""
    try:
        parsed = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return parsed.strftime("%Y.%m.%d")


def _format_attribution(source: WikiSource | None) -> str:
    if source is None:
        return "출처 정보 확인 안 됨"
    parts = [
        part
        for part in (source.document_title, source.source_name, _format_citation_date(source.published_at))
        if part
    ]
    return " · ".join(parts) if parts else "출처 정보 확인 안 됨"


def rewrite_raw_citation_ids(markdown: str, sources: tuple[WikiSource, ...]) -> str:
    """본문에 남은 `document_version_id=...` 원문 노출을 제목·매체명·게시일 표기로
    바꾼다 (이슈 페이지 결정론적 생성 코드와, 토픽·dedup 병합 LLM이 자유 형식으로
    출처를 적을 때 과거 프롬프트가 이 형식을 그대로 보여준 탓에 모방한 문제 — 이미
    발행된 문서에 소급 적용하기 위한 순수 함수)."""
    sources_by_id = {source.document_version_id: source for source in sources}

    def _replace(match: re.Match[str]) -> str:
        return _format_attribution(sources_by_id.get(match.group("doc_id")))

    rewritten = _RAW_CITATION_TOKEN.sub(_replace, markdown)
    rewritten = _TRAILING_CITATION_ORDER.sub("", rewritten)
    rewritten = _EMPTY_PARENS.sub("", rewritten)
    return rewritten


def clean_raw_citation_ids_for_workspace(
    workspace_id: str,
    *,
    supabase: Client | None = None,
) -> list[str]:
    """워크스페이스의 published 위키 페이지를 훑어, 본문에 원문 document_version_id가
    그대로 노출된 페이지를 찾아 제목·매체명·게시일 표기로 정리한다.

    자동 생성된 이슈 페이지(src/wiki/generation.py `_build_issue_page_markdown`)의
    결정론적 버그와, 토픽·dedup 병합 LLM(generation_prompts.py/dedup_prompts.py)이
    과거 프롬프트에 노출됐던 "document_version_id=X citation_order=Y" 참조 형식을
    그대로 흉내 낸 문제 둘 다를 정리 대상으로 삼는다 — 생성 코드/프롬프트는 고쳤지만
    이미 발행된 페이지는 소급 적용되지 않으므로 이 배치로 한 번 정리한다.

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

        cleaned_markdown = rewrite_raw_citation_ids(content.markdown, content.sources)
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
            change_summary="본문 출처 표기를 원문 ID 대신 제목·매체명·게시일로 정리",
            generated_by="llm",
        )
        version_id = create_wiki_version(draft, supabase=db)
        record_wiki_validation(version_id, "passed", None, supabase=db)
        review_wiki_version(version_id, None, "approved", supabase=db)
        publish_wiki_version(content.page_id, version_id, supabase=db)

        cleaned_slugs.append(slug)
        logger.info("wiki_raw_citation_id_cleanup_applied", extra={"slug": slug})

    return cleaned_slugs

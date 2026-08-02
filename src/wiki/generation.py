from __future__ import annotations

import logging

from ..report.models import ReportSectionDraft
from .interface import (
    WikiDraftInput,
    WikiSourceInput,
    create_wiki_version,
    publish_wiki_version,
    record_wiki_validation,
    review_wiki_version,
    upsert_wiki_page,
)

logger = logging.getLogger(__name__)

AUTO_PUBLISH_CONFIDENCE_THRESHOLD = 0.6


def _build_issue_page_markdown(section: ReportSectionDraft) -> str:
    lines = [f"# {section.title}", "", "## 현재 상황", section.current_summary or "", ""]
    lines.append("## 핵심 사실")
    lines.extend(f"- {fact}" for fact in section.key_facts)
    lines.append("")
    lines.append("## 시사점")
    lines.extend(f"- {implication}" for implication in section.implications)
    lines.append("")
    lines.append("## 주시할 지점")
    lines.extend(f"- {watch_point}" for watch_point in section.watch_points)
    lines.append("")
    lines.append("## 출처")
    for citation in section.news_citations:
        lines.append(f"- {citation.evidence_text or ''} (document_version_id={citation.document_version_id})")
    return "\n".join(lines)


def _build_issue_page_sources(section: ReportSectionDraft) -> list[WikiSourceInput]:
    return [
        WikiSourceInput(
            document_version_id=citation.document_version_id,
            claim_text=citation.evidence_text or "",
            source_start_line=citation.source_start_line,
            source_end_line=citation.source_end_line,
            citation_order=citation.citation_order,
        )
        for citation in section.news_citations
    ]


def _generate_issue_page(
    section: ReportSectionDraft,
    *,
    workspace_id: str,
    requested_by: str | None,
    parent_page_id: str | None = None,
) -> tuple[str, str]:
    page_id = upsert_wiki_page(
        workspace_id,
        section.issue_key,
        section.title,
        "issue",
        parent_page_id,
    )
    draft = WikiDraftInput(
        workspace_id=workspace_id,
        slug=section.issue_key,
        title=section.title,
        page_type="issue",
        parent_page_id=parent_page_id,
        markdown=_build_issue_page_markdown(section),
        sources=_build_issue_page_sources(section),
        change_summary="리포트 파이프라인에서 자동 생성",
        created_by=requested_by,
        generated_by="llm",
    )
    version_id = create_wiki_version(draft)
    record_wiki_validation(version_id, "passed", None)
    review_wiki_version(version_id, None, "approved")
    publish_wiki_version(page_id, version_id)
    return page_id, version_id

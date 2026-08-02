from __future__ import annotations

import logging

from supabase import Client

from ..analysis.classifier import create_json_completion, get_openrouter_settings, parse_json_response
from ..report.models import EnrichedIssueGroup, ReportSectionDraft, WikiContext
from .generation_models import TopicPageCandidate, TopLevelTopicPage, WikiDraftGenerationResult, WikiPageIdentity, WikiTopicLLMResult
from .generation_prompts import WIKI_TOPIC_SYSTEM_PROMPT, build_wiki_topic_user_prompt
from .generation_repository import archive_wiki_page, find_stale_published_page_ids, get_wiki_page_identity, list_top_level_topic_pages
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


def _wiki_contexts_to_candidates(wiki_contexts: list[WikiContext]) -> list[TopicPageCandidate]:
    return [
        TopicPageCandidate(
            wiki_page_id=context.wiki_page_id,
            title=context.title,
            content=context.content,
            similarity_score=context.similarity_score,
        )
        for context in wiki_contexts
    ]


def _generate_topic_page(
    section: ReportSectionDraft,
    wiki_contexts: list[WikiContext],
    *,
    workspace_id: str,
    requested_by: str | None,
) -> tuple[str, str | None, str | None]:
    settings = get_openrouter_settings()
    candidates = _wiki_contexts_to_candidates(wiki_contexts)
    top_level_pages = list_top_level_topic_pages(workspace_id)

    response_text = create_json_completion(
        system_prompt=WIKI_TOPIC_SYSTEM_PROMPT,
        user_prompt=build_wiki_topic_user_prompt(
            section=section, candidates=candidates, top_level_pages=top_level_pages,
        ),
        model=settings.model,
    )
    payload = parse_json_response(response_text)
    result = WikiTopicLLMResult.model_validate(payload)

    if result.action == "skip" or not result.claims:
        return "skip", None, None

    sources = [
        WikiSourceInput(
            document_version_id=claim.document_version_id,
            claim_text=claim.claim_text,
            citation_order=claim.citation_order,
        )
        for claim in result.claims
    ]

    if result.action == "update_existing":
        if not result.target_wiki_page_id:
            return "skip", None, None
        # create_wiki_version()이 내부적으로 upsert_wiki_page()를 다시 실행하므로,
        # 기존 페이지의 실제 slug/title/page_type/parent_page_id를 그대로 넘겨
        # 같은 페이지로 멱등하게 귀결되도록 한다 (LLM은 update 시 이 값들을 안 줌).
        identity = get_wiki_page_identity(result.target_wiki_page_id)
        if identity is None:
            return "skip", None, None
        page_id = identity.page_id
        draft_slug = identity.slug
        draft_title = identity.title
        draft_page_type = identity.page_type
        draft_parent_page_id = identity.parent_page_id
    else:
        if not (result.slug and result.title and result.page_type):
            return "skip", None, None
        page_id = upsert_wiki_page(
            workspace_id, result.slug, result.title, result.page_type, result.parent_page_id,
        )
        draft_slug = result.slug
        draft_title = result.title
        draft_page_type = result.page_type
        draft_parent_page_id = result.parent_page_id

    draft = WikiDraftInput(
        workspace_id=workspace_id,
        slug=draft_slug,
        title=draft_title,
        page_type=draft_page_type,
        parent_page_id=draft_parent_page_id,
        markdown=result.markdown or "",
        sources=sources,
        change_summary=result.change_summary,
        created_by=requested_by,
        generated_by="llm",
    )
    version_id = create_wiki_version(draft)

    confidence = result.confidence_score
    if confidence is not None and confidence >= AUTO_PUBLISH_CONFIDENCE_THRESHOLD:
        record_wiki_validation(version_id, "passed", confidence)
        review_wiki_version(version_id, None, "approved")
        publish_wiki_version(page_id, version_id)
    else:
        record_wiki_validation(version_id, "pending", confidence)

    return result.action, page_id, version_id


def generate_wiki_drafts_for_sections(
    sections: list[ReportSectionDraft],
    enriched_groups: list[EnrichedIssueGroup],
    *,
    workspace_id: str,
    requested_by: str | None = None,
) -> list[WikiDraftGenerationResult]:
    """
    섹션별로 주제 페이지(Topic)를 먼저 생성하고, 그 결과를 이슈 페이지(Issue)의 parent_page_id로 연결한다.

    주제 페이지 생성 실패가 이슈 페이지 생성을 막지 않으며, 이슈 페이지 생성 실패도 다른 섹션 처리를 막지 않는다.
    (단계별 실패 격리)
    """
    wiki_contexts_by_issue_key = {
        group.issue_group.issue_key: group.wiki_contexts for group in enriched_groups
    }

    # 주제 페이지를 먼저 정해야 이슈 페이지의 parent_page_id로 연결할 수 있다.
    # (upsert_wiki_page는 ignore_duplicates=True라 기존 페이지의 parent_page_id를
    #  나중에 수정할 방법이 없으므로, 이슈 페이지를 처음 만들 때 값을 넣어야 한다.)
    results: list[WikiDraftGenerationResult] = []
    for section in sections:
        wiki_contexts = wiki_contexts_by_issue_key.get(section.issue_key, [])

        topic_action: str = "skip"
        topic_page_id: str | None = None
        topic_version_id: str | None = None
        topic_error: str | None = None
        try:
            topic_action, topic_page_id, topic_version_id = _generate_topic_page(
                section, wiki_contexts, workspace_id=workspace_id, requested_by=requested_by,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("wiki_topic_page_generation_failed", extra={"issue_key": section.issue_key})
            topic_action, topic_page_id, topic_version_id = "failed", None, None
            topic_error = str(exc)

        try:
            issue_page_id, issue_version_id = _generate_issue_page(
                section,
                workspace_id=workspace_id,
                requested_by=requested_by,
                parent_page_id=topic_page_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("wiki_issue_page_generation_failed", extra={"issue_key": section.issue_key})
            results.append(
                WikiDraftGenerationResult(
                    issue_key=section.issue_key,
                    issue_page_id="",
                    issue_version_id="",
                    topic_action=topic_action,
                    topic_page_id=topic_page_id,
                    topic_version_id=topic_version_id,
                    error_message=str(exc) if topic_error is None else f"{topic_error}; {exc}",
                )
            )
            continue

        results.append(
            WikiDraftGenerationResult(
                issue_key=section.issue_key,
                issue_page_id=issue_page_id,
                issue_version_id=issue_version_id,
                topic_action=topic_action,
                topic_page_id=topic_page_id,
                topic_version_id=topic_version_id,
                error_message=topic_error,
            )
        )

    return results


def archive_stale_wiki_pages(
    workspace_id: str,
    *,
    staleness_days: int = 90,
    supabase: Client | None = None,
) -> list[str]:
    stale_page_ids = find_stale_published_page_ids(
        workspace_id, staleness_days=staleness_days, supabase=supabase,
    )
    for page_id in stale_page_ids:
        archive_wiki_page(page_id, supabase=supabase)
    return stale_page_ids

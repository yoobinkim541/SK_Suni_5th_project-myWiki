from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from collections.abc import Callable

from pydantic import ValidationError
from supabase import Client

from ..analysis.classifier import create_json_completion, get_openrouter_settings, parse_json_response
from ..analysis.reliability_models import ReliabilityLevel
from ..report.candidate_provider import get_recently_analyzed_candidates
from ..report.composer import compose_report_sections
from ..report.grouper import group_report_candidates
from ..report.models import EnrichedIssueGroup, ReportCandidate, ReportSectionDraft, WikiContext
from ..report.selector import select_report_candidates
from ..report.wiki_context import enrich_issue_groups
from .generation_models import (
    IssuePageRewriteResult,
    TopicPageCandidate,
    TopLevelTopicPage,
    WikiDraftGenerationResult,
    WikiPageIdentity,
    WikiTopicLLMResult,
)
from .generation_prompts import (
    ISSUE_PAGE_REWRITE_SYSTEM_PROMPT,
    WIKI_TOPIC_SYSTEM_PROMPT,
    build_issue_page_rewrite_user_prompt,
    build_wiki_topic_user_prompt,
)
from .generation_repository import (
    archive_wiki_page,
    filter_to_topic_page_ids,
    find_matching_issue_page,
    find_stale_published_page_ids,
    get_wiki_page_identity,
    list_top_level_topic_pages,
)
from .interface import (
    WikiDraftInput,
    WikiSourceInput,
    create_wiki_version,
    publish_wiki_version,
    record_wiki_validation,
    review_wiki_version,
    search_wiki_contexts,
    upsert_wiki_page,
)
from .text_similarity import is_duplicate_title
from ..notifications.service import send_wiki_notification

logger = logging.getLogger(__name__)

# (system_prompt, user_prompt, model) -> raw JSON 문자열.
# src/report/composer.py의 llm_client 주입 패턴과 같은 형태의 호출 가능 객체다.
WikiTopicLLMClient = Callable[[str, str, str | None], str]


def build_evidence_text_map(enriched_groups: list[EnrichedIssueGroup]) -> dict[str, dict[str, str]]:
    """issue_key -> {document_version_id: 근거 텍스트} 맵을 만든다.

    `ReportCitationDraft.evidence_text`는 composer가 채우지 않으므로(항상 None),
    실제로 채워져 있는 `ReportCandidate.summary`(없으면 `title`)를 근거 텍스트로 쓴다.
    """
    mapping: dict[str, dict[str, str]] = {}
    for group in enriched_groups:
        texts: dict[str, str] = {}
        for candidate in group.issue_group.candidates:
            text = (candidate.summary or candidate.title or "").strip()
            if not text:
                continue
            texts.setdefault(candidate.document_version_id, text)
        mapping[group.issue_group.issue_key] = texts
    return mapping


def _resolve_evidence_text(
    evidence_texts: dict[str, str] | None,
    document_version_id: str,
    fallback: str | None = None,
) -> str:
    """근거 텍스트 조회. 맵에 없으면 fallback, 그것도 없으면 빈 문자열(예외 없음)."""
    if evidence_texts:
        text = evidence_texts.get(document_version_id)
        if text:
            return text
    return fallback or ""


def build_citation_attribution_map(
    enriched_groups: list[EnrichedIssueGroup],
) -> dict[str, dict[str, ReportCandidate]]:
    """issue_key -> {document_version_id: 원문 후보} 맵을 만든다.

    `_build_issue_page_markdown`의 "## 출처" 절에서 document_version_id를 그대로
    노출하는 대신 매체명·게시일로 사람이 읽을 수 있게 표시하는 데 쓴다.
    """
    mapping: dict[str, dict[str, ReportCandidate]] = {}
    for group in enriched_groups:
        by_version: dict[str, ReportCandidate] = {}
        for candidate in group.issue_group.candidates:
            by_version.setdefault(candidate.document_version_id, candidate)
        mapping[group.issue_group.issue_key] = by_version
    return mapping


def _format_citation_date(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime("%Y.%m.%d")


def _format_citation_attribution(candidate: ReportCandidate | None) -> str:
    """WikiPage.jsx 사이드바 "근거 출처"와 같은 표기(매체명 · 날짜)로 맞춘다."""
    if candidate is None:
        return ""
    parts = [part for part in (candidate.source_name, _format_citation_date(candidate.published_at)) if part]
    return f" · {' · '.join(parts)}" if parts else ""


def _build_issue_page_markdown(
    section: ReportSectionDraft,
    evidence_texts: dict[str, str] | None = None,
    citation_attribution: dict[str, ReportCandidate] | None = None,
) -> str:
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
        evidence = _resolve_evidence_text(
            evidence_texts, citation.document_version_id, citation.evidence_text,
        )
        candidate = (citation_attribution or {}).get(citation.document_version_id)
        lines.append(f"- {evidence}{_format_citation_attribution(candidate)}")
    return "\n".join(lines)


def _build_issue_page_sources(
    section: ReportSectionDraft,
    evidence_texts: dict[str, str] | None = None,
) -> list[WikiSourceInput]:
    return [
        WikiSourceInput(
            document_version_id=citation.document_version_id,
            claim_text=_resolve_evidence_text(
                evidence_texts, citation.document_version_id, citation.evidence_text,
            ),
            source_start_line=citation.source_start_line,
            source_end_line=citation.source_end_line,
            citation_order=citation.citation_order,
        )
        for citation in section.news_citations
    ]


def _rewrite_issue_page_content(
    section: ReportSectionDraft,
    evidence_texts: dict[str, str] | None = None,
    *,
    llm_client: WikiTopicLLMClient | None = None,
) -> ReportSectionDraft:
    """이슈 페이지 본문 4개 필드(현재상황/핵심사실/시사점/주시할지점)를 LLM으로 다듬는다.

    실패(LLM 오류·잘못된 JSON·빈 필드)하면 원본 section을 그대로 반환한다 — 이슈 페이지는
    지금까지 LLM 없이도 항상 생성에 성공했으므로, 이 재작성 단계가 그 신뢰성을 깨서는 안 된다.
    "## 출처" 섹션(_build_issue_page_sources)은 여기서 건드리는 4개 필드와 무관해 영향받지 않는다.
    """
    settings = get_openrouter_settings()
    user_prompt = build_issue_page_rewrite_user_prompt(section, evidence_texts)
    try:
        if llm_client is not None:
            response_text = llm_client(ISSUE_PAGE_REWRITE_SYSTEM_PROMPT, user_prompt, settings.model)
        else:
            response_text = create_json_completion(
                system_prompt=ISSUE_PAGE_REWRITE_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                model=settings.model,
            )
        payload = parse_json_response(response_text)
        result = IssuePageRewriteResult.model_validate(payload)
    except Exception as exc:  # noqa: BLE001 — 이 함수는 항상 성공해야 하므로 모든 실패를 폴백으로 흡수한다.
        logger.exception(
            "issue_page_rewrite_llm_fallback",
            extra={"issue_key": section.issue_key, "error": str(exc)},
        )
        return section

    return section.model_copy(update={
        "current_summary": result.current_summary,
        "key_facts": result.key_facts,
        "implications": result.implications,
        "watch_points": result.watch_points,
    })


def _generate_issue_page(
    section: ReportSectionDraft,
    *,
    workspace_id: str,
    requested_by: str | None,
    parent_page_id: str | None = None,
    evidence_texts: dict[str, str] | None = None,
    citation_attribution: dict[str, ReportCandidate] | None = None,
    supabase: Client | None = None,
    llm_client: WikiTopicLLMClient | None = None,
) -> tuple[str, str]:
    rewritten_section = _rewrite_issue_page_content(section, evidence_texts, llm_client=llm_client)

    matched = find_matching_issue_page(
        workspace_id,
        category=section.category.value,
        document_version_ids=[c.document_version_id for c in section.news_citations],
        supabase=supabase,
    )

    if matched is not None:
        page_id = matched.page_id
        draft_slug = matched.slug
        draft_title = matched.title
        draft_page_type = matched.page_type
        draft_parent_page_id = matched.parent_page_id if matched.parent_page_id is not None else parent_page_id
    else:
        page_id = upsert_wiki_page(
            workspace_id,
            section.issue_key,
            section.title,
            "issue",
            parent_page_id,
            supabase=supabase,
        )
        draft_slug = section.issue_key
        draft_title = section.title
        draft_page_type = "issue"
        draft_parent_page_id = parent_page_id

    draft = WikiDraftInput(
        workspace_id=workspace_id,
        slug=draft_slug,
        title=draft_title,
        page_type=draft_page_type,
        parent_page_id=draft_parent_page_id,
        markdown=_build_issue_page_markdown(rewritten_section, evidence_texts, citation_attribution),
        sources=_build_issue_page_sources(section, evidence_texts),
        change_summary=(
            "리포트 파이프라인에서 기존 이슈 페이지 갱신" if matched is not None else "리포트 파이프라인에서 자동 생성"
        ),
        created_by=requested_by,
        generated_by="llm",
    )
    version_id = create_wiki_version(draft, supabase=supabase)
    record_wiki_validation(version_id, "passed", None, supabase=supabase)
    review_wiki_version(version_id, None, "approved", supabase=supabase)
    publish_wiki_version(page_id, version_id, supabase=supabase)
    return page_id, version_id


def _wiki_contexts_to_candidates(
    wiki_contexts: list[WikiContext],
    *,
    workspace_id: str,
    supabase: Client | None = None,
) -> list[TopicPageCandidate]:
    """검색 결과를 주제 페이지 후보로 변환한다.

    자동 발행된 이슈 페이지(page_type='issue')는 후보에서 제외한다. 제외하지 않으면
    이전 회차에 자동 생성된 이슈 페이지가 다음 회차의 주제 후보로 다시 올라오는
    자기 피드백 루프가 생긴다.
    """
    if not wiki_contexts:
        return []
    topic_page_ids = filter_to_topic_page_ids(
        [context.wiki_page_id for context in wiki_contexts],
        workspace_id=workspace_id,
        supabase=supabase,
    )
    return [
        TopicPageCandidate(
            wiki_page_id=context.wiki_page_id,
            title=context.title,
            content=context.content,
            similarity_score=context.similarity_score,
        )
        for context in wiki_contexts
        if context.wiki_page_id in topic_page_ids
    ]


def _generate_topic_page(
    section: ReportSectionDraft,
    wiki_contexts: list[WikiContext],
    *,
    workspace_id: str,
    requested_by: str | None,
    evidence_texts: dict[str, str] | None = None,
    citation_attribution: dict[str, ReportCandidate] | None = None,
    supabase: Client | None = None,
    llm_client: WikiTopicLLMClient | None = None,
) -> tuple[str, str | None, str | None]:
    settings = get_openrouter_settings()
    candidates = _wiki_contexts_to_candidates(
        wiki_contexts, workspace_id=workspace_id, supabase=supabase,
    )
    top_level_pages = list_top_level_topic_pages(workspace_id, supabase=supabase)

    user_prompt = build_wiki_topic_user_prompt(
        section=section,
        candidates=candidates,
        top_level_pages=top_level_pages,
        evidence_texts=evidence_texts,
        citation_attribution=citation_attribution,
    )
    if llm_client is not None:
        response_text = llm_client(WIKI_TOPIC_SYSTEM_PROMPT, user_prompt, settings.model)
    else:
        response_text = create_json_completion(
            system_prompt=WIKI_TOPIC_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=settings.model,
        )
    payload = parse_json_response(response_text)
    try:
        result = WikiTopicLLMResult.model_validate(payload)
    except ValidationError as exc:
        # page_type만 스키마 밖 값이면(예: LLM이 지어낸 카테고리명) industry로 대체해
        # 페이지 생성 자체가 막히지 않게 한다. 다른 필드 문제면 그대로 올린다.
        if {e["loc"] for e in exc.errors()} != {("page_type",)}:
            raise
        logger.warning(
            "wiki_topic_page_type_fallback",
            extra={"issue_key": section.issue_key, "invalid_page_type": payload.get("page_type")},
        )
        payload = {**payload, "page_type": "industry"}
        result = WikiTopicLLMResult.model_validate(payload)

    # LLM이 돌려준 식별자는 프롬프트에 보여준 값에서만 골라야 한다.
    allowed_document_version_ids = {
        citation.document_version_id for citation in section.news_citations
    }
    valid_claims = [
        claim for claim in result.claims
        if claim.document_version_id in allowed_document_version_ids
    ]

    if result.action == "skip" or not valid_claims:
        return "skip", None, None
    if not (result.markdown or "").strip():
        # 본문이 비면 빈 페이지가 자동 발행되므로 근거 없음과 동일하게 취급한다.
        return "skip", None, None

    if result.reliability.reliability_level == ReliabilityLevel.LOW:
        logger.info(
            "wiki_topic_page_skipped_low_reliability",
            extra={"issue_key": section.issue_key, "reliability_score": result.reliability.reliability_score},
        )
        return "skip", None, None

    sources = [
        WikiSourceInput(
            document_version_id=claim.document_version_id,
            claim_text=claim.claim_text,
            citation_order=claim.citation_order,
        )
        for claim in valid_claims
    ]

    if result.action == "update_existing":
        candidate_page_ids = {candidate.wiki_page_id for candidate in candidates}
        if not result.target_wiki_page_id or result.target_wiki_page_id not in candidate_page_ids:
            return "skip", None, None
        # create_wiki_version()이 내부적으로 upsert_wiki_page()를 다시 실행하므로,
        # 기존 페이지의 실제 slug/title/page_type/parent_page_id를 그대로 넘겨
        # 같은 페이지로 멱등하게 귀결되도록 한다 (LLM은 update 시 이 값들을 안 줌).
        identity = get_wiki_page_identity(
            result.target_wiki_page_id, workspace_id=workspace_id, supabase=supabase,
        )
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
        if is_duplicate_title(result.title, section.title):
            logger.info(
                "wiki_topic_page_skipped_duplicate_title",
                extra={"issue_key": section.issue_key, "topic_title": result.title},
            )
            return "skip", None, None
        allowed_parent_page_ids = {page.wiki_page_id for page in top_level_pages}
        parent_page_id = (
            result.parent_page_id
            if result.parent_page_id in allowed_parent_page_ids
            else None
        )
        page_id = upsert_wiki_page(
            workspace_id, result.slug, result.title, result.page_type, parent_page_id,
            supabase=supabase,
        )
        draft_slug = result.slug
        draft_title = result.title
        draft_page_type = result.page_type
        draft_parent_page_id = parent_page_id

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
        page_reliability_score=result.reliability.reliability_score,
        page_reliability_level=result.reliability.reliability_level.value,
        page_reliability_detail=result.reliability.model_dump(),
    )
    version_id = create_wiki_version(draft, supabase=supabase)

    # 설계 §5(2026-08-04 개정): LLM 위키이므로 검증 통과 시 신뢰도와 무관하게 항상
    # 자동 승인·발행한다. confidence_score는 계속 기록해서(표시·분석용) 남기되,
    # 더 이상 발행 여부를 가르는 게이트로는 쓰지 않는다 — 이슈 페이지와 동일한 정책.
    confidence = result.confidence_score
    record_wiki_validation(version_id, "passed", confidence, supabase=supabase)
    review_wiki_version(version_id, None, "approved", supabase=supabase)
    publish_wiki_version(page_id, version_id, supabase=supabase)

    return result.action, page_id, version_id


def generate_wiki_drafts_for_sections(
    sections: list[ReportSectionDraft],
    enriched_groups: list[EnrichedIssueGroup],
    *,
    workspace_id: str,
    requested_by: str | None = None,
    supabase: Client | None = None,
    llm_client: WikiTopicLLMClient | None = None,
    deadline: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
) -> list[WikiDraftGenerationResult]:
    """
    섹션별로 주제 페이지(Topic)를 먼저 생성하고, 그 결과를 이슈 페이지(Issue)의 parent_page_id로 연결한다.

    주제 페이지 생성 실패가 이슈 페이지 생성을 막지 않으며, 이슈 페이지 생성 실패도 다른 섹션 처리를 막지 않는다.
    (단계별 실패 격리)

    deadline이 주어지면(예: GH Actions job timeout보다 여유 있게 잡은 자체 시간 예산),
    섹션 처리 도중 그 시각을 넘기는 순간부터는 남은 섹션을 건너뛰고 여기까지의 결과만
    반환한다 — 외부 프로세스가 통째로 강제 종료돼 아무 상태도 안 남는 것보다,
    처리한 만큼이라도 발행되고 호출자가 정상적으로 후속 처리(예: 게이트 타임스탬프 갱신)를
    이어갈 수 있는 쪽이 낫다.
    """
    now = clock or (lambda: datetime.now(timezone.utc))
    wiki_contexts_by_issue_key = {
        group.issue_group.issue_key: group.wiki_contexts for group in enriched_groups
    }
    evidence_texts_by_issue_key = build_evidence_text_map(enriched_groups)
    citation_attribution_by_issue_key = build_citation_attribution_map(enriched_groups)

    # 주제 페이지를 먼저 정해야 이슈 페이지의 parent_page_id로 연결할 수 있다.
    # (upsert_wiki_page는 ignore_duplicates=True라 기존 페이지의 parent_page_id를
    #  나중에 수정할 방법이 없으므로, 이슈 페이지를 처음 만들 때 값을 넣어야 한다.)
    results: list[WikiDraftGenerationResult] = []
    for index, section in enumerate(sections):
        if deadline is not None and now() >= deadline:
            logger.warning(
                "wiki_refresh_time_budget_exceeded",
                extra={"processed": index, "remaining": len(sections) - index},
            )
            break
        wiki_contexts = wiki_contexts_by_issue_key.get(section.issue_key, [])
        evidence_texts = evidence_texts_by_issue_key.get(section.issue_key, {})
        citation_attribution = citation_attribution_by_issue_key.get(section.issue_key, {})

        topic_action: str = "skip"
        topic_page_id: str | None = None
        topic_version_id: str | None = None
        topic_error: str | None = None
        try:
            topic_action, topic_page_id, topic_version_id = _generate_topic_page(
                section,
                wiki_contexts,
                workspace_id=workspace_id,
                requested_by=requested_by,
                evidence_texts=evidence_texts,
                citation_attribution=citation_attribution,
                supabase=supabase,
                llm_client=llm_client,
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
                evidence_texts=evidence_texts,
                citation_attribution=citation_attribution,
                supabase=supabase,
                llm_client=llm_client,
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

    published_count = sum(
        (1 if result.issue_page_id else 0) + (1 if result.topic_page_id is not None else 0)
        for result in results
    )
    if published_count > 0:
        try:
            send_wiki_notification(workspace_id, published_count, supabase=supabase)
        except Exception:  # noqa: BLE001
            logger.exception("wiki_notification_failed", extra={"workspace_id": workspace_id})

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


def refresh_wiki_from_recent_analysis(
    workspace_id: str,
    *,
    since_hours: int = 2,
    requested_by: str | None = None,
    supabase: Client | None = None,
    deadline: datetime | None = None,
) -> list[WikiDraftGenerationResult]:
    """리포트 파이프라인과 별개로, 최근 since_hours 내 분석 완료된 문서를 근거로
    위키만 갱신한다. reports/report_sections에는 아무것도 남기지 않는다."""
    # report.interface가 모듈 최상단에서 wiki.generation을 import하므로(순환 참조),
    # ReportGenerationConfig는 호출 시점에 지연 import한다. report/interface.py 파일 자체는 수정하지 않는다.
    from ..report.interface import ReportGenerationConfig

    config = ReportGenerationConfig()
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)

    candidates = get_recently_analyzed_candidates(workspace_id=workspace_id, since=since, supabase=supabase)
    selected = select_report_candidates(
        candidates,
        max_candidates=config.selection.max_candidates or 15,
        min_reliability_score=config.selection.min_reliability_score,
        min_importance_score=config.selection.min_importance_score,
        min_ranking_score=config.selection.min_ranking_score,
        category_limits=config.selection.category_limits,
    )
    issue_groups = group_report_candidates(selected, config=config.grouping)
    enriched_groups = enrich_issue_groups(
        issue_groups,
        wiki_search=lambda wiki_request: search_wiki_contexts(wiki_request, supabase=supabase),
        limit_per_group=config.wiki.limit_per_group,
    )
    sections = compose_report_sections(enriched_groups, config=config.composer)

    return generate_wiki_drafts_for_sections(
        sections, enriched_groups, workspace_id=workspace_id, requested_by=requested_by, supabase=supabase,
        deadline=deadline,
    )

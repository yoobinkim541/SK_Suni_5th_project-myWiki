from __future__ import annotations

import logging
from collections.abc import Callable

from supabase import Client

from ..analysis.classifier import create_json_completion, get_openrouter_settings, parse_json_response
from .dedup_models import DedupCandidatePair, DedupResult, WikiDedupLLMResult
from .dedup_prompts import WIKI_DEDUP_SYSTEM_PROMPT, build_wiki_dedup_user_prompt
from .dedup_repository import reparent_children
from .generation_repository import archive_wiki_page
from .interface import (
    WikiDraftInput,
    WikiPageContent,
    WikiSourceInput,
    create_wiki_version,
    publish_wiki_version,
    record_wiki_validation,
    review_wiki_version,
)

logger = logging.getLogger(__name__)

# (system_prompt, user_prompt, model) -> raw JSON 문자열. generation.py의
# WikiTopicLLMClient와 같은 형태의 호출 가능 객체다.
WikiDedupLLMClient = Callable[[str, str, str | None], str]


def _judge_and_merge(
    pair: DedupCandidatePair,
    content_a: WikiPageContent,
    content_b: WikiPageContent,
    *,
    workspace_id: str,
    requested_by: str | None = None,
    supabase: Client | None = None,
    llm_client: WikiDedupLLMClient | None = None,
) -> DedupResult:
    settings = get_openrouter_settings()
    user_prompt = build_wiki_dedup_user_prompt(content_a, content_b)

    if llm_client is not None:
        response_text = llm_client(WIKI_DEDUP_SYSTEM_PROMPT, user_prompt, settings.model)
    else:
        response_text = create_json_completion(
            system_prompt=WIKI_DEDUP_SYSTEM_PROMPT, user_prompt=user_prompt, model=settings.model,
        )
    payload = parse_json_response(response_text)
    result = WikiDedupLLMResult.model_validate(payload)

    not_duplicate = DedupResult(
        page_a_id=pair.page_a.page_id, page_b_id=pair.page_b.page_id, decision="not_duplicate",
    )

    if result.decision != "merge":
        return not_duplicate

    candidates_by_id = {content_a.page_id: (pair.page_a, content_a), content_b.page_id: (pair.page_b, content_b)}
    if result.representative_page_id not in candidates_by_id:
        return not_duplicate

    representative_info, _ = candidates_by_id[result.representative_page_id]
    other_page_id = pair.page_b.page_id if representative_info.page_id == pair.page_a.page_id else pair.page_a.page_id
    other_info, _ = candidates_by_id[other_page_id]

    allowed_document_version_ids = {s.document_version_id for s in content_a.sources} | {
        s.document_version_id for s in content_b.sources
    }
    valid_claims = [c for c in result.claims if c.document_version_id in allowed_document_version_ids]

    if not valid_claims or not (result.markdown or "").strip():
        return not_duplicate

    sources = [
        WikiSourceInput(
            document_version_id=claim.document_version_id,
            claim_text=claim.claim_text,
            citation_order=claim.citation_order,
        )
        for claim in valid_claims
    ]

    draft = WikiDraftInput(
        workspace_id=workspace_id,
        slug=representative_info.slug,
        title=representative_info.title,
        page_type=representative_info.page_type,
        parent_page_id=representative_info.parent_page_id,
        markdown=result.markdown or "",
        sources=sources,
        change_summary=result.change_summary,
        created_by=requested_by,
        generated_by="llm",
    )
    version_id = create_wiki_version(draft, supabase=supabase)
    record_wiki_validation(version_id, "passed", None, supabase=supabase)
    review_wiki_version(version_id, None, "approved", supabase=supabase)
    publish_wiki_version(representative_info.page_id, version_id, supabase=supabase)
    archive_wiki_page(other_info.page_id, supabase=supabase)
    reparent_children(other_info.page_id, representative_info.page_id, workspace_id=workspace_id, supabase=supabase)

    return DedupResult(
        page_a_id=pair.page_a.page_id,
        page_b_id=pair.page_b.page_id,
        decision="merged",
        representative_page_id=representative_info.page_id,
        archived_page_id=other_info.page_id,
        version_id=version_id,
    )

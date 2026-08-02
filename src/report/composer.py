from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from functools import lru_cache

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError, field_validator

from ..analysis.importance_models import ImpactDirection, TimeHorizon
from ..analysis.models import Category
from .models import (
    EnrichedIssueGroup,
    ReportCandidate,
    ReportCitationDraft,
    ReportSectionDraft,
    ReportWikiReferenceDraft,
    WikiContext,
)
from .prompts import SECTION_PROMPT_VERSION, build_report_section_messages

DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_REPORT_MODEL = "openai/gpt-4.1-mini"


class ReportComposerError(Exception):
    pass


class ReportReferenceValidationError(ReportComposerError):
    pass


class ReportComposerConfig(BaseModel):
    model: str = DEFAULT_REPORT_MODEL
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    language: str = "ko"
    max_wiki_contexts: int = Field(default=3, ge=0)
    max_wiki_chars_per_context: int = Field(default=2000, ge=1)
    max_total_wiki_chars: int = Field(default=4000, ge=1)
    prompt_version: str = SECTION_PROMPT_VERSION
    max_retries: int = Field(default=1, ge=0)


class ComposerNewsSource(BaseModel):
    source_ref: str
    analysis_result_id: str
    document_id: str
    document_version_id: str
    title: str
    summary: str | None = None
    source_name: str | None = None
    canonical_url: str | None = None
    published_at: str | None = None
    reliability_score: int | None = None
    importance_score: int | None = None
    ranking_score: str | None = None
    impact_direction: str | None = None
    time_horizon: str | None = None
    is_representative: bool


class ComposerWikiSource(BaseModel):
    source_ref: str
    wiki_page_id: str
    wiki_version_id: str | None = None
    title: str
    content: str | None = None
    similarity_score: float | None = None
    updated_at: str | None = None
    source_document_version_ids: list[str] = Field(default_factory=list)
    content_truncated: bool = False


class ReportSectionComposerInput(BaseModel):
    issue_key: str
    category: Category
    representative_analysis_result_id: str
    language: str
    importance_score: int | None = None
    impact_direction: ImpactDirection | None = None
    time_horizon: TimeHorizon | None = None
    news_sources: list[ComposerNewsSource]
    wiki_sources: list[ComposerWikiSource] = Field(default_factory=list)


class GeneratedSummary(BaseModel):
    text: str
    news_refs: list[str] = Field(default_factory=list)
    wiki_refs: list[str] = Field(default_factory=list)
    is_inference: bool = False

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("text must not be empty.")
        return text


class GeneratedPoint(BaseModel):
    text: str
    news_refs: list[str] = Field(default_factory=list)
    wiki_refs: list[str] = Field(default_factory=list)
    is_inference: bool = False

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("text must not be empty.")
        return text


class GeneratedReportSectionPayload(BaseModel):
    title: str
    current_summary: GeneratedSummary
    key_facts: list[GeneratedPoint] = Field(default_factory=list)
    historical_context: list[GeneratedPoint] = Field(default_factory=list)
    implications: list[GeneratedPoint] = Field(default_factory=list)
    watch_points: list[GeneratedPoint] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("title must not be empty.")
        return text


class OpenRouterSettings(BaseModel):
    api_key: str
    model: str
    base_url: str


def compose_report_sections(
    enriched_groups: Sequence[EnrichedIssueGroup],
    *,
    config: ReportComposerConfig,
    llm_client: Callable[[str, str, ReportComposerConfig], str] | None = None,
) -> list[ReportSectionDraft]:
    return [
        compose_report_section(
            enriched_group,
            config=config,
            llm_client=llm_client,
        )
        for enriched_group in enriched_groups
    ]


def compose_report_section(
    enriched_group: EnrichedIssueGroup,
    *,
    config: ReportComposerConfig,
    llm_client: Callable[[str, str, ReportComposerConfig], str] | None = None,
) -> ReportSectionDraft:
    composer_input = build_composer_input(enriched_group, config=config)

    last_error: Exception | None = None
    for _attempt in range(config.max_retries + 1):
        system_prompt, user_prompt = build_report_section_messages(composer_input)
        raw_response = call_section_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            config=config,
            llm_client=llm_client,
        )
        try:
            payload = _parse_section_payload(raw_response)
            validate_llm_source_references(payload, composer_input=composer_input)
            return to_report_section_draft(
                enriched_group,
                composer_input=composer_input,
                payload=payload,
            )
        except (ValidationError, ValueError, ReportReferenceValidationError) as exc:
            last_error = exc

    raise ReportComposerError("Failed to compose a valid report section.") from last_error


def build_composer_input(
    enriched_group: EnrichedIssueGroup,
    *,
    config: ReportComposerConfig,
) -> ReportSectionComposerInput:
    representative = _get_representative_candidate(enriched_group)
    news_sources = [
        _to_news_source(candidate, representative_analysis_result_id=representative.analysis_result_id, index=index)
        for index, candidate in enumerate(enriched_group.issue_group.candidates, start=1)
    ]
    wiki_sources = _build_wiki_sources(enriched_group.wiki_contexts, config=config)
    return ReportSectionComposerInput(
        issue_key=enriched_group.issue_group.issue_key,
        category=enriched_group.issue_group.category,
        representative_analysis_result_id=representative.analysis_result_id,
        language=config.language,
        importance_score=representative.importance_score,
        impact_direction=representative.impact_direction,
        time_horizon=representative.time_horizon,
        news_sources=news_sources,
        wiki_sources=wiki_sources,
    )


def call_section_llm(
    *,
    system_prompt: str,
    user_prompt: str,
    config: ReportComposerConfig,
    llm_client: Callable[[str, str, ReportComposerConfig], str] | None = None,
) -> str:
    if llm_client is not None:
        return llm_client(system_prompt, user_prompt, config)
    return _create_report_json_completion(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        config=config,
    )


def validate_llm_source_references(
    payload: GeneratedReportSectionPayload,
    *,
    composer_input: ReportSectionComposerInput,
) -> None:
    valid_news_refs = {source.source_ref for source in composer_input.news_sources}
    valid_wiki_refs = {source.source_ref for source in composer_input.wiki_sources}

    _validate_summary_refs(payload.current_summary, valid_news_refs=valid_news_refs, valid_wiki_refs=valid_wiki_refs)

    for point in payload.key_facts:
        if not point.news_refs:
            raise ReportReferenceValidationError("Each key fact must cite at least one news reference.")
        if point.wiki_refs:
            raise ReportReferenceValidationError("Key facts must not cite wiki references.")
        _validate_ref_membership(point, valid_news_refs=valid_news_refs, valid_wiki_refs=valid_wiki_refs)

    for point in payload.historical_context:
        if not point.wiki_refs:
            raise ReportReferenceValidationError("Each historical context item must cite at least one wiki reference.")
        if point.news_refs:
            raise ReportReferenceValidationError("Historical context must not cite news references.")
        _validate_ref_membership(point, valid_news_refs=valid_news_refs, valid_wiki_refs=valid_wiki_refs)

    for point in payload.implications:
        if not point.news_refs and not point.wiki_refs:
            raise ReportReferenceValidationError("Each implication must cite at least one source.")
        _validate_ref_membership(point, valid_news_refs=valid_news_refs, valid_wiki_refs=valid_wiki_refs)

    for point in payload.watch_points:
        if not point.news_refs and not point.wiki_refs:
            raise ReportReferenceValidationError("Each watch point must cite at least one source.")
        _validate_ref_membership(point, valid_news_refs=valid_news_refs, valid_wiki_refs=valid_wiki_refs)


def to_report_section_draft(
    enriched_group: EnrichedIssueGroup,
    *,
    composer_input: ReportSectionComposerInput,
    payload: GeneratedReportSectionPayload,
) -> ReportSectionDraft:
    news_citations = build_report_citation_drafts(
        composer_input=composer_input,
        payload=payload,
    )
    wiki_references = build_report_wiki_reference_drafts(
        composer_input=composer_input,
        payload=payload,
    )
    return ReportSectionDraft(
        issue_key=enriched_group.issue_group.issue_key,
        representative_analysis_result_id=composer_input.representative_analysis_result_id,
        category=composer_input.category,
        importance_score=composer_input.importance_score,
        impact_direction=composer_input.impact_direction,
        time_horizon=composer_input.time_horizon,
        title=payload.title,
        current_summary=payload.current_summary.text,
        key_facts=[point.text for point in payload.key_facts],
        historical_context=[point.text for point in payload.historical_context],
        implications=[point.text for point in payload.implications],
        watch_points=[point.text for point in payload.watch_points],
        news_citations=news_citations,
        wiki_references=wiki_references,
    )


def build_report_citation_drafts(
    *,
    composer_input: ReportSectionComposerInput,
    payload: GeneratedReportSectionPayload,
) -> list[ReportCitationDraft]:
    refs = collect_used_news_refs(payload)
    news_by_ref = {source.source_ref: source for source in composer_input.news_sources}
    drafts: list[ReportCitationDraft] = []
    for order, ref in enumerate(refs, start=1):
        source = news_by_ref[ref]
        drafts.append(
            ReportCitationDraft(
                analysis_result_id=source.analysis_result_id,
                document_version_id=source.document_version_id,
                citation_order=order,
                citation_role="section_support",
            )
        )
    return drafts


def build_report_wiki_reference_drafts(
    *,
    composer_input: ReportSectionComposerInput,
    payload: GeneratedReportSectionPayload,
) -> list[ReportWikiReferenceDraft]:
    refs = collect_used_wiki_refs(payload)
    wiki_by_ref = {source.source_ref: source for source in composer_input.wiki_sources}
    drafts: list[ReportWikiReferenceDraft] = []
    for order, ref in enumerate(refs, start=1):
        source = wiki_by_ref[ref]
        drafts.append(
            ReportWikiReferenceDraft(
                wiki_page_id=source.wiki_page_id,
                wiki_version_id=source.wiki_version_id,
                reference_order=order,
                reference_role="section_context",
                similarity_score=source.similarity_score,
            )
        )
    return drafts


def collect_used_news_refs(payload: GeneratedReportSectionPayload) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for ref in _iter_news_refs(payload):
        if ref in seen:
            continue
        ordered.append(ref)
        seen.add(ref)
    return ordered


def collect_used_wiki_refs(payload: GeneratedReportSectionPayload) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for ref in _iter_wiki_refs(payload):
        if ref in seen:
            continue
        ordered.append(ref)
        seen.add(ref)
    return ordered


def get_openrouter_settings() -> OpenRouterSettings:
    load_dotenv()
    return OpenRouterSettings(
        api_key=os.getenv("OPENROUTER_API_KEY", "").strip(),
        model=os.getenv("OPENROUTER_MODEL", "").strip() or DEFAULT_REPORT_MODEL,
        base_url=os.getenv("OPENROUTER_BASE_URL", "").strip() or DEFAULT_OPENROUTER_BASE_URL,
    )


@lru_cache(maxsize=1)
def get_openrouter_client() -> OpenAI:
    settings = get_openrouter_settings()
    return OpenAI(
        base_url=settings.base_url,
        api_key=settings.api_key,
        max_retries=1,
    )


def _iter_news_refs(payload: GeneratedReportSectionPayload):
    yield from payload.current_summary.news_refs
    for point in payload.key_facts:
        yield from point.news_refs
    for point in payload.implications:
        yield from point.news_refs
    for point in payload.watch_points:
        yield from point.news_refs


def _iter_wiki_refs(payload: GeneratedReportSectionPayload):
    yield from payload.current_summary.wiki_refs
    for point in payload.key_facts:
        yield from point.wiki_refs
    for point in payload.historical_context:
        yield from point.wiki_refs
    for point in payload.implications:
        yield from point.wiki_refs
    for point in payload.watch_points:
        yield from point.wiki_refs


def _validate_summary_refs(
    summary: GeneratedSummary,
    *,
    valid_news_refs: set[str],
    valid_wiki_refs: set[str],
) -> None:
    if not summary.news_refs:
        raise ReportReferenceValidationError("current_summary must cite at least one news reference.")
    if summary.wiki_refs:
        raise ReportReferenceValidationError("current_summary must not cite wiki references.")
    _validate_ref_membership(summary, valid_news_refs=valid_news_refs, valid_wiki_refs=valid_wiki_refs)


def _validate_ref_membership(
    point: GeneratedSummary | GeneratedPoint,
    *,
    valid_news_refs: set[str],
    valid_wiki_refs: set[str],
) -> None:
    unknown_news_refs = [ref for ref in point.news_refs if ref not in valid_news_refs]
    if unknown_news_refs:
        raise ReportReferenceValidationError(f"Unknown news refs: {unknown_news_refs}")
    unknown_wiki_refs = [ref for ref in point.wiki_refs if ref not in valid_wiki_refs]
    if unknown_wiki_refs:
        raise ReportReferenceValidationError(f"Unknown wiki refs: {unknown_wiki_refs}")


def _build_wiki_sources(
    wiki_contexts: Sequence[WikiContext],
    *,
    config: ReportComposerConfig,
) -> list[ComposerWikiSource]:
    limited_contexts = list(wiki_contexts[: config.max_wiki_contexts])
    remaining_total_chars = config.max_total_wiki_chars
    wiki_sources: list[ComposerWikiSource] = []
    for index, context in enumerate(limited_contexts, start=1):
        available_chars = min(config.max_wiki_chars_per_context, remaining_total_chars)
        if available_chars <= 0:
            break
        content = context.content
        content_truncated = False
        if content is not None and len(content) > available_chars:
            content = content[:available_chars].rstrip()
            content_truncated = True
        if content is not None:
            remaining_total_chars -= len(content)
        wiki_sources.append(
            ComposerWikiSource(
                source_ref=f"W{index}",
                wiki_page_id=context.wiki_page_id,
                wiki_version_id=context.wiki_version_id,
                title=context.title,
                content=content,
                similarity_score=context.similarity_score,
                updated_at=context.updated_at.isoformat() if context.updated_at is not None else None,
                source_document_version_ids=list(context.source_document_version_ids),
                content_truncated=content_truncated,
            )
        )
    return wiki_sources


def _get_representative_candidate(enriched_group: EnrichedIssueGroup) -> ReportCandidate:
    representative_id = enriched_group.issue_group.representative_analysis_result_id
    if representative_id is None:
        raise ValueError("Issue group is missing representative_analysis_result_id.")
    for candidate in enriched_group.issue_group.candidates:
        if candidate.analysis_result_id == representative_id:
            return candidate
    raise ValueError("representative_analysis_result_id does not exist in issue_group.candidates.")


def _to_news_source(
    candidate: ReportCandidate,
    *,
    representative_analysis_result_id: str,
    index: int,
) -> ComposerNewsSource:
    return ComposerNewsSource(
        source_ref=f"N{index}",
        analysis_result_id=candidate.analysis_result_id,
        document_id=candidate.document_id,
        document_version_id=candidate.document_version_id,
        title=candidate.title,
        summary=candidate.summary,
        source_name=candidate.source_name,
        canonical_url=candidate.canonical_url,
        published_at=candidate.published_at.isoformat() if candidate.published_at is not None else None,
        reliability_score=candidate.reliability_score,
        importance_score=candidate.importance_score,
        ranking_score=str(candidate.ranking_score) if candidate.ranking_score is not None else None,
        impact_direction=candidate.impact_direction.value if candidate.impact_direction is not None else None,
        time_horizon=candidate.time_horizon.value if candidate.time_horizon is not None else None,
        is_representative=candidate.analysis_result_id == representative_analysis_result_id,
    )


def _parse_section_payload(raw_response: str) -> GeneratedReportSectionPayload:
    try:
        payload = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM response is not valid JSON.") from exc
    return GeneratedReportSectionPayload.model_validate(payload)


def _create_report_json_completion(
    *,
    system_prompt: str,
    user_prompt: str,
    config: ReportComposerConfig,
) -> str:
    settings = get_openrouter_settings()
    if not settings.api_key:
        raise ReportComposerError("OPENROUTER_API_KEY is not configured.")

    response = get_openrouter_client().chat.completions.create(
        model=config.model or settings.model,
        temperature=config.temperature,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        timeout=30,
    )
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise ReportComposerError("LLM response does not contain choices.")
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None)
    if not content or not isinstance(content, str):
        raise ReportComposerError("LLM response content is empty.")
    return content

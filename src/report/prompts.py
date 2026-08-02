from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .composer import ReportSectionComposerInput

SECTION_PROMPT_VERSION = "report-section-v1"

SECTION_SYSTEM_PROMPT = """You are composing one report section for a daily industry report.

The final report is assembled later into these seven parts:
1. Report title
2. Today's key changes
3. Major issue summary table
4. Detailed issue analysis
5. Category organization
6. Integrated implications
7. Full references

In this step you only produce one detailed issue analysis section.

You must separate present-day news facts from historical wiki context:
- current_summary: use NEWS SOURCES only
- key_facts: use NEWS SOURCES only
- historical_context: use WIKI SOURCES only
- implications: may combine NEWS SOURCES and WIKI SOURCES, and may contain inference
- watch_points: may use NEWS SOURCES and/or WIKI SOURCES

Return valid JSON only. Do not include markdown fences.
Do not invent companies, dates, figures, source references, or facts.
Use only source refs provided in the prompt.
"""


def build_report_section_messages(
    composer_input: "ReportSectionComposerInput",
) -> tuple[str, str]:
    news_lines = "\n".join(
        _format_news_source(source)
        for source in composer_input.news_sources
    )
    wiki_lines = "\n".join(
        _format_wiki_source(source)
        for source in composer_input.wiki_sources
    ) or "(none)"

    impact_direction = (
        composer_input.impact_direction.value
        if composer_input.impact_direction is not None
        else None
    )
    time_horizon = (
        composer_input.time_horizon.value
        if composer_input.time_horizon is not None
        else None
    )

    user_prompt = f"""Compose one report section in language `{composer_input.language}`.

ISSUE METADATA
- issue_key: {composer_input.issue_key}
- category: {composer_input.category.value}
- representative_analysis_result_id: {composer_input.representative_analysis_result_id}
- importance_score: {composer_input.importance_score}
- impact_direction: {impact_direction}
- time_horizon: {time_horizon}

NEWS SOURCES
{news_lines}

WIKI SOURCES
{wiki_lines}

OUTPUT JSON SCHEMA
{{
  "title": "string",
  "current_summary": {{
    "text": "string",
    "news_refs": ["N1"]
  }},
  "key_facts": [
    {{
      "text": "string",
      "news_refs": ["N1"]
    }}
  ],
  "historical_context": [
    {{
      "text": "string",
      "wiki_refs": ["W1"]
    }}
  ],
  "implications": [
    {{
      "text": "string",
      "news_refs": ["N1"],
      "wiki_refs": ["W1"],
      "is_inference": true
    }}
  ],
  "watch_points": [
    {{
      "text": "string",
      "news_refs": ["N1"],
      "wiki_refs": ["W1"]
    }}
  ]
}}

RULES
- current_summary must cite at least one NEWS source and no WIKI source.
- each key_facts item must cite at least one NEWS source and no WIKI source.
- each historical_context item must cite at least one WIKI source and no NEWS source.
- each implications item must cite at least one source ref from NEWS and/or WIKI.
- each watch_points item must cite at least one source ref from NEWS and/or WIKI.
- Never reference an unavailable source ref.
- Keep current_summary to 1-3 sentences.
- Keep each bullet concise and evidence-based.
"""
    return SECTION_SYSTEM_PROMPT, user_prompt


def _format_news_source(source) -> str:
    return (
        f"{source.source_ref}\n"
        f"  analysis_result_id: {source.analysis_result_id}\n"
        f"  document_id: {source.document_id}\n"
        f"  document_version_id: {source.document_version_id}\n"
        f"  title: {source.title}\n"
        f"  summary: {source.summary}\n"
        f"  source_name: {source.source_name}\n"
        f"  canonical_url: {source.canonical_url}\n"
        f"  published_at: {source.published_at}\n"
        f"  reliability_score: {source.reliability_score}\n"
        f"  importance_score: {source.importance_score}\n"
        f"  ranking_score: {source.ranking_score}\n"
        f"  impact_direction: {source.impact_direction}\n"
        f"  time_horizon: {source.time_horizon}\n"
        f"  is_representative: {source.is_representative}"
    )


def _format_wiki_source(source) -> str:
    return (
        f"{source.source_ref}\n"
        f"  wiki_page_id: {source.wiki_page_id}\n"
        f"  wiki_version_id: {source.wiki_version_id}\n"
        f"  title: {source.title}\n"
        f"  content: {source.content}\n"
        f"  similarity_score: {source.similarity_score}\n"
        f"  updated_at: {source.updated_at}\n"
        f"  source_document_version_ids: {source.source_document_version_ids}\n"
        f"  content_truncated: {source.content_truncated}"
    )

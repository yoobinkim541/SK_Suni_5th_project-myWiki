from __future__ import annotations

from datetime import datetime, timezone

from src.analysis.models import Category
from src.report.models import ReportCandidate, ReportCitationDraft, ReportSectionDraft
from src.wiki.generation_models import TopicPageCandidate, TopLevelTopicPage
from src.wiki.generation_prompts import WIKI_TOPIC_SYSTEM_PROMPT, build_wiki_topic_user_prompt


def _section(evidence_text: str | None = "HBM4 수요가 급증했다") -> ReportSectionDraft:
    return ReportSectionDraft(
        issue_key="issue-hbm4-supply",
        representative_analysis_result_id="analysis-1",
        category=Category.PRODUCT_TECHNOLOGY,
        title="HBM4 공급 부족 심화",
        current_summary="HBM4 공급이 예상보다 더 타이트해지고 있다.",
        key_facts=["주요 고객사 수요 증가", "생산 capa 제약"],
        implications=["SK하이닉스 협상력 강화"],
        watch_points=["경쟁사 증설 발표 여부"],
        news_citations=[
            ReportCitationDraft(analysis_result_id="analysis-1", document_version_id="doc-1", citation_order=1, evidence_text=evidence_text)
        ],
    )


def test_system_prompt_forbids_unsupported_claims():
    assert "근거" in WIKI_TOPIC_SYSTEM_PROMPT
    assert "JSON" in WIKI_TOPIC_SYSTEM_PROMPT


def test_user_prompt_includes_section_and_candidates():
    prompt = build_wiki_topic_user_prompt(
        section=_section(),
        candidates=[TopicPageCandidate(wiki_page_id="page-1", title="HBM4_수급현황", content="기존 본문")],
        top_level_pages=[TopLevelTopicPage(wiki_page_id="page-top-1", title="SK하이닉스", page_type="company")],
    )
    assert "HBM4 공급 부족 심화" in prompt
    assert "HBM4_수급현황" in prompt
    assert "기존 본문" in prompt
    assert "SK하이닉스" in prompt
    assert "doc-1" in prompt


def test_user_prompt_handles_no_candidates():
    prompt = build_wiki_topic_user_prompt(section=_section(), candidates=[], top_level_pages=[])
    assert "HBM4 공급 부족 심화" in prompt
    assert "없음" in prompt


def test_user_prompt_fills_evidence_from_map_when_citation_has_none():
    """composer가 evidence_text를 안 채우므로 맵이 실제 근거 텍스트 출처가 된다."""
    prompt = build_wiki_topic_user_prompt(
        section=_section(evidence_text=None),
        candidates=[],
        top_level_pages=[],
        evidence_texts={"doc-1": "HBM4 수요가 급증했다"},
    )
    assert "document_version_id=doc-1 citation_order=1: HBM4 수요가 급증했다" in prompt


def test_user_prompt_leaves_evidence_blank_when_unmapped():
    prompt = build_wiki_topic_user_prompt(
        section=_section(evidence_text=None),
        candidates=[],
        top_level_pages=[],
        evidence_texts={"doc-other": "관련 없음"},
    )
    assert "document_version_id=doc-1 citation_order=1: " in prompt
    assert "관련 없음" not in prompt


def test_system_prompt_instructs_source_section_to_use_title_source_date_not_raw_id():
    assert "매체명" in WIKI_TOPIC_SYSTEM_PROMPT
    assert "document_version_id 문자열을" in WIKI_TOPIC_SYSTEM_PROMPT
    assert "그대로 노출하지 마십시오" in WIKI_TOPIC_SYSTEM_PROMPT


def test_user_prompt_surfaces_citation_attribution_for_llm():
    candidate = ReportCandidate(
        analysis_result_id="analysis-1", workspace_id="ws-1", document_id="doc-1",
        document_version_id="doc-1", category=Category.PRODUCT_TECHNOLOGY,
        title="중국 턱밑 추격에…삼성·SK하이닉스, HBM·차세대 기술 개발 '전력투구' - 뉴시스",
        source_name="Google RSS - SK하이닉스",
        published_at=datetime(2026, 8, 2, 7, 23, 1, tzinfo=timezone.utc),
    )
    prompt = build_wiki_topic_user_prompt(
        section=_section(evidence_text=None),
        candidates=[],
        top_level_pages=[],
        evidence_texts={"doc-1": "HBM4 수요가 급증했다"},
        citation_attribution={"doc-1": candidate},
    )
    assert (
        "중국 턱밑 추격에…삼성·SK하이닉스, HBM·차세대 기술 개발 '전력투구' - 뉴시스"
        " · Google RSS - SK하이닉스 · 2026.08.02" in prompt
    )

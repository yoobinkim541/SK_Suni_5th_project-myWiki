from __future__ import annotations

from src.analysis.models import Category
from src.report.models import ReportCitationDraft, ReportSectionDraft
from src.wiki.generation_models import TopicPageCandidate, TopLevelTopicPage
from src.wiki.generation_prompts import WIKI_TOPIC_SYSTEM_PROMPT, build_wiki_topic_user_prompt


def _section() -> ReportSectionDraft:
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
            ReportCitationDraft(analysis_result_id="analysis-1", document_version_id="doc-1", citation_order=1, evidence_text="HBM4 수요가 급증했다")
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

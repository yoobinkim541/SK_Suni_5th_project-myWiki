from __future__ import annotations

import json
from decimal import Decimal

import pytest

from src.analysis.models import Category
from src.report.models import (
    EnrichedIssueGroup,
    IssueGroup,
    ReportCandidate,
    ReportCitationDraft,
    ReportSectionDraft,
    WikiContext,
)
from src.wiki import generation


def _section(issue_key: str = "issue-hbm4-supply", evidence_text: str | None = None) -> ReportSectionDraft:
    """composer는 evidence_text를 채우지 않으므로 기본값은 None(실제 파이프라인과 동일)."""
    return ReportSectionDraft(
        issue_key=issue_key,
        representative_analysis_result_id="analysis-1",
        category=Category.PRODUCT_TECHNOLOGY,
        title="HBM4 공급 부족 심화",
        current_summary="HBM4 공급이 예상보다 더 타이트해지고 있다.",
        key_facts=["주요 고객사 수요 증가"],
        implications=["SK하이닉스 협상력 강화"],
        watch_points=["경쟁사 증설 발표 여부"],
        news_citations=[
            ReportCitationDraft(
                analysis_result_id="analysis-1",
                document_version_id="doc-1",
                citation_order=1,
                evidence_text=evidence_text,
            )
        ],
    )


def _patch_topic_candidates_filter(monkeypatch, allowed: set[str] | None = None) -> None:
    """filter_to_topic_page_ids를 대체한다. allowed=None이면 전부 통과."""
    monkeypatch.setattr(
        generation,
        "filter_to_topic_page_ids",
        lambda page_ids, *, workspace_id, supabase=None: (
            set(page_ids) if allowed is None else {pid for pid in page_ids if pid in allowed}
        ),
    )


def test_generate_issue_page_creates_and_auto_publishes(monkeypatch):
    calls = []

    def fake_upsert_wiki_page(workspace_id, slug, title, page_type, parent_page_id=None, *, supabase=None):
        calls.append(("upsert", slug, page_type, parent_page_id))
        return "page-1"

    def fake_create_wiki_version(draft, *, supabase=None):
        calls.append(("create", draft.slug, draft.page_type, [s.document_version_id for s in draft.sources]))
        return "version-1"

    def fake_record_wiki_validation(version_id, validation_status, confidence_score, *, supabase=None):
        calls.append(("validate", version_id, validation_status, confidence_score))

    def fake_review_wiki_version(version_id, reviewer_id, decision, *, supabase=None):
        calls.append(("review", version_id, reviewer_id, decision))

    def fake_publish_wiki_version(page_id, version_id, *, supabase=None):
        calls.append(("publish", page_id, version_id))

    monkeypatch.setattr(generation, "find_matching_issue_page", lambda *a, **k: None)
    monkeypatch.setattr(generation, "upsert_wiki_page", fake_upsert_wiki_page)
    monkeypatch.setattr(generation, "create_wiki_version", fake_create_wiki_version)
    monkeypatch.setattr(generation, "record_wiki_validation", fake_record_wiki_validation)
    monkeypatch.setattr(generation, "review_wiki_version", fake_review_wiki_version)
    monkeypatch.setattr(generation, "publish_wiki_version", fake_publish_wiki_version)

    page_id, version_id = generation._generate_issue_page(
        _section(), workspace_id="ws-1", requested_by=None, parent_page_id="page-topic",
    )

    assert page_id == "page-1"
    assert version_id == "version-1"
    assert ("upsert", "issue-hbm4-supply", "issue", "page-topic") in calls
    assert ("validate", "version-1", "passed", None) in calls
    assert ("review", "version-1", None, "approved") in calls
    assert ("publish", "page-1", "version-1") in calls

    create_call = next(call for call in calls if call[0] == "create")
    assert create_call[3] == ["doc-1"]


def test_generate_issue_page_defaults_parent_to_none(monkeypatch):
    calls = []
    monkeypatch.setattr(generation, "find_matching_issue_page", lambda *a, **k: None)
    monkeypatch.setattr(generation, "upsert_wiki_page", lambda *a, **k: calls.append(("upsert", a)) or "page-1")
    monkeypatch.setattr(generation, "create_wiki_version", lambda draft, **k: "version-1")
    monkeypatch.setattr(generation, "record_wiki_validation", lambda *a, **k: None)
    monkeypatch.setattr(generation, "review_wiki_version", lambda *a, **k: None)
    monkeypatch.setattr(generation, "publish_wiki_version", lambda *a, **k: None)

    generation._generate_issue_page(_section(), workspace_id="ws-1", requested_by=None)

    upsert_call = next(call for call in calls if call[0] == "upsert")
    assert upsert_call[1] == ("ws-1", "issue-hbm4-supply", "HBM4 공급 부족 심화", "issue", None)


def test_generate_issue_page_reuses_matched_page_identity(monkeypatch):
    calls = []
    matched = generation.WikiPageIdentity(
        page_id="page-existing", slug="issue-existing", title="기존 제목",
        page_type="issue", parent_page_id="page-parent-existing",
    )
    monkeypatch.setattr(generation, "find_matching_issue_page", lambda *a, **k: calls.append(("find", k)) or matched)
    monkeypatch.setattr(generation, "upsert_wiki_page", lambda *a, **k: calls.append(("upsert", a)) or "should-not-be-used")
    monkeypatch.setattr(
        generation, "create_wiki_version",
        lambda draft, **k: calls.append(
            ("create", draft.slug, draft.title, draft.page_type, draft.parent_page_id, draft.change_summary)
        ) or "version-new",
    )
    monkeypatch.setattr(generation, "record_wiki_validation", lambda *a, **k: None)
    monkeypatch.setattr(generation, "review_wiki_version", lambda *a, **k: None)
    monkeypatch.setattr(generation, "publish_wiki_version", lambda *a, **k: calls.append(("publish", a)))

    page_id, version_id = generation._generate_issue_page(_section(), workspace_id="ws-1", requested_by=None)

    assert page_id == "page-existing"
    assert version_id == "version-new"
    assert not any(call[0] == "upsert" for call in calls)  # 매칭됐으면 upsert_wiki_page를 호출하지 않는다
    create_call = next(call for call in calls if call[0] == "create")
    assert create_call[1:5] == ("issue-existing", "기존 제목", "issue", "page-parent-existing")
    assert create_call[5] == "리포트 파이프라인에서 기존 이슈 페이지 갱신"  # 매칭 시점엔 "갱신" 문구로 구분
    assert ("publish", ("page-existing", "version-new")) in calls
    find_call = next(call for call in calls if call[0] == "find")
    assert find_call[1]["category"] == _section().category.value


def test_generate_issue_page_adopts_new_parent_when_matched_page_has_none(monkeypatch):
    """매칭된 기존 페이지의 parent_page_id가 None으로 고착돼 있어도(예: 이전 회차
    주제 페이지 생성 실패), 이번 회차가 parent_page_id를 성공적으로 계산했다면
    그 값을 채택해야 한다 — 영원히 고아 상태로 남으면 안 된다."""
    calls = []
    matched = generation.WikiPageIdentity(
        page_id="page-existing", slug="issue-existing", title="기존 제목",
        page_type="issue", parent_page_id=None,
    )
    monkeypatch.setattr(generation, "find_matching_issue_page", lambda *a, **k: matched)
    monkeypatch.setattr(generation, "upsert_wiki_page", lambda *a, **k: calls.append(("upsert", a)) or "should-not-be-used")
    monkeypatch.setattr(
        generation, "create_wiki_version",
        lambda draft, **k: calls.append(("create", draft.parent_page_id)) or "version-new",
    )
    monkeypatch.setattr(generation, "record_wiki_validation", lambda *a, **k: None)
    monkeypatch.setattr(generation, "review_wiki_version", lambda *a, **k: None)
    monkeypatch.setattr(generation, "publish_wiki_version", lambda *a, **k: None)

    generation._generate_issue_page(
        _section(), workspace_id="ws-1", requested_by=None, parent_page_id="page-parent-new",
    )

    create_call = next(call for call in calls if call[0] == "create")
    assert create_call[1] == "page-parent-new"


def test_generate_issue_page_creates_new_when_no_match(monkeypatch):
    calls = []
    monkeypatch.setattr(generation, "find_matching_issue_page", lambda *a, **k: None)
    monkeypatch.setattr(generation, "upsert_wiki_page", lambda *a, **k: calls.append(("upsert", a)) or "page-new")
    monkeypatch.setattr(generation, "create_wiki_version", lambda draft, **k: calls.append(("create", draft.slug)) or "version-new")
    monkeypatch.setattr(generation, "record_wiki_validation", lambda *a, **k: None)
    monkeypatch.setattr(generation, "review_wiki_version", lambda *a, **k: None)
    monkeypatch.setattr(generation, "publish_wiki_version", lambda *a, **k: None)

    page_id, version_id = generation._generate_issue_page(_section("issue-hbm4-supply"), workspace_id="ws-1", requested_by=None)

    assert page_id == "page-new"
    upsert_call = next(call for call in calls if call[0] == "upsert")
    assert upsert_call[1][1] == "issue-hbm4-supply"  # section.issue_key 그대로 slug로 씀


def test_generate_issue_page_markdown_contains_all_sections():
    markdown = generation._build_issue_page_markdown(_section())
    assert "HBM4 공급 부족 심화" in markdown
    assert "HBM4 공급이 예상보다 더 타이트해지고 있다." in markdown
    assert "주요 고객사 수요 증가" in markdown
    assert "SK하이닉스 협상력 강화" in markdown
    assert "경쟁사 증발 발표 여부" not in markdown  # 오탈자 없이 원문 그대로 들어가는지
    assert "경쟁사 증설 발표 여부" in markdown


# ---------------------------------------------------------------------------
# 근거 텍스트(evidence_text) 매핑
# ---------------------------------------------------------------------------


def test_build_evidence_text_map_uses_summary_then_title():
    groups = [
        _enriched_group("issue-1", candidate_summary="HBM4 수요가 급증했다"),
        _enriched_group("issue-2", candidate_summary=None),
    ]
    mapping = generation.build_evidence_text_map(groups)
    assert mapping["issue-1"]["doc-1"] == "HBM4 수요가 급증했다"
    # summary가 없으면 title로 대체된다.
    assert mapping["issue-2"]["doc-1"] == "HBM4 공급 부족 심화"


def test_issue_page_markdown_uses_evidence_text_map():
    markdown = generation._build_issue_page_markdown(
        _section(), {"doc-1": "HBM4 수요가 급증했다"},
    )
    assert "- HBM4 수요가 급증했다" in markdown
    assert "document_version_id" not in markdown  # 원문 ID를 그대로 노출하지 않는다


def test_issue_page_markdown_attributes_source_name_and_date_instead_of_raw_id():
    from datetime import datetime, timezone

    candidate = ReportCandidate(
        analysis_result_id="analysis-1",
        workspace_id="ws-1",
        document_id="doc-1",
        document_version_id="doc-1",
        category=Category.PRODUCT_TECHNOLOGY,
        title="중국 턱밑 추격에…삼성·SK하이닉스, HBM·차세대 기술 개발 '전력투구' - 뉴시스",
        source_name="Google RSS - SK하이닉스",
        published_at=datetime(2026, 8, 2, 7, 23, 1, tzinfo=timezone.utc),
    )
    markdown = generation._build_issue_page_markdown(
        _section(),
        {"doc-1": candidate.title},
        {"doc-1": candidate},
    )
    assert (
        "- 중국 턱밑 추격에…삼성·SK하이닉스, HBM·차세대 기술 개발 '전력투구' - 뉴시스"
        " · Google RSS - SK하이닉스 · 2026.08.02" in markdown
    )
    assert "document_version_id" not in markdown


def test_build_citation_attribution_map_keys_by_issue_key_and_document_version_id():
    groups = [_enriched_group("issue-1", candidate_summary="HBM4 수요가 급증했다")]
    mapping = generation.build_citation_attribution_map(groups)
    assert mapping["issue-1"]["doc-1"].title == "HBM4 공급 부족 심화"


def test_issue_page_sources_use_evidence_text_map():
    sources = generation._build_issue_page_sources(
        _section(), {"doc-1": "HBM4 수요가 급증했다"},
    )
    assert [source.claim_text for source in sources] == ["HBM4 수요가 급증했다"]


def test_issue_page_sources_fall_back_to_empty_string_when_unmapped():
    sources = generation._build_issue_page_sources(_section(), {"doc-other": "관련 없음"})
    assert [source.claim_text for source in sources] == [""]


def test_issue_page_sources_fall_back_to_citation_evidence_text():
    sources = generation._build_issue_page_sources(_section(evidence_text="원문 근거"), None)
    assert [source.claim_text for source in sources] == ["원문 근거"]


def test_generate_wiki_drafts_threads_evidence_texts_into_both_pages(monkeypatch):
    seen: dict[str, object] = {}

    def fake_generate_topic_page(section, wiki_contexts, **kwargs):
        seen["topic"] = kwargs["evidence_texts"]
        return "skip", None, None

    def fake_generate_issue_page(section, **kwargs):
        seen["issue"] = kwargs["evidence_texts"]
        return "page-1", "version-1"

    monkeypatch.setattr(generation, "_generate_topic_page", fake_generate_topic_page)
    monkeypatch.setattr(generation, "_generate_issue_page", fake_generate_issue_page)
    monkeypatch.setattr(generation, "send_wiki_notification", lambda *a, **k: None)

    generation.generate_wiki_drafts_for_sections(
        [_section("issue-ok")],
        [_enriched_group("issue-ok", candidate_summary="HBM4 수요가 급증했다")],
        workspace_id="ws-1",
    )

    assert seen["topic"] == {"doc-1": "HBM4 수요가 급증했다"}
    assert seen["issue"] == {"doc-1": "HBM4 수요가 급증했다"}


def test_generate_wiki_drafts_threads_citation_attribution_into_both_pages(monkeypatch):
    seen: dict[str, object] = {}

    def fake_generate_topic_page(section, wiki_contexts, **kwargs):
        seen["topic"] = kwargs["citation_attribution"]
        return "skip", None, None

    def fake_generate_issue_page(section, **kwargs):
        seen["issue"] = kwargs["citation_attribution"]
        return "page-1", "version-1"

    monkeypatch.setattr(generation, "_generate_topic_page", fake_generate_topic_page)
    monkeypatch.setattr(generation, "_generate_issue_page", fake_generate_issue_page)
    monkeypatch.setattr(generation, "send_wiki_notification", lambda *a, **k: None)

    generation.generate_wiki_drafts_for_sections(
        [_section("issue-ok")],
        [_enriched_group("issue-ok", candidate_summary="HBM4 수요가 급증했다")],
        workspace_id="ws-1",
    )

    assert seen["topic"]["doc-1"].title == "HBM4 공급 부족 심화"
    assert seen["issue"]["doc-1"].title == "HBM4 공급 부족 심화"


def test_generate_topic_page_prompt_includes_mapped_evidence_text(monkeypatch):
    prompts: list[str] = []
    monkeypatch.setattr(generation, "list_top_level_topic_pages", lambda workspace_id, supabase=None: [])

    def fake_completion(**kwargs):
        prompts.append(kwargs["user_prompt"])
        return json.dumps({"action": "skip", "claims": [], "confidence_score": 0.1})

    monkeypatch.setattr(generation, "create_json_completion", fake_completion)

    generation._generate_topic_page(
        _section(), [], workspace_id="ws-1", requested_by=None,
        evidence_texts={"doc-1": "HBM4 수요가 급증했다"},
    )

    assert "document_version_id=doc-1 citation_order=1: HBM4 수요가 급증했다" in prompts[0]


# ---------------------------------------------------------------------------
# 주제 페이지 생성
# ---------------------------------------------------------------------------


def test_generate_topic_page_skips_when_llm_returns_skip(monkeypatch):
    monkeypatch.setattr(generation, "list_top_level_topic_pages", lambda workspace_id, supabase=None: [])
    monkeypatch.setattr(
        generation,
        "create_json_completion",
        lambda **kwargs: json.dumps({"action": "skip", "claims": [], "confidence_score": 0.1}),
    )

    action, page_id, version_id = generation._generate_topic_page(
        _section(), [], workspace_id="ws-1", requested_by=None,
    )

    assert action == "skip"
    assert page_id is None
    assert version_id is None


def test_generate_topic_page_updates_existing_when_confidence_high(monkeypatch):
    calls = []
    _patch_topic_candidates_filter(monkeypatch)
    monkeypatch.setattr(generation, "list_top_level_topic_pages", lambda workspace_id, supabase=None: [])
    monkeypatch.setattr(
        generation,
        "get_wiki_page_identity",
        lambda page_id, *, workspace_id, supabase=None: generation.WikiPageIdentity(
            page_id="page-existing", slug="hbm4-supply", title="HBM4_수급현황",
            page_type="technology", parent_page_id="page-parent",
        ),
    )
    monkeypatch.setattr(
        generation,
        "create_json_completion",
        lambda **kwargs: json.dumps(
            {
                "action": "update_existing",
                "target_wiki_page_id": "page-existing",
                "markdown": "# 갱신된 본문",
                "change_summary": "신규 근거 반영",
                "claims": [{"document_version_id": "doc-1", "claim_text": "근거", "citation_order": 1}],
                "confidence_score": 0.9,
            }
        ),
    )
    monkeypatch.setattr(
        generation, "create_wiki_version",
        lambda draft, **k: calls.append(("create", draft.slug, draft.page_type, draft.parent_page_id)) or "version-2",
    )
    monkeypatch.setattr(generation, "record_wiki_validation", lambda *a, **k: calls.append(("validate", a)))
    monkeypatch.setattr(generation, "review_wiki_version", lambda *a, **k: calls.append(("review", a)))
    monkeypatch.setattr(generation, "publish_wiki_version", lambda *a, **k: calls.append(("publish", a)))

    wiki_context = WikiContext(wiki_page_id="page-existing", title="HBM4_수급현황", content="기존 본문")
    action, page_id, version_id = generation._generate_topic_page(
        _section(), [wiki_context], workspace_id="ws-1", requested_by=None,
    )

    assert action == "update_existing"
    assert page_id == "page-existing"
    assert version_id == "version-2"
    assert ("create", "hbm4-supply", "technology", "page-parent") in calls
    assert ("publish", ("page-existing", "version-2")) in calls


def test_generate_topic_page_skips_when_target_page_identity_missing(monkeypatch):
    _patch_topic_candidates_filter(monkeypatch)
    monkeypatch.setattr(generation, "list_top_level_topic_pages", lambda workspace_id, supabase=None: [])
    monkeypatch.setattr(generation, "get_wiki_page_identity", lambda page_id, *, workspace_id, supabase=None: None)
    monkeypatch.setattr(
        generation,
        "create_json_completion",
        lambda **kwargs: json.dumps(
            {
                "action": "update_existing",
                "target_wiki_page_id": "page-deleted",
                "markdown": "# 갱신된 본문",
                "claims": [{"document_version_id": "doc-1", "claim_text": "근거", "citation_order": 1}],
                "confidence_score": 0.9,
            }
        ),
    )

    wiki_context = WikiContext(wiki_page_id="page-deleted", title="삭제된 페이지", content="본문")
    action, page_id, version_id = generation._generate_topic_page(
        _section(), [wiki_context], workspace_id="ws-1", requested_by=None,
    )

    assert action == "skip"
    assert page_id is None
    assert version_id is None


def test_generate_topic_page_creates_new_under_chosen_parent(monkeypatch):
    calls = []
    top_level = generation.TopLevelTopicPage(wiki_page_id="page-parent", title="SK하이닉스", page_type="company")
    monkeypatch.setattr(generation, "list_top_level_topic_pages", lambda workspace_id, supabase=None: [top_level])
    monkeypatch.setattr(
        generation,
        "create_json_completion",
        lambda **kwargs: json.dumps(
            {
                "action": "create_new",
                "slug": "hbm4-supply",
                "title": "HBM4_수급현황",
                "page_type": "technology",
                "parent_page_id": "page-parent",
                "markdown": "# HBM4_수급현황",
                "change_summary": "최초 생성",
                "claims": [{"document_version_id": "doc-1", "claim_text": "근거", "citation_order": 1}],
                "confidence_score": 0.85,
            }
        ),
    )
    monkeypatch.setattr(generation, "upsert_wiki_page", lambda *a, **k: calls.append(("upsert", a)) or "page-new")
    monkeypatch.setattr(generation, "create_wiki_version", lambda draft, **k: "version-4")
    monkeypatch.setattr(generation, "record_wiki_validation", lambda *a, **k: None)
    monkeypatch.setattr(generation, "review_wiki_version", lambda *a, **k: None)
    monkeypatch.setattr(generation, "publish_wiki_version", lambda *a, **k: None)

    action, page_id, version_id = generation._generate_topic_page(
        _section(), [], workspace_id="ws-1", requested_by=None,
    )

    assert action == "create_new"
    assert page_id == "page-new"
    upsert_call = next(call for call in calls if call[0] == "upsert")
    assert upsert_call[1] == ("ws-1", "hbm4-supply", "HBM4_수급현황", "technology", "page-parent")


def test_generate_topic_page_skips_when_title_duplicates_issue_title(monkeypatch):
    """토픽 제목이 이슈 제목(section.title)과 사실상 같으면(자기 자신을 참조하는 꼴)
    LLM이 create_new를 반환해도 페이지를 만들지 않고 skip으로 처리해야 한다 —
    실사용 데이터에서 발견된 이슈/토픽 중복 생성 버그의 회귀 테스트."""
    calls = []
    monkeypatch.setattr(generation, "list_top_level_topic_pages", lambda workspace_id, supabase=None: [])
    monkeypatch.setattr(
        generation,
        "create_json_completion",
        lambda **kwargs: json.dumps(
            {
                "action": "create_new",
                "slug": "hbm4-supply-shortage-2026",
                "title": "HBM4 공급 부족 심화",  # _section()의 title과 완전히 동일
                "page_type": "market",
                "parent_page_id": None,
                "markdown": "# HBM4 공급 부족 심화",
                "change_summary": "최초 생성",
                "claims": [{"document_version_id": "doc-1", "claim_text": "근거", "citation_order": 1}],
                "confidence_score": 0.85,
            }
        ),
    )
    monkeypatch.setattr(generation, "upsert_wiki_page", lambda *a, **k: calls.append(("upsert", a)) or "page-new")
    monkeypatch.setattr(generation, "create_wiki_version", lambda draft, **k: calls.append(("create", draft.slug)) or "version-4")
    monkeypatch.setattr(generation, "record_wiki_validation", lambda *a, **k: calls.append(("validate", a)))
    monkeypatch.setattr(generation, "review_wiki_version", lambda *a, **k: calls.append(("review", a)))
    monkeypatch.setattr(generation, "publish_wiki_version", lambda *a, **k: calls.append(("publish", a)))

    action, page_id, version_id = generation._generate_topic_page(
        _section(), [], workspace_id="ws-1", requested_by=None,
    )

    assert action == "skip"
    assert page_id is None
    assert version_id is None
    assert calls == []  # DB에 아무것도 쓰지 않아야 한다


def test_generate_topic_page_creates_when_title_meaningfully_broader(monkeypatch):
    """제목이 이슈와 다르면(넓은 주제) 정상적으로 create_new가 진행되어야 한다 —
    중복 가드가 정당한 create_new까지 막지 않는지 확인."""
    calls = []
    monkeypatch.setattr(generation, "list_top_level_topic_pages", lambda workspace_id, supabase=None: [])
    monkeypatch.setattr(
        generation,
        "create_json_completion",
        lambda **kwargs: json.dumps(
            {
                "action": "create_new",
                "slug": "hbm4-supply",
                "title": "HBM4_수급현황",
                "page_type": "technology",
                "parent_page_id": None,
                "markdown": "# HBM4_수급현황",
                "change_summary": "최초 생성",
                "claims": [{"document_version_id": "doc-1", "claim_text": "근거", "citation_order": 1}],
                "confidence_score": 0.85,
            }
        ),
    )
    monkeypatch.setattr(generation, "upsert_wiki_page", lambda *a, **k: calls.append(("upsert", a)) or "page-new")
    monkeypatch.setattr(generation, "create_wiki_version", lambda draft, **k: "version-4")
    monkeypatch.setattr(generation, "record_wiki_validation", lambda *a, **k: None)
    monkeypatch.setattr(generation, "review_wiki_version", lambda *a, **k: None)
    monkeypatch.setattr(generation, "publish_wiki_version", lambda *a, **k: None)

    action, page_id, version_id = generation._generate_topic_page(
        _section(), [], workspace_id="ws-1", requested_by=None,
    )

    assert action == "create_new"
    assert page_id == "page-new"
    assert calls  # upsert가 호출됨


def test_generate_topic_page_falls_back_to_industry_on_invalid_page_type(monkeypatch):
    """설계(2026-08-04, wiki-page-type-expansion): LLM이 스키마 밖 page_type을 지어내도
    industry로 대체해 생성 자체는 막히지 않아야 한다."""
    calls = []
    monkeypatch.setattr(generation, "list_top_level_topic_pages", lambda workspace_id, supabase=None: [])
    monkeypatch.setattr(
        generation,
        "create_json_completion",
        lambda **kwargs: json.dumps(
            {
                "action": "create_new",
                "slug": "market-mgmt-issue",
                "title": "시장·경영 이슈",
                "page_type": "market_management",  # 스키마(7종) 밖 값 — LLM이 지어낸 값
                "parent_page_id": None,
                "markdown": "# 시장·경영 이슈",
                "change_summary": "최초 생성",
                "claims": [{"document_version_id": "doc-1", "claim_text": "근거", "citation_order": 1}],
                "confidence_score": 0.85,
            }
        ),
    )
    monkeypatch.setattr(generation, "upsert_wiki_page", lambda *a, **k: calls.append(("upsert", a)) or "page-new")
    monkeypatch.setattr(generation, "create_wiki_version", lambda draft, **k: "version-4")
    monkeypatch.setattr(generation, "record_wiki_validation", lambda *a, **k: None)
    monkeypatch.setattr(generation, "review_wiki_version", lambda *a, **k: None)
    monkeypatch.setattr(generation, "publish_wiki_version", lambda *a, **k: None)

    action, page_id, version_id = generation._generate_topic_page(
        _section(), [], workspace_id="ws-1", requested_by=None,
    )

    assert action == "create_new"
    assert page_id == "page-new"
    upsert_call = next(call for call in calls if call[0] == "upsert")
    assert upsert_call[1] == ("ws-1", "market-mgmt-issue", "시장·경영 이슈", "industry", None)


def test_generate_topic_page_auto_publishes_even_when_confidence_low(monkeypatch):
    """설계 §5(2026-08-04 개정): 신뢰도 게이트 폐지 — confidence가 낮아도 항상 자동 승인·발행."""
    calls = []
    monkeypatch.setattr(generation, "list_top_level_topic_pages", lambda workspace_id, supabase=None: [])
    monkeypatch.setattr(
        generation,
        "create_json_completion",
        lambda **kwargs: json.dumps(
            {
                "action": "create_new",
                "slug": "new-topic",
                "title": "새 주제",
                "page_type": "technology",
                "parent_page_id": None,
                "markdown": "# 새 주제",
                "change_summary": "최초 생성",
                "claims": [{"document_version_id": "doc-1", "claim_text": "근거", "citation_order": 1}],
                "confidence_score": 0.3,
            }
        ),
    )
    monkeypatch.setattr(generation, "upsert_wiki_page", lambda *a, **k: "page-new")
    monkeypatch.setattr(generation, "create_wiki_version", lambda draft, **k: "version-3")
    monkeypatch.setattr(generation, "record_wiki_validation", lambda *a, **k: calls.append(("validate", a)))
    monkeypatch.setattr(generation, "review_wiki_version", lambda *a, **k: calls.append(("review", a)))
    monkeypatch.setattr(generation, "publish_wiki_version", lambda *a, **k: calls.append(("publish", a)))

    action, page_id, version_id = generation._generate_topic_page(
        _section(), [], workspace_id="ws-1", requested_by=None,
    )

    assert action == "create_new"
    assert page_id == "page-new"
    assert version_id == "version-3"
    assert ("validate", ("version-3", "passed", 0.3)) in calls
    assert ("review", ("version-3", None, "approved")) in calls
    assert ("publish", ("page-new", "version-3")) in calls


# ---------------------------------------------------------------------------
# LLM이 돌려준 식별자 검증
# ---------------------------------------------------------------------------


def test_generate_topic_page_drops_issue_pages_from_candidates(monkeypatch):
    """자동 발행된 이슈 페이지는 주제 후보로 LLM에 노출되지 않는다."""
    prompts: list[str] = []
    monkeypatch.setattr(generation, "list_top_level_topic_pages", lambda workspace_id, supabase=None: [])
    _patch_topic_candidates_filter(monkeypatch, allowed={"page-topic"})

    def fake_completion(**kwargs):
        prompts.append(kwargs["user_prompt"])
        return json.dumps({"action": "skip", "claims": []})

    monkeypatch.setattr(generation, "create_json_completion", fake_completion)

    contexts = [
        WikiContext(wiki_page_id="page-topic", title="HBM4_수급현황", content="주제 본문"),
        WikiContext(wiki_page_id="page-issue", title="이슈 페이지", content="이슈 본문"),
    ]
    generation._generate_topic_page(_section(), contexts, workspace_id="ws-1", requested_by=None)

    assert "wiki_page_id=page-topic" in prompts[0]
    assert "wiki_page_id=page-issue" not in prompts[0]


def test_generate_topic_page_skips_when_all_claims_reference_unknown_documents(monkeypatch):
    monkeypatch.setattr(generation, "list_top_level_topic_pages", lambda workspace_id, supabase=None: [])
    monkeypatch.setattr(
        generation,
        "create_json_completion",
        lambda **kwargs: json.dumps(
            {
                "action": "create_new",
                "slug": "new-topic",
                "title": "새 주제",
                "page_type": "technology",
                "markdown": "# 새 주제",
                "claims": [{"document_version_id": "doc-hallucinated", "claim_text": "근거", "citation_order": 1}],
                "confidence_score": 0.9,
            }
        ),
    )

    action, page_id, version_id = generation._generate_topic_page(
        _section(), [], workspace_id="ws-1", requested_by=None,
    )

    assert action == "skip"
    assert page_id is None
    assert version_id is None


def test_generate_topic_page_filters_unknown_document_ids_from_sources(monkeypatch):
    drafts = []
    monkeypatch.setattr(generation, "list_top_level_topic_pages", lambda workspace_id, supabase=None: [])
    monkeypatch.setattr(
        generation,
        "create_json_completion",
        lambda **kwargs: json.dumps(
            {
                "action": "create_new",
                "slug": "new-topic",
                "title": "새 주제",
                "page_type": "technology",
                "markdown": "# 새 주제",
                "claims": [
                    {"document_version_id": "doc-1", "claim_text": "실제 근거", "citation_order": 1},
                    {"document_version_id": "doc-hallucinated", "claim_text": "허구", "citation_order": 2},
                ],
                "confidence_score": 0.9,
            }
        ),
    )
    monkeypatch.setattr(generation, "upsert_wiki_page", lambda *a, **k: "page-new")
    monkeypatch.setattr(generation, "create_wiki_version", lambda draft, **k: drafts.append(draft) or "version-9")
    monkeypatch.setattr(generation, "record_wiki_validation", lambda *a, **k: None)
    monkeypatch.setattr(generation, "review_wiki_version", lambda *a, **k: None)
    monkeypatch.setattr(generation, "publish_wiki_version", lambda *a, **k: None)

    generation._generate_topic_page(_section(), [], workspace_id="ws-1", requested_by=None)

    assert [source.document_version_id for source in drafts[0].sources] == ["doc-1"]


def test_generate_topic_page_ignores_unknown_parent_page_id(monkeypatch):
    calls = []
    top_level = generation.TopLevelTopicPage(wiki_page_id="page-parent", title="SK하이닉스", page_type="company")
    monkeypatch.setattr(generation, "list_top_level_topic_pages", lambda workspace_id, supabase=None: [top_level])
    monkeypatch.setattr(
        generation,
        "create_json_completion",
        lambda **kwargs: json.dumps(
            {
                "action": "create_new",
                "slug": "new-topic",
                "title": "새 주제",
                "page_type": "technology",
                "parent_page_id": "page-hallucinated",
                "markdown": "# 새 주제",
                "claims": [{"document_version_id": "doc-1", "claim_text": "근거", "citation_order": 1}],
                "confidence_score": 0.9,
            }
        ),
    )
    monkeypatch.setattr(generation, "upsert_wiki_page", lambda *a, **k: calls.append(("upsert", a)) or "page-new")
    monkeypatch.setattr(generation, "create_wiki_version", lambda draft, **k: calls.append(("create", draft.parent_page_id)) or "version-5")
    monkeypatch.setattr(generation, "record_wiki_validation", lambda *a, **k: None)
    monkeypatch.setattr(generation, "review_wiki_version", lambda *a, **k: None)
    monkeypatch.setattr(generation, "publish_wiki_version", lambda *a, **k: None)

    generation._generate_topic_page(_section(), [], workspace_id="ws-1", requested_by=None)

    upsert_call = next(call for call in calls if call[0] == "upsert")
    assert upsert_call[1][4] is None
    assert ("create", None) in calls


def test_generate_topic_page_skips_when_target_page_not_in_candidates(monkeypatch):
    """LLM이 후보로 보여주지 않은 페이지 id를 돌려주면 조회조차 하지 않는다."""
    _patch_topic_candidates_filter(monkeypatch)
    monkeypatch.setattr(generation, "list_top_level_topic_pages", lambda workspace_id, supabase=None: [])

    def exploding_identity(page_id, *, workspace_id, supabase=None):  # pragma: no cover
        raise AssertionError("후보 밖 페이지는 조회하면 안 된다.")

    monkeypatch.setattr(generation, "get_wiki_page_identity", exploding_identity)
    monkeypatch.setattr(
        generation,
        "create_json_completion",
        lambda **kwargs: json.dumps(
            {
                "action": "update_existing",
                "target_wiki_page_id": "page-other-workspace",
                "markdown": "# 갱신된 본문",
                "claims": [{"document_version_id": "doc-1", "claim_text": "근거", "citation_order": 1}],
                "confidence_score": 0.9,
            }
        ),
    )

    wiki_context = WikiContext(wiki_page_id="page-known", title="알려진 주제", content="본문")
    action, page_id, version_id = generation._generate_topic_page(
        _section(), [wiki_context], workspace_id="ws-1", requested_by=None,
    )

    assert action == "skip"
    assert page_id is None
    assert version_id is None


def test_generate_topic_page_passes_workspace_id_to_identity_lookup(monkeypatch):
    seen: dict[str, object] = {}
    _patch_topic_candidates_filter(monkeypatch)
    monkeypatch.setattr(generation, "list_top_level_topic_pages", lambda workspace_id, supabase=None: [])

    def fake_identity(page_id, *, workspace_id, supabase=None):
        seen["workspace_id"] = workspace_id
        return None

    monkeypatch.setattr(generation, "get_wiki_page_identity", fake_identity)
    monkeypatch.setattr(
        generation,
        "create_json_completion",
        lambda **kwargs: json.dumps(
            {
                "action": "update_existing",
                "target_wiki_page_id": "page-known",
                "markdown": "# 갱신된 본문",
                "claims": [{"document_version_id": "doc-1", "claim_text": "근거", "citation_order": 1}],
                "confidence_score": 0.9,
            }
        ),
    )

    wiki_context = WikiContext(wiki_page_id="page-known", title="알려진 주제", content="본문")
    generation._generate_topic_page(
        _section(), [wiki_context], workspace_id="ws-1", requested_by=None,
    )

    assert seen["workspace_id"] == "ws-1"


@pytest.mark.parametrize("markdown", [None, "", "   \n  "])
def test_generate_topic_page_skips_when_markdown_is_blank(monkeypatch, markdown):
    monkeypatch.setattr(generation, "list_top_level_topic_pages", lambda workspace_id, supabase=None: [])

    def exploding_create(draft, **kwargs):  # pragma: no cover
        raise AssertionError("빈 본문으로 버전을 만들면 안 된다.")

    monkeypatch.setattr(generation, "create_wiki_version", exploding_create)
    monkeypatch.setattr(
        generation,
        "create_json_completion",
        lambda **kwargs: json.dumps(
            {
                "action": "create_new",
                "slug": "new-topic",
                "title": "새 주제",
                "page_type": "technology",
                "markdown": markdown,
                "claims": [{"document_version_id": "doc-1", "claim_text": "근거", "citation_order": 1}],
                "confidence_score": 0.9,
            }
        ),
    )

    action, page_id, version_id = generation._generate_topic_page(
        _section(), [], workspace_id="ws-1", requested_by=None,
    )

    assert action == "skip"
    assert page_id is None
    assert version_id is None


# ---------------------------------------------------------------------------
# 의존성 주입 (supabase / llm_client)
# ---------------------------------------------------------------------------


def test_generate_topic_page_uses_injected_llm_client(monkeypatch):
    seen: dict[str, object] = {}
    monkeypatch.setattr(generation, "list_top_level_topic_pages", lambda workspace_id, supabase=None: [])

    def exploding_completion(**kwargs):  # pragma: no cover
        raise AssertionError("llm_client가 주입되면 실제 API를 부르면 안 된다.")

    monkeypatch.setattr(generation, "create_json_completion", exploding_completion)

    def fake_llm(system_prompt, user_prompt, model):
        seen["system_prompt"] = system_prompt
        return json.dumps({"action": "skip", "claims": []})

    action, _page_id, _version_id = generation._generate_topic_page(
        _section(), [], workspace_id="ws-1", requested_by=None, llm_client=fake_llm,
    )

    assert action == "skip"
    assert seen["system_prompt"] == generation.WIKI_TOPIC_SYSTEM_PROMPT


def test_generate_topic_page_threads_supabase_into_repository_and_writes(monkeypatch):
    seen: list[object] = []
    sentinel = object()

    monkeypatch.setattr(
        generation, "list_top_level_topic_pages",
        lambda workspace_id, supabase=None: seen.append(supabase) or [],
    )
    monkeypatch.setattr(generation, "upsert_wiki_page", lambda *a, supabase=None, **k: seen.append(supabase) or "page-new")
    monkeypatch.setattr(generation, "create_wiki_version", lambda draft, supabase=None: seen.append(supabase) or "version-1")
    monkeypatch.setattr(generation, "record_wiki_validation", lambda *a, supabase=None: seen.append(supabase))
    monkeypatch.setattr(generation, "review_wiki_version", lambda *a, supabase=None: seen.append(supabase))
    monkeypatch.setattr(generation, "publish_wiki_version", lambda *a, supabase=None: seen.append(supabase))

    generation._generate_topic_page(
        _section(), [], workspace_id="ws-1", requested_by=None, supabase=sentinel,
        llm_client=lambda *_a: json.dumps(
            {
                "action": "create_new",
                "slug": "new-topic",
                "title": "새 주제",
                "page_type": "technology",
                "markdown": "# 새 주제",
                "claims": [{"document_version_id": "doc-1", "claim_text": "근거", "citation_order": 1}],
                "confidence_score": 0.9,
            }
        ),
    )

    assert seen and all(item is sentinel for item in seen)


def test_generate_issue_page_threads_supabase_into_writes(monkeypatch):
    seen: list[object] = []
    sentinel = object()

    monkeypatch.setattr(generation, "find_matching_issue_page", lambda *a, supabase=None, **k: None)
    monkeypatch.setattr(generation, "upsert_wiki_page", lambda *a, supabase=None, **k: seen.append(supabase) or "page-1")
    monkeypatch.setattr(generation, "create_wiki_version", lambda draft, supabase=None: seen.append(supabase) or "version-1")
    monkeypatch.setattr(generation, "record_wiki_validation", lambda *a, supabase=None: seen.append(supabase))
    monkeypatch.setattr(generation, "review_wiki_version", lambda *a, supabase=None: seen.append(supabase))
    monkeypatch.setattr(generation, "publish_wiki_version", lambda *a, supabase=None: seen.append(supabase))

    generation._generate_issue_page(
        _section(), workspace_id="ws-1", requested_by=None, supabase=sentinel,
    )

    assert len(seen) == 5
    assert all(item is sentinel for item in seen)


def test_generate_wiki_drafts_for_sections_threads_injected_clients(monkeypatch):
    seen: dict[str, object] = {}
    supabase = object()
    llm_client = object()

    def fake_generate_topic_page(section, wiki_contexts, **kwargs):
        seen["topic_supabase"] = kwargs["supabase"]
        seen["topic_llm_client"] = kwargs["llm_client"]
        return "skip", None, None

    def fake_generate_issue_page(section, **kwargs):
        seen["issue_supabase"] = kwargs["supabase"]
        return "page-1", "version-1"

    monkeypatch.setattr(generation, "_generate_topic_page", fake_generate_topic_page)
    monkeypatch.setattr(generation, "_generate_issue_page", fake_generate_issue_page)
    monkeypatch.setattr(generation, "send_wiki_notification", lambda *a, **k: None)

    generation.generate_wiki_drafts_for_sections(
        [_section("issue-ok")],
        [_enriched_group("issue-ok")],
        workspace_id="ws-1",
        supabase=supabase,
        llm_client=llm_client,
    )

    assert seen["topic_supabase"] is supabase
    assert seen["topic_llm_client"] is llm_client
    assert seen["issue_supabase"] is supabase


# ---------------------------------------------------------------------------
# 오케스트레이션
# ---------------------------------------------------------------------------


def _enriched_group(
    issue_key: str,
    wiki_contexts=None,
    candidate_summary: str | None = None,
) -> EnrichedIssueGroup:
    candidate = ReportCandidate(
        analysis_result_id="analysis-1",
        workspace_id="ws-1",
        document_id="doc-1",
        document_version_id="doc-1",
        category=Category.PRODUCT_TECHNOLOGY,
        title="HBM4 공급 부족 심화",
        summary=candidate_summary,
        reliability_score=80,
        importance_score=85,
        ranking_score=90,
    )
    return EnrichedIssueGroup(
        issue_group=IssueGroup(issue_key=issue_key, category=Category.PRODUCT_TECHNOLOGY, candidates=[candidate]),
        wiki_contexts=wiki_contexts or [],
    )


def test_generate_wiki_drafts_for_sections_isolates_issue_page_failures(monkeypatch):
    """토픽 생성은 성공했는데 이슈 페이지 생성이 실패해도, 다른 이슈 처리는 막지 않는다."""
    section_ok = _section("issue-ok")
    section_fail = _section("issue-fail")

    def fake_generate_topic_page(section, wiki_contexts, **kwargs):
        return "skip", None, None

    def fake_generate_issue_page(section, **kwargs):
        if section.issue_key == "issue-fail":
            raise RuntimeError("Storage 업로드 실패")
        return "page-ok", "version-ok"

    monkeypatch.setattr(generation, "_generate_topic_page", fake_generate_topic_page)
    monkeypatch.setattr(generation, "_generate_issue_page", fake_generate_issue_page)
    monkeypatch.setattr(generation, "send_wiki_notification", lambda *a, **k: None)

    results = generation.generate_wiki_drafts_for_sections(
        [section_ok, section_fail],
        [_enriched_group("issue-ok"), _enriched_group("issue-fail")],
        workspace_id="ws-1",
    )

    assert len(results) == 2
    ok_result = next(r for r in results if r.issue_key == "issue-ok")
    fail_result = next(r for r in results if r.issue_key == "issue-fail")
    assert ok_result.issue_page_id == "page-ok"
    assert fail_result.issue_page_id == ""
    assert fail_result.error_message is not None


def test_generate_wiki_drafts_for_sections_isolates_topic_page_failures(monkeypatch):
    """토픽 생성이 LLM 오류로 실패해도 이슈 페이지는 정상 생성된다."""

    def fake_generate_topic_page(section, wiki_contexts, **kwargs):
        raise RuntimeError("LLM JSON 파싱 실패")

    def fake_generate_issue_page(section, **kwargs):
        return "page-ok", "version-ok"

    monkeypatch.setattr(generation, "_generate_topic_page", fake_generate_topic_page)
    monkeypatch.setattr(generation, "_generate_issue_page", fake_generate_issue_page)
    monkeypatch.setattr(generation, "send_wiki_notification", lambda *a, **k: None)

    results = generation.generate_wiki_drafts_for_sections(
        [_section("issue-ok")],
        [_enriched_group("issue-ok")],
        workspace_id="ws-1",
    )

    assert len(results) == 1
    assert results[0].issue_page_id == "page-ok"
    assert results[0].topic_action == "failed"
    assert results[0].error_message is not None


def test_generate_wiki_drafts_for_sections_links_issue_page_to_resolved_topic(monkeypatch):
    """토픽 페이지가 만들어지면, 이슈 페이지의 parent_page_id로 그 id가 전달된다."""
    seen_parent_ids = []

    monkeypatch.setattr(
        generation,
        "_generate_topic_page",
        lambda section, wiki_contexts, **kwargs: ("create_new", "page-topic", "version-topic"),
    )

    def fake_generate_issue_page(section, *, parent_page_id=None, **kwargs):
        seen_parent_ids.append(parent_page_id)
        return "page-issue", "version-issue"

    monkeypatch.setattr(generation, "_generate_issue_page", fake_generate_issue_page)
    monkeypatch.setattr(generation, "send_wiki_notification", lambda *a, **k: None)

    generation.generate_wiki_drafts_for_sections(
        [_section("issue-ok")],
        [_enriched_group("issue-ok")],
        workspace_id="ws-1",
    )

    assert seen_parent_ids == ["page-topic"]


def test_generate_wiki_drafts_for_sections_passes_matching_wiki_contexts(monkeypatch):
    seen_contexts = []

    def fake_generate_topic_page(section, wiki_contexts, **kwargs):
        seen_contexts.append(wiki_contexts)
        return "skip", None, None

    monkeypatch.setattr(generation, "_generate_topic_page", fake_generate_topic_page)
    monkeypatch.setattr(
        generation, "_generate_issue_page", lambda section, **kwargs: ("page-1", "version-1")
    )
    monkeypatch.setattr(generation, "send_wiki_notification", lambda *a, **k: None)

    wiki_context = WikiContext(wiki_page_id="page-existing", title="HBM4_수급현황", content="본문")
    generation.generate_wiki_drafts_for_sections(
        [_section("issue-ok")],
        [_enriched_group("issue-ok", wiki_contexts=[wiki_context])],
        workspace_id="ws-1",
    )

    assert seen_contexts == [[wiki_context]]


def test_archive_stale_wiki_pages_archives_each_stale_id(monkeypatch):
    archived = []
    monkeypatch.setattr(
        generation, "find_stale_published_page_ids",
        lambda workspace_id, *, staleness_days, supabase=None: ["page-1", "page-2"],
    )
    monkeypatch.setattr(generation, "archive_wiki_page", lambda page_id, supabase=None: archived.append(page_id))

    result = generation.archive_stale_wiki_pages("ws-1", staleness_days=90)

    assert result == ["page-1", "page-2"]
    assert archived == ["page-1", "page-2"]


def test_archive_stale_wiki_pages_returns_empty_when_none_stale(monkeypatch):
    monkeypatch.setattr(
        generation, "find_stale_published_page_ids",
        lambda workspace_id, *, staleness_days, supabase=None: [],
    )
    result = generation.archive_stale_wiki_pages("ws-1")
    assert result == []


# ---------------------------------------------------------------------------
# 리포트와 별개의 위키 갱신 오케스트레이션
# ---------------------------------------------------------------------------

from datetime import datetime, timedelta, timezone


def test_refresh_wiki_from_recent_analysis_runs_pipeline_and_skips_report_persistence(monkeypatch):
    calls = []
    sentinel_supabase = object()

    candidate = ReportCandidate(
        analysis_result_id="analysis-1",
        workspace_id="ws-1",
        document_id="doc-1",
        document_version_id="doc-ver-1",
        category=Category.PRODUCT_TECHNOLOGY,
        title="HBM4 공급 부족 심화",
        reliability_score=80,
        importance_score=85,
        ranking_score=Decimal("90"),
    )
    issue_group = IssueGroup(issue_key="issue-1", category=Category.PRODUCT_TECHNOLOGY, candidates=[candidate])
    enriched_group = EnrichedIssueGroup(issue_group=issue_group, wiki_contexts=[])
    section = _section("issue-1")

    monkeypatch.setattr(generation, "get_recently_analyzed_candidates", lambda *, workspace_id, since, supabase=None: calls.append(("candidates", workspace_id, since)) or [candidate])
    monkeypatch.setattr(generation, "select_report_candidates", lambda candidates, **kwargs: calls.append(("select", len(candidates))) or candidates)
    monkeypatch.setattr(generation, "group_report_candidates", lambda candidates, **kwargs: calls.append(("group", len(candidates))) or [issue_group])
    monkeypatch.setattr(generation, "enrich_issue_groups", lambda groups, **kwargs: calls.append(("enrich", len(groups))) or [enriched_group])
    monkeypatch.setattr(generation, "compose_report_sections", lambda groups, **kwargs: calls.append(("compose", len(groups))) or [section])
    monkeypatch.setattr(generation, "generate_wiki_drafts_for_sections", lambda sections, groups, **kwargs: calls.append(("wiki", len(sections), kwargs)) or [])

    result = generation.refresh_wiki_from_recent_analysis("ws-1", since_hours=2, supabase=sentinel_supabase)

    assert result == []
    call_names = [c[0] for c in calls]
    assert call_names == ["candidates", "select", "group", "enrich", "compose", "wiki"]
    assert calls[0][1] == "ws-1"
    wiki_kwargs = calls[5][2]
    assert wiki_kwargs.get("workspace_id") == "ws-1"
    # supabase가 읽기 경로(get_recently_analyzed_candidates 등)뿐 아니라
    # 쓰기 경로(generate_wiki_drafts_for_sections)에도 동일하게 전달돼야 한다.
    assert wiki_kwargs.get("supabase") is sentinel_supabase

    # report_sections/reports 저장 함수는 wiki.generation 네임스페이스에 아예 없어야 한다
    # (구조적으로 리포트 영속화가 불가능함을 보장).
    for name in ("save_report_sections", "mark_report_completed", "create_report_version", "create_and_save_markdown_artifact"):
        assert not hasattr(generation, name)


def test_refresh_wiki_from_recent_analysis_passes_empty_list_through_all_stages(monkeypatch):
    calls = []
    monkeypatch.setattr(generation, "get_recently_analyzed_candidates", lambda **kwargs: [])
    monkeypatch.setattr(generation, "select_report_candidates", lambda *a, **k: calls.append("select") or [])
    monkeypatch.setattr(generation, "group_report_candidates", lambda *a, **k: calls.append("group") or [])
    monkeypatch.setattr(generation, "enrich_issue_groups", lambda *a, **k: calls.append("enrich") or [])
    monkeypatch.setattr(generation, "compose_report_sections", lambda *a, **k: calls.append("compose") or [])
    monkeypatch.setattr(generation, "generate_wiki_drafts_for_sections", lambda *a, **k: calls.append("wiki") or [])

    result = generation.refresh_wiki_from_recent_analysis("ws-1")

    assert result == []
    # 후보가 없어도 조기 종료하지 않는다: 각 단계가 빈 리스트를 그대로 받아
    # 예외 없이 no-op으로 통과하며, 마지막 단계까지 전부 호출된다.
    assert calls == ["select", "group", "enrich", "compose", "wiki"]


def test_generate_wiki_drafts_for_sections_sends_one_notification_for_batch(monkeypatch):
    """이슈 1건 + 주제 1건이 발행되면 알림은 딱 한 번, 합산 건수(2)로 호출된다."""
    calls = []
    monkeypatch.setattr(
        generation, "_generate_topic_page",
        lambda section, wiki_contexts, **kwargs: ("create_new", "page-topic", "version-topic"),
    )
    monkeypatch.setattr(
        generation, "_generate_issue_page",
        lambda section, **kwargs: ("page-issue", "version-issue"),
    )
    monkeypatch.setattr(
        generation, "send_wiki_notification",
        lambda workspace_id, count, **kwargs: calls.append((workspace_id, count)),
    )

    generation.generate_wiki_drafts_for_sections(
        [_section("issue-ok")],
        [_enriched_group("issue-ok")],
        workspace_id="ws-1",
    )

    assert calls == [("ws-1", 2)]


def test_generate_wiki_drafts_for_sections_skips_notification_when_nothing_published(monkeypatch):
    calls = []
    monkeypatch.setattr(
        generation, "_generate_topic_page",
        lambda section, wiki_contexts, **kwargs: ("skip", None, None),
    )
    monkeypatch.setattr(
        generation, "_generate_issue_page",
        lambda section, **kwargs: (_ for _ in ()).throw(RuntimeError("실패")),
    )
    monkeypatch.setattr(
        generation, "send_wiki_notification",
        lambda workspace_id, count, **kwargs: calls.append((workspace_id, count)),
    )

    generation.generate_wiki_drafts_for_sections(
        [_section("issue-fail")],
        [_enriched_group("issue-fail")],
        workspace_id="ws-1",
    )

    assert calls == []


def test_generate_wiki_drafts_for_sections_survives_notification_failure(monkeypatch):
    monkeypatch.setattr(
        generation, "_generate_topic_page",
        lambda section, wiki_contexts, **kwargs: ("skip", None, None),
    )
    monkeypatch.setattr(
        generation, "_generate_issue_page",
        lambda section, **kwargs: ("page-issue", "version-issue"),
    )

    def raising_notification(*a, **k):
        raise RuntimeError("푸시 발송 실패")

    monkeypatch.setattr(generation, "send_wiki_notification", raising_notification)

    results = generation.generate_wiki_drafts_for_sections(
        [_section("issue-ok")],
        [_enriched_group("issue-ok")],
        workspace_id="ws-1",
    )

    assert len(results) == 1
    assert results[0].issue_page_id == "page-issue"

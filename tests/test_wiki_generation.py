from __future__ import annotations

import json

import pytest

from src.analysis.models import Category
from src.report.models import ReportCitationDraft, ReportSectionDraft, WikiContext
from src.wiki import generation


def _section(issue_key: str = "issue-hbm4-supply") -> ReportSectionDraft:
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
                evidence_text="HBM4 수요가 급증했다",
            )
        ],
    )


def test_generate_issue_page_creates_and_auto_publishes(monkeypatch):
    calls = []

    def fake_upsert_wiki_page(workspace_id, slug, title, page_type, parent_page_id=None):
        calls.append(("upsert", slug, page_type, parent_page_id))
        return "page-1"

    def fake_create_wiki_version(draft):
        calls.append(("create", draft.slug, draft.page_type, [s.document_version_id for s in draft.sources]))
        return "version-1"

    def fake_record_wiki_validation(version_id, validation_status, confidence_score):
        calls.append(("validate", version_id, validation_status, confidence_score))

    def fake_review_wiki_version(version_id, reviewer_id, decision):
        calls.append(("review", version_id, reviewer_id, decision))

    def fake_publish_wiki_version(page_id, version_id):
        calls.append(("publish", page_id, version_id))

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
    monkeypatch.setattr(generation, "upsert_wiki_page", lambda *a, **k: calls.append(("upsert", a)) or "page-1")
    monkeypatch.setattr(generation, "create_wiki_version", lambda draft: "version-1")
    monkeypatch.setattr(generation, "record_wiki_validation", lambda *a, **k: None)
    monkeypatch.setattr(generation, "review_wiki_version", lambda *a, **k: None)
    monkeypatch.setattr(generation, "publish_wiki_version", lambda *a, **k: None)

    generation._generate_issue_page(_section(), workspace_id="ws-1", requested_by=None)

    upsert_call = next(call for call in calls if call[0] == "upsert")
    assert upsert_call[1] == ("ws-1", "issue-hbm4-supply", "HBM4 공급 부족 심화", "issue", None)


def test_generate_issue_page_markdown_contains_all_sections():
    markdown = generation._build_issue_page_markdown(_section())
    assert "HBM4 공급 부족 심화" in markdown
    assert "HBM4 공급이 예상보다 더 타이트해지고 있다." in markdown
    assert "주요 고객사 수요 증가" in markdown
    assert "SK하이닉스 협상력 강화" in markdown
    assert "경쟁사 증발 발표 여부" not in markdown  # 오탈자 없이 원문 그대로 들어가는지
    assert "경쟁사 증설 발표 여부" in markdown


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
    monkeypatch.setattr(generation, "list_top_level_topic_pages", lambda workspace_id, supabase=None: [])
    monkeypatch.setattr(
        generation,
        "get_wiki_page_identity",
        lambda page_id, supabase=None: generation.WikiPageIdentity(
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
        lambda draft: calls.append(("create", draft.slug, draft.page_type, draft.parent_page_id)) or "version-2",
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
    monkeypatch.setattr(generation, "list_top_level_topic_pages", lambda workspace_id, supabase=None: [])
    monkeypatch.setattr(generation, "get_wiki_page_identity", lambda page_id, supabase=None: None)
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

    action, page_id, version_id = generation._generate_topic_page(
        _section(), [], workspace_id="ws-1", requested_by=None,
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
    monkeypatch.setattr(generation, "create_wiki_version", lambda draft: "version-4")
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


def test_generate_topic_page_leaves_pending_when_confidence_low(monkeypatch):
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
    monkeypatch.setattr(generation, "create_wiki_version", lambda draft: "version-3")
    monkeypatch.setattr(generation, "record_wiki_validation", lambda *a, **k: calls.append(("validate", a)))
    monkeypatch.setattr(generation, "review_wiki_version", lambda *a, **k: calls.append(("review", a)))
    monkeypatch.setattr(generation, "publish_wiki_version", lambda *a, **k: calls.append(("publish", a)))

    action, page_id, version_id = generation._generate_topic_page(
        _section(), [], workspace_id="ws-1", requested_by=None,
    )

    assert action == "create_new"
    assert page_id == "page-new"
    assert version_id == "version-3"
    assert not any(call[0] in ("review", "publish") for call in calls)
    assert ("validate", ("version-3", "pending", 0.3)) in calls

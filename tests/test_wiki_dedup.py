from __future__ import annotations

import json

from src.wiki import dedup
from src.wiki.dedup_models import DedupCandidatePair, DedupPageInfo
from src.wiki.interface import WikiPageContent, WikiSource

WORKSPACE_ID = "ws-1"


def _content(page_id, slug, title, page_type, markdown, sources, parent_page_id=None):
    return WikiPageContent(
        page_id=page_id, slug=slug, title=title, page_type=page_type, published_at=None,
        version_id=f"v-{page_id}", version_no=1, markdown=markdown, change_summary=None,
        confidence_score=None, validation_status="passed", review_status="approved",
        generated_by="llm", generator_model=None, created_at="2026-08-04T00:00:00Z",
        sources=tuple(sources), versions=(),
    )


def _pair(page_a_id="page-a", page_b_id="page-b", page_a_parent=None, page_b_parent=None):
    return DedupCandidatePair(
        page_a=DedupPageInfo(page_id=page_a_id, slug="a", title="제목 A", page_type="issue", parent_page_id=page_a_parent),
        page_b=DedupPageInfo(page_id=page_b_id, slug="b", title="제목 B", page_type="market", parent_page_id=page_b_parent),
        shared_source_count=1, title_similarity=0.9,
    )


def test_merge_creates_version_archives_other_and_reparents_children(monkeypatch):
    calls = []
    monkeypatch.setattr(
        dedup, "create_json_completion",
        lambda **kwargs: json.dumps({
            "decision": "merge",
            "representative_page_id": "page-b",
            "markdown": "# 통합 본문",
            "change_summary": "두 문서를 통합",
            "claims": [{"document_version_id": "doc-1", "claim_text": "근거", "citation_order": 1}],
        }),
    )
    monkeypatch.setattr(dedup, "create_wiki_version", lambda draft, **k: calls.append(("create", draft.slug, draft.page_type, draft.parent_page_id, [s.document_version_id for s in draft.sources])) or "version-new")
    monkeypatch.setattr(dedup, "record_wiki_validation", lambda *a, **k: calls.append(("validate", a)))
    monkeypatch.setattr(dedup, "review_wiki_version", lambda *a, **k: calls.append(("review", a)))
    monkeypatch.setattr(dedup, "publish_wiki_version", lambda *a, **k: calls.append(("publish", a)))
    monkeypatch.setattr(dedup, "archive_wiki_page", lambda page_id, **k: calls.append(("archive", page_id)))
    monkeypatch.setattr(dedup, "reparent_children", lambda old, new, **k: calls.append(("reparent", old, new)) or 0)

    pair = _pair(page_a_parent="page-parent")
    content_a = _content("page-a", "a", "제목 A", "issue", "# A", [
        WikiSource(document_version_id="doc-1", citation_order=1, claim_text="근거A", support_type="supports", source_start_line=None, source_end_line=None),
    ])
    content_b = _content("page-b", "b", "제목 B", "market", "# B", [])

    result = dedup._judge_and_merge(pair, content_a, content_b, workspace_id=WORKSPACE_ID, requested_by=None)

    assert result.decision == "merged"
    assert result.representative_page_id == "page-b"
    assert result.archived_page_id == "page-a"
    assert result.version_id == "version-new"
    create_call = next(c for c in calls if c[0] == "create")
    assert create_call[1:4] == ("b", "market", None)  # 대표(page-b)의 slug/page_type/parent_page_id 유지
    assert create_call[4] == ["doc-1"]
    assert ("publish", ("page-b", "version-new")) in calls
    assert ("archive", "page-a") in calls
    assert ("reparent", "page-a", "page-b") in calls


def test_not_duplicate_decision_does_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(
        dedup, "create_json_completion",
        lambda **kwargs: json.dumps({"decision": "not_duplicate", "claims": []}),
    )
    monkeypatch.setattr(dedup, "create_wiki_version", lambda draft, **k: calls.append(("create",)) or "should-not-run")
    monkeypatch.setattr(dedup, "archive_wiki_page", lambda page_id, **k: calls.append(("archive", page_id)))

    pair = _pair()
    content_a = _content("page-a", "a", "제목 A", "issue", "# A", [])
    content_b = _content("page-b", "b", "제목 B", "market", "# B", [])

    result = dedup._judge_and_merge(pair, content_a, content_b, workspace_id=WORKSPACE_ID, requested_by=None)

    assert result.decision == "not_duplicate"
    assert calls == []


def test_merge_skipped_when_representative_page_id_is_invalid(monkeypatch):
    """LLM이 두 후보 page_id 중 하나가 아닌 값을 반환하면(지어낸 값) 병합하지 않는다."""
    calls = []
    monkeypatch.setattr(
        dedup, "create_json_completion",
        lambda **kwargs: json.dumps({
            "decision": "merge", "representative_page_id": "page-not-in-pair",
            "markdown": "# 통합", "change_summary": "요약",
            "claims": [{"document_version_id": "doc-1", "claim_text": "근거", "citation_order": 1}],
        }),
    )
    monkeypatch.setattr(dedup, "create_wiki_version", lambda draft, **k: calls.append(("create",)) or "should-not-run")

    pair = _pair()
    content_a = _content("page-a", "a", "제목 A", "issue", "# A", [
        WikiSource(document_version_id="doc-1", citation_order=1, claim_text="근거", support_type="supports", source_start_line=None, source_end_line=None),
    ])
    content_b = _content("page-b", "b", "제목 B", "market", "# B", [])

    result = dedup._judge_and_merge(pair, content_a, content_b, workspace_id=WORKSPACE_ID, requested_by=None)

    assert result.decision == "not_duplicate"
    assert calls == []


def test_merge_skipped_when_no_valid_grounded_claims(monkeypatch):
    """claims가 두 문서 어느 근거에도 없는 document_version_id만 가리키면 병합하지 않는다."""
    calls = []
    monkeypatch.setattr(
        dedup, "create_json_completion",
        lambda **kwargs: json.dumps({
            "decision": "merge", "representative_page_id": "page-b",
            "markdown": "# 통합", "change_summary": "요약",
            "claims": [{"document_version_id": "doc-unknown", "claim_text": "근거", "citation_order": 1}],
        }),
    )
    monkeypatch.setattr(dedup, "create_wiki_version", lambda draft, **k: calls.append(("create",)) or "should-not-run")

    pair = _pair()
    content_a = _content("page-a", "a", "제목 A", "issue", "# A", [])
    content_b = _content("page-b", "b", "제목 B", "market", "# B", [])

    result = dedup._judge_and_merge(pair, content_a, content_b, workspace_id=WORKSPACE_ID, requested_by=None)

    assert result.decision == "not_duplicate"
    assert calls == []


def test_uses_injected_llm_client_instead_of_create_json_completion(monkeypatch):
    received = {}

    def fake_llm_client(system_prompt, user_prompt, model):
        received["system_prompt"] = system_prompt
        received["user_prompt"] = user_prompt
        return json.dumps({"decision": "not_duplicate", "claims": []})

    monkeypatch.setattr(
        dedup, "create_json_completion",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("llm_client가 있으면 이건 호출되면 안 됨")),
    )

    pair = _pair()
    content_a = _content("page-a", "a", "제목 A", "issue", "# A", [])
    content_b = _content("page-b", "b", "제목 B", "market", "# B", [])

    result = dedup._judge_and_merge(
        pair, content_a, content_b, workspace_id=WORKSPACE_ID, requested_by=None, llm_client=fake_llm_client,
    )

    assert result.decision == "not_duplicate"
    assert "문서 A" in received["user_prompt"]

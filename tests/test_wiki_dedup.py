from __future__ import annotations

import json

from src.wiki import dedup
from src.wiki.dedup_models import DedupCandidatePair, DedupPageInfo, DedupResult
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


def _pair(page_a_id="page-a", page_b_id="page-b", page_a_parent=None, page_b_parent=None, page_a_slug="a", page_b_slug="b"):
    return DedupCandidatePair(
        page_a=DedupPageInfo(page_id=page_a_id, slug=page_a_slug, title="제목 A", page_type="issue", parent_page_id=page_a_parent),
        page_b=DedupPageInfo(page_id=page_b_id, slug=page_b_slug, title="제목 B", page_type="market", parent_page_id=page_b_parent),
        shared_source_count=1, title_similarity=0.9,
    )


def test_merge_creates_version_archives_other_and_reparents_children(monkeypatch):
    calls = []
    monkeypatch.setattr(
        dedup, "create_json_completion",
        lambda **kwargs: json.dumps({
            "decision": "merge",
            "representative_page_id": "page-b",
            "title": "통합 제목",
            "markdown": "# 통합 본문",
            "change_summary": "두 문서를 통합",
            "claims": [{"document_version_id": "doc-1", "claim_text": "근거", "citation_order": 1}],
        }),
    )
    monkeypatch.setattr(dedup, "create_wiki_version", lambda draft, **k: calls.append(("create", draft.slug, draft.page_type, draft.parent_page_id, [s.document_version_id for s in draft.sources])) or "version-new")
    monkeypatch.setattr(dedup, "record_wiki_validation", lambda *a, **k: calls.append(("validate", a)))
    monkeypatch.setattr(dedup, "review_wiki_version", lambda *a, **k: calls.append(("review", a)))
    monkeypatch.setattr(dedup, "publish_wiki_version", lambda *a, **k: calls.append(("publish", a)))
    monkeypatch.setattr(dedup, "update_wiki_page_title", lambda page_id, title, **k: calls.append(("update_title", page_id, title)))
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
    assert ("update_title", "page-b", "통합 제목") in calls
    assert ("archive", "page-a") in calls
    assert ("reparent", "page-a", "page-b") in calls


def test_merge_skipped_when_title_is_blank(monkeypatch):
    """병합을 결정했는데 title을 못 만들면(빈 문자열/공백) 본문만 바뀌고 제목은 그대로인
    반쪽짜리 상태를 막기 위해 병합 자체를 취소한다."""
    calls = []
    monkeypatch.setattr(
        dedup, "create_json_completion",
        lambda **kwargs: json.dumps({
            "decision": "merge",
            "representative_page_id": "page-b",
            "title": "   ",
            "markdown": "# 통합 본문",
            "change_summary": "두 문서를 통합",
            "claims": [{"document_version_id": "doc-1", "claim_text": "근거", "citation_order": 1}],
        }),
    )
    monkeypatch.setattr(dedup, "create_wiki_version", lambda draft, **k: calls.append(("create",)) or "should-not-run")
    monkeypatch.setattr(dedup, "update_wiki_page_title", lambda page_id, title, **k: calls.append(("update_title",)))
    monkeypatch.setattr(dedup, "archive_wiki_page", lambda page_id, **k: calls.append(("archive", page_id)))

    pair = _pair()
    content_a = _content("page-a", "a", "제목 A", "issue", "# A", [
        WikiSource(document_version_id="doc-1", citation_order=1, claim_text="근거", support_type="supports", source_start_line=None, source_end_line=None),
    ])
    content_b = _content("page-b", "b", "제목 B", "market", "# B", [])

    result = dedup._judge_and_merge(pair, content_a, content_b, workspace_id=WORKSPACE_ID, requested_by=None)

    assert result.decision == "not_duplicate"
    assert calls == []


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


def test_run_wiki_dedup_batch_processes_each_candidate_pair(monkeypatch):
    pair1 = _pair(page_a_id="page-1a", page_b_id="page-1b", page_a_slug="a1", page_b_slug="b1")
    pair2 = _pair(page_a_id="page-2a", page_b_id="page-2b", page_a_slug="a2", page_b_slug="b2")
    monkeypatch.setattr(dedup, "find_duplicate_candidate_pairs", lambda workspace_id, **k: [pair1, pair2])

    contents = {
        "a1": _content("page-1a", "a1", "제목", "issue", "# A", []),
        "b1": _content("page-1b", "b1", "제목", "market", "# B", []),
        "a2": _content("page-2a", "a2", "제목", "issue", "# A", []),
        "b2": _content("page-2b", "b2", "제목", "market", "# B", []),
    }
    monkeypatch.setattr(
        dedup, "get_published_wiki_page",
        lambda workspace_id, slug: next((c for key, c in contents.items() if c.slug == slug), None),
    )

    judged_pairs = []
    monkeypatch.setattr(
        dedup, "_judge_and_merge",
        lambda pair, content_a, content_b, **k: judged_pairs.append((pair.page_a.page_id, pair.page_b.page_id))
        or DedupResult(page_a_id=pair.page_a.page_id, page_b_id=pair.page_b.page_id, decision="not_duplicate"),
    )

    results = dedup.run_wiki_dedup_batch(WORKSPACE_ID)

    assert len(results) == 2
    assert ("page-1a", "page-1b") in judged_pairs
    assert ("page-2a", "page-2b") in judged_pairs


def test_run_wiki_dedup_batch_skips_pair_when_a_page_already_archived(monkeypatch):
    """이번 배치에서 앞선 페어 처리로 이미 아카이빙된 페이지는 get_published_wiki_page가
    None을 반환하므로(status='published' 필터), 뒤 페어는 건너뛴다."""
    pair = _pair()
    monkeypatch.setattr(dedup, "find_duplicate_candidate_pairs", lambda workspace_id, **k: [pair])
    monkeypatch.setattr(dedup, "get_published_wiki_page", lambda workspace_id, slug: None)

    judge_calls = []
    monkeypatch.setattr(dedup, "_judge_and_merge", lambda *a, **k: judge_calls.append(1))

    results = dedup.run_wiki_dedup_batch(WORKSPACE_ID)

    assert results == []
    assert judge_calls == []


def test_run_wiki_dedup_batch_isolates_pair_failures(monkeypatch):
    """한 페어 처리 중 예외가 나도 다른 페어 처리를 막지 않는다."""
    pair1 = _pair(page_a_id="page-1a", page_b_id="page-1b")
    pair2 = _pair(page_a_id="page-2a", page_b_id="page-2b")
    monkeypatch.setattr(dedup, "find_duplicate_candidate_pairs", lambda workspace_id, **k: [pair1, pair2])
    monkeypatch.setattr(
        dedup, "get_published_wiki_page",
        lambda workspace_id, slug: _content(slug, slug, "제목", "issue", "# 본문", []),
    )

    def fake_judge(pair, content_a, content_b, **k):
        if pair.page_a.page_id == "page-1a":
            raise RuntimeError("boom")
        return DedupResult(page_a_id=pair.page_a.page_id, page_b_id=pair.page_b.page_id, decision="not_duplicate")

    monkeypatch.setattr(dedup, "_judge_and_merge", fake_judge)

    results = dedup.run_wiki_dedup_batch(WORKSPACE_ID)

    assert len(results) == 2
    failed = next(r for r in results if r.page_a_id == "page-1a")
    assert failed.decision == "failed"
    assert "boom" in failed.error_message
    succeeded = next(r for r in results if r.page_a_id == "page-2a")
    assert succeeded.decision == "not_duplicate"

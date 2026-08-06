from __future__ import annotations

import json

from pydantic import ValidationError

from src.analysis.exceptions import OpenRouterTimeoutError
from src.wiki import keyword_batch


def test_extract_keywords_filters_out_of_dictionary_values(monkeypatch):
    monkeypatch.setattr(
        keyword_batch,
        "create_json_completion",
        lambda **kwargs: json.dumps({"keywords": ["HBM", "지어낸키워드", "삼성전자"]}),
    )

    keywords = keyword_batch.extract_keywords_for_page("HBM 관련 문서, 삼성전자 언급")

    assert keywords == ["HBM", "삼성전자"]


def test_extract_keywords_truncates_to_max_eight(monkeypatch):
    from src.categories.keywords import CATEGORY_KEYWORDS

    nine_real_keywords = list(CATEGORY_KEYWORDS["제품·기술"]) + list(CATEGORY_KEYWORDS["경쟁사"])
    nine_real_keywords = nine_real_keywords[:9]
    assert len(nine_real_keywords) == 9

    monkeypatch.setattr(
        keyword_batch, "create_json_completion",
        lambda **kwargs: json.dumps({"keywords": nine_real_keywords}),
    )

    keywords = keyword_batch.extract_keywords_for_page("본문")

    assert len(keywords) == keyword_batch.MAX_KEYWORDS_PER_PAGE
    assert keywords == nine_real_keywords[:8]


def test_extract_keywords_returns_empty_list_when_no_match(monkeypatch):
    monkeypatch.setattr(
        keyword_batch, "create_json_completion", lambda **kwargs: json.dumps({"keywords": []}),
    )

    assert keyword_batch.extract_keywords_for_page("아무 관련 없는 본문") == []


def test_extract_keywords_uses_injected_llm_client():
    calls = []

    def fake_client(system_prompt, user_prompt, model):
        calls.append((system_prompt, user_prompt, model))
        return json.dumps({"keywords": ["HBM"]})

    keywords = keyword_batch.extract_keywords_for_page("본문", llm_client=fake_client)

    assert keywords == ["HBM"]
    assert len(calls) == 1
    assert calls[0][0] == keyword_batch.WIKI_KEYWORD_SYSTEM_PROMPT


def test_extract_keywords_raises_on_llm_exception(monkeypatch):
    def raise_timeout(**kwargs):
        raise OpenRouterTimeoutError("timeout")

    monkeypatch.setattr(keyword_batch, "create_json_completion", raise_timeout)

    try:
        keyword_batch.extract_keywords_for_page("본문")
        assert False, "OpenRouterTimeoutError가 그대로 올라와야 한다"
    except OpenRouterTimeoutError:
        pass


def test_extract_keywords_raises_on_invalid_schema(monkeypatch):
    monkeypatch.setattr(
        keyword_batch, "create_json_completion", lambda **kwargs: json.dumps({"not_keywords": []}),
    )

    try:
        keyword_batch.extract_keywords_for_page("본문")
        assert False, "ValidationError가 그대로 올라와야 한다"
    except ValidationError:
        pass


from src.wiki.interface import WikiPageContent


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []
        self.in_filters = []

    def select(self, _fields):
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def in_(self, field, values):
        self.in_filters.append((field, set(values)))
        return self

    def execute(self):
        rows = self.rows
        for field, value in self.filters:
            rows = [r for r in rows if r.get(field) == value]
        for field, values in self.in_filters:
            rows = [r for r in rows if r.get(field) in values]
        return FakeResult([dict(r) for r in rows])


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return FakeTable(self.tables.get(name, []))


def _content(page_id, slug, markdown):
    return WikiPageContent(
        page_id=page_id, slug=slug, title=f"제목-{slug}", page_type="issue",
        published_at=None, version_id=f"v-{slug}", version_no=1, markdown=markdown,
        change_summary=None, confidence_score=None, validation_status="passed",
        review_status="approved", generated_by="llm", generator_model=None,
        created_at="2026-08-06T00:00:00Z", sources=(), versions=(),
    )


def test_find_pages_missing_keywords_excludes_pages_with_existing_keywords():
    db = FakeSupabase({
        "wiki_pages": [
            {"id": "page-1", "slug": "hbm4", "status": "published", "workspace_id": "ws-1"},
            {"id": "page-2", "slug": "supply", "status": "published", "workspace_id": "ws-1"},
        ],
        "wiki_page_keywords": [{"page_id": "page-1", "keyword": "HBM"}],
    })

    candidates = keyword_batch.find_pages_missing_keywords("ws-1", supabase=db)

    assert candidates == [{"id": "page-2", "slug": "supply"}]


def test_find_pages_missing_keywords_excludes_other_workspace_pages():
    db = FakeSupabase({
        "wiki_pages": [
            {"id": "page-1", "slug": "hbm4", "status": "published", "workspace_id": "ws-1"},
            {"id": "page-2", "slug": "other-ws-page", "status": "published", "workspace_id": "ws-2"},
        ],
        "wiki_page_keywords": [],
    })

    candidates = keyword_batch.find_pages_missing_keywords("ws-1", supabase=db)

    assert candidates == [{"id": "page-1", "slug": "hbm4"}]


def test_run_wiki_keyword_batch_tags_page_and_inserts_keywords(monkeypatch):
    db = FakeSupabase({
        "wiki_pages": [{"id": "page-1", "slug": "hbm4", "status": "published", "workspace_id": "ws-1"}],
        "wiki_page_keywords": [],
    })
    monkeypatch.setattr(keyword_batch, "get_published_wiki_page", lambda ws, slug: _content("page-1", "hbm4", "HBM4 본문"))

    inserted = []
    monkeypatch.setattr(keyword_batch, "_insert_page_keywords", lambda page_id, keywords, *, supabase: inserted.append((page_id, keywords)))
    monkeypatch.setattr(keyword_batch, "extract_keywords_for_page", lambda markdown: ["HBM"])

    results = keyword_batch.run_wiki_keyword_batch("ws-1", supabase=db)

    assert len(results) == 1
    assert results[0].status == "tagged"
    assert results[0].keywords == ["HBM"]
    assert inserted == [("page-1", ["HBM"])]


def test_run_wiki_keyword_batch_marks_no_match_without_insert(monkeypatch):
    db = FakeSupabase({
        "wiki_pages": [{"id": "page-1", "slug": "hbm4", "status": "published", "workspace_id": "ws-1"}],
        "wiki_page_keywords": [],
    })
    monkeypatch.setattr(keyword_batch, "get_published_wiki_page", lambda ws, slug: _content("page-1", "hbm4", "무관한 본문"))
    monkeypatch.setattr(keyword_batch, "extract_keywords_for_page", lambda markdown: [])

    inserted = []
    monkeypatch.setattr(keyword_batch, "_insert_page_keywords", lambda *a, **k: inserted.append(a))

    results = keyword_batch.run_wiki_keyword_batch("ws-1", supabase=db)

    assert results[0].status == "no_match"
    assert inserted == []


def test_run_wiki_keyword_batch_continues_after_one_page_fails(monkeypatch):
    db = FakeSupabase({
        "wiki_pages": [
            {"id": "page-1", "slug": "fails", "status": "published", "workspace_id": "ws-1"},
            {"id": "page-2", "slug": "ok", "status": "published", "workspace_id": "ws-1"},
        ],
        "wiki_page_keywords": [],
    })
    contents = {"fails": _content("page-1", "fails", "본문1"), "ok": _content("page-2", "ok", "본문2")}
    monkeypatch.setattr(keyword_batch, "get_published_wiki_page", lambda ws, slug: contents[slug])

    def fake_extract(markdown):
        if markdown == "본문1":
            raise OpenRouterTimeoutError("timeout")
        return ["HBM"]

    monkeypatch.setattr(keyword_batch, "extract_keywords_for_page", fake_extract)
    monkeypatch.setattr(keyword_batch, "_insert_page_keywords", lambda *a, **k: None)

    results = keyword_batch.run_wiki_keyword_batch("ws-1", supabase=db)

    assert len(results) == 2
    by_slug = {r.slug: r for r in results}
    assert by_slug["fails"].status == "failed"
    assert "timeout" in by_slug["fails"].error_message
    assert by_slug["ok"].status == "tagged"

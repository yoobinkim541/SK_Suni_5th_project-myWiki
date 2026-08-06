from __future__ import annotations

from src.wiki import citation_id_cleanup
from src.wiki.interface import WikiPageContent, WikiSource

WORKSPACE_ID = "ws-1"

CXMT_SOURCE = WikiSource(
    document_version_id="93f0ebe5-7373-43ea-ba84-c60533b7f033",
    citation_order=1, claim_text="근거", support_type="supports",
    source_start_line=None, source_end_line=None,
    document_title="중국 턱밑 추격에…삼성·SK하이닉스, HBM·차세대 기술 개발 '전력투구' - 뉴시스",
    source_name="Google RSS - SK하이닉스",
    published_at="2026-08-02T07:23:01+00:00",
)
CXMT_ATTRIBUTION = (
    "중국 턱밑 추격에…삼성·SK하이닉스, HBM·차세대 기술 개발 '전력투구' - 뉴시스"
    " · Google RSS - SK하이닉스 · 2026.08.02"
)


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []

    def select(self, _fields):
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def execute(self):
        rows = self.rows
        for field, value in self.filters:
            rows = [r for r in rows if r.get(field) == value]
        return FakeResult([dict(r) for r in rows])


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return FakeTable(self.tables[name])


def _page_row(slug, parent_page_id=None):
    return {"slug": slug, "parent_page_id": parent_page_id, "workspace_id": WORKSPACE_ID, "status": "published"}


def _content(slug, markdown, sources, page_type="issue"):
    return WikiPageContent(
        page_id=f"page-{slug}", slug=slug, title=f"제목-{slug}", page_type=page_type,
        published_at=None, version_id=f"v-{slug}", version_no=1, markdown=markdown,
        change_summary=None, confidence_score=None, validation_status="passed",
        review_status="approved", generated_by="llm", generator_model=None,
        created_at="2026-08-05T00:00:00Z", sources=tuple(sources), versions=(),
    )


# ---------------------------------------------------------------------------
# rewrite_raw_citation_ids — 실제 프로덕션에서 관찰된 네 가지 형태
# ---------------------------------------------------------------------------


def test_rewrites_deterministic_issue_page_format():
    """src/wiki/generation.py `_build_issue_page_markdown`의 과거 버그 형태."""
    markdown = "- 근거 문장 (document_version_id=93f0ebe5-7373-43ea-ba84-c60533b7f033)"
    result = citation_id_cleanup.rewrite_raw_citation_ids(markdown, (CXMT_SOURCE,))
    assert result == f"- 근거 문장 ({CXMT_ATTRIBUTION})"


def test_rewrites_llm_prefixed_format_with_trailing_citation_order():
    """토픽/dedup 병합 LLM이 프롬프트의 참조 형식을 그대로 흉내 낸 형태."""
    markdown = (
        "1. document_version_id=93f0ebe5-7373-43ea-ba84-c60533b7f033: CXMT가 상장을 통해"
        " 자금을 조달했다. (citation_order=1)"
    )
    result = citation_id_cleanup.rewrite_raw_citation_ids(markdown, (CXMT_SOURCE,))
    assert result == f"1. {CXMT_ATTRIBUTION}: CXMT가 상장을 통해 자금을 조달했다."


def test_rewrites_bare_id_with_bracket_marker():
    """chat-based dedup 병합 페이지의 "- [N] document_version_id=X" 형태."""
    markdown = "- [1] document_version_id=93f0ebe5-7373-43ea-ba84-c60533b7f033"
    result = citation_id_cleanup.rewrite_raw_citation_ids(markdown, (CXMT_SOURCE,))
    assert result == f"- [1] {CXMT_ATTRIBUTION}"


def test_rewrites_bare_numbered_id_with_no_evidence():
    markdown = "1. document_version_id=93f0ebe5-7373-43ea-ba84-c60533b7f033"
    result = citation_id_cleanup.rewrite_raw_citation_ids(markdown, (CXMT_SOURCE,))
    assert result == f"1. {CXMT_ATTRIBUTION}"


def test_rewrites_inline_comma_citation_order_before_closing_paren():
    markdown = (
        "1. 인도 정부는 벤처캐피털과 공동 투자한다."
        " (document_version_id=93f0ebe5-7373-43ea-ba84-c60533b7f033, citation_order=1)"
    )
    result = citation_id_cleanup.rewrite_raw_citation_ids(markdown, (CXMT_SOURCE,))
    assert result == f"1. 인도 정부는 벤처캐피털과 공동 투자한다. ({CXMT_ATTRIBUTION})"


def test_falls_back_to_placeholder_when_source_missing():
    markdown = "- 근거 문장 (document_version_id=doc-unknown)"
    result = citation_id_cleanup.rewrite_raw_citation_ids(markdown, sources=())
    assert result == "- 근거 문장 (출처 정보 확인 안 됨)"  # 원문 마크다운의 괄호는 그대로 유지된다


def test_leaves_clean_markdown_untouched():
    markdown = f"## 출처\n- 근거 문장 · {CXMT_ATTRIBUTION}"
    result = citation_id_cleanup.rewrite_raw_citation_ids(markdown, sources=())
    assert result == markdown


# ---------------------------------------------------------------------------
# clean_raw_citation_ids_for_workspace
# ---------------------------------------------------------------------------


def test_cleans_page_with_raw_citation_id(monkeypatch):
    db = FakeSupabase({"wiki_pages": [_page_row("a")]})
    content = _content(
        "a",
        "## 출처\n- 근거 문장 (document_version_id=93f0ebe5-7373-43ea-ba84-c60533b7f033)",
        [CXMT_SOURCE],
    )
    monkeypatch.setattr(citation_id_cleanup, "get_published_wiki_page", lambda ws, slug: content)

    calls = []
    monkeypatch.setattr(
        citation_id_cleanup, "create_wiki_version",
        lambda draft, **k: calls.append((
            "create", draft.slug, draft.markdown, draft.parent_page_id,
            [s.document_version_id for s in draft.sources],
        )) or "version-new",
    )
    monkeypatch.setattr(citation_id_cleanup, "record_wiki_validation", lambda *a, **k: calls.append(("validate", a)))
    monkeypatch.setattr(citation_id_cleanup, "review_wiki_version", lambda *a, **k: calls.append(("review", a)))
    monkeypatch.setattr(citation_id_cleanup, "publish_wiki_version", lambda *a, **k: calls.append(("publish", a)))

    cleaned = citation_id_cleanup.clean_raw_citation_ids_for_workspace(WORKSPACE_ID, supabase=db)

    assert cleaned == ["a"]
    create_call = next(c for c in calls if c[0] == "create")
    assert create_call[2] == f"## 출처\n- 근거 문장 ({CXMT_ATTRIBUTION})"
    assert create_call[4] == ["93f0ebe5-7373-43ea-ba84-c60533b7f033"]
    assert ("publish", ("page-a", "version-new")) in calls


def test_skips_page_with_no_raw_citation_ids(monkeypatch):
    db = FakeSupabase({"wiki_pages": [_page_row("a")]})
    content = _content("a", f"## 출처\n- 근거 문장 · {CXMT_ATTRIBUTION}", [CXMT_SOURCE])
    monkeypatch.setattr(citation_id_cleanup, "get_published_wiki_page", lambda ws, slug: content)

    calls = []
    monkeypatch.setattr(citation_id_cleanup, "create_wiki_version", lambda draft, **k: calls.append(("create",)) or "should-not-run")

    cleaned = citation_id_cleanup.clean_raw_citation_ids_for_workspace(WORKSPACE_ID, supabase=db)

    assert cleaned == []
    assert calls == []


def test_skips_page_when_content_missing(monkeypatch):
    db = FakeSupabase({"wiki_pages": [_page_row("a")]})
    monkeypatch.setattr(citation_id_cleanup, "get_published_wiki_page", lambda ws, slug: None)

    cleaned = citation_id_cleanup.clean_raw_citation_ids_for_workspace(WORKSPACE_ID, supabase=db)

    assert cleaned == []


def test_carries_parent_page_id_through(monkeypatch):
    db = FakeSupabase({"wiki_pages": [_page_row("a", "page-parent")]})
    content = _content("a", "- 근거 (document_version_id=doc-9)", [])
    monkeypatch.setattr(citation_id_cleanup, "get_published_wiki_page", lambda ws, slug: content)

    calls = []
    monkeypatch.setattr(
        citation_id_cleanup, "create_wiki_version",
        lambda draft, **k: calls.append(("create", draft.parent_page_id)) or "version-new",
    )
    monkeypatch.setattr(citation_id_cleanup, "record_wiki_validation", lambda *a, **k: None)
    monkeypatch.setattr(citation_id_cleanup, "review_wiki_version", lambda *a, **k: None)
    monkeypatch.setattr(citation_id_cleanup, "publish_wiki_version", lambda *a, **k: None)

    citation_id_cleanup.clean_raw_citation_ids_for_workspace(WORKSPACE_ID, supabase=db)

    create_call = next(c for c in calls if c[0] == "create")
    assert create_call[1] == "page-parent"

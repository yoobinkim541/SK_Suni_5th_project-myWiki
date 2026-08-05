from __future__ import annotations

from src.wiki import citation_cleanup
from src.wiki.interface import WikiPageContent, WikiSource

WORKSPACE_ID = "ws-1"


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


def test_cleans_page_with_orphaned_citation_markers(monkeypatch):
    db = FakeSupabase({"wiki_pages": [_page_row("a")]})
    content = _content("a", "문장[1] 문장[4].", [
        WikiSource(document_version_id="doc-1", citation_order=1, claim_text="근거",
                   support_type="supports", source_start_line=None, source_end_line=None),
    ])
    monkeypatch.setattr(citation_cleanup, "get_published_wiki_page", lambda ws, slug: content)

    calls = []
    monkeypatch.setattr(
        citation_cleanup, "create_wiki_version",
        lambda draft, **k: calls.append((
            "create", draft.slug, draft.markdown, draft.parent_page_id,
            [s.document_version_id for s in draft.sources],
        )) or "version-new",
    )
    monkeypatch.setattr(citation_cleanup, "record_wiki_validation", lambda *a, **k: calls.append(("validate", a)))
    monkeypatch.setattr(citation_cleanup, "review_wiki_version", lambda *a, **k: calls.append(("review", a)))
    monkeypatch.setattr(citation_cleanup, "publish_wiki_version", lambda *a, **k: calls.append(("publish", a)))

    cleaned = citation_cleanup.clean_orphaned_citations_for_workspace(WORKSPACE_ID, supabase=db)

    assert cleaned == ["a"]
    create_call = next(c for c in calls if c[0] == "create")
    assert create_call[2] == "문장[1] 문장."
    assert create_call[4] == ["doc-1"]
    assert ("publish", ("page-a", "version-new")) in calls


def test_skips_page_with_no_orphaned_markers(monkeypatch):
    db = FakeSupabase({"wiki_pages": [_page_row("a")]})
    content = _content("a", "문장[1].", [
        WikiSource(document_version_id="doc-1", citation_order=1, claim_text="근거",
                   support_type="supports", source_start_line=None, source_end_line=None),
    ])
    monkeypatch.setattr(citation_cleanup, "get_published_wiki_page", lambda ws, slug: content)

    calls = []
    monkeypatch.setattr(citation_cleanup, "create_wiki_version", lambda draft, **k: calls.append(("create",)) or "should-not-run")

    cleaned = citation_cleanup.clean_orphaned_citations_for_workspace(WORKSPACE_ID, supabase=db)

    assert cleaned == []
    assert calls == []


def test_skips_page_when_content_missing(monkeypatch):
    db = FakeSupabase({"wiki_pages": [_page_row("a")]})
    monkeypatch.setattr(citation_cleanup, "get_published_wiki_page", lambda ws, slug: None)

    cleaned = citation_cleanup.clean_orphaned_citations_for_workspace(WORKSPACE_ID, supabase=db)

    assert cleaned == []


def test_carries_parent_page_id_through(monkeypatch):
    db = FakeSupabase({"wiki_pages": [_page_row("a", "page-parent")]})
    content = _content("a", "문장[9].", [])
    monkeypatch.setattr(citation_cleanup, "get_published_wiki_page", lambda ws, slug: content)

    calls = []
    monkeypatch.setattr(
        citation_cleanup, "create_wiki_version",
        lambda draft, **k: calls.append(("create", draft.parent_page_id)) or "version-new",
    )
    monkeypatch.setattr(citation_cleanup, "record_wiki_validation", lambda *a, **k: None)
    monkeypatch.setattr(citation_cleanup, "review_wiki_version", lambda *a, **k: None)
    monkeypatch.setattr(citation_cleanup, "publish_wiki_version", lambda *a, **k: None)

    citation_cleanup.clean_orphaned_citations_for_workspace(WORKSPACE_ID, supabase=db)

    create_call = next(c for c in calls if c[0] == "create")
    assert create_call[1] == "page-parent"

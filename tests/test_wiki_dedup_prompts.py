from __future__ import annotations

from src.wiki.dedup_prompts import WIKI_DEDUP_SYSTEM_PROMPT, build_wiki_dedup_user_prompt
from src.wiki.interface import WikiPageContent, WikiSource


def _content(page_id, title, markdown, sources):
    return WikiPageContent(
        page_id=page_id, slug=page_id, title=title, page_type="issue", published_at=None,
        version_id=f"v-{page_id}", version_no=1, markdown=markdown, change_summary=None,
        confidence_score=None, validation_status="passed", review_status="approved",
        generated_by="llm", generator_model=None, created_at="2026-08-04T00:00:00Z",
        sources=tuple(sources), versions=(),
    )


def test_system_prompt_requires_grounded_claims_and_allows_not_duplicate():
    assert "not_duplicate" in WIKI_DEDUP_SYSTEM_PROMPT
    assert "claims" in WIKI_DEDUP_SYSTEM_PROMPT


def test_user_prompt_includes_both_pages_titles_and_markdown():
    content_a = _content("page-a", "제목 A", "# 본문 A", [
        WikiSource(document_version_id="doc-1", citation_order=1, claim_text="근거 A",
                   support_type="supports", source_start_line=None, source_end_line=None),
    ])
    content_b = _content("page-b", "제목 B", "# 본문 B", [
        WikiSource(document_version_id="doc-2", citation_order=1, claim_text="근거 B",
                   support_type="supports", source_start_line=None, source_end_line=None),
    ])

    prompt = build_wiki_dedup_user_prompt(content_a, content_b)

    assert "page_id=page-a" in prompt
    assert "제목 A" in prompt
    assert "# 본문 A" in prompt
    assert "document_version_id=doc-1" in prompt
    assert "제목 B" in prompt
    assert "# 본문 B" in prompt
    assert "document_version_id=doc-2" in prompt


def test_user_prompt_handles_page_with_no_sources():
    content_a = _content("page-a", "제목 A", "# 본문", [])
    content_b = _content("page-b", "제목 B", "# 본문", [])
    prompt = build_wiki_dedup_user_prompt(content_a, content_b)
    assert "없음" in prompt

from __future__ import annotations

from src.wiki.dedup_models import DedupCandidatePair
from src.wiki.dedup_repository import find_duplicate_candidate_pairs

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
        self.filters.append(("eq", field, value))
        return self

    def in_(self, field, values):
        self.filters.append(("in", field, set(values)))
        return self

    def execute(self):
        return FakeResult([dict(r) for r in self._filtered_rows()])

    def _filtered_rows(self):
        rows = self.rows
        for op, field, value in self.filters:
            if op == "eq":
                rows = [r for r in rows if r.get(field) == value]
            elif op == "in":
                rows = [r for r in rows if r.get(field) in value]
        return rows


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return FakeTable(self.tables[name])


def _page(page_id, slug, title, page_type="issue", parent_page_id=None, current_version_id=None):
    return {
        "id": page_id, "workspace_id": WORKSPACE_ID, "slug": slug, "title": title,
        "page_type": page_type, "parent_page_id": parent_page_id, "status": "published",
        "current_version_id": current_version_id or f"v-{page_id}",
    }


def test_pairs_with_shared_source_become_candidates():
    db = FakeSupabase(
        {
            "wiki_pages": [
                _page("page-a", "a", "제목 A"),
                _page("page-b", "b", "제목 B"),
            ],
            "wiki_page_sources": [
                {"wiki_version_id": "v-page-a", "document_version_id": "doc-1"},
                {"wiki_version_id": "v-page-b", "document_version_id": "doc-1"},
            ],
        }
    )
    pairs = find_duplicate_candidate_pairs(WORKSPACE_ID, supabase=db)
    assert len(pairs) == 1
    assert {pairs[0].page_a.page_id, pairs[0].page_b.page_id} == {"page-a", "page-b"}
    assert pairs[0].shared_source_count == 1


def test_pairs_with_similar_title_but_no_shared_source_become_candidates():
    db = FakeSupabase(
        {
            "wiki_pages": [
                _page("page-a", "china-reg", "china_semiconductor_design_protection_regulation"),
                _page("page-b", "china-reg-2026", "china_semiconductor_design_protection_regulation_2026"),
            ],
            "wiki_page_sources": [
                {"wiki_version_id": "v-page-a", "document_version_id": "doc-1"},
                {"wiki_version_id": "v-page-b", "document_version_id": "doc-2"},  # 겹치는 근거 없음
            ],
        }
    )
    pairs = find_duplicate_candidate_pairs(WORKSPACE_ID, supabase=db)
    assert len(pairs) == 1
    assert pairs[0].shared_source_count == 0
    assert pairs[0].title_similarity > 0.8


def test_unrelated_pages_are_not_candidates():
    db = FakeSupabase(
        {
            "wiki_pages": [
                _page("page-a", "a", "SK하이닉스"),
                _page("page-b", "b", "HBM4 공급 부족 심화"),
            ],
            "wiki_page_sources": [
                {"wiki_version_id": "v-page-a", "document_version_id": "doc-1"},
                {"wiki_version_id": "v-page-b", "document_version_id": "doc-2"},
            ],
        }
    )
    pairs = find_duplicate_candidate_pairs(WORKSPACE_ID, supabase=db)
    assert pairs == []


def test_max_pairs_caps_and_prioritizes_highest_score():
    db = FakeSupabase(
        {
            "wiki_pages": [
                _page("page-a", "a", "제목 A"),
                _page("page-b", "b", "제목 A"),  # 완전 동일 제목(가장 강한 후보)
                _page("page-c", "c", "제목 C"),
            ],
            "wiki_page_sources": [
                {"wiki_version_id": "v-page-a", "document_version_id": "doc-1"},
                {"wiki_version_id": "v-page-b", "document_version_id": "doc-1"},
                {"wiki_version_id": "v-page-c", "document_version_id": "doc-1"},
            ],
        }
    )
    pairs = find_duplicate_candidate_pairs(WORKSPACE_ID, supabase=db, max_pairs=1)
    assert len(pairs) == 1
    assert {pairs[0].page_a.slug, pairs[0].page_b.slug} == {"a", "b"}  # 제목까지 겹치는 쌍이 우선


def test_parent_page_id_is_carried_through():
    db = FakeSupabase(
        {
            "wiki_pages": [
                _page("page-a", "a", "제목 A", page_type="market", parent_page_id="page-parent"),
                _page("page-b", "b", "제목 A"),
            ],
            "wiki_page_sources": [
                {"wiki_version_id": "v-page-a", "document_version_id": "doc-1"},
                {"wiki_version_id": "v-page-b", "document_version_id": "doc-1"},
            ],
        }
    )
    pairs = find_duplicate_candidate_pairs(WORKSPACE_ID, supabase=db)
    page_a_info = next(p for p in (pairs[0].page_a, pairs[0].page_b) if p.slug == "a")
    assert page_a_info.parent_page_id == "page-parent"

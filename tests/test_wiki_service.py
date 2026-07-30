import uuid

import pytest
from dotenv import load_dotenv

load_dotenv()

from src.wiki.interface import upsert_wiki_page
from src.wiki.query import _get_client


@pytest.fixture(scope="module")
def workspace_id() -> str:
    db = _get_client()
    res = db.table("workspaces").select("id").eq("slug", "mywiki").single().execute()
    return res.data["id"]


def test_upsert_wiki_page_creates_new(workspace_id):
    slug = f"test-{uuid.uuid4().hex[:8]}"
    page_id = upsert_wiki_page(workspace_id, slug, "테스트 페이지", "term")
    assert isinstance(page_id, str)
    db = _get_client()
    db.table("wiki_pages").delete().eq("id", page_id).execute()


def test_upsert_wiki_page_returns_same_id_for_duplicate_slug(workspace_id):
    slug = f"test-dup-{uuid.uuid4().hex[:8]}"
    id1 = upsert_wiki_page(workspace_id, slug, "제목1", "term")
    id2 = upsert_wiki_page(workspace_id, slug, "제목2", "term")
    assert id1 == id2
    db = _get_client()
    db.table("wiki_pages").delete().eq("id", id1).execute()

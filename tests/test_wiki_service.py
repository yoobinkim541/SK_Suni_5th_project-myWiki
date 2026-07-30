import uuid

import pytest
from dotenv import load_dotenv

load_dotenv()

from src.wiki.interface import upsert_wiki_page, create_wiki_version, WikiDraftInput, WikiSourceInput
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
    row = db.table("wiki_pages").select("title").eq("id", id1).single().execute()
    assert row.data["title"] == "제목1"
    db.table("wiki_pages").delete().eq("id", id1).execute()


def test_create_wiki_version_basic(workspace_id):
    slug = f"test-ver-{uuid.uuid4().hex[:8]}"
    draft = WikiDraftInput(
        workspace_id=workspace_id,
        slug=slug,
        title="버전 테스트",
        page_type="term",
        markdown="# 테스트\n내용입니다.",
        sources=[],
    )
    version_id = create_wiki_version(draft)
    assert isinstance(version_id, str)

    db = _get_client()
    ver = db.table("wiki_page_versions").select("*").eq("id", version_id).single().execute()
    assert ver.data["validation_status"] == "pending"
    assert ver.data["review_status"] == "pending"

    obj_key = ver.data["markdown_object_key"]
    content = db.storage.from_("wiki").download(obj_key)
    assert content.decode("utf-8") == "# 테스트\n내용입니다."

    # teardown
    db.storage.from_("wiki").remove([obj_key])
    db.table("wiki_page_sources").delete().eq("wiki_version_id", version_id).execute()
    db.table("wiki_page_versions").delete().eq("id", version_id).execute()
    db.table("wiki_pages").delete().eq("slug", slug).eq("workspace_id", workspace_id).execute()


def test_create_wiki_version_with_sources(workspace_id):
    slug = f"test-src-{uuid.uuid4().hex[:8]}"
    db = _get_client()
    doc_ver = db.table("document_versions").select("id").limit(1).execute()
    if not doc_ver.data:
        pytest.skip("document_versions 데이터 없음")
    doc_ver_id = doc_ver.data[0]["id"]

    draft = WikiDraftInput(
        workspace_id=workspace_id,
        slug=slug,
        title="출처 테스트",
        page_type="term",
        markdown="근거 있는 내용",
        sources=[
            WikiSourceInput(
                document_version_id=doc_ver_id,
                claim_text="근거 주장",
                support_type="supports",
            )
        ],
    )
    version_id = create_wiki_version(draft)

    sources = db.table("wiki_page_sources").select("*").eq("wiki_version_id", version_id).execute()
    assert len(sources.data) == 1
    assert sources.data[0]["citation_order"] == 1

    # teardown
    ver = db.table("wiki_page_versions").select("markdown_object_key").eq("id", version_id).single().execute()
    obj_key = ver.data["markdown_object_key"]
    db.storage.from_("wiki").remove([obj_key])
    db.table("wiki_page_sources").delete().eq("wiki_version_id", version_id).execute()
    db.table("wiki_page_versions").delete().eq("id", version_id).execute()
    db.table("wiki_pages").delete().eq("slug", slug).eq("workspace_id", workspace_id).execute()

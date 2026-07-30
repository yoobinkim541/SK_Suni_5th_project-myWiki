import uuid

import pytest
from dotenv import load_dotenv

load_dotenv()

from src.wiki.interface import upsert_wiki_page, create_wiki_version, WikiDraftInput, WikiSourceInput, record_wiki_validation, review_wiki_version, publish_wiki_version
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


@pytest.fixture
def version_id(workspace_id):
    slug = f"test-val-{uuid.uuid4().hex[:8]}"
    draft = WikiDraftInput(
        workspace_id=workspace_id,
        slug=slug,
        title="검증 테스트",
        page_type="term",
        markdown="내용",
        sources=[],
    )
    vid = create_wiki_version(draft)
    yield vid
    db = _get_client()
    ver = db.table("wiki_page_versions").select("markdown_object_key,page_id").eq("id", vid).single().execute()
    db.storage.from_("wiki").remove([ver.data["markdown_object_key"]])
    db.table("wiki_page_sources").delete().eq("wiki_version_id", vid).execute()
    db.table("wiki_page_versions").delete().eq("id", vid).execute()
    db.table("wiki_pages").delete().eq("id", ver.data["page_id"]).execute()


def test_record_wiki_validation(version_id):
    record_wiki_validation(version_id, "passed", 0.92)
    db = _get_client()
    ver = db.table("wiki_page_versions").select("validation_status,confidence_score").eq("id", version_id).single().execute()
    assert ver.data["validation_status"] == "passed"
    assert abs(ver.data["confidence_score"] - 0.92) < 0.001


def test_review_wiki_version(workspace_id, version_id):
    db = _get_client()
    profile = db.table("profiles").select("id").limit(1).execute()
    if not profile.data:
        pytest.skip("profiles 데이터 없음")
    reviewer_id = profile.data[0]["id"]

    review_wiki_version(version_id, reviewer_id, "approved")
    ver = db.table("wiki_page_versions").select("review_status,reviewed_by").eq("id", version_id).single().execute()
    assert ver.data["review_status"] == "approved"
    assert ver.data["reviewed_by"] == reviewer_id


def test_publish_wiki_version_raises_if_not_validated(version_id):
    db = _get_client()
    ver = db.table("wiki_page_versions").select("page_id").eq("id", version_id).single().execute()
    page_id = ver.data["page_id"]
    with pytest.raises(ValueError):
        publish_wiki_version(page_id, version_id)


def test_publish_wiki_version_success(workspace_id):
    slug = f"test-pub-{uuid.uuid4().hex[:8]}"
    draft = WikiDraftInput(
        workspace_id=workspace_id,
        slug=slug,
        title="게시 테스트",
        page_type="term",
        markdown="게시할 내용",
        sources=[],
    )
    vid = create_wiki_version(draft)
    db = _get_client()
    ver = db.table("wiki_page_versions").select("page_id,markdown_object_key").eq("id", vid).single().execute()
    page_id = ver.data["page_id"]
    obj_key = ver.data["markdown_object_key"]

    record_wiki_validation(vid, "passed", 0.95)
    profile = db.table("profiles").select("id").limit(1).execute()
    if not profile.data:
        pytest.skip("profiles 데이터 없음")
    review_wiki_version(vid, profile.data[0]["id"], "approved")

    publish_wiki_version(page_id, vid)

    page = db.table("wiki_pages").select("current_version_id,status,published_at").eq("id", page_id).single().execute()
    assert page.data["current_version_id"] == vid
    assert page.data["status"] == "published"
    assert page.data["published_at"] is not None

    # teardown — current_version_id FK를 먼저 해제해야 wiki_page_versions 삭제 가능
    db.table("wiki_pages").update({"current_version_id": None}).eq("id", page_id).execute()
    db.storage.from_("wiki").remove([obj_key])
    db.table("wiki_page_sources").delete().eq("wiki_version_id", vid).execute()
    db.table("wiki_page_versions").delete().eq("id", vid).execute()
    db.table("wiki_pages").delete().eq("id", page_id).execute()

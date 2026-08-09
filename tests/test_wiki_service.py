import os
import uuid

import pytest
from dotenv import load_dotenv

load_dotenv()

from src.wiki.interface import upsert_wiki_page, update_wiki_page_title, create_wiki_version, WikiDraftInput, WikiSourceInput, record_wiki_validation, review_wiki_version, publish_wiki_version, request_wiki_index
from src.wiki.query import get_published_wiki_page
from src.wiki.query import _get_client
from src.wiki.service import _build_source_rows


def test_build_source_rows_merges_claims_for_same_document():
    """create_wiki_version()의 실제 삽입 직전 단계. 같은 document_version_id를 근거로
    삼는 서로 다른 claim이 여러 개 들어와도(위키 중복 병합 배치가 두 원본 페이지의
    claim을 그대로 이어붙이는 경우) 프론트 "근거 문서" 목록에 같은 출처가 여러 장
    뜨지 않도록 한 문서당 한 행으로 합쳐야 한다. claim_text는 버리지 않고 이어붙인다."""
    rows = _build_source_rows(
        "version-1",
        [
            WikiSourceInput(document_version_id="doc-1", claim_text="주장 A", citation_order=1),
            WikiSourceInput(document_version_id="doc-1", claim_text="주장 B", citation_order=1),
            WikiSourceInput(document_version_id="doc-1", claim_text="주장 C", citation_order=2),
            WikiSourceInput(document_version_id="doc-2", claim_text="주장 D", citation_order=3),
        ],
    )

    assert len(rows) == 2
    doc1_row = next(r for r in rows if r["document_version_id"] == "doc-1")
    doc2_row = next(r for r in rows if r["document_version_id"] == "doc-2")
    assert doc1_row["citation_order"] == 1
    assert "주장 A" in doc1_row["claim_text"]
    assert "주장 B" in doc1_row["claim_text"]
    assert "주장 C" in doc1_row["claim_text"]
    assert doc2_row["citation_order"] == 3
    assert doc2_row["claim_text"] == "주장 D"


def test_build_source_rows_still_dedupes_identical_repeats():
    """기존 동작(같은 claim_text가 그대로 반복 전송되는 경우 1건으로) 회귀 방지."""
    rows = _build_source_rows(
        "version-1",
        [
            WikiSourceInput(document_version_id="doc-1", claim_text="같은 주장"),
            WikiSourceInput(document_version_id="doc-1", claim_text="같은 주장"),
        ],
    )
    assert len(rows) == 1
    assert rows[0]["claim_text"] == "같은 주장"


@pytest.fixture(scope="module")
def workspace_id() -> str:
    if not os.environ.get("SUPABASE_URL") or not (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SECRET_KEY")):
        pytest.skip("Supabase service credentials are not configured for wiki integration tests.")
    try:
        db = _get_client()
        res = db.table("workspaces").select("id").eq("slug", "mywiki").single().execute()
        return res.data["id"]
    except Exception as e:
        pytest.skip(f"Supabase connection failed (likely placeholder credentials): {type(e).__name__}")


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


def test_update_wiki_page_title_overwrites_existing_title(workspace_id):
    """upsert_wiki_page()는 위 테스트처럼 기존 title을 절대 안 바꾼다 — update_wiki_page_title()은
    그와 달리 명시적으로 덮어써야 한다(챗봇 재저장 시 사이드바 제목을 최신 LLM 제목으로 맞추는 용도)."""
    slug = f"test-title-{uuid.uuid4().hex[:8]}"
    page_id = upsert_wiki_page(workspace_id, slug, "원래 제목", "term")
    update_wiki_page_title(page_id, "새 제목")
    db = _get_client()
    row = db.table("wiki_pages").select("title").eq("id", page_id).single().execute()
    assert row.data["title"] == "새 제목"
    db.table("wiki_pages").delete().eq("id", page_id).execute()


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


def test_create_wiki_version_deduplicates_identical_sources(workspace_id):
    slug = f"test-src-dedupe-{uuid.uuid4().hex[:8]}"
    db = _get_client()
    doc_ver = db.table("document_versions").select("id").limit(1).execute()
    if not doc_ver.data:
        pytest.skip("document_versions ???? ??")
    doc_ver_id = doc_ver.data[0]["id"]

    draft = WikiDraftInput(
        workspace_id=workspace_id,
        slug=slug,
        title="?? ?? ?? ???",
        page_type="term",
        markdown="?? ?? ?? ???",
        sources=[
            WikiSourceInput(document_version_id=doc_ver_id, claim_text="?? ??", support_type="supports"),
            WikiSourceInput(document_version_id=doc_ver_id, claim_text="?? ??", support_type="supports"),
        ],
    )
    version_id = create_wiki_version(draft)

    sources = db.table("wiki_page_sources").select("*").eq("wiki_version_id", version_id).execute()
    assert len(sources.data) == 1

    ver = db.table("wiki_page_versions").select("markdown_object_key").eq("id", version_id).single().execute()
    obj_key = ver.data["markdown_object_key"]
    db.storage.from_("wiki").remove([obj_key])
    db.table("wiki_page_sources").delete().eq("wiki_version_id", version_id).execute()
    db.table("wiki_page_versions").delete().eq("id", version_id).execute()
    db.table("wiki_pages").delete().eq("slug", slug).eq("workspace_id", workspace_id).execute()


def test_create_wiki_version_merges_multiple_claims_for_same_document(workspace_id):
    """같은 document_version_id를 근거로 삼는 서로 다른 claim이 여러 개 들어와도
    (예: 위키 중복 병합 배치가 두 원본 페이지의 claim을 그대로 이어붙이는 경우),
    프론트 "근거 문서" 목록에 같은 출처가 여러 장 뜨지 않도록 한 문서당 한 행으로
    합쳐 저장해야 한다. 개별 claim_text는 버리지 않고 한 행에 이어붙인다."""
    slug = f"test-src-merge-{uuid.uuid4().hex[:8]}"
    db = _get_client()
    doc_ver = db.table("document_versions").select("id").limit(1).execute()
    if not doc_ver.data:
        pytest.skip("document_versions 데이터 없음")
    doc_ver_id = doc_ver.data[0]["id"]

    draft = WikiDraftInput(
        workspace_id=workspace_id,
        slug=slug,
        title="같은 출처 다중 claim 테스트",
        page_type="term",
        markdown="내용",
        sources=[
            WikiSourceInput(document_version_id=doc_ver_id, claim_text="주장 A", citation_order=1),
            WikiSourceInput(document_version_id=doc_ver_id, claim_text="주장 B", citation_order=1),
            WikiSourceInput(document_version_id=doc_ver_id, claim_text="주장 C", citation_order=2),
        ],
    )
    version_id = create_wiki_version(draft)

    sources = db.table("wiki_page_sources").select("*").eq("wiki_version_id", version_id).execute()
    assert len(sources.data) == 1
    row = sources.data[0]
    assert row["document_version_id"] == doc_ver_id
    assert row["citation_order"] == 1
    assert "주장 A" in row["claim_text"]
    assert "주장 B" in row["claim_text"]
    assert "주장 C" in row["claim_text"]

    # teardown
    ver = db.table("wiki_page_versions").select("markdown_object_key").eq("id", version_id).single().execute()
    obj_key = ver.data["markdown_object_key"]
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


def test_published_page_reads_only_latest_version_sources(workspace_id):
    slug = f"test-latest-src-{uuid.uuid4().hex[:8]}"
    db = _get_client()
    doc_ver_rows = db.table("document_versions").select("id").limit(2).execute()
    if len(doc_ver_rows.data) < 1:
        pytest.skip("document_versions ???? ??")
    first_doc_id = doc_ver_rows.data[0]["id"]
    second_doc_id = doc_ver_rows.data[-1]["id"]

    first_version_id = create_wiki_version(
        WikiDraftInput(
            workspace_id=workspace_id,
            slug=slug,
            title="?? ?? ?? ???",
            page_type="term",
            markdown="? ?? ??",
            sources=[WikiSourceInput(document_version_id=first_doc_id, claim_text="? ??")],
        )
    )
    first_version = db.table("wiki_page_versions").select("page_id,markdown_object_key").eq("id", first_version_id).single().execute()
    page_id = first_version.data["page_id"]
    first_obj_key = first_version.data["markdown_object_key"]

    second_version_id = create_wiki_version(
        WikiDraftInput(
            workspace_id=workspace_id,
            slug=slug,
            title="?? ?? ?? ???",
            page_type="term",
            markdown="? ?? ??",
            sources=[WikiSourceInput(document_version_id=second_doc_id, claim_text="?? ??")],
        )
    )
    second_version = db.table("wiki_page_versions").select("markdown_object_key").eq("id", second_version_id).single().execute()
    second_obj_key = second_version.data["markdown_object_key"]

    record_wiki_validation(second_version_id, "passed", 0.95)
    profile = db.table("profiles").select("id").limit(1).execute()
    if not profile.data:
        pytest.skip("profiles ???? ??")
    review_wiki_version(second_version_id, profile.data[0]["id"], "approved")
    publish_wiki_version(page_id, second_version_id)

    published = get_published_wiki_page(workspace_id, slug)
    assert published is not None
    assert [source.document_version_id for source in published.sources] == [str(second_doc_id)]

    db.table("wiki_pages").update({"current_version_id": None}).eq("id", page_id).execute()
    db.storage.from_("wiki").remove([first_obj_key, second_obj_key])
    db.table("wiki_page_sources").delete().eq("wiki_version_id", first_version_id).execute()
    db.table("wiki_page_sources").delete().eq("wiki_version_id", second_version_id).execute()
    db.table("wiki_page_versions").delete().eq("id", first_version_id).execute()
    db.table("wiki_page_versions").delete().eq("id", second_version_id).execute()
    db.table("wiki_pages").delete().eq("id", page_id).execute()


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


def test_request_wiki_index(workspace_id):
    slug = f"test-idx-{uuid.uuid4().hex[:8]}"
    draft = WikiDraftInput(
        workspace_id=workspace_id,
        slug=slug,
        title="색인 테스트",
        page_type="term",
        markdown="색인할 내용",
        sources=[],
    )
    vid = create_wiki_version(draft)
    db = _get_client()
    ver = db.table("wiki_page_versions").select("page_id,markdown_object_key").eq("id", vid).single().execute()
    page_id = ver.data["page_id"]
    obj_key = ver.data["markdown_object_key"]

    job_id = request_wiki_index(vid, "wiki-ko")
    assert isinstance(job_id, str)

    job = db.table("pipeline_jobs").select("*").eq("id", job_id).single().execute()
    assert job.data["job_type"] == "index_qmd"
    assert job.data["status"] == "pending"
    assert job.data["workspace_id"] == workspace_id

    entry = db.table("qmd_index_entries").select("*").eq("wiki_version_id", vid).single().execute()
    assert entry.data["collection_name"] == "wiki-ko"
    assert entry.data["status"] == "pending"

    # teardown
    db.table("pipeline_jobs").delete().eq("id", job_id).execute()
    db.table("qmd_index_entries").delete().eq("wiki_version_id", vid).execute()
    db.storage.from_("wiki").remove([obj_key])
    db.table("wiki_page_versions").delete().eq("id", vid).execute()
    db.table("wiki_pages").delete().eq("id", page_id).execute()


def test_review_wiki_version_accepts_none_reviewer_for_auto_approval(workspace_id):
    slug = f"test-auto-{uuid.uuid4().hex[:8]}"
    draft = WikiDraftInput(
        workspace_id=workspace_id,
        slug=slug,
        title="자동승인 테스트",
        page_type="term",
        markdown="# 테스트\n내용",
        sources=[],
        generated_by="llm",
    )
    version_id = create_wiki_version(draft)

    review_wiki_version(version_id, None, "approved")

    db = _get_client()
    ver = db.table("wiki_page_versions").select("review_status, reviewed_by").eq("id", version_id).single().execute()
    assert ver.data["review_status"] == "approved"
    assert ver.data["reviewed_by"] is None

    page = db.table("wiki_pages").select("id").eq("workspace_id", workspace_id).eq("slug", slug).single().execute()
    db.table("wiki_page_versions").delete().eq("id", version_id).execute()
    db.table("wiki_pages").delete().eq("id", page.data["id"]).execute()


def test_published_page_sources_include_document_metadata(workspace_id):
    """
    WikiPage 화면(mockWiki.js)이 기대하는 출처 표시(매체명·문서 제목·게시일·신뢰도)는
    wiki_page_sources가 document_version_id만 줘서는 못 채운다 — document_versions/
    documents/sources/document_analysis_results 조인 결과가 실려 오는지 확인한다.
    """
    db = _get_client()
    analyzed = (
        db.table("document_analysis_results")
        .select("document_version_id")
        .eq("workspace_id", workspace_id)
        .not_.is_("reliability_score", "null")
        .limit(1)
        .execute()
    )
    if not analyzed.data:
        pytest.skip("신뢰도 점수가 있는 document_analysis_results 데이터 없음")
    doc_ver_id = analyzed.data[0]["document_version_id"]

    slug = f"test-src-meta-{uuid.uuid4().hex[:8]}"
    draft = WikiDraftInput(
        workspace_id=workspace_id,
        slug=slug,
        title="출처 메타데이터 테스트",
        page_type="term",
        markdown="근거 있는 내용",
        sources=[WikiSourceInput(document_version_id=doc_ver_id, claim_text="근거 주장")],
    )
    version_id = create_wiki_version(draft)
    ver = db.table("wiki_page_versions").select("page_id,markdown_object_key").eq("id", version_id).single().execute()
    page_id = ver.data["page_id"]
    obj_key = ver.data["markdown_object_key"]

    record_wiki_validation(version_id, "passed", 0.95)
    profile = db.table("profiles").select("id").limit(1).execute()
    if not profile.data:
        pytest.skip("profiles 데이터 없음")
    review_wiki_version(version_id, profile.data[0]["id"], "approved")
    publish_wiki_version(page_id, version_id)

    published = get_published_wiki_page(workspace_id, slug)
    assert published is not None
    assert len(published.sources) == 1
    source = published.sources[0]
    assert source.document_version_id == str(doc_ver_id)
    assert source.document_title is not None
    assert source.reliability_score is not None

    # teardown
    db.table("wiki_pages").update({"current_version_id": None}).eq("id", page_id).execute()
    db.storage.from_("wiki").remove([obj_key])
    db.table("wiki_page_sources").delete().eq("wiki_version_id", version_id).execute()
    db.table("wiki_page_versions").delete().eq("id", version_id).execute()
    db.table("wiki_pages").delete().eq("id", page_id).execute()

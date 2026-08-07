"""
collectors / preprocessing 파이프라인 5케이스.

1. 신규 문서                        test_collect_creates_new_document
2. 동일 해시 skip                   test_preprocess_skips_when_content_hash_unchanged
3. 내용 변경 시 version_no 증가     test_preprocess_bumps_version_no_when_content_changes
4. 파서 실패 기록                   test_preprocess_records_parser_failure
5. 다른 workspace 데이터 조회 차단  test_other_workspace_data_is_not_visible
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from conftest import EMPTY_HTML, StubFeed
from fake_supabase import FakeSupabase

from src.collectors.interface import collect, register_source
from src.pipeline_common.constants import MAX_RETRY
from src.pipeline_common.models import CollectRequest
from src.preprocessing.interface import get_document_refs, get_markdown, preprocess


def _jobs(supabase: FakeSupabase, **filters) -> list[dict]:
    return [
        row
        for row in supabase.rows("pipeline_jobs")
        if all(str(row.get(k)) == str(v) for k, v in filters.items())
    ]


def _collect_once(workspace_id: UUID, source_id: UUID) -> list:
    return collect(CollectRequest(workspace_id=workspace_id, source_id=source_id))


# ------------------------------------------------------------
# 1. 신규 문서
# ------------------------------------------------------------


def test_collect_creates_new_document(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed: StubFeed
) -> None:
    collected = _collect_once(workspace_id, source_id)

    assert len(collected) == 1
    document = collected[0]
    assert document.is_new_document is True
    assert document.status == "active"
    assert document.workspace_id == workspace_id
    assert str(document.canonical_url) == "https://example.com/news/1"
    assert document.title == "SK하이닉스 HBM4 양산"

    # documents 행 1개
    rows = supabase.rows("documents")
    assert len(rows) == 1
    assert rows[0]["workspace_id"] == str(workspace_id)

    # raw 버킷 파일 (명세 §6-2 경로 규칙, object_key에 버킷명 포함)
    expected_key = f"raw/{workspace_id}/{document.document_id}/1.html"
    assert document.raw_object_key == expected_key
    assert expected_key in supabase.objects

    # document_versions는 만들지 않는다 (명세 §3-2)
    assert supabase.rows("document_versions") == []

    # job 2계층: 소스 단위는 target_type NULL, 문서 단위는 'document'
    source_jobs = [j for j in _jobs(supabase, job_type="collect") if j.get("target_type") is None]
    assert len(source_jobs) == 1
    assert source_jobs[0]["status"] == "completed"
    assert source_jobs[0]["progress"] == 100
    assert source_jobs[0]["result"]["collected"] == 1
    assert source_jobs[0]["payload"]["source_id"] == str(source_id)

    document_jobs = _jobs(supabase, job_type="collect", target_type="document")
    assert len(document_jobs) == 1
    assert document_jobs[0]["status"] == "completed"
    assert document_jobs[0]["result"]["raw_object_key"] == expected_key
    assert document_jobs[0]["result"]["content_type"] == "text/html"
    assert str(document_jobs[0]["id"]) == str(document.collect_job_id)

    # 같은 URL 재수집: 새 문서를 만들지 않는다 (uq_documents_workspace_url)
    again = _collect_once(workspace_id, source_id)
    assert again[0].is_new_document is False
    assert again[0].document_id == document.document_id
    assert len(supabase.rows("documents")) == 1


# ------------------------------------------------------------
# 1-b. canonical_url 정규화 (pipeline_common/urls.py 배선)
#
# 함수 단위 검증은 test_urls.py에 있다. 여기서는 collect()가 실제로 그 함수를
# 거쳐 documents.canonical_url을 정하는지, 그래서 문서가 합쳐지는지를 본다.
# ------------------------------------------------------------


def test_collect_normalizes_canonical_url(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed: StubFeed
) -> None:
    feed.set_article(url="https://example.com/news/1?oc=5&hl=en-US&idxno=99")

    document = _collect_once(workspace_id, source_id)[0]

    # 구글 표시 파라미터만 빠지고 CMS 식별자는 남는다
    assert str(document.canonical_url) == "https://example.com/news/1?idxno=99"
    assert supabase.rows("documents")[0]["canonical_url"] == "https://example.com/news/1?idxno=99"


def test_collect_folds_urls_that_differ_only_by_google_params(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed: StubFeed
) -> None:
    """표시 파라미터만 다른 같은 기사가 두 문서가 되면 안 된다."""
    feed.set_article(url="https://example.com/news/1?oc=5&hl=en-US")
    first = _collect_once(workspace_id, source_id)[0]

    feed.set_article(url="https://example.com/news/1?hl=ko&ceid=KR:ko")
    second = _collect_once(workspace_id, source_id)[0]

    assert second.is_new_document is False
    assert second.document_id == first.document_id
    assert len(supabase.rows("documents")) == 1


def test_collect_keeps_www_variants_separate(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed: StubFeed
) -> None:
    """
    www.을 지우지 않기로 한 결정을 고정한다. 지우면 기존 문서 209건과 값이
    어긋나 다음 수집에서 전부 중복으로 재생성된다(2026-08-06 실측).
    이 테스트가 깨지면 그 결정이 바뀐 것이므로 백필을 함께 검토해야 한다.
    """
    feed.set_article(url="https://www.example.com/news/1")
    _collect_once(workspace_id, source_id)

    feed.set_article(url="https://example.com/news/1")
    second = _collect_once(workspace_id, source_id)[0]

    assert second.is_new_document is True
    assert len(supabase.rows("documents")) == 2


# ------------------------------------------------------------
# 2. 동일 해시 skip
# ------------------------------------------------------------


def test_preprocess_skips_when_content_hash_unchanged(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed: StubFeed
) -> None:
    document_id = _collect_once(workspace_id, source_id)[0].document_id

    first = preprocess(document_id)
    assert first is not None
    assert first.is_new_version is True
    assert first.version_no == 1
    assert first.markdown_object_key == f"processed/{workspace_id}/{document_id}/1.md"
    assert first.parser_version == "html-v1.1"
    assert first.language == "ko"

    # 재수집 자체는 raw v2를 올린다. 내용이 같아 버전 행이 안 생기므로 미참조
    # 파일로 남지만, 삭제하지 않고 그대로 둔다 (명세 §6-3)
    _collect_once(workspace_id, source_id)
    assert f"raw/{workspace_id}/{document_id}/2.html" in supabase.objects

    # 같은 원문을 다시 정제 -> 새 행도 새 파일도 만들지 않는다 (명세 §3-3)
    objects_before_second = dict(supabase.objects)
    second = preprocess(document_id)

    assert second is not None
    assert second.is_new_version is False
    assert second.document_version_id == first.document_version_id
    assert second.content_hash == first.content_hash
    assert len(supabase.rows("document_versions")) == 1
    # Markdown 업로드도 하지 않는다 (해시 계산은 메모리에서 끝난다)
    assert supabase.objects == objects_before_second
    assert [k for k in supabase.objects if k.startswith("processed/")] == [
        first.markdown_object_key
    ]

    parse_jobs = _jobs(supabase, job_type="parse_document")
    assert len(parse_jobs) == 1  # idempotency_key 충돌 -> 기존 job 재사용
    assert parse_jobs[0]["status"] == "completed"
    assert parse_jobs[0]["retry_count"] == 0  # 실패가 없었으므로 재시도 횟수도 0
    assert parse_jobs[0]["result"]["is_new_version"] is False


# ------------------------------------------------------------
# 3. 내용 변경 시 version_no 증가
# ------------------------------------------------------------


def test_preprocess_bumps_version_no_when_content_changes(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed: StubFeed
) -> None:
    document_id = _collect_once(workspace_id, source_id)[0].document_id
    first = preprocess(document_id)
    assert first is not None and first.version_no == 1

    # 같은 URL, 본문만 변경
    feed.set_article(body="SK하이닉스가 HBM4 양산을 연기했다고 정정 보도가 나왔다.")
    collected = _collect_once(workspace_id, source_id)
    assert collected[0].is_new_document is False
    assert collected[0].raw_object_key == f"raw/{workspace_id}/{document_id}/2.html"

    second = preprocess(document_id)

    assert second is not None
    assert second.is_new_version is True
    assert second.version_no == 2
    assert second.content_hash != first.content_hash
    assert second.document_version_id != first.document_version_id
    assert second.markdown_object_key == f"processed/{workspace_id}/{document_id}/2.md"
    # raw_object_key는 경로를 재계산하지 않고 collect job의 값을 그대로 쓴다 (명세 §6-2)
    assert second.raw_object_key == f"raw/{workspace_id}/{document_id}/2.html"

    versions = supabase.rows("document_versions")
    assert sorted(v["version_no"] for v in versions) == [1, 2]
    # 기존 버전은 수정·삭제하지 않는다 (명세 §7-2)
    assert get_markdown(first.document_version_id, workspace_id) != get_markdown(
        second.document_version_id, workspace_id
    )


# ------------------------------------------------------------
# 4. 파서 실패 기록
# ------------------------------------------------------------


def test_preprocess_records_parser_failure(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed: StubFeed
) -> None:
    feed.set_article(raw=EMPTY_HTML)
    document_id = _collect_once(workspace_id, source_id)[0].document_id

    assert preprocess(document_id) is None

    parse_jobs = _jobs(supabase, job_type="parse_document", target_id=document_id)
    assert len(parse_jobs) == 1
    job = parse_jobs[0]
    assert job["status"] == "failed"
    assert job["target_type"] == "document"
    assert "정제 실패" in job["error_message"]
    assert job["retry_count"] == 1

    # 실패해도 버전은 생기지 않고, raw는 재시도 대상이라 남는다 (명세 §6-3)
    assert supabase.rows("document_versions") == []
    assert f"raw/{workspace_id}/{document_id}/1.html" in supabase.objects
    assert supabase.rows("documents")[0]["status"] == "active"

    # MAX_RETRY까지 반복 실패하면 documents.status='failed' (명세 §3-3, §5-1)
    for _ in range(MAX_RETRY - 1):
        assert preprocess(document_id) is None

    assert _jobs(supabase, job_type="parse_document")[0]["retry_count"] == MAX_RETRY
    assert supabase.rows("documents")[0]["status"] == "failed"


# ------------------------------------------------------------
# 5. 다른 workspace 데이터가 조회되지 않는지
# ------------------------------------------------------------


def test_other_workspace_data_is_not_visible(
    supabase: FakeSupabase,
    workspace_id: UUID,
    other_workspace_id: UUID,
    source_id: UUID,
    feed: StubFeed,
) -> None:
    mine = preprocess(_collect_once(workspace_id, source_id)[0].document_id)
    assert mine is not None

    # 다른 workspace가 자기 소스로 자기 문서를 수집·정제한다
    other_source_id = register_source(
        other_workspace_id, name="다른 워크스페이스 RSS", source_type="rss"
    )
    feed.set_article(
        url="https://example.com/news/2", title="다른 워크스페이스 문서", body="다른 워크스페이스 본문."
    )
    theirs = preprocess(_collect_once(other_workspace_id, other_source_id)[0].document_id)
    assert theirs is not None

    # get_markdown: 소유 workspace로만 읽힌다 (명세 §3-6)
    assert "HBM4" in get_markdown(mine.document_version_id, workspace_id)
    with pytest.raises(FileNotFoundError):
        get_markdown(theirs.document_version_id, workspace_id)
    with pytest.raises(FileNotFoundError):
        get_markdown(mine.document_version_id, other_workspace_id)
    with pytest.raises(FileNotFoundError):
        get_markdown(mine.document_version_id, uuid4())

    # get_document_refs: 다른 workspace의 id는 결과에서 제외된다 (명세 §3-7)
    refs = get_document_refs(
        [mine.document_version_id, theirs.document_version_id], workspace_id
    )
    assert len(refs) == 1
    assert refs[0].document_version_id == mine.document_version_id
    assert refs[0].source_name == "테스트 RSS"
    assert refs[0].source_type == "rss"
    assert refs[0].version_no == 1
    assert refs[0].title == "SK하이닉스 HBM4 양산"

    assert get_document_refs([theirs.document_version_id], workspace_id) == []
    assert get_document_refs([mine.document_version_id], other_workspace_id) == []
    assert get_document_refs([], workspace_id) == []

    # sources도 workspace 밖에서는 보이지 않는다
    assert _collect_once(workspace_id, other_source_id) == []
    cancelled = [j for j in supabase.rows("pipeline_jobs") if j["status"] == "cancelled"]
    assert len(cancelled) == 1

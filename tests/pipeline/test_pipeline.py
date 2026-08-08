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

from src.collectors import fetchers
from src.collectors import interface as collectors_interface
from src.collectors.interface import collect, register_source
from src.pipeline_common import repository
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


def test_active_문서가_한_페이지를_넘으면_전건을_받는다(
    supabase: FakeSupabase, workspace_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    PostgREST는 한 응답에 기본 1,000행까지만 주고 넘으면 **에러도 경고도 없이** 자른다.

    2026-08-07 실측: active 문서 1,470건인데 list_active_documents가 1,000건만
    돌려주고 있었다. find_pending_documents가 이 목록으로 정제 대상을 고르므로
    나머지 470건은 재정제 대상이 되지 못했고, 재해시 마이그레이션도 172건을 놓쳤다.

    조용히 잘리는 종류라 눈으로는 안 보인다. 페이지 크기를 작게 바꿔 경계를 넘긴다.
    """
    monkeypatch.setattr(repository, "_PAGE_SIZE", 3)
    total = 7  # 페이지 3 + 3 + 1
    for index in range(total):
        repository.insert_document(
            workspace_id,
            source_id=None,
            title=f"문서 {index}",
            canonical_url=f"https://example.com/{index}",
            published_at=None,
        )

    rows = repository.list_active_documents(workspace_id)

    assert len(rows) == total
    assert len({str(r["id"]) for r in rows}) == total  # 페이지가 겹치지 않는다


def test_다른_workspace_문서는_페이지_조회에도_안_섞인다(
    supabase: FakeSupabase, workspace_id: UUID, other_workspace_id: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """페이지를 나눠도 workspace 필터가 매 페이지에 걸려야 한다."""
    monkeypatch.setattr(repository, "_PAGE_SIZE", 2)
    for index in range(5):
        repository.insert_document(
            workspace_id, source_id=None, title=f"내 문서 {index}",
            canonical_url=f"https://example.com/mine/{index}", published_at=None,
        )
    for index in range(4):
        repository.insert_document(
            other_workspace_id, source_id=None, title=f"남의 문서 {index}",
            canonical_url=f"https://example.com/other/{index}", published_at=None,
        )

    rows = repository.list_active_documents(workspace_id)

    assert len(rows) == 5
    assert all(str(r["workspace_id"]) == str(workspace_id) for r in rows)


# ---------------------------------------------------------------------------
# 재수집 간격 정책
#
# 수집이 스케줄러 실행시간의 82%인데(2026-08-07 실측) 매번 피드 전량을 다시 받는다.
# 그중 실제로 본문이 바뀌는 건 3.6%였다. 조건부 요청은 이 코퍼스에서 안 통한다
# (도메인 18종 전부 200 응답, 304 0건).
# ---------------------------------------------------------------------------


def test_최근_수집한_주소는_다시_받지_않는다(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed
) -> None:
    _collect_once(workspace_id, source_id)

    should_fetch = collectors_interface._build_refetch_policy(workspace_id)

    assert should_fetch("https://example.com/news/1") is False


def test_간격이_지난_주소는_다시_받는다(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed, monkeypatch
) -> None:
    """간격을 0으로 두면 방금 받은 것도 대상이 된다 — 경계가 시각 비교임을 고정한다."""
    _collect_once(workspace_id, source_id)
    monkeypatch.setattr(collectors_interface, "REFETCH_INTERVAL_HOURS", 0)

    should_fetch = collectors_interface._build_refetch_policy(workspace_id)

    assert should_fetch("https://example.com/news/1") is True


def test_처음_보는_주소는_받는다(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed
) -> None:
    _collect_once(workspace_id, source_id)

    should_fetch = collectors_interface._build_refetch_policy(workspace_id)

    assert should_fetch("https://example.com/news/처음") is True


def test_표기가_달라도_같은_주소로_본다(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed
) -> None:
    """
    수집기가 주는 주소와 documents.canonical_url은 같은 정규화를 거쳐야 맞는다.
    안 맞으면 정책이 통과시켜 버려서 절감이 0이 된다 — 조용히 실패하는 종류다.
    """
    _collect_once(workspace_id, source_id)

    should_fetch = collectors_interface._build_refetch_policy(workspace_id)

    assert should_fetch("https://example.com/news/1?utm_source=x") is False


def test_수집이_끝나면_정책을_푼다(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed
) -> None:
    """모듈 전역이라 안 풀면 다음 호출까지 새어 나간다."""
    _collect_once(workspace_id, source_id)

    assert fetchers._refetch_policy is None


def test_정책이_없으면_전부_받는다() -> None:
    """주입 전 기본 동작은 기존과 같아야 한다."""
    fetchers.reset_refetch_policy()

    fetchers._ensure_fetchable("https://example.com/아무거나")  # 예외 없음


def test_정책이_거부하면_RecentlyFetchedError() -> None:
    fetchers.set_refetch_policy(lambda url: False)
    try:
        with pytest.raises(fetchers.RecentlyFetchedError):
            fetchers._ensure_fetchable("https://example.com/1")
    finally:
        fetchers.reset_refetch_policy()

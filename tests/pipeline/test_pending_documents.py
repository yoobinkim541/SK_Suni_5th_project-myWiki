"""
정제 대기 목록 판정 테스트 (scripts/run_pipeline.py).

대기 조건은 "document_versions 행이 없는 문서"만으로는 부족하다. collect()는
재수집 때마다 raw를 새로 올리는데 정제를 건너뛰면 document_versions가 참조하지
않는 파일만 쌓이고, content_hash·version_no 구조가 자동 경로에서 동작하지 않는다.
그래서 "마지막 완료된 collect job이 최신 버전보다 나중"인 문서도 대기에 넣는다.

실제 API·DB를 쓰지 않는다. conftest의 FakeSupabase와 StubFeed로 돈다.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from uuid import UUID

from fake_supabase import FakeSupabase

from src.collectors.interface import collect
from src.pipeline_common.models import CollectRequest
from src.preprocessing.interface import preprocess

# scripts/는 패키지가 아니라 파일 경로로 읽어들인다.
_RUN_PIPELINE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_pipeline.py"
_spec = importlib.util.spec_from_file_location("run_pipeline", _RUN_PIPELINE_PATH)
run_pipeline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_pipeline)


def _collect_once(workspace_id: UUID, source_id: UUID):
    return collect(CollectRequest(workspace_id=workspace_id, source_id=source_id))


def test_document_without_version_is_pending_as_new(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed
) -> None:
    """아직 정제된 적 없는 문서는 '신규'로 잡힌다."""
    document_id = _collect_once(workspace_id, source_id)[0].document_id

    new_targets, recollected = run_pipeline.find_pending_documents(workspace_id)

    assert new_targets == [document_id]
    assert recollected == []


def test_recollected_document_is_pending_as_reprocess(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed
) -> None:
    """정제 이후 다시 수집된 문서는 '재정제'로 잡힌다."""
    document_id = _collect_once(workspace_id, source_id)[0].document_id
    preprocess(document_id)
    _collect_once(workspace_id, source_id)  # 마지막 버전보다 나중에 끝난 collect job

    new_targets, recollected = run_pipeline.find_pending_documents(workspace_id)

    assert new_targets == []
    assert recollected == [document_id]


def test_processed_document_without_recollect_is_not_pending(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed
) -> None:
    """정제 후 재수집이 없었으면 대기 목록에서 빠진다 — 불필요한 호출을 줄이는 게 목적이다."""
    document_id = _collect_once(workspace_id, source_id)[0].document_id
    preprocess(document_id)

    new_targets, recollected = run_pipeline.find_pending_documents(workspace_id)

    assert new_targets == []
    assert recollected == []


def test_reprocess_with_same_content_creates_no_new_version(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed
) -> None:
    """
    재정제해도 내용이 같으면 새 행도 새 파일도 만들지 않는다 (명세 §3-3).
    이 멱등성 덕분에 (2) 조건으로 몇 번 더 불러도 버전이 부풀지 않는다.
    """
    document_id = _collect_once(workspace_id, source_id)[0].document_id
    first = preprocess(document_id)
    _collect_once(workspace_id, source_id)  # 본문 그대로 재수집

    second = preprocess(document_id)

    assert second is not None
    assert second.is_new_version is False
    assert second.document_version_id == first.document_version_id
    assert second.version_no == 1
    assert len(supabase.rows("document_versions")) == 1


def test_reprocess_with_same_content_clears_pending(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed
) -> None:
    """
    내용이 같아 새 버전이 안 생긴 문서도 재정제 후에는 대기에서 빠져야 한다.

    버전 생성 시각만 보면 dedup된 문서는 버전 시각이 갱신되지 않아 매 실행마다
    다시 잡힌다 — 줄이려던 불필요한 호출이 그대로 남는다.
    """
    document_id = _collect_once(workspace_id, source_id)[0].document_id
    preprocess(document_id)
    _collect_once(workspace_id, source_id)  # 본문 그대로 재수집
    assert run_pipeline.find_pending_documents(workspace_id)[1] == [document_id]

    preprocess(document_id)  # 재정제 -> 내용 같아 새 버전 없음

    new_targets, recollected = run_pipeline.find_pending_documents(workspace_id)
    assert new_targets == []
    assert recollected == []
    assert len(supabase.rows("document_versions")) == 1


def test_reprocess_with_changed_content_bumps_version_no(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed
) -> None:
    """본문이 바뀐 뒤 재수집·재정제하면 version_no가 2로 올라간다."""
    document_id = _collect_once(workspace_id, source_id)[0].document_id
    first = preprocess(document_id)
    feed.set_article(body="HBM4 양산 일정이 한 분기 앞당겨졌다.")
    _collect_once(workspace_id, source_id)

    second = preprocess(document_id)

    assert second is not None
    assert second.is_new_version is True
    assert second.version_no == 2
    assert second.content_hash != first.content_hash
    assert len(supabase.rows("document_versions")) == 2


def test_summary_separates_new_and_reprocess_counts(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed
) -> None:
    """요약에서 신규 정제와 재정제가 구분돼야 한다."""
    # 문서 A: 정제까지 마친 뒤 본문이 바뀐 채 재수집 -> 재정제 대상
    document_id = _collect_once(workspace_id, source_id)[0].document_id
    preprocess(document_id)
    feed.set_article(body="본문이 바뀌었다.")
    _collect_once(workspace_id, source_id)
    # 문서 B: 한 번도 정제된 적 없음 -> 신규
    feed.set_article(url="https://example.com/news/2", title="새 기사")
    _collect_once(workspace_id, source_id)

    summary = run_pipeline.run_preprocess(workspace_id)

    assert summary["new"] == 1
    assert summary["recollected"] == 1
    assert summary["pending"] == 2
    assert summary["succeeded"] == 2
    assert summary["new_versions"] == 2  # 재정제분은 내용이 바뀌었으므로 새 버전
    assert summary["failed"] == 0


def _collect_documents(workspace_id: UUID, source_id: UUID, feed, count: int) -> None:
    """서로 다른 URL로 문서 count건을 수집한다 (정제는 하지 않는다)."""
    for index in range(count):
        feed.set_article(url=f"https://example.com/news/{index}", title=f"기사 {index}")
        _collect_once(workspace_id, source_id)


def test_한_회차에_상한만큼만_정제한다(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed
) -> None:
    """
    무제한 루프였다. 대기가 적을 땐 안 보이다가, list_active_documents의 1,000행
    잘림을 고치자 그동안 안 보이던 문서 307건이 한꺼번에 대기로 들어오면서 드러났다.
    대기가 더 커지면 한 회차가 예산을 통째로 먹는다.
    """
    _collect_documents(workspace_id, source_id, feed, 5)

    summary = run_pipeline.run_preprocess(workspace_id, limit=2)

    assert summary["pending"] == 5  # 대기열 전체
    assert summary["processing"] == 2  # 이번 회차 몫
    assert summary["deferred"] == 3
    assert summary["succeeded"] == 2
    assert len(supabase.rows("document_versions")) == 2


def test_미룬_문서는_다음_회차가_이어서_처리한다(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed
) -> None:
    """상한이 문서를 버리는 게 아니라 미루는 것임을 고정한다."""
    _collect_documents(workspace_id, source_id, feed, 5)

    run_pipeline.run_preprocess(workspace_id, limit=2)
    second = run_pipeline.run_preprocess(workspace_id, limit=2)
    third = run_pipeline.run_preprocess(workspace_id, limit=2)

    assert second["processing"] == 2
    assert third["processing"] == 1  # 남은 1건
    assert third["deferred"] == 0
    assert len(supabase.rows("document_versions")) == 5


def test_상한이_없으면_대기를_전부_처리한다(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed
) -> None:
    _collect_documents(workspace_id, source_id, feed, 5)

    summary = run_pipeline.run_preprocess(workspace_id, limit=None)

    assert summary["processing"] == 5
    assert summary["deferred"] == 0
    assert len(supabase.rows("document_versions")) == 5

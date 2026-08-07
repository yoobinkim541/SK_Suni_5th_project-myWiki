"""
재해시 마이그레이션 테스트 (scripts/run_pipeline.py --rehash).

이 경로가 지켜야 하는 것은 하나다 — **새 document_versions 행을 만들지 않는다.**
분석 단계는 "분석 행이 없는 document_versions"를 잡아가므로, 파서 교체로 993개 행이
새로 생기면 그대로 LLM 4단계 대기열에 얹힌다. 백로그를 줄이려는 변경이 백로그를
1.5배로 만든다.

행 id가 그대로여야 기존 document_analysis_results·wiki_page_sources·report_citations·
message_citations가 전부 유효하게 남는다는 뜻이기도 하다.

실제 API·DB를 쓰지 않는다. conftest의 FakeSupabase와 StubFeed로 돈다.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from uuid import UUID

import pytest
from fake_supabase import FakeSupabase

from src.collectors.interface import collect
from src.pipeline_common import repository, storage
from src.pipeline_common.models import CollectRequest
from src.preprocessing.interface import preprocess
from src.preprocessing.parsers import PARSER_VERSIONS

_RUN_PIPELINE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_pipeline.py"
_spec = importlib.util.spec_from_file_location("run_pipeline", _RUN_PIPELINE_PATH)
run_pipeline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_pipeline)

# 구 파서가 남겼다고 가정할 해시. 형식만 맞으면 된다(SHA-256 소문자 hex 64자).
OLD_HASH = "0" * 64
OLD_MARKDOWN = "# 예전 정제 결과\n\n관련기사 목록이 섞여 있던 시절의 Markdown이다.\n"


def _versions(supabase: FakeSupabase) -> list[dict]:
    return supabase.rows("document_versions")


def _make_v1_document(workspace_id: UUID, source_id: UUID) -> tuple[UUID, dict]:
    """정상 수집·정제 후, 그 행을 '구 파서가 만든 것'처럼 되돌려 놓는다."""
    document_id = collect(
        CollectRequest(workspace_id=workspace_id, source_id=source_id)
    )[0].document_id
    processed = preprocess(document_id)
    assert processed is not None

    version_id = UUID(str(processed.document_version_id))
    storage.upload(
        processed.markdown_object_key, OLD_MARKDOWN.encode("utf-8"), "text/markdown"
    )
    repository.update_document_version_content(
        version_id, content_hash=OLD_HASH, parser_version="html-v1.0", language="ko"
    )
    return document_id, repository.get_version(version_id)


@pytest.fixture
def report_path(tmp_path: Path) -> Path:
    return tmp_path / "rehash.jsonl"


def test_재해시는_새_버전_행을_만들지_않는다(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed, report_path: Path
) -> None:
    """이 테스트가 깨지면 마이그레이션의 존재 이유가 사라진다."""
    _, before = _make_v1_document(workspace_id, source_id)
    assert len(_versions(supabase)) == 1

    summary = run_pipeline.run_rehash(
        workspace_id, limit=None, dry_run=False, force=False, report_path=report_path
    )

    assert summary["rehashed"] == 1
    assert len(_versions(supabase)) == 1

    after = repository.get_version(UUID(str(before["id"])))
    assert after["id"] == before["id"]  # 인용이 가리키는 id가 그대로다
    assert after["version_no"] == before["version_no"]
    assert after["content_hash"] != OLD_HASH
    assert after["parser_version"] == PARSER_VERSIONS["html"]


def test_재해시_뒤_정상_정제는_새_버전을_만들지_않는다(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed, report_path: Path
) -> None:
    """
    이 작업의 목적 그 자체.

    재해시로 행의 해시가 신 파서 기준이 됐으므로, 다음 정상 정제는 같은 해시를 계산해
    dedup 경로로 빠진다. 이게 안 되면 마이그레이션 직후부터 다시 버전이 쌓인다.
    """
    document_id, _ = _make_v1_document(workspace_id, source_id)
    run_pipeline.run_rehash(
        workspace_id, limit=None, dry_run=False, force=False, report_path=report_path
    )

    processed = preprocess(document_id)

    assert processed is not None
    assert processed.is_new_version is False
    assert len(_versions(supabase)) == 1


def test_markdown_객체를_같은_경로에_덮어쓴다(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed, report_path: Path
) -> None:
    """경로가 바뀌면 uq_dv_markdown_object_key 때문에 제자리 갱신 자체가 불가능하다."""
    _, before = _make_v1_document(workspace_id, source_id)
    bucket, path = storage.split_key(before["markdown_object_key"])

    run_pipeline.run_rehash(
        workspace_id, limit=None, dry_run=False, force=False, report_path=report_path
    )

    after = repository.get_version(UUID(str(before["id"])))
    assert after["markdown_object_key"] == before["markdown_object_key"]
    assert supabase.objects[f"{bucket}/{path}"].decode("utf-8") != OLD_MARKDOWN


def test_dry_run은_아무것도_쓰지_않는다(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed, report_path: Path
) -> None:
    _, before = _make_v1_document(workspace_id, source_id)

    summary = run_pipeline.run_rehash(
        workspace_id, limit=None, dry_run=True, force=False, report_path=report_path
    )

    after = repository.get_version(UUID(str(before["id"])))
    assert summary["rehashed"] == 1  # 판정은 했다
    assert after["content_hash"] == OLD_HASH  # 쓰지는 않았다
    assert after["parser_version"] == "html-v1.0"
    assert report_path.exists()  # 리포트는 남는다


def test_parser_version이_커서라_두_번_돌려도_한_번만_처리한다(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed, report_path: Path
) -> None:
    """993건을 배치로 나눠 돌리고 중간에 끊겨도 이어서 처리할 수 있어야 한다."""
    _make_v1_document(workspace_id, source_id)

    first = run_pipeline.run_rehash(
        workspace_id, limit=None, dry_run=False, force=False, report_path=report_path
    )
    second = run_pipeline.run_rehash(
        workspace_id, limit=None, dry_run=False, force=False, report_path=report_path
    )

    assert first["targets"] == 1
    assert second["targets"] == 0


def test_force는_커서를_무시한다(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed, report_path: Path
) -> None:
    """롤백 경로 — 파서를 되돌린 뒤 같은 명령으로 원복한다."""
    _make_v1_document(workspace_id, source_id)
    run_pipeline.run_rehash(
        workspace_id, limit=None, dry_run=False, force=False, report_path=report_path
    )

    forced = run_pipeline.run_rehash(
        workspace_id, limit=None, dry_run=False, force=True, report_path=report_path
    )

    assert forced["targets"] == 1


def test_해시가_같으면_parser_version만_갱신한다(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed, report_path: Path
) -> None:
    """상용구가 없던 문서. Storage 업로드까지 갈 이유가 없다."""
    document_id = collect(
        CollectRequest(workspace_id=workspace_id, source_id=source_id)
    )[0].document_id
    processed = preprocess(document_id)
    version_id = UUID(str(processed.document_version_id))
    # 해시는 그대로 두고 parser_version만 구 버전으로 되돌린다.
    repository.update_document_version_content(
        version_id,
        content_hash=processed.content_hash,
        parser_version="html-v1.0",
        language="ko",
    )

    summary = run_pipeline.run_rehash(
        workspace_id, limit=None, dry_run=False, force=False, report_path=report_path
    )

    assert summary["parser_version_only"] == 1
    assert summary["rehashed"] == 0
    assert repository.get_version(version_id)["parser_version"] == PARSER_VERSIONS["html"]


def test_raw를_못_받으면_행을_건드리지_않고_게이트4가_FAIL이다(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed, report_path: Path
) -> None:
    """
    raw가 없으면 '이전 파서로 되돌릴 수 있다'는 근거가 성립하지 않는다.
    데이터는 안전하지만(행을 안 건드림) 게이트는 통과시키지 않는다.
    """
    _, before = _make_v1_document(workspace_id, source_id)
    bucket, path = storage.split_key(before["raw_object_key"])
    del supabase.objects[f"{bucket}/{path}"]

    summary = run_pipeline.run_rehash(
        workspace_id, limit=None, dry_run=False, force=False, report_path=report_path
    )

    after = repository.get_version(UUID(str(before["id"])))
    assert summary["skipped"] == 1
    assert after["content_hash"] == OLD_HASH  # 그대로다
    assert summary["gates"]["gate4_rollback"]["verdict"] == "FAIL"


def test_리포트에_원복_정보가_전건_남는다(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed, report_path: Path
) -> None:
    """롤백은 이 리포트의 old_content_hash와 대조해 검증한다 (게이트 4)."""
    import json

    _make_v1_document(workspace_id, source_id)

    run_pipeline.run_rehash(
        workspace_id, limit=None, dry_run=False, force=False, report_path=report_path
    )

    records = [json.loads(line) for line in report_path.read_text().splitlines()]
    assert len(records) == 1
    record = records[0]
    assert record["old_content_hash"] == OLD_HASH
    assert record["old_parser_version"] == "html-v1.0"
    assert record["raw_object_key"]
    assert record["markdown_object_key"]
    assert record["action"] == "rehash"


def test_limit으로_배치를_나눈다(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed, report_path: Path
) -> None:
    for index in range(3):
        feed.set_article(url=f"https://example.com/news/{index}")
        _make_v1_document(workspace_id, source_id)

    summary = run_pipeline.run_rehash(
        workspace_id, limit=2, dry_run=False, force=False, report_path=report_path
    )

    assert summary["targets"] == 2

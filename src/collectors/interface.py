"""
정보 수집·통합 (명세 §3-1, §3-2).

담당 테이블: sources, documents, pipeline_jobs(job_type='collect')

이 파트는 document_versions를 만들지 않는다. 정제(preprocessing)가 만든다.
실패는 예외로 던지지 않고 pipeline_jobs에 남긴다 (명세 §1-3).

스켈레톤의 collect(source_id: str) / 5필드 CollectedDocument는 명세 §3-2의
collect(CollectRequest) / 11필드 모델로 대체됐다. documents.workspace_id가
NOT NULL이라 workspace_id가 필요하고, since·limit로 배치를 분할한다
(명세 §2-2 "스켈레톤 대비 변경점").
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from ..pipeline_common import db, jobs, repository, storage
from ..pipeline_common.constants import JOB_TYPE_COLLECT, SOURCE_TYPES, TARGET_TYPE_DOCUMENT
from ..pipeline_common.models import CollectedDocument, CollectRequest, RawFetchResult
from ..pipeline_common.refs import get_document_refs, get_markdown
from ..pipeline_common.versioning import next_document_version_no
from . import fetchers
from .fetchers import FetchError

__all__ = [
    "register_source",
    "collect",
    "CollectRequest",
    "CollectedDocument",
    "get_markdown",
    "get_document_refs",
]


def register_source(
    workspace_id: UUID,
    name: str,
    source_type: str,
    base_url: str | None = None,
    config: dict | None = None,
) -> UUID:
    """
    sources에 출처를 등록하고 id를 반환. 이미 있으면 기존 id를 그대로 반환한다.

    upsert를 쓰지 않는다. (workspace_id, name)으로 먼저 SELECT해서 있으면 그 id를
    반환하고, 없을 때만 INSERT한다. upsert는 기존 config·base_url을 덮어써
    운영 중 설정이 날아갈 수 있다 (명세 §3-1).
    """
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"source_type이 CHECK 허용값이 아니다: {source_type!r} (허용: {SOURCE_TYPES})")

    existing = repository.find_source_by_name(workspace_id, name)
    if existing is not None:
        return UUID(str(existing["id"]))

    try:
        created = repository.insert_source(workspace_id, name, source_type, base_url, config)
        return UUID(str(created["id"]))
    except Exception as exc:  # noqa: BLE001
        if not db.is_unique_violation(exc):
            raise
        # 동시 INSERT로 uq_sources_workspace_name 위반 -> 1회 재조회 후 기존 id 반환
        raced = repository.find_source_by_name(workspace_id, name)
        if raced is None:
            raise
        return UUID(str(raced["id"]))


def collect(request: CollectRequest) -> list[CollectedDocument]:
    """
    소스에서 새 문서를 수집해 documents 행 생성 + raw 파일을 업로드한다.

    job은 2계층이다 (명세 §3-2).
        소스 단위: target_type=NULL   - 소스 접근 실패, 전체 진행률
        문서 단위: target_type='document' - 문서별 성공/실패, result.raw_object_key

    예외를 던지지 않는다. 반환 리스트에는 성공 건만 담긴다.
    """
    workspace_id = request.workspace_id
    source_job = jobs.start_job(
        workspace_id,
        JOB_TYPE_COLLECT,
        # ck_pj_target_type에 'source'가 없다. NULL을 쓰고 payload에 소스를 남긴다.
        idempotency_key=jobs.source_collect_key(request.source_id),
        payload={
            "source_id": str(request.source_id),
            "since": request.since.isoformat() if request.since else None,
            "limit": request.limit,
        },
        requested_by=request.requested_by,
    )

    source = repository.get_source(request.source_id, workspace_id)
    if source is None:
        # 소스가 없거나 sources.workspace_id != request.workspace_id
        jobs.cancel_job(source_job["id"], "소스가 없거나 workspace가 일치하지 않는다")
        return []
    if not source.get("enabled", True):
        jobs.cancel_job(source_job["id"], "sources.enabled = false")
        return []

    try:
        outcome = fetchers.get_fetcher(source["source_type"])(source, request)
    except FetchError as exc:
        jobs.fail_job(source_job["id"], f"소스 접근 실패: {exc}")
        return []
    except Exception as exc:  # noqa: BLE001 - 수집기 내부 예외도 job에 남긴다
        jobs.fail_job(source_job["id"], f"소스 수집 중 예외: {exc}")
        return []

    collected: list[CollectedDocument] = []
    skip_reasons: dict[str, int] = dict(outcome.skip_reasons)
    failed = 0
    total = len(outcome.items)

    for index, item in enumerate(outcome.items, start=1):
        url = (item.url or "").strip()
        if not url:
            # canonical_url이 NULL이면 uq_documents_workspace_url이 적용되지 않아
            # 같은 문서가 무한 중복된다. 문서를 만들지 않고 사유만 남긴다 (명세 §4-2).
            skip_reasons["no_canonical_url"] = skip_reasons.get("no_canonical_url", 0) + 1
            continue

        try:
            document, is_new_document = _resolve_document(workspace_id, source, item, url)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            skip_reasons["document_error"] = skip_reasons.get("document_error", 0) + 1
            jobs.update_progress(source_job["id"], int(index * 100 / total))
            _ = exc
            continue

        document_id = UUID(str(document["id"]))
        document_job = jobs.start_job(
            workspace_id,
            JOB_TYPE_COLLECT,
            target_type=TARGET_TYPE_DOCUMENT,
            target_id=document_id,
            idempotency_key=jobs.document_collect_key(document_id),
            payload={"source_id": str(request.source_id), "url": url},
            requested_by=request.requested_by,
        )

        try:
            raw_object_key = _upload_raw(workspace_id, document_id, item)
        except Exception as exc:  # noqa: BLE001 - 문서 1건 실패. 배치는 계속 진행한다
            jobs.fail_job(document_job["id"], f"raw 업로드 실패: {exc}")
            failed += 1
            jobs.update_progress(source_job["id"], int(index * 100 / total))
            continue

        jobs.complete_job(
            document_job["id"],
            {
                "raw_object_key": raw_object_key,
                "content_type": item.content_type,
                "bytes": len(item.body),
            },
        )
        collected.append(
            CollectedDocument(
                workspace_id=workspace_id,
                document_id=document_id,
                source_id=document.get("source_id"),
                title=document["title"],
                canonical_url=document.get("canonical_url"),
                published_at=document.get("published_at"),
                status=document["status"],
                raw_object_key=raw_object_key,
                content_type=item.content_type,
                collect_job_id=UUID(str(document_job["id"])),
                is_new_document=is_new_document,
            )
        )
        jobs.update_progress(source_job["id"], int(index * 100 / total))

    jobs.complete_job(
        source_job["id"],
        {
            "collected": len(collected),
            "skipped": sum(skip_reasons.values()),
            "failed": failed,
            "skip_reasons": skip_reasons,
        },
    )
    return collected


# ------------------------------------------------------------
# 내부
# ------------------------------------------------------------


def _resolve_document(
    workspace_id: UUID, source: dict, item: RawFetchResult, url: str
) -> tuple[dict, bool]:
    """
    (workspace_id, canonical_url)로 먼저 SELECT한다. upsert를 쓰지 않는다 (명세 §4-2).

    - 없으면 INSERT, status='active', is_new_document=True
    - 있으면 기존 행 반환. title·published_at이 다를 때만 UPDATE한다
      (같은데 UPDATE하면 updated_at만 의미 없이 갱신된다)
    """
    title = _resolve_title(item, url)
    published_at = item.published_at_hint

    existing = repository.find_document_by_url(workspace_id, url)
    if existing is not None:
        patched = _sync_meta(existing, workspace_id, title, published_at)
        return patched, False

    try:
        created = repository.insert_document(
            workspace_id=workspace_id,
            source_id=UUID(str(source["id"])),
            title=title,
            canonical_url=url,
            published_at=published_at,
        )
        return created, True
    except Exception as exc:  # noqa: BLE001
        if not db.is_unique_violation(exc):
            raise
        # 동시 수집으로 uq_documents_workspace_url 위반 -> 1회 재조회
        raced = repository.find_document_by_url(workspace_id, url)
        if raced is None:
            raise
        return raced, False


def _sync_meta(
    document: dict, workspace_id: UUID, title: str, published_at: datetime | None
) -> dict:
    """원문 제목·발행일이 정정된 경우에만 UPDATE한다."""
    title_changed = bool(title) and title != document.get("title")
    published_changed = published_at is not None and not _same_moment(
        published_at, document.get("published_at")
    )
    if not (title_changed or published_changed):
        return document

    updated = repository.update_document_meta(
        UUID(str(document["id"])),
        workspace_id,
        title if title_changed else document["title"],
        published_at if published_changed else None,
    )
    return updated or document


def _same_moment(left: datetime, right: Any) -> bool:
    if right is None:
        return False
    if not isinstance(right, datetime):
        from ..preprocessing.parsers import parse_datetime

        right = parse_datetime(str(right))
        if right is None:
            return False
    return left == right


def _resolve_title(item: RawFetchResult, url: str) -> str:
    """documents.title은 NOT NULL이다. 힌트가 없으면 URL로라도 채운다."""
    title = (item.title_hint or "").strip()
    return (title or url)[:500]  # documents.title VARCHAR(500)


def _upload_raw(workspace_id: UUID, document_id: UUID, item: RawFetchResult) -> str:
    """
    raw/{workspace_id}/{document_id}/{version_no}.{ext}에 원문을 올린다.

    version_no는 아직 document_versions 행이 없으므로 next_document_version_no()로
    산출한다. 정제 시점에 실제로 부여되는 값과 다를 수 있어서, document_versions에는
    여기서 만든 경로를 collect job의 result를 통해 그대로 인계한다 (명세 §6-2).
    """
    version_no = next_document_version_no(document_id)
    object_key = storage.raw_object_key(workspace_id, document_id, version_no, item.content_type)
    storage.upload(object_key, item.body, item.content_type)
    return object_key

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

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from ..pipeline_common import db, jobs, repository, storage
from ..pipeline_common.constants import JOB_TYPE_COLLECT, SOURCE_TYPES, TARGET_TYPE_DOCUMENT
from ..pipeline_common.models import CollectedDocument, CollectRequest, RawFetchResult
from ..pipeline_common.refs import get_document_refs, get_markdown
from ..pipeline_common.timeutil import parse_datetime
from ..pipeline_common.urls import normalize_url
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


REFETCH_INTERVAL_HOURS = 6
"""
같은 기사를 다시 받아오기까지 두는 최소 간격.

왜 필요한가: 수집이 스케줄러 실행시간의 82%다(2026-08-07 실측, 27.7분 중 22.8분).
30분 주기로 매번 피드 전량 225건을 다시 받는데, 그중 실제로 본문이 바뀌는 건
극소수다 — 재수집 28건을 재정제해 보니 24건이 내용 동일, 3건은 조회수·댓글 수
카운터였고 실제 본문 변경은 1건(3.6%)이었다.

조건부 요청(If-Modified-Since/ETag)을 먼저 시도했는데 이 코퍼스에서는 쓸 수 없다.
도메인 18종에 걸어 보니 전부 200으로 응답했고(304 0건), ETag는 1곳, Last-Modified는
2곳만 준다. 언론사 페이지가 대부분 동적 렌더링이라 조건부 GET을 지원하지 않는다.
서버에 묻는 방식이 안 되니 우리가 안 받는 쪽으로 간다.

6시간인 이유: 정정은 보통 발행 직후에 일어나고, 그보다 늦은 정정을 30분 안에 잡으려고
같은 기사를 하루 48번 받는 것은 비용이 맞지 않는다. 이 값이면 하루 4번 확인한다.

⚠ 이건 제품 동작을 바꾸는 값이다. 정정 반영이 최대 6시간 늦어진다.
줄이면 반영은 빨라지지만 수집 시간이 그만큼 늘어난다.
"""


def _build_refetch_policy(workspace_id: UUID):
    """
    url -> 받아올지 여부. 최근 REFETCH_INTERVAL_HOURS 안에 수집한 문서면 False.

    판정 기준은 문서 단위 collect job의 완료 시각이다. documents.updated_at은
    제목 교정 등으로도 갱신돼서 '마지막으로 원문을 받아온 시각'을 뜻하지 않는다.

    문서 목록과 job을 미리 한 번씩만 받아 캐시한다 — 항목마다 조회하면 N+1이고,
    아끼려는 시간을 DB 왕복으로 도로 쓴다.
    """
    documents = repository.list_active_documents(workspace_id)
    document_ids = [UUID(str(doc["id"])) for doc in documents]
    collect_jobs = repository.latest_completed_collect_jobs_by_document(
        workspace_id, document_ids
    )

    cutoff = datetime.now(timezone.utc) - timedelta(hours=REFETCH_INTERVAL_HOURS)
    fetched_at_by_url: dict[str, datetime] = {}
    for doc in documents:
        url = (doc.get("canonical_url") or "").strip()
        if not url:
            continue
        job = collect_jobs.get(str(doc["id"]))
        finished = parse_datetime(
            str((job or {}).get("completed_at") or (job or {}).get("created_at") or "")
        )
        if finished is not None:
            fetched_at_by_url[url] = finished

    def should_fetch(url: str) -> bool:
        # 수집기가 주는 주소와 documents.canonical_url은 같은 정규화를 거쳐야 맞는다.
        # cutoff와 정확히 같은 시각도 대상에 포함한다(<=) — REFETCH_INTERVAL_HOURS=0이면
        # cutoff가 "지금"이 되는데, datetime.now() 해상도가 낮은 환경(예: Windows)에서는
        # 수집 시각과 이 시각이 같은 tick에 찍혀 완전히 동일한 값이 될 수 있다. 엄격한
        # "<"만 쓰면 그런 경우 "0시간 지나면 즉시 재수집 대상"이라는 의도가 깨진다.
        fetched_at = fetched_at_by_url.get((normalize_url(url) or "").strip())
        return fetched_at is None or fetched_at <= cutoff

    return should_fetch


def collect(request: CollectRequest) -> list[CollectedDocument]:
    """
    소스에서 새 문서를 수집해 documents 행 생성 + raw 파일을 업로드한다.
    이미 canonical_url이 존재하면 문서를 새로 만들지 않는다.

    raw_object_key 경로 구성 순서 (스켈레톤 주석 그대로):
      1) documents 행을 INSERT 또는 조회해 document_id 확보
      2) next_document_version_no(document_id) 로 next_ver 계산
         (명세 §3-5에 따라 pipeline_common.versioning으로 옮겼다.
          preprocessing.interface에서도 그대로 re-export한다)
      3) raw/{workspace_id}/{document_id}/{next_ver}.{ext} 에 파일 업로드
      4) CollectedDocument.raw_object_key 에 해당 경로 저장

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

    # 최근에 이미 받아온 주소는 다시 받지 않는다 (_build_refetch_policy 참조).
    # 소스 단위로 걸고, 어떤 경로로 끝나든 반드시 푼다 — 모듈 전역이라 남으면
    # 다음 호출까지 새어 나간다.
    fetchers.set_refetch_policy(_build_refetch_policy(workspace_id))
    try:
        outcome = fetchers.get_fetcher(source["source_type"])(source, request)
    except FetchError as exc:
        jobs.fail_job(source_job["id"], f"소스 접근 실패: {exc}")
        return []
    except Exception as exc:  # noqa: BLE001 - 수집기 내부 예외도 job에 남긴다
        jobs.fail_job(source_job["id"], f"소스 수집 중 예외: {exc}")
        return []
    finally:
        fetchers.reset_refetch_policy()

    collected: list[CollectedDocument] = []
    # skip_reasons는 "문서를 만들지 않고 건너뛴" 사유만 센다. 실패는 failure_reasons로
    # 따로 세야 result.skipped와 result.failed가 같은 건을 이중으로 세지 않는다.
    skip_reasons: dict[str, int] = dict(outcome.skip_reasons)
    failure_reasons: dict[str, int] = {}
    failed = 0
    total = len(outcome.items)

    for index, item in enumerate(outcome.items, start=1):
        # canonical_url은 uq_documents_workspace_url이 걸린 문서 식별자다. 표기만
        # 다른 주소가 별개 문서가 되지 않게 여기 한 곳에서 통일한다 — 아래 조회·INSERT가
        # 모두 이 url을 쓰므로 수집기별로 흩어놓지 않는다.
        url = (normalize_url(item.url) or "").strip()
        if not url:
            # canonical_url이 NULL이면 uq_documents_workspace_url이 적용되지 않아
            # 같은 문서가 무한 중복된다. 문서를 만들지 않고 사유만 남긴다 (명세 §4-2).
            skip_reasons["no_canonical_url"] = skip_reasons.get("no_canonical_url", 0) + 1
            continue

        try:
            document, is_new_document = _resolve_document(workspace_id, source, item, url)
        except Exception as exc:  # noqa: BLE001 - 문서 1건 실패. 배치는 계속 진행한다
            # 아직 document_id가 없어 문서 단위 job을 만들 수 없다.
            # 사유를 소스 job의 result에 남겨야 원인이 사라지지 않는다.
            failed += 1
            reason = f"document_error:{type(exc).__name__}"
            failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
            jobs.update_progress(source_job["id"], int(index * 100 / total))
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
            failure_reasons["raw_upload_failed"] = (
                failure_reasons.get("raw_upload_failed", 0) + 1
            )
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
            "failure_reasons": failure_reasons,
            # 소스가 알려준 제약 안내 (예: 요금제 때문에 결과가 잘림).
            # 수집 0건인데 실패도 없는 상황의 원인이 여기 남는다.
            "notices": list(outcome.notices),
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

"""
pipeline_jobs 기록 (명세 §4-4, §5-2).

실패는 예외로 던지지 않고 여기에 남긴다 (명세 §1-3).

job 2계층 구조 (명세 §3-2)
    소스 단위 collect : target_type=NULL, target_id=NULL, payload.source_id에 소스 기록
    문서 단위 collect : target_type='document', target_id=documents.id
    parse_document    : target_type='document', target_id=documents.id

ck_pj_target_type에 'source'가 없다. 소스 단위 job에 'source'를 넣으면
INSERT가 거부되므로 NULL을 쓴다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from . import db, repository
from .constants import (
    JOB_TYPE_COLLECT,
    JOB_TYPE_PARSE_DOCUMENT,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_RUNNING,
    TARGET_TYPE_DOCUMENT,
)

KST = timezone(timedelta(hours=9))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def kst_date(now: datetime | None = None) -> str:
    """idempotency_key에 쓰는 YYYY-MM-DD. 배치가 08:00 KST에 도는 것과 맞춘다."""
    moment = now or datetime.now(timezone.utc)
    return moment.astimezone(KST).strftime("%Y-%m-%d")


def source_collect_key(source_id: UUID, now: datetime | None = None) -> str:
    return f"{JOB_TYPE_COLLECT}:source:{source_id}:{kst_date(now)}"


def document_collect_key(document_id: UUID, now: datetime | None = None) -> str:
    return f"{JOB_TYPE_COLLECT}:document:{document_id}:{kst_date(now)}"


def parse_document_key(document_id: UUID, now: datetime | None = None) -> str:
    return f"{JOB_TYPE_PARSE_DOCUMENT}:{document_id}:{kst_date(now)}"


def _update(job_id: str, patch: dict[str, Any]) -> dict | None:
    res = db.get_client().table("pipeline_jobs").update(patch).eq("id", job_id).execute()
    rows = list(res.data or [])
    return rows[0] if rows else None


def start_job(
    workspace_id: UUID,
    job_type: str,
    *,
    target_type: str | None = None,
    target_id: UUID | None = None,
    idempotency_key: str | None = None,
    payload: dict | None = None,
    requested_by: UUID | None = None,
) -> dict:
    """
    job을 running 상태로 만든다.

    idempotency_key는 전역 UNIQUE라 같은 날 재실행하면 INSERT가 실패한다.
    그때는 새 job을 만들지 않고 기존 job을 running으로 되돌린 뒤 재사용한다 (명세 §4-4).

    [명세 해석] §4-4는 재사용 시 retry_count+1을, §3-3은 실패 시 retry_count+1을
    요구한다. 둘 다 그대로 적용하면 "실패 -> 재실행"마다 2씩 올라, §3-3의
    `retry_count >= MAX_RETRY`가 실패 횟수를 세지 못한다. 그래서 증가는 실패
    시점(fail_job) 한 곳으로 모으고, 여기서는 결과를 남기지 못한 채 끊긴
    실행(status='running')을 재개할 때만 올린다. 그 경우 실패가 기록된 적이
    없어 아무도 세지 않았기 때문이다.

    idempotency_key=None이면 UNIQUE 대상이 아니므로 몇 번이든 만들 수 있다.
    수동 강제 재실행 경로다.
    """
    row: dict[str, Any] = {
        "workspace_id": str(workspace_id),
        "job_type": job_type,
        "status": STATUS_RUNNING,
        "progress": 0,
        "payload": payload or {},
        "started_at": _now_iso(),
    }
    if target_type is not None:
        row["target_type"] = target_type
    if target_id is not None:
        row["target_id"] = str(target_id)
    if idempotency_key is not None:
        row["idempotency_key"] = idempotency_key
    if requested_by is not None:
        row["requested_by"] = str(requested_by)

    try:
        res = db.get_client().table("pipeline_jobs").insert(row).execute()
        return list(res.data)[0]
    except Exception as exc:  # noqa: BLE001 - 재사용 경로 판별 후 나머지는 그대로 올린다
        if not (idempotency_key and db.is_unique_violation(exc)):
            raise
    existing = repository.find_job_by_idempotency_key(idempotency_key)
    if existing is None:  # 경합 상대가 롤백된 드문 경우
        raise RuntimeError(f"idempotency_key 충돌인데 기존 job을 못 찾았다: {idempotency_key}")
    retry_count = int(existing.get("retry_count") or 0)
    if existing.get("status") == STATUS_RUNNING:
        retry_count += 1  # 결과 없이 끊긴 실행. fail_job이 세지 못한 몫이다
    reused = _update(
        existing["id"],
        {
            "status": STATUS_RUNNING,
            "retry_count": retry_count,
            "started_at": _now_iso(),
            "error_message": None,
            "payload": payload or existing.get("payload") or {},
        },
    )
    return reused or existing


def update_progress(job_id: str, progress: int) -> dict | None:
    """소스 단위 job의 진행률. 처리한 문서 수 / 전체 문서 수 비율 (명세 §5-2)."""
    bounded = max(0, min(100, int(progress)))
    return _update(job_id, {"progress": bounded})


def complete_job(job_id: str, result: dict | None = None, progress: int = 100) -> dict | None:
    return _update(
        job_id,
        {
            "status": STATUS_COMPLETED,
            "progress": max(0, min(100, int(progress))),
            "result": result or {},
            "completed_at": _now_iso(),
        },
    )


def fail_job(job_id: str, error_message: str, result: dict | None = None) -> dict | None:
    """
    job을 failed로 남기고 retry_count를 1 올린다.
    progress는 마지막 값을 유지한다 (명세 §5-2).

    반환된 행의 retry_count로 호출자가 MAX_RETRY 초과 여부를 판단한다.
    """
    current = _get(job_id)
    patch: dict[str, Any] = {
        "status": STATUS_FAILED,
        "error_message": error_message,
        "retry_count": int((current or {}).get("retry_count") or 0) + 1,
    }
    if result is not None:
        patch["result"] = result
    return _update(job_id, patch)


def cancel_job(job_id: str, error_message: str | None = None) -> dict | None:
    """상위 배치 중단·소스 비활성 시 (명세 §5-2)."""
    patch: dict[str, Any] = {"status": STATUS_CANCELLED}
    if error_message is not None:
        patch["error_message"] = error_message
    return _update(job_id, patch)


def _get(job_id: str) -> dict | None:
    res = db.get_client().table("pipeline_jobs").select("*").eq("id", job_id).limit(1).execute()
    rows = list(res.data or [])
    return rows[0] if rows else None


__all__ = [
    "KST",
    "kst_date",
    "source_collect_key",
    "document_collect_key",
    "parse_document_key",
    "start_job",
    "update_progress",
    "complete_job",
    "fail_job",
    "cancel_job",
    "TARGET_TYPE_DOCUMENT",
]

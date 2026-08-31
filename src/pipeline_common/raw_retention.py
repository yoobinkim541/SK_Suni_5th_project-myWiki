"""raw Storage 객체의 보존기간을 관리한다.

raw는 정제 직후에는 필요하지만, processed Markdown이 생성된 뒤에는 재처리
대기시간을 제외하면 애플리케이션 조회에 사용되지 않는다. 이 모듈은 Storage
API로만 오래된 객체를 삭제해 ``storage.objects`` 메타데이터와 실제 파일이
엇갈리지 않게 한다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from . import db
from .constants import BUCKET_RAW

DEFAULT_RETENTION_DAYS = 3
DEFAULT_BATCH_SIZE = 1000  # Supabase Storage remove API의 최대 요청 수
DEFAULT_MAX_BYTES = 850_000_000  # 1GB 한도 아래의 운영 여유 공간


@dataclass(frozen=True)
class RawCleanupSummary:
    cutoff: datetime
    scanned: int
    candidates: int
    deleted: int
    deleted_bytes: int


def configured_retention_days() -> int:
    raw = os.environ.get("RAW_RETENTION_DAYS", str(DEFAULT_RETENTION_DAYS))
    try:
        days = int(raw)
    except ValueError as exc:
        raise ValueError("RAW_RETENTION_DAYS는 정수여야 한다") from exc
    if days < 1:
        raise ValueError("RAW_RETENTION_DAYS는 1 이상이어야 한다")
    return days


def configured_max_bytes() -> int:
    raw = os.environ.get("RAW_MAX_BYTES", str(DEFAULT_MAX_BYTES))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("RAW_MAX_BYTES는 정수여야 한다") from exc
    if not 1 <= value <= 900_000_000:
        raise ValueError("RAW_MAX_BYTES는 1..900000000 범위여야 한다")
    return value


def _objects_table(client: Any) -> Any:
    schema = getattr(client, "schema", None)
    if callable(schema):
        return schema("storage").table("objects")
    # 테스트 더블이나 구버전 클라이언트 호환 경로
    return client.table("storage.objects")


def _join_storage_path(prefix: str, name: str) -> str:
    return f"{prefix.rstrip('/')}/{name}" if prefix else name


def _list_bucket_objects(bucket: Any, batch_size: int) -> list[dict[str, Any]]:
    """Storage API로 raw 객체를 재귀 조회한다.

    ``storage.objects``는 일반 PostgREST 노출 스키마가 아니므로, 운영 환경은
    Storage API의 list 엔드포인트를 사용한다. 일부 테스트 더블/구버전 클라이언트에
    list가 없을 때만 호출부에서 SQL fallback을 사용한다.
    """
    objects: list[dict[str, Any]] = []
    pending_prefixes = [""]
    while pending_prefixes:
        prefix = pending_prefixes.pop()
        offset = 0
        while True:
            page = bucket.list(
                prefix,
                {
                    "limit": batch_size,
                    "offset": offset,
                    "sortBy": {"column": "created_at", "order": "asc"},
                },
            )
            page = list(page or [])
            for item in page:
                row = dict(item) if isinstance(item, dict) else vars(item)
                name = str(row.get("name") or "").strip()
                if not name:
                    continue
                # Storage list 응답에서 폴더는 id/metadata가 null이다.
                if row.get("id") is None and row.get("metadata") is None:
                    pending_prefixes.append(_join_storage_path(prefix, name))
                    continue
                objects.append(
                    {
                        "name": _join_storage_path(prefix, name),
                        "metadata": row.get("metadata"),
                        "created_at": row.get("created_at"),
                    }
                )
            if len(page) < batch_size:
                break
            offset += batch_size
    return objects


def _row_size(row: dict[str, Any]) -> int:
    metadata = row.get("metadata")
    if isinstance(metadata, dict):
        value = metadata.get("size")
        try:
            return max(0, int(value)) if value is not None else 0
        except (TypeError, ValueError):
            return 0
    return 0


def cleanup_raw_objects(
    *,
    retention_days: int | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_bytes: int | None = None,
) -> RawCleanupSummary:
    """보존기간보다 오래된 raw 객체를 Storage API로 삭제한다.

    삭제 전에 페이지 단위로 전체 목록을 읽고, 삭제는 목록을 고정한 뒤
    배치로 수행한다. 삭제 중 offset을 증가시키면 일부 객체를 건너뛸 수
    있기 때문이다.
    """
    days = configured_retention_days() if retention_days is None else int(retention_days)
    if days < 1:
        raise ValueError("retention_days는 1 이상이어야 한다")
    if not 1 <= batch_size <= DEFAULT_BATCH_SIZE:
        raise ValueError(f"batch_size는 1..{DEFAULT_BATCH_SIZE} 범위여야 한다")

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    cutoff = current - timedelta(days=days)
    configured_limit = configured_max_bytes() if max_bytes is None else int(max_bytes)
    if not 1 <= configured_limit <= 900_000_000:
        raise ValueError("max_bytes는 1..900000000 범위여야 한다")

    client = db.get_client()
    bucket = client.storage.from_(BUCKET_RAW)
    list_method = getattr(bucket, "list", None)
    if callable(list_method):
        rows = _list_bucket_objects(bucket, batch_size)
    else:
        # 테스트 더블이나 구버전 클라이언트 호환 경로
        rows = []
        offset = 0
        while True:
            query = (
                _objects_table(client)
                .select("name,metadata,created_at")
                .eq("bucket_id", BUCKET_RAW)
                .order("created_at", desc=False)
                .range(offset, offset + batch_size - 1)
                .execute()
            )
            page = list(getattr(query, "data", None) or [])
            rows.extend(page)
            if len(page) < batch_size:
                break
            offset += batch_size

    scanned = len(rows)
    total_bytes = sum(_row_size(row) for row in rows)
    selected: list[dict[str, Any]] = []
    selected_names: set[str] = set()
    remaining_bytes = total_bytes

    # 1차: 보존기간이 지난 모든 raw 삭제
    for row in rows:
        created_at = str(row.get("created_at") or "")
        name = str(row.get("name") or "").strip()
        if name and created_at and created_at < cutoff.isoformat():
            selected.append(row)
            selected_names.add(name)
            remaining_bytes -= _row_size(row)

    # 2차: 보존기간 내 객체까지 포함해 운영 상한(850MB)을 넘지 않게 한다.
    # 이 단계는 정제 직후 실행되는 것을 전제로 하며, 재처리 대기보다 용량
    # 상한을 우선한다. 실제 하류는 processed/wiki를 사용한다.
    if remaining_bytes > configured_limit:
        for row in rows:
            name = str(row.get("name") or "").strip()
            if not name or name in selected_names:
                continue
            selected.append(row)
            selected_names.add(name)
            remaining_bytes -= _row_size(row)
            if remaining_bytes <= configured_limit:
                break

    candidates = len(selected)
    deleted = deleted_bytes = 0
    if not dry_run:
        for start in range(0, len(selected), batch_size):
            batch = selected[start : start + batch_size]
            names = [str(row.get("name") or "").strip() for row in batch]
            names = [name for name in names if name]
            if not names:
                continue
            # Storage API는 실패 시 예외를 던지므로 일부만 지워졌다고 가정하지
            # 않는다. 호출이 성공한 경우에만 해당 배치를 삭제 완료로 센다.
            result = bucket.remove(names)
            result_data = getattr(result, "data", result)
            deleted += len(result_data) if isinstance(result_data, list) else len(names)
            deleted_bytes += sum(_row_size(row) for row in batch)

    return RawCleanupSummary(
        cutoff=cutoff,
        scanned=scanned,
        candidates=candidates,
        deleted=deleted,
        deleted_bytes=deleted_bytes,
    )


__all__ = [
    "RawCleanupSummary",
    "cleanup_raw_objects",
    "configured_max_bytes",
    "configured_retention_days",
]


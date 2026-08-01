"""
sources / documents / document_versions / pipeline_jobs 접근을 한곳에 모은 계층.

- 미확정 항목이 확정될 때 이 파일만 고치면 되게 한다 (프로젝트 지침 §7).
- document_versions에는 workspace_id 컬럼이 없다. 조회할 때는 반드시
  documents를 거쳐 workspace_id를 건다 (명세 §4-3).
- 조인은 PostgREST embed 문법 대신 2단계 조회로 처리한다. 배치가 RLS를
  우회하므로 workspace 필터를 애플리케이션 코드에서 눈으로 확인할 수 있어야 한다.

id/created_at/updated_at은 DB DEFAULT가 채우므로 INSERT에 넣지 않는다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from . import db
from .constants import (
    DOC_STATUS_ACTIVE,
    JOB_TYPE_COLLECT,
    STATUS_COMPLETED,
    TARGET_TYPE_DOCUMENT,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rows(res: Any) -> list[dict]:
    return list(res.data or [])


def _first(res: Any) -> dict | None:
    rows = _rows(res)
    return rows[0] if rows else None


# ------------------------------------------------------------
# sources
# ------------------------------------------------------------


def find_source_by_name(workspace_id: UUID, name: str) -> dict | None:
    res = (
        db.get_client()
        .table("sources")
        .select("*")
        .eq("workspace_id", str(workspace_id))
        .eq("name", name)
        .limit(1)
        .execute()
    )
    return _first(res)


def get_source(source_id: UUID, workspace_id: UUID) -> dict | None:
    """workspace가 다르면 None. collect()의 사전조건 검사에 쓴다 (명세 §3-2)."""
    res = (
        db.get_client()
        .table("sources")
        .select("*")
        .eq("id", str(source_id))
        .eq("workspace_id", str(workspace_id))
        .limit(1)
        .execute()
    )
    return _first(res)


def insert_source(
    workspace_id: UUID,
    name: str,
    source_type: str,
    base_url: str | None,
    config: dict | None,
) -> dict:
    row: dict[str, Any] = {
        "workspace_id": str(workspace_id),
        "name": name,
        "source_type": source_type,
    }
    if base_url is not None:
        row["base_url"] = base_url
    if config is not None:
        # 미지정이면 DB DEFAULT '{}'::jsonb가 적용된다 (명세 §4-1)
        row["config"] = config
    # reliability_score는 초기값·갱신 기준 미정이라 NULL로 둔다.
    # TODO(미확정): 지침 §9-A-6 / 명세 §8 잔류 6번
    res = db.get_client().table("sources").insert(row).execute()
    return _rows(res)[0]


def get_sources_by_ids(source_ids: list[UUID], workspace_id: UUID) -> dict[str, dict]:
    """id -> 행. workspace가 다른 소스는 결과에서 빠진다."""
    if not source_ids:
        return {}
    res = (
        db.get_client()
        .table("sources")
        .select("*")
        .in_("id", [str(sid) for sid in source_ids])
        .eq("workspace_id", str(workspace_id))
        .execute()
    )
    return {row["id"]: row for row in _rows(res)}


# ------------------------------------------------------------
# documents
# ------------------------------------------------------------


def find_document_by_url(workspace_id: UUID, canonical_url: str) -> dict | None:
    res = (
        db.get_client()
        .table("documents")
        .select("*")
        .eq("workspace_id", str(workspace_id))
        .eq("canonical_url", canonical_url)
        .limit(1)
        .execute()
    )
    return _first(res)


def get_document(document_id: UUID) -> dict | None:
    """
    workspace 필터 없이 id로 조회한다.

    preprocess()는 인자로 document_id만 받으므로 (명세 §3-3) 여기서 얻은
    workspace_id를 이후 모든 쿼리의 필터로 쓴다. 즉 이 함수는 workspace를
    '확인'하는 게 아니라 '확보'하는 지점이다.
    """
    res = db.get_client().table("documents").select("*").eq("id", str(document_id)).limit(1).execute()
    return _first(res)


def get_documents_by_ids(document_ids: list[UUID | str], workspace_id: UUID) -> dict[str, dict]:
    """id -> 행. 다른 workspace의 문서는 결과에서 빠진다."""
    if not document_ids:
        return {}
    res = (
        db.get_client()
        .table("documents")
        .select("*")
        .in_("id", [str(did) for did in document_ids])
        .eq("workspace_id", str(workspace_id))
        .execute()
    )
    return {row["id"]: row for row in _rows(res)}


def insert_document(
    workspace_id: UUID,
    source_id: UUID | None,
    title: str,
    canonical_url: str,
    published_at: datetime | None,
) -> dict:
    row: dict[str, Any] = {
        "workspace_id": str(workspace_id),
        "title": title,
        "canonical_url": canonical_url,
        "status": DOC_STATUS_ACTIVE,
        # uploaded_by: 배치는 NULL (명세 §4-2)
    }
    if source_id is not None:
        row["source_id"] = str(source_id)
    if published_at is not None:
        row["published_at"] = published_at.isoformat()
    res = db.get_client().table("documents").insert(row).execute()
    return _rows(res)[0]


def update_document_meta(
    document_id: UUID, workspace_id: UUID, title: str, published_at: datetime | None
) -> dict | None:
    """원문 제목 정정 등을 반영한다. 호출 전에 값이 실제로 달라졌는지 확인할 것 (명세 §4-2)."""
    patch: dict[str, Any] = {"title": title}
    if published_at is not None:
        patch["published_at"] = published_at.isoformat()
    res = (
        db.get_client()
        .table("documents")
        .update(patch)
        .eq("id", str(document_id))
        .eq("workspace_id", str(workspace_id))
        .execute()
    )
    return _first(res)


def set_document_status(document_id: UUID, workspace_id: UUID, status: str) -> dict | None:
    res = (
        db.get_client()
        .table("documents")
        .update({"status": status})
        .eq("id", str(document_id))
        .eq("workspace_id", str(workspace_id))
        .execute()
    )
    return _first(res)


# ------------------------------------------------------------
# document_versions
# ------------------------------------------------------------


def find_version_by_hash(document_id: UUID, content_hash: str) -> dict | None:
    res = (
        db.get_client()
        .table("document_versions")
        .select("*")
        .eq("document_id", str(document_id))
        .eq("content_hash", content_hash)
        .limit(1)
        .execute()
    )
    return _first(res)


def latest_version(document_id: UUID) -> dict | None:
    res = (
        db.get_client()
        .table("document_versions")
        .select("*")
        .eq("document_id", str(document_id))
        .order("version_no", desc=True)
        .limit(1)
        .execute()
    )
    return _first(res)


def insert_document_version(
    document_id: UUID,
    version_no: int,
    content_hash: str,
    markdown_object_key: str,
    raw_object_key: str | None,
    parser_version: str | None,
    language: str | None,
) -> dict:
    row: dict[str, Any] = {
        "document_id": str(document_id),
        "version_no": version_no,
        "content_hash": content_hash,
        "markdown_object_key": markdown_object_key,
    }
    if raw_object_key is not None:
        row["raw_object_key"] = raw_object_key
    if parser_version is not None:
        row["parser_version"] = parser_version
    if language is not None:
        row["language"] = language
    res = db.get_client().table("document_versions").insert(row).execute()
    return _rows(res)[0]


def get_version(document_version_id: UUID) -> dict | None:
    """
    workspace 필터가 없다. 호출자는 반환된 document_id로 documents를 조회해
    workspace_id를 반드시 확인해야 한다 (명세 §4-3).
    """
    res = (
        db.get_client()
        .table("document_versions")
        .select("*")
        .eq("id", str(document_version_id))
        .limit(1)
        .execute()
    )
    return _first(res)


def get_versions_by_ids(document_version_ids: list[UUID]) -> list[dict]:
    """workspace 필터 없음. 호출자가 documents 조회로 걸러야 한다."""
    if not document_version_ids:
        return []
    res = (
        db.get_client()
        .table("document_versions")
        .select("*")
        .in_("id", [str(vid) for vid in document_version_ids])
        .execute()
    )
    return _rows(res)


# ------------------------------------------------------------
# pipeline_jobs (조회)
# ------------------------------------------------------------


def latest_completed_collect_job(workspace_id: UUID, document_id: UUID) -> dict | None:
    """
    preprocess()의 사전조건 (명세 §3-3).

    select result from pipeline_jobs
    where workspace_id = :workspace_id
      and job_type = 'collect' and target_type = 'document'
      and target_id = :document_id and status = 'completed'
    order by created_at desc limit 1;
    """
    res = (
        db.get_client()
        .table("pipeline_jobs")
        .select("*")
        .eq("workspace_id", str(workspace_id))
        .eq("job_type", JOB_TYPE_COLLECT)
        .eq("target_type", TARGET_TYPE_DOCUMENT)
        .eq("target_id", str(document_id))
        .eq("status", STATUS_COMPLETED)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return _first(res)


def find_job_by_idempotency_key(idempotency_key: str) -> dict | None:
    res = (
        db.get_client()
        .table("pipeline_jobs")
        .select("*")
        .eq("idempotency_key", idempotency_key)
        .limit(1)
        .execute()
    )
    return _first(res)

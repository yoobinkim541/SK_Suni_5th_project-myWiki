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
    JOB_TYPE_PARSE_DOCUMENT,
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


def list_enabled_sources(workspace_id: UUID) -> list[dict]:
    """워크스페이스의 enabled=true 출처 전체. 배치 진입점이 소스 목록을 도는 데 쓴다."""
    res = (
        db.get_client()
        .table("sources")
        .select("*")
        .eq("workspace_id", str(workspace_id))
        .eq("enabled", True)
        .execute()
    )
    return _rows(res)


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


def list_active_documents(workspace_id: UUID) -> list[dict]:
    """워크스페이스의 status='active' 문서 전체. 정제 대기 목록 산출의 1단계다."""
    res = (
        db.get_client()
        .table("documents")
        .select("*")
        .eq("workspace_id", str(workspace_id))
        .eq("status", DOC_STATUS_ACTIVE)
        .execute()
    )
    return _rows(res)


# ------------------------------------------------------------
# document_versions
# ------------------------------------------------------------


_IN_CLAUSE_CHUNK_SIZE = 150
"""
.in_() 한 번에 넣을 id 개수 상한.

백로그(active 문서 수)가 커지면 document_ids가 수백~수천 개가 되는데, 이걸
전부 한 URL의 .in_(...)에 담으면 PostgREST가 400 Bad Request로 거부한다
(2026-08-06 확인: run 31103317893 등에서 재현, latest_versions_by_document가
document_ids ~500개로 크래시). id 하나(UUID, 36자)+콤마 기준 150개면 여유 있게
안전권이라 이 값으로 잡았다.
"""


def _chunked(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def latest_versions_by_document(document_ids: list[UUID | str]) -> dict[str, dict]:
    """document_id -> 가장 최근 version_no 행. 버전이 없는 문서는 키가 없다.

    정제 대기 목록을 만들 때 문서마다 latest_version()을 부르면 N+1이 된다.
    한 번에 받아 파이썬에서 문서별 최댓값을 고른다. document_ids가 많으면
    _IN_CLAUSE_CHUNK_SIZE 단위로 나눠 여러 번 조회한다 (여전히 N+1은 아니다 —
    문서 수가 아니라 상수 크기로 나눈 배치 수만큼만 조회).

    workspace 필터가 없다 — document_versions에는 workspace_id 컬럼이 없으므로
    (명세 §4-3) 호출자가 workspace로 걸러낸 document_ids를 넘겨야 한다.
    """
    if not document_ids:
        return {}
    latest: dict[str, dict] = {}
    for chunk in _chunked([str(did) for did in document_ids], _IN_CLAUSE_CHUNK_SIZE):
        res = db.get_client().table("document_versions").select("*").in_("document_id", chunk).execute()
        for row in _rows(res):
            key = str(row["document_id"])
            current = latest.get(key)
            if current is None or int(row["version_no"]) > int(current["version_no"]):
                latest[key] = row
    return latest


def latest_completed_parse_jobs_by_document(
    workspace_id: UUID, document_ids: list[UUID | str]
) -> dict[str, dict]:
    """document_id -> 가장 최근 완료된 parse_document job.

    "언제 마지막으로 정제했는가"를 document_versions.created_at만으로는 알 수 없다.
    내용이 그대로면 preprocess()가 기존 버전을 재사용해 새 행을 만들지 않으므로
    (명세 §3-3) 버전 시각이 갱신되지 않고, 그 문서는 재수집될 때마다 영원히
    재정제 대상으로 남는다. 실제로 정제를 돌린 시각은 이 job에 남는다.
    """
    return _latest_jobs_by_target(workspace_id, JOB_TYPE_PARSE_DOCUMENT, document_ids)


def latest_completed_collect_jobs_by_document(
    workspace_id: UUID, document_ids: list[UUID | str]
) -> dict[str, dict]:
    """document_id -> 가장 최근 완료된 문서 단위 collect job.

    latest_completed_collect_job()의 목록 판이다. 정제 대기 목록을 만들 때
    문서마다 그 함수를 부르면 N+1이 된다.

    최신 판정은 latest_completed_collect_job()과 같게 created_at 기준이다.
    """
    return _latest_jobs_by_target(workspace_id, JOB_TYPE_COLLECT, document_ids)


def _latest_jobs_by_target(
    workspace_id: UUID, job_type: str, document_ids: list[UUID | str]
) -> dict[str, dict]:
    """target_id -> 해당 job_type의 가장 최근 완료 job. document_ids를
    _IN_CLAUSE_CHUNK_SIZE 단위로 나눠 조회한다 (N+1이 아니라 상수 크기 배치 —
    latest_versions_by_document 위 주석 참조)."""
    if not document_ids:
        return {}
    latest: dict[str, dict] = {}
    for chunk in _chunked([str(did) for did in document_ids], _IN_CLAUSE_CHUNK_SIZE):
        res = (
            db.get_client()
            .table("pipeline_jobs")
            .select("*")
            .eq("workspace_id", str(workspace_id))
            .eq("job_type", job_type)
            .eq("target_type", TARGET_TYPE_DOCUMENT)
            .eq("status", STATUS_COMPLETED)
            .in_("target_id", chunk)
            .execute()
        )
        for row in _rows(res):
            key = str(row["target_id"])
            current = latest.get(key)
            if current is None or str(row.get("created_at") or "") > str(
                current.get("created_at") or ""
            ):
                latest[key] = row
    return latest


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


def update_document_version_content(
    document_version_id: UUID,
    *,
    content_hash: str,
    parser_version: str,
    language: str | None,
) -> dict | None:
    """
    파서를 바꿔 같은 원문을 다시 정제했을 때 기존 행을 제자리에서 갱신한다.

    ⚠ 이건 일반 정제 경로가 쓰는 함수가 아니다. preprocess()는 내용이 바뀌면
    새 행을 만든다(insert_document_version). 이 함수는 재해시 마이그레이션
    (scripts/run_pipeline.py --rehash) 전용이다.

    새 행을 만들지 않는 이유: 분석 단계가 "분석 행이 없는 document_versions"를
    잡아가므로, 파서 교체로 993개 행을 새로 만들면 993건이 그대로 LLM 4단계
    대기열에 얹힌다. 제자리 갱신은 id가 그대로라 기존 분석·인용이 전부 유효하다.

    raw는 건드리지 않는다 — markdown은 raw에서 언제든 다시 만들 수 있는 파생물이고,
    그래서 되돌리기가 '이전 파서로 다시 돌리기'로 끝난다 (절대원칙 §3 예외 근거).

    workspace 필터가 없다. document_versions에 workspace_id 컬럼이 없어서
    get_version과 같은 제약이다 — 호출자가 documents를 거쳐 확인해야 한다.
    """
    patch: dict[str, Any] = {
        "content_hash": content_hash,
        "parser_version": parser_version,
    }
    if language is not None:
        patch["language"] = language
    res = (
        db.get_client()
        .table("document_versions")
        .update(patch)
        .eq("id", str(document_version_id))
        .execute()
    )
    return _first(res)


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

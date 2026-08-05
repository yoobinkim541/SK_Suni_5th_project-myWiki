"""
데이터 정제·검증 (명세 §3-3, §3-4).

담당 테이블: document_versions, pipeline_jobs(job_type='parse_document')

실패는 예외로 던지지 않고 pipeline_jobs에 남긴다. 단 하류 조회 헬퍼
get_markdown()·get_document_refs()는 조회 전용이라 예외를 던진다 (명세 §1-3).

스켈레톤의 process_document()/DocumentVersion은 명세 §3-3의 preprocess()/
ProcessedDocument로 대체됐다. 하류가 documents 조인 없이 출처 메타를 쓰려면
필드가 더 필요하다 (명세 §2-2 "스켈레톤 대비 변경점").

next_document_version_no()는 collect(경로 산출)와 preprocess(행 생성) 양쪽이
호출하므로 명세 §3-5에 따라 src/pipeline_common/versioning.py로 옮겼다.
기존 호출부가 그대로 동작하도록 여기서 re-export한다
(`from src.preprocessing.interface import next_document_version_no` 유효).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from ..pipeline_common import db, jobs, repository, storage
from ..pipeline_common.constants import (
    DOC_STATUS_FAILED,
    JOB_TYPE_PARSE_DOCUMENT,
    MAX_RETRY,
    TARGET_TYPE_DOCUMENT,
)
from ..pipeline_common.models import DocumentRef, ProcessedDocument
from ..pipeline_common.refs import get_document_refs, get_markdown
from ..pipeline_common.titles import normalize_title
from ..pipeline_common.versioning import next_document_version_no
from . import parsers
from .parsers import ParseError

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")

__all__ = [
    "preprocess",
    "deduplicate",
    "next_document_version_no",
    "get_markdown",
    "get_document_refs",
    "ProcessedDocument",
    "DocumentRef",
]


def deduplicate(document_id: UUID, content_hash: str) -> UUID | None:
    """
    동일 content_hash를 가진 document_versions.id가 있으면 반환, 없으면 None.

    읽기 전용이다. uq_dv_document_hash가 최종 방어선이지만 불필요한 Storage
    업로드를 막으려고 INSERT 전에 먼저 호출한다 (명세 §3-4).
    """
    if not _SHA256_HEX.match(content_hash or ""):
        raise ValueError(f"content_hash는 SHA-256 소문자 hex 64자여야 한다: {content_hash!r}")
    row = repository.find_version_by_hash(document_id, content_hash)
    return UUID(str(row["id"])) if row else None


def preprocess(document_id: UUID) -> ProcessedDocument | None:
    """
    raw 원문을 Markdown으로 정제하고 document_versions 행을 생성한다.
    실패 시 None을 반환하고 사유는 pipeline_jobs에 남긴다.

    raw_object_key와 content_type은 collect가 남긴 문서 단위 job의 result에서 읽는다.
    경로를 재계산하지 않는 이유: 수집 시점의 version_no와 정제 시점의 값이
    다를 수 있다 (명세 §6-2).
    """
    document = repository.get_document(document_id)
    if document is None:
        # workspace_id를 모르면 pipeline_jobs 행조차 만들 수 없다 (NOT NULL).
        return None
    workspace_id = UUID(str(document["workspace_id"]))

    collect_job = repository.latest_completed_collect_job(workspace_id, document_id)
    collect_result: dict[str, Any] = (collect_job or {}).get("result") or {}
    raw_object_key = collect_result.get("raw_object_key")

    job = jobs.start_job(
        workspace_id,
        JOB_TYPE_PARSE_DOCUMENT,
        target_type=TARGET_TYPE_DOCUMENT,
        target_id=document_id,
        idempotency_key=jobs.parse_document_key(document_id),
        payload={"raw_object_key": raw_object_key},
    )

    if collect_job is None:
        _record_failure(job, document_id, workspace_id, "collect job 없음")
        return None
    if not raw_object_key:
        _record_failure(
            job, document_id, workspace_id, "collect job의 result에 raw_object_key가 없음"
        )
        return None

    content_type = collect_result.get("content_type") or "text/html"

    try:
        body = storage.download(raw_object_key)
    except Exception as exc:  # noqa: BLE001 - Storage 예외 종류가 버전마다 다르다
        _record_failure(job, document_id, workspace_id, f"raw 다운로드 실패: {exc}")
        return None

    try:
        parsed = parsers.parse(
            body,
            content_type,
            # DB의 제목은 collect가 RSS <title>을 그대로 넣은 값이라 매체명 꼬리표가 붙어 있다.
            # 그대로 힌트로 주면 원문 <title>이 없을 때 오염된 값이 되돌아온다.
            title_hint=normalize_title(document.get("title") or ""),
            published_at_hint=_as_datetime(document.get("published_at")),
        )
    except ParseError as exc:
        _record_failure(job, document_id, workspace_id, f"정제 실패: {exc}")
        return None
    except Exception as exc:  # noqa: BLE001 - 파서 라이브러리 예외도 job에 남긴다
        _record_failure(job, document_id, workspace_id, f"정제 중 예외: {exc}")
        return None

    # documents.title의 매체명 꼬리표를 벗긴다.
    # 내용이 안 바뀌어도(=아래 dedup 경로) 제목은 틀려 있을 수 있으므로 dedup 판정 전에 한다.
    title_error = _sync_title(document, workspace_id)

    # 동일 해시면 새 행도 새 파일도 만들지 않는다. Markdown 업로드조차 하지 않는다 (명세 §3-3).
    existing_id = deduplicate(document_id, parsed.content_hash)
    if existing_id is not None:
        existing = repository.get_version(existing_id)
        if existing is not None:
            _complete(job, existing["id"], parsed, is_new_version=False, title_error=title_error)
            return _build_processed(document, existing, is_new_version=False)

    try:
        version, reused = _insert_version(document_id, workspace_id, parsed, raw_object_key)
    except _VersionInsertError as exc:
        _record_failure(job, document_id, workspace_id, str(exc))
        return None
    except Exception as exc:  # noqa: BLE001
        _record_failure(job, document_id, workspace_id, f"버전 생성 실패: {exc}")
        return None

    is_new_version = not reused
    _complete(job, version["id"], parsed, is_new_version=is_new_version, title_error=title_error)
    return _build_processed(document, version, is_new_version=is_new_version)


# ------------------------------------------------------------
# 내부
# ------------------------------------------------------------


class _VersionInsertError(Exception):
    """version_no 경합을 재시도까지 하고도 실패한 경우."""


def _insert_version(
    document_id: UUID,
    workspace_id: UUID,
    parsed: Any,
    raw_object_key: str,
) -> tuple[dict, bool]:
    """
    Markdown 업로드 + document_versions INSERT. (행, 기존행_재사용여부)를 반환한다.

    - uq_dv_document_versionno 충돌: 1회 재조회 후 재시도, 그래도 실패하면 job failed
    - uq_dv_document_hash 충돌: 경합 상대가 먼저 넣은 것이므로 그 행을 조회해 재사용
    (명세 §4-3)
    """
    last_error: Exception | None = None
    for _ in range(2):
        version_no = next_document_version_no(document_id)
        markdown_key = storage.markdown_object_key(workspace_id, document_id, version_no)
        storage.upload(markdown_key, parsed.markdown.encode("utf-8"), "text/markdown")
        try:
            row = repository.insert_document_version(
                document_id=document_id,
                version_no=version_no,
                content_hash=parsed.content_hash,
                markdown_object_key=markdown_key,
                # 경로를 재계산하지 않고 collect job의 값을 그대로 기록한다 (명세 §6-2)
                raw_object_key=raw_object_key,
                parser_version=parsed.parser_version,
                language=parsed.language,
            )
            return row, False
        except Exception as exc:  # noqa: BLE001
            if not db.is_unique_violation(exc):
                raise
            last_error = exc
            existing = repository.find_version_by_hash(document_id, parsed.content_hash)
            if existing is not None:  # 해시 충돌 -> 경합 상대의 행을 그대로 쓴다
                return existing, True
            # version_no 충돌 -> 다음 루프에서 재조회 후 재시도
    raise _VersionInsertError(f"version_no 경합으로 버전 생성 실패: {last_error}")


def _sync_title(document: dict, workspace_id: UUID) -> str | None:
    """
    documents.title에서 매체명 꼬리표를 벗긴다.

    collect는 RSS <title>을 가공 없이 넣으므로 '기사제목 - 매체명' 꼬리표가 남는다
    (collectors/interface.py _resolve_title). 2026-08-05 기준 279건 중 149건(53.4%)이
    이 상태였고, 구글 뉴스 RSS 소스는 100%였다.

    파서가 뽑은 parsed.title을 쓰지 않는 이유: 원문 <title>이 항상 더 낫지는 않다.
    JS 렌더링 페이지나 일부 언론사는 <title>이 '네이버 뉴스' 같은 사이트명이라,
    그걸 채택하면 멀쩡한 RSS 제목을 사이트명으로 덮어쓴다. 기존 제목에서 꼬리표만
    벗기면 관측된 149건을 전부 덮으면서 그 위험이 없다.

    collectors의 _sync_meta와 같은 규칙 — 값이 실제로 달라졌을 때만 UPDATE한다
    (repository.update_document_meta docstring 요구사항).

    반환값은 실패 사유다. run_preprocess의 루프에는 예외 처리가 없어서 여기서 예외가
    올라가면 배치 전체가 죽는다. 버전 생성이 본 작업이고 제목 교정은 부가라서,
    실패해도 진행하되 사유를 job result에 남겨 눈에 보이게 한다.
    """
    current = (document.get("title") or "").strip()
    corrected = normalize_title(current)
    if not corrected or corrected == current:
        return None
    try:
        repository.update_document_meta(
            UUID(str(document["id"])), workspace_id, corrected, None
        )
    except Exception as exc:  # noqa: BLE001 - 제목 교정 실패로 정제를 잃지 않는다
        return f"제목 교정 실패: {exc}"
    # 하류가 교정된 제목을 받도록 반환용 dict도 같이 고친다 (_build_processed가 이걸 읽는다).
    document["title"] = corrected
    return None


def _complete(
    job: dict,
    document_version_id: Any,
    parsed: Any,
    *,
    is_new_version: bool,
    title_error: str | None = None,
) -> None:
    result = {
        "document_version_id": str(document_version_id),
        "is_new_version": is_new_version,
        "content_hash": parsed.content_hash,
        "markdown_bytes": len(parsed.markdown.encode("utf-8")),
        "parser_version": parsed.parser_version,
    }
    if title_error:
        result["title_error"] = title_error
    jobs.complete_job(job["id"], result)


def _record_failure(job: dict, document_id: UUID, workspace_id: UUID, message: str) -> None:
    """job을 failed로 남기고, 반복 실패면 documents.status를 failed로 내린다 (명세 §3-3, §5-1)."""
    failed = jobs.fail_job(job["id"], message)
    retry_count = int((failed or {}).get("retry_count") or 0)
    if retry_count >= MAX_RETRY:
        repository.set_document_status(document_id, workspace_id, DOC_STATUS_FAILED)


def _as_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return parsers.parse_datetime(str(value))


def _build_processed(document: dict, version: dict, *, is_new_version: bool) -> ProcessedDocument:
    return ProcessedDocument(
        workspace_id=document["workspace_id"],
        document_id=document["id"],
        document_version_id=version["id"],
        source_id=document.get("source_id"),
        title=document["title"],
        canonical_url=document.get("canonical_url"),
        published_at=document.get("published_at"),
        version_no=version["version_no"],
        content_hash=version["content_hash"],
        raw_object_key=version.get("raw_object_key"),
        markdown_object_key=version["markdown_object_key"],
        parser_version=version.get("parser_version"),
        language=version.get("language"),
        created_at=version["created_at"],
        is_new_version=is_new_version,
    )

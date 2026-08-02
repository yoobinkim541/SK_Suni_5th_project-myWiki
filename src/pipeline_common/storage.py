"""
Storage 경로 규칙과 업로드·다운로드 (명세 §6).

경로 규칙
    raw/{workspace_id}/{document_id}/{version_no}.{ext}
    processed/{workspace_id}/{document_id}/{version_no}.md

object_key 컬럼값에는 버킷명을 포함해 저장한다 (명세 §6-2 확정).
Storage 호출 시에만 접두사를 떼며, 그 변환은 이 모듈 한곳에만 둔다.
"""
from __future__ import annotations

from uuid import UUID

from . import db
from .constants import BUCKET_PROCESSED, BUCKET_RAW

# 명세 §6-2 확장자 매핑
EXT_BY_CONTENT_TYPE = {
    "text/html": "html",
    "application/pdf": "pdf",
    "application/json": "json",
    "text/plain": "txt",
}
DEFAULT_EXT = "bin"


def ext_for(content_type: str) -> str:
    """content_type -> 파일 확장자. 매핑에 없으면 'bin'."""
    base = (content_type or "").split(";")[0].strip().lower()
    return EXT_BY_CONTENT_TYPE.get(base, DEFAULT_EXT)


def raw_object_key(
    workspace_id: UUID, document_id: UUID, version_no: int, content_type: str
) -> str:
    return f"{BUCKET_RAW}/{workspace_id}/{document_id}/{version_no}.{ext_for(content_type)}"


def markdown_object_key(workspace_id: UUID, document_id: UUID, version_no: int) -> str:
    return f"{BUCKET_PROCESSED}/{workspace_id}/{document_id}/{version_no}.md"


def split_key(object_key: str) -> tuple[str, str]:
    """'raw/ws/doc/1.html' -> ('raw', 'ws/doc/1.html')."""
    bucket, _, path = object_key.partition("/")
    if not bucket or not path:
        raise ValueError(f"object_key에 버킷 접두사가 없다: {object_key!r}")
    return bucket, path


def upload(object_key: str, data: bytes, content_type: str) -> None:
    """
    버킷명이 포함된 object_key로 업로드한다.

    같은 경로가 이미 있으면 덮어쓴다. document_versions가 참조하지 않는
    파일만 같은 경로로 다시 올라오므로 "원본 불변" 원칙에 어긋나지 않는다 (명세 §6-3).
    """
    bucket, path = split_key(object_key)
    db.get_client().storage.from_(bucket).upload(
        path=path,
        file=data,
        file_options={"content-type": content_type, "upsert": "true"},
    )


def download(object_key: str) -> bytes:
    """버킷명이 포함된 object_key에서 내려받는다. 없으면 예외가 그대로 올라온다."""
    bucket, path = split_key(object_key)
    return db.get_client().storage.from_(bucket).download(path)

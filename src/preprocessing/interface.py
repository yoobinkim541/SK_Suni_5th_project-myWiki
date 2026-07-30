from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class DocumentVersion:
    id: str
    document_id: str
    version_no: int
    content_hash: str
    markdown_object_key: str
    is_new_version: bool  # True면 실제로 내용이 바뀌어 새 버전이 생성됨, False면 기존 버전 재사용


def next_document_version_no(document_id: str) -> int:
    """
    document_versions 에서 MAX(version_no) + 1 을 반환한다.
    수집 시점에 raw_object_key 경로를 구성할 때 호출한다.

    경로 규칙: raw/{workspace_id}/{document_id}/{version_no}.{ext}
    version_no 는 document_versions 행 INSERT 전에 이 함수로 미리 확정하고,
    해당 경로에 파일을 올린 뒤 같은 version_no 로 행을 삽입한다.
    INSERT 가 실패하면 Storage 파일은 고아 상태로 남는다 (MVP 허용 범위).
    """
    raise NotImplementedError


def process_document(document_id: str) -> DocumentVersion:
    """
    documents.raw_object_key 원문을 읽어 Markdown으로 정제하고,
    content_hash가 기존 버전과 같으면 새로 만들지 않고 기존 버전을 반환한다.
    다르면 next_document_version_no() 로 version_no 를 확정한 뒤
    새 document_versions 행을 만든다.
    """
    raise NotImplementedError


def deduplicate(document_id: str, content_hash: str) -> Optional[str]:
    """이미 동일한 content_hash를 가진 document_versions.id가 있으면 그 id를 반환한다."""
    raise NotImplementedError

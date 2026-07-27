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


def process_document(document_id: str) -> DocumentVersion:
    """
    documents.raw_object_key 원문을 읽어 Markdown으로 정제하고,
    content_hash가 기존 버전과 같으면 새로 만들지 않고 기존 버전을 반환한다.
    다르면 version_no를 올려 새 document_versions 행을 만든다.
    """
    raise NotImplementedError


def deduplicate(document_id: str, content_hash: str) -> Optional[str]:
    """이미 동일한 content_hash를 가진 document_versions.id가 있으면 그 id를 반환한다."""
    raise NotImplementedError

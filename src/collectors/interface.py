"""
데이터 수집 담당이 구현할 인터페이스 초안.
실제 구현은 이 시그니처를 유지하면서 채워 넣으면 되고, 바꿔야 하면 팀에 먼저 공유한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class CollectedDocument:
    document_id: str
    source_id: str
    title: str
    canonical_url: Optional[str]
    raw_object_key: str  # Storage에 업로드된 원문(HTML/PDF 등) 경로


def register_source(
    workspace_id: str, name: str, source_type: str, base_url: Optional[str], config: dict
) -> str:
    """sources 테이블에 새 출처를 등록하고 source_id를 반환한다."""
    raise NotImplementedError


def collect(source_id: str) -> list[CollectedDocument]:
    """
    해당 출처에서 새 문서를 수집한다.
    - 이미 canonical_url이 존재하면 새로 만들지 않는다.
    - 성공/실패 여부는 pipeline_jobs에 기록한다 (job_type='collect').
    """
    raise NotImplementedError

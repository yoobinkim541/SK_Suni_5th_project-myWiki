"""
src/agent/wiki_tools.py의 WikiTools.read_wiki_page()가 이 파트의 산출물을 그대로 소비한다.
아래 dataclass 필드명은 agent 쪽 기대값과 맞춰뒀으니 임의로 이름을 바꾸지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class WikiSourceInput:
    document_version_id: str
    claim_text: str
    source_start_line: Optional[int] = None
    source_end_line: Optional[int] = None
    support_type: str = "supports"  # 'supports' | 'contradicts' | 'context'


def upsert_wiki_page(
    workspace_id: str, slug: str, title: str, page_type: str
) -> str:
    """slug 기준으로 wiki_pages를 찾거나 새로 만들고 id를 반환한다."""
    raise NotImplementedError


def add_wiki_version(
    page_id: str,
    markdown: str,
    change_summary: str,
    sources: list[WikiSourceInput],
    created_by: Optional[str] = None,
) -> str:
    """
    새 wiki_page_versions를 추가한다 (기존 버전은 절대 수정/삭제하지 않는다).
    - markdown을 Storage에 업로드하고 markdown_object_key를 채운다
    - sources를 wiki_page_sources로 저장한다
    - wiki_pages.current_version_id를 이 새 버전으로 갱신한다
    반환값은 새 wiki_page_versions.id.
    """
    raise NotImplementedError

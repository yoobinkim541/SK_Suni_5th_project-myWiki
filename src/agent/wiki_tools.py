"""
Wiki 조회 도구 — Agent 전용 어댑터 (Karpathy LLM Wiki 패턴).

Agent 가 list_wiki_topics() → read_wiki_page() 를 순차 호출해 필요한 문서만 읽는다.
실제 DB/Storage 조회는 src/wiki/query.py 에 위임한다.

변경 시 주의:
- WikiPageContent.sources 의 필드명은 core.py 가 __dict__ 로 직접 접근하므로
  src/wiki/interface.py 의 WikiSource 필드명과 맞춰야 한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..wiki import query as wiki_query
from ..wiki.interface import WikiPageContent, WikiPageSummary, WikiSource


@dataclass
class WikiTopic:
    id: str
    slug: str
    title: str
    page_type: str
    status: str


class WikiTools:
    """workspace_id 로 스코프를 고정해 다른 workspace 데이터가 섞이지 않게 한다."""

    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id

    def list_wiki_topics(self) -> list[WikiTopic]:
        """published 위키 페이지 목록을 반환한다."""
        pages: list[WikiPageSummary] = wiki_query.list_published_wiki_pages(self.workspace_id)
        return [
            WikiTopic(
                id=p.id,
                slug=p.slug,
                title=p.title,
                page_type=p.page_type,
                status=p.status,
            )
            for p in pages
        ]

    def read_wiki_page(self, slug: str) -> Optional[WikiPageContent]:
        """
        게시·승인·검증된 Wiki 페이지 본문과 원문 근거를 반환한다.
        validation_status='passed' AND review_status='approved' 를 모두 확인한다.
        """
        return wiki_query.get_published_wiki_page(self.workspace_id, slug)

"""
Wiki·원문 문서 조회 도구 — Agent 전용 어댑터 (Karpathy LLM Wiki 패턴).

Agent 가 list_wiki_topics() → read_wiki_page() 를 순차 호출해 필요한 문서만 읽는다.
위키에 근거가 없을 때는 search_documents() → read_document()로 수집된 원문(뉴스+DART,
위키 발행 여부 무관)에서 근거를 찾는다.
그마저 없을 때는 search_web()으로 웹에서, search_recent_disclosures()/read_disclosure()로 최신 DART 공시를 찾는다.
실제 DB/Storage 조회는 src/wiki/query.py, src/pipeline_common/document_search.py 에 위임한다.

변경 시 주의:
- WikiPageContent.sources 의 필드명은 core.py 가 __dict__ 로 직접 접근하므로
  src/wiki/interface.py 의 WikiSource 필드명과 맞춰야 한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..pipeline_common import dart_lookup, document_search, web_search
from ..wiki import query as wiki_query
from ..wiki.interface import WikiPageContent, WikiPageSummary, WikiSource
from ..wiki.interface import search_wiki_contexts
from ..wiki.models import WikiSearchRequest

DEFAULT_SEARCH_LIMIT = 5
# list_published_wiki_pages()의 기본 limit=50은 프론트 WikiPage 트리의 페이지네이션
# 기준값이다. Agent는 페이지를 나눠 보여줄 화면이 없어 한 번에 전체 목록을 훑어야
# 하므로, wiki_router.py의 상한(le=200)까지 명시적으로 끌어올려 요청한다.
LIST_TOPICS_LIMIT = 200


@dataclass
class WikiTopic:
    id: str
    slug: str
    title: str
    page_type: str
    status: str


@dataclass
class WikiSearchHit:
    slug: str
    title: str
    score: float


class WikiTools:
    """workspace_id 로 스코프를 고정해 다른 workspace 데이터가 섞이지 않게 한다."""

    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id

    def list_wiki_topics(self) -> list[WikiTopic]:
        """published 위키 페이지 목록을 반환한다."""
        pages: list[WikiPageSummary] = wiki_query.list_published_wiki_pages(
            self.workspace_id, limit=LIST_TOPICS_LIMIT
        )
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

    def search_wiki_pages(self, query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> list[WikiSearchHit]:
        """
        질문 키워드로 위키 페이지를 title+본문 관련도 순으로 찾는다 (Report 파이프라인과
        같은 search_wiki_contexts()를 재사용). list_wiki_topics()는 제목 문자열만
        보여줘서 LLM이 제목과 질문 문구가 겹치지 않으면 관련 페이지를 놓치는 문제가 있었다
        — 본문까지 반영해 점수를 매기는 이 도구로 그 문제를 보완한다.
        """
        request = WikiSearchRequest(workspace_id=self.workspace_id, query=query, limit=limit)
        results = search_wiki_contexts(request)
        return [WikiSearchHit(slug=r.slug, title=r.title, score=r.score) for r in results]

    def search_documents(
        self, query: str, limit: int = DEFAULT_SEARCH_LIMIT
    ) -> list[document_search.DocumentSearchHit]:
        """
        질문 키워드로 수집된 원문(뉴스+DART, 위키 발행 여부 무관)을 title+본문 관련도
        순으로 찾는다. 위키에 근거가 없을 때(_document_answer)만 쓰는 2차 검색 도구다 —
        위키 발행 여부와 무관하게 수집된 원문 전체를 대상으로 한다.
        """
        return document_search.search_documents(self.workspace_id, query, limit=limit)

    def read_document(self, document_version_id: str) -> Optional[document_search.DocumentDetail]:
        """원문 문서 1건의 전체 내용과 출처 메타데이터(매체명·게시일·원문 링크)를 반환한다."""
        return document_search.get_document_detail(self.workspace_id, document_version_id)

    def search_web(self, query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> list[web_search.WebSearchHit]:
        """실시간 웹(네이버 검색)에서 찾는다. 위키·원문 모두 근거가 없을 때(_web_search_answer)만
        쓰는 3차 검색 도구 — workspace 스코프 데이터가 아니라 workspace_id를 받지 않는다."""
        return web_search.search_web(query, limit)

    def search_recent_disclosures(
        self, days: int = dart_lookup.DEFAULT_LOOKBACK_DAYS, pblntf_ty: str | None = None
    ) -> list[dart_lookup.DisclosureHit]:
        """이 워크스페이스에 등록된 회사들의 최근 N일 DART 공시 목록. 위키·원문·웹
        검색 어디에도 없을 때(_web_search_answer)만 쓰는 3차 그라운딩 도구.
        pblntf_ty로 공시유형 하나를 좁혀서 조회할 수 있다(예: 'B'=주요사항보고)."""
        return dart_lookup.search_recent_disclosures(self.workspace_id, days, pblntf_ty)

    def read_disclosure(self, rcept_no: str) -> Optional[str]:
        """공시 1건의 실제 본문(태그 제거·길이 상한 적용된 일반 텍스트)."""
        return dart_lookup.read_disclosure(rcept_no)

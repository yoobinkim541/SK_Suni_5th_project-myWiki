"""
위키 조회 도구 (Karpathy LLM Wiki 패턴)
- 벡터DB/임베딩 없이, Agent가 list_wiki_topics() -> read_wiki_page()를
  순차적으로 호출해서 필요한 문서만 읽어들이는 방식.
- 실제 원문 마크다운은 Supabase Storage에 저장돼 있고, DB에는 경로(object_key)만 있다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from supabase import Client


@dataclass
class WikiTopic:
    id: str
    slug: str
    title: str
    page_type: str
    status: str


@dataclass
class WikiSource:
    """wiki_page_sources 한 행 = 위키 본문의 특정 주장과, 그걸 뒷받침하는 원문 근거"""
    id: str
    document_version_id: str
    claim_text: Optional[str]
    source_start_line: Optional[int]
    source_end_line: Optional[int]
    support_type: Optional[str]


@dataclass
class WikiPageContent:
    page_id: str
    slug: str
    title: str
    markdown: str
    sources: list[WikiSource]


class WikiTools:
    """workspace_id로 스코프를 고정해서, 다른 workspace 데이터가 섞이지 않게 한다."""

    def __init__(self, supabase: Client, workspace_id: str, storage_bucket: str = "myWiki"):
        self.supabase = supabase
        self.workspace_id = workspace_id
        self.storage_bucket = storage_bucket

    def list_wiki_topics(self) -> list[WikiTopic]:
        """index.md 역할 — 지금 workspace에 있는 모든 published 위키 페이지 목록."""
        res = (
            self.supabase.table("wiki_pages")
            .select("id, slug, title, page_type, status")
            .eq("workspace_id", self.workspace_id)
            .eq("status", "published")
            .execute()
        )
        return [WikiTopic(**row) for row in res.data]

    def read_wiki_page(self, slug: str) -> Optional[WikiPageContent]:
        """
        특정 위키 페이지의 현재 버전 본문 + 근거(wiki_page_sources)를 함께 반환한다.
        Agent가 이 본문에서 답을 찾으면, sources 중 알맞은 document_version_id를
        citation으로 그대로 쓸 수 있게 하기 위함.
        """
        page_res = (
            self.supabase.table("wiki_pages")
            .select("id, slug, title, current_version_id")
            .eq("workspace_id", self.workspace_id)
            .eq("slug", slug)
            .maybe_single()
            .execute()
        )
        if not page_res.data or not page_res.data.get("current_version_id"):
            return None

        page = page_res.data
        version_id = page["current_version_id"]

        version_res = (
            self.supabase.table("wiki_page_versions")
            .select("id, markdown_object_key")
            .eq("id", version_id)
            .single()
            .execute()
        )
        object_key = version_res.data["markdown_object_key"]

        markdown_bytes = self.supabase.storage.from_(self.storage_bucket).download(object_key)
        markdown = markdown_bytes.decode("utf-8")

        sources_res = (
            self.supabase.table("wiki_page_sources")
            .select(
                "id, document_version_id, claim_text, source_start_line, source_end_line, support_type"
            )
            .eq("wiki_version_id", version_id)
            .order("citation_order")
            .execute()
        )
        sources = [WikiSource(**row) for row in sources_res.data]

        return WikiPageContent(
            page_id=page["id"], slug=page["slug"], title=page["title"],
            markdown=markdown, sources=sources,
        )

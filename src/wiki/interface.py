"""
src/wiki/ 팀 간 공개 Python 계약 — DTO + 함수 시그니처.

command 함수: 생성·검증·검수·게시 (구현은 service.py, PR 2)
query 함수:   게시된 Wiki 조회 (구현은 query.py, Agent·Report 공용)

규칙:
- 아래 dataclass 필드명은 src/agent/wiki_tools.py와 맞춰져 있으므로 임의로 변경하지 않는다.
- current_version_id 변경은 publish_wiki_version() 에서만 허용한다.
- 초안 생성만으로 current_version_id 를 바꾸지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

PageType = Literal['industry', 'company', 'technology', 'issue', 'term']
SupportType = Literal['supports', 'contradicts', 'context']
ValidationStatus = Literal['pending', 'passed', 'failed']
ReviewDecision = Literal['approved', 'rejected']


# ---------------------------------------------------------------------------
# 입력 DTO
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WikiSourceInput:
    """wiki_page_sources 한 행 삽입용 입력."""
    document_version_id: str
    claim_text: str
    source_start_line: Optional[int] = None
    source_end_line: Optional[int] = None
    support_type: SupportType = 'supports'
    citation_order: Optional[int] = None


@dataclass(frozen=True)
class WikiDraftInput:
    """create_wiki_version() 단일 진입 DTO."""
    workspace_id: str
    slug: str
    title: str
    page_type: PageType
    markdown: str
    sources: list[WikiSourceInput]
    change_summary: Optional[str] = None
    parent_page_id: Optional[str] = None
    created_by: Optional[str] = None
    generated_by: Literal['human', 'llm'] = 'llm'
    generator_model: Optional[str] = None
    generator_prompt_version: Optional[str] = None
    generation_run_id: Optional[str] = None


# ---------------------------------------------------------------------------
# 출력 DTO
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WikiPageSummary:
    """list_published_wiki_pages() 목록 항목."""
    id: str
    slug: str
    title: str
    page_type: str
    status: str
    parent_page_id: Optional[str]
    published_at: Optional[str]


@dataclass(frozen=True)
class WikiVersionSummary:
    """버전 이력 목록 항목."""
    id: str
    version_no: int
    change_summary: Optional[str]
    created_at: str


@dataclass(frozen=True)
class WikiSource:
    """Wiki 본문의 특정 주장과 그 원문 근거."""
    document_version_id: str
    citation_order: Optional[int]
    claim_text: Optional[str]
    support_type: Optional[str]
    source_start_line: Optional[int]
    source_end_line: Optional[int]


@dataclass(frozen=True)
class WikiPageContent:
    """get_published_wiki_page() 상세 응답. 반드시 게시·승인·검증된 버전만 반환한다."""
    page_id: str
    slug: str
    title: str
    page_type: str
    published_at: Optional[str]
    version_id: str
    version_no: int
    markdown: str
    change_summary: Optional[str]
    confidence_score: Optional[float]
    validation_status: str
    review_status: str
    generated_by: str
    generator_model: Optional[str]
    created_at: str
    sources: tuple[WikiSource, ...]
    versions: tuple[WikiVersionSummary, ...]


# ---------------------------------------------------------------------------
# 공개 command 함수 (구현: service.py)
# ---------------------------------------------------------------------------

def upsert_wiki_page(
    workspace_id: str,
    slug: str,
    title: str,
    page_type: PageType,
    parent_page_id: Optional[str] = None,
) -> str:
    """slug 기준으로 wiki_pages를 찾거나 새로 만들고 id를 반환한다."""
    from .service import upsert_wiki_page as _impl
    return _impl(workspace_id, slug, title, page_type, parent_page_id)


def create_wiki_version(draft: WikiDraftInput) -> str:
    """
    새 wiki_page_versions 초안을 만든다.
    - review_status='pending', validation_status='pending' 으로 삽입한다.
    - current_version_id 는 변경하지 않는다.
    반환값: 새 wiki_page_versions.id
    """
    from .service import create_wiki_version as _impl
    return _impl(draft)


def record_wiki_validation(
    version_id: str,
    validation_status: ValidationStatus,
    confidence_score: Optional[float],
) -> None:
    """wiki_page_versions.validation_status / confidence_score 를 기록한다."""
    raise NotImplementedError


def review_wiki_version(
    version_id: str,
    reviewer_id: str,
    decision: ReviewDecision,
) -> None:
    """검수 결과를 기록한다. current_version_id 는 변경하지 않는다."""
    raise NotImplementedError


def publish_wiki_version(page_id: str, version_id: str) -> None:
    """
    validation_status='passed' 이고 review_status='approved' 인 버전만 게시한다.
    wiki_pages.current_version_id 와 published_at 은 이 함수에서만 변경한다.
    """
    raise NotImplementedError


def request_wiki_index(
    wiki_version_id: str,
    collection_name: str,
    requested_by: Optional[str] = None,
) -> str:
    """QMD 색인 pipeline_job 을 생성하고 job_id 를 반환한다."""
    raise NotImplementedError


# ---------------------------------------------------------------------------
# 공용 query 함수 — 구현은 query.py, Agent·Report 공용 진입점
# ---------------------------------------------------------------------------

def list_published_wiki_pages(
    workspace_id: str,
    page_type: Optional[PageType] = None,
    query: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[WikiPageSummary]:
    """게시된 Wiki 페이지 목록을 반환한다."""
    from .query import list_published_wiki_pages as _impl
    return _impl(workspace_id, page_type=page_type, query=query, limit=limit, offset=offset)


def get_published_wiki_page(
    workspace_id: str,
    slug: str,
) -> Optional[WikiPageContent]:
    """
    게시된 Wiki 페이지 상세를 반환한다.
    wiki_pages.status='published'
    AND wiki_page_versions.validation_status='passed'
    AND wiki_page_versions.review_status='approved'
    세 조건을 모두 확인한다.
    """
    from .query import get_published_wiki_page as _impl
    return _impl(workspace_id, slug)


def list_wiki_versions(
    workspace_id: str,
    page_id: str,
) -> list[WikiVersionSummary]:
    """특정 페이지의 버전 이력을 최신순으로 반환한다."""
    from .query import list_wiki_versions as _impl
    return _impl(workspace_id, page_id)

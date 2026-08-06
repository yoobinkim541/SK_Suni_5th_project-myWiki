"""
Wiki 조회 REST 엔드포인트 — 프론트엔드 WikiPage 화면 전용 진입점.

실제 조회는 src/wiki/query.py 에 위임한다 (Agent·Report와 동일한 공용 진입점).
이 라우터는 그 위에 workspace 인증·스코프만 얹는다.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from . import db
from .auth import get_current_user
from .schemas import WikiKeywordCountOut, WikiPageContentOut, WikiPageSummaryOut, WikiVersionSummaryOut
from ..wiki import query as wiki_query
from ..wiki.interface import PageType

router = APIRouter(prefix="/wiki", tags=["wiki"])


def _require_workspace(profile: dict) -> str:
    workspace_id = db.get_default_workspace_id(profile["id"])
    if not workspace_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="workspace 소속이 없음")
    return workspace_id


@router.get("/pages", response_model=list[WikiPageSummaryOut])
def list_pages(
    page_type: Optional[PageType] = Query(default=None),
    q: Optional[str] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    profile: dict = Depends(get_current_user),
):
    """WikiPage 좌측 트리용 목록. page_type으로 그룹핑해서 렌더링한다."""
    workspace_id = _require_workspace(profile)
    return wiki_query.list_published_wiki_pages(
        workspace_id, page_type=page_type, query=q, keyword=keyword, limit=limit, offset=offset
    )


@router.get("/pages/{slug}", response_model=WikiPageContentOut)
def get_page(slug: str, profile: dict = Depends(get_current_user)):
    """WikiPage 본문 영역 — 게시·승인·검증된 버전만 반환한다."""
    workspace_id = _require_workspace(profile)
    page = wiki_query.get_published_wiki_page(workspace_id, slug)
    if page is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="게시된 위키 페이지를 찾을 수 없음"
        )
    return page


@router.get("/pages/{page_id}/versions", response_model=list[WikiVersionSummaryOut])
def get_versions(page_id: str, profile: dict = Depends(get_current_user)):
    """WikiPage "변경 이력" 타임라인용."""
    workspace_id = _require_workspace(profile)
    return wiki_query.list_wiki_versions(workspace_id, page_id)


@router.get("/keywords", response_model=list[WikiKeywordCountOut])
def list_keywords(profile: dict = Depends(get_current_user)):
    """위키 목록 화면의 키워드 필터 칩 바용 — 실제 사용 중인 키워드+건수."""
    workspace_id = _require_workspace(profile)
    return wiki_query.list_workspace_keyword_counts(workspace_id)

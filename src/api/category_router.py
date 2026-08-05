"""
카테고리 현황 조회 REST 엔드포인트 — 프론트엔드 CategoryPage 화면 전용 진입점.

실제 집계는 src/categories/service.py 에 위임한다.
dashboard_router.py와 같은 구조다 (_require_workspace 포함).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from . import db
from .auth import get_current_user
from .schemas import CategoryStatsOut
from ..categories import service as category_service

router = APIRouter(prefix="/categories", tags=["categories"])


def _require_workspace(profile: dict) -> str:
    workspace_id = db.get_default_workspace_id(profile["id"])
    if not workspace_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="workspace 소속이 없음")
    return workspace_id


@router.get("/stats", response_model=CategoryStatsOut)
def get_stats(profile: dict = Depends(get_current_user)):
    """CategoryPage의 카드 6장 + 상단 요약용 집계 (최근 7일)."""
    workspace_id = _require_workspace(profile)
    return category_service.get_category_stats(workspace_id)

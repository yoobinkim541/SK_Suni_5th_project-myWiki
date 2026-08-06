"""
대시보드 KPI 조회 REST 엔드포인트 — 프론트엔드 DashboardPage 화면 전용 진입점.

실제 집계는 src/dashboard/service.py 에 위임한다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from . import db
from .auth import get_current_user
from .schemas import DashboardSummaryOut, DashboardTrendOut
from ..dashboard import service as dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _require_workspace(profile: dict) -> str:
    workspace_id = db.get_default_workspace_id(profile["id"])
    if not workspace_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="workspace 소속이 없음")
    return workspace_id


@router.get("/summary", response_model=DashboardSummaryOut)
def get_summary(profile: dict = Depends(get_current_user)):
    """DashboardPage KPI 카드(수집 문서·생성 보고서·위키 문서·평균 신뢰도) 전용."""
    workspace_id = _require_workspace(profile)
    return dashboard_service.get_dashboard_summary(workspace_id)


@router.get("/trend", response_model=DashboardTrendOut)
def get_trend(profile: dict = Depends(get_current_user)):
    """DashboardPage 동향 차트 전용. 최근 7일 일별 수집·채택 건수 (KST 기준)."""
    workspace_id = _require_workspace(profile)
    return dashboard_service.get_dashboard_trend(workspace_id)

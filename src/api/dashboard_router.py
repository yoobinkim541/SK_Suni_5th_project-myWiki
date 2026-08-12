"""
대시보드 KPI 조회 REST 엔드포인트 — 프론트엔드 DashboardPage 화면 전용 진입점.

실제 집계는 src/dashboard/service.py 에 위임한다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from . import db
from .auth import get_current_user
from .schemas import (
    DashboardIssuesOut,
    DashboardKeywordsOut,
    DashboardNewsOut,
    DashboardSummaryOut,
    DashboardTrendOut,
)
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


@router.get("/keywords", response_model=DashboardKeywordsOut)
def get_keywords(profile: dict = Depends(get_current_user)):
    """DashboardPage '오늘의 키워드' 칩 전용. 제목에 등장한 낱말 상위 8개 (최근 7일)."""
    workspace_id = _require_workspace(profile)
    return dashboard_service.get_dashboard_keywords(workspace_id)


@router.get("/news", response_model=DashboardNewsOut)
def get_news(profile: dict = Depends(get_current_user)):
    """DashboardPage '최신 뉴스' 카드 전용. 문서 단위로 접은 뒤 발행일 내림차순."""
    workspace_id = _require_workspace(profile)
    return dashboard_service.get_dashboard_news(workspace_id)


@router.get("/issues", response_model=DashboardIssuesOut)
def get_issues(profile: dict = Depends(get_current_user)):
    """DashboardPage '최근 산업 이슈' 전용. 최근 7일 발행 공시 중 분석이 끝난 것만.

    '최신 뉴스'와 창은 같지만 공시만 담는다. 분석 미완료 공시는 빠지므로 건수가
    수집된 공시 수보다 적다 — 자세한 기준은 service.get_dashboard_issues 참조.
    """
    workspace_id = _require_workspace(profile)
    return dashboard_service.get_dashboard_issues(workspace_id)

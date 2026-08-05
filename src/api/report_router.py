from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

from . import db
from .auth import get_current_user
from .schemas import DailyReportOut
from ..report import service as report_service

router = APIRouter(prefix="/reports", tags=["reports"])


def _require_workspace(profile: dict) -> str:
    workspace_id = db.get_default_workspace_id(profile["id"])
    if not workspace_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="workspace ??? ??")
    return workspace_id


@router.get("/daily", response_model=DailyReportOut)
def get_daily_report(
    date: date = Query(...),
    profile: dict = Depends(get_current_user),
):
    workspace_id = _require_workspace(profile)
    report = report_service.get_daily_report(workspace_id, date)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="daily report not found")
    return report

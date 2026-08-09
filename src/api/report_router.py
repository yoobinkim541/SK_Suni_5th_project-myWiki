from __future__ import annotations

from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from . import db
from .auth import get_current_user
from .schemas import DailyReportGenerateRequest, DailyReportGenerateResponse, DailyReportHistoryItemOut, DailyReportOut
from ..report import service as report_service

router = APIRouter(prefix="/reports", tags=["reports"])


def _require_workspace(profile: dict) -> str:
    workspace_id = db.get_default_workspace_id(profile["id"])
    if not workspace_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="workspace not found")
    return workspace_id


@router.get("/daily/history", response_model=list[DailyReportHistoryItemOut])
def get_daily_report_history(
    limit: int = Query(default=30, ge=1, le=100),
    profile: dict = Depends(get_current_user),
):
    workspace_id = _require_workspace(profile)
    return report_service.get_daily_report_history(workspace_id, limit=limit)


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


@router.post("/daily/generate", response_model=DailyReportGenerateResponse)
def generate_daily_report(
    body: DailyReportGenerateRequest,
    profile: dict = Depends(get_current_user),
):
    workspace_id = _require_workspace(profile)
    try:
        return report_service.generate_daily_report_artifacts(
            workspace_id=workspace_id,
            report_date=body.date,
            max_sections=body.max_sections,
            language=body.language,
            requested_by=profile["id"],
            formats=body.formats,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="failed to generate daily report",
        ) from exc


@router.get("/daily/download")
def download_daily_report(
    date: date = Query(...),
    format: str = Query(...),
    profile: dict = Depends(get_current_user),
):
    workspace_id = _require_workspace(profile)
    try:
        download = report_service.get_daily_report_download(
            workspace_id,
            date,
            format,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except report_service.ReportDownloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="failed to download daily report artifact",
        ) from exc

    if download is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="daily report artifact not found")

    return Response(
        content=download.payload,
        media_type=download.mime_type,
        headers={"Content-Disposition": _build_attachment_disposition(download.filename)},
    )


def _build_attachment_disposition(filename: str) -> str:
    escaped = filename.replace('"', "")
    encoded = quote(escaped)
    return f'attachment; filename="{escaped}"; filename*=UTF-8\'\'{encoded}'

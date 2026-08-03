"""워크스페이스 설정 REST 엔드포인트."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from . import db
from .auth import get_current_user
from .schemas import UpdateWorkspaceSettingsRequest, WorkspaceSettingsOut
from ..settings import service as settings_service

router = APIRouter(tags=["settings"])


def _require_workspace(profile: dict) -> str:
    workspace_id = db.get_default_workspace_id(profile["id"])
    if not workspace_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="workspace 소속이 없음")
    return workspace_id


@router.get("/settings", response_model=WorkspaceSettingsOut)
def get_settings(profile: dict = Depends(get_current_user)):
    workspace_id = _require_workspace(profile)
    return settings_service.get_workspace_settings(workspace_id)


@router.patch("/settings", response_model=WorkspaceSettingsOut)
def patch_settings(body: UpdateWorkspaceSettingsRequest, profile: dict = Depends(get_current_user)):
    workspace_id = _require_workspace(profile)

    kwargs: dict = {"updated_by": profile["id"]}
    if body.wiki_update_cycle_minutes is not None:
        kwargs["wiki_update_cycle_minutes"] = body.wiki_update_cycle_minutes
    if "chat_retention_days" in body.model_fields_set:
        if (
            body.chat_retention_days is not None
            and body.chat_retention_days not in settings_service.CHAT_RETENTION_DAYS_CHOICES
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"chat_retention_days는 {settings_service.CHAT_RETENTION_DAYS_CHOICES} 또는 null이어야 함",
            )
        kwargs["chat_retention_days"] = body.chat_retention_days

    try:
        return settings_service.update_workspace_settings(workspace_id, **kwargs)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

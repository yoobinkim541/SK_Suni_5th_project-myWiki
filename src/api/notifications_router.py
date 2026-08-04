"""위키 발행 브라우저 푸시 알림 구독 REST 엔드포인트."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from . import db
from .auth import get_current_user
from .schemas import SubscribeRequest
from ..notifications import service as notifications_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _require_workspace(profile: dict) -> str:
    workspace_id = db.get_default_workspace_id(profile["id"])
    if not workspace_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="workspace 소속이 없음")
    return workspace_id


@router.post("/subscribe", status_code=status.HTTP_204_NO_CONTENT)
def subscribe(body: SubscribeRequest, profile: dict = Depends(get_current_user)):
    workspace_id = _require_workspace(profile)
    notifications_service.save_subscription(
        workspace_id, profile["id"], body.endpoint, body.keys.p256dh, body.keys.auth,
    )


@router.delete("/subscribe", status_code=status.HTTP_204_NO_CONTENT)
def unsubscribe(endpoint: str = Query(...), profile: dict = Depends(get_current_user)):
    notifications_service.delete_subscription(profile["id"], endpoint)

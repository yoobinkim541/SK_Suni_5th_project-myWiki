"""
Wiki command 구현 — upsert·생성·검증·검수·게시·색인.

규칙:
  current_version_id 변경은 publish_wiki_version() 에서만 허용한다.
  create_wiki_version() 은 validation_status='pending', review_status='pending' 으로만 삽입한다.

SERVICE_ROLE_KEY 를 사용하며, 모든 쿼리에 workspace_id 필터를 명시한다.
"""
from __future__ import annotations

from typing import Optional

from .query import WIKI_BUCKET, _get_client
from .interface import PageType, WikiDraftInput


def upsert_wiki_page(
    workspace_id: str,
    slug: str,
    title: str,
    page_type: PageType,
    parent_page_id: Optional[str] = None,
) -> str:
    db = _get_client()
    data = {
        "workspace_id": workspace_id,
        "slug": slug,
        "title": title,
        "page_type": page_type,
        "status": "draft",
        "review_policy": "review",
    }
    if parent_page_id:
        data["parent_page_id"] = parent_page_id
    res = (
        db.table("wiki_pages")
        .upsert(data, on_conflict="workspace_id,slug")
        .execute()
    )
    return res.data[0]["id"]

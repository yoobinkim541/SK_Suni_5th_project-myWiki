from __future__ import annotations

from datetime import datetime, timedelta, timezone

from supabase import Client

from ..analysis.repository import get_supabase
from .generation_models import TopLevelTopicPage, WikiPageIdentity

TOP_LEVEL_TOPIC_PAGE_TYPES = ("industry", "company", "technology", "term")


def list_top_level_topic_pages(
    workspace_id: str,
    *,
    supabase: Client | None = None,
) -> list[TopLevelTopicPage]:
    db = supabase or get_supabase()
    rows = (
        db.table("wiki_pages")
        .select("id, title, page_type")
        .eq("workspace_id", workspace_id)
        .eq("status", "published")
        .is_("parent_page_id", None)
        .in_("page_type", list(TOP_LEVEL_TOPIC_PAGE_TYPES))
        .execute()
        .data
    )
    return [
        TopLevelTopicPage(wiki_page_id=str(row["id"]), title=row["title"], page_type=row["page_type"])
        for row in rows
    ]


def find_stale_published_page_ids(
    workspace_id: str,
    *,
    staleness_days: int,
    supabase: Client | None = None,
) -> list[str]:
    db = supabase or get_supabase()
    pages = (
        db.table("wiki_pages")
        .select("id, current_version_id")
        .eq("workspace_id", workspace_id)
        .eq("status", "published")
        .execute()
        .data
    )
    version_ids = [row["current_version_id"] for row in pages if row.get("current_version_id")]
    if not version_ids:
        return []

    versions = (
        db.table("wiki_page_versions")
        .select("id, created_at")
        .in_("id", version_ids)
        .execute()
        .data
    )
    created_at_by_version = {str(row["id"]): row["created_at"] for row in versions}

    threshold = datetime.now(timezone.utc) - timedelta(days=staleness_days)
    stale_page_ids: list[str] = []
    for page in pages:
        version_id = page.get("current_version_id")
        if not version_id:
            continue
        created_at_raw = created_at_by_version.get(str(version_id))
        if not created_at_raw:
            continue
        created_at = datetime.fromisoformat(str(created_at_raw).replace("Z", "+00:00"))
        if created_at < threshold:
            stale_page_ids.append(str(page["id"]))
    return stale_page_ids


def archive_wiki_page(page_id: str, *, supabase: Client | None = None) -> None:
    db = supabase or get_supabase()
    db.table("wiki_pages").update({"status": "archived"}).eq("id", page_id).execute()


def get_wiki_page_identity(page_id: str, *, supabase: Client | None = None) -> WikiPageIdentity | None:
    """기존 페이지 갱신 시 create_wiki_version() 내부의 upsert_wiki_page() 재실행이
    같은 slug/title/page_type/parent_page_id로 멱등하게 맞아떨어지도록 조회한다."""
    db = supabase or get_supabase()
    rows = (
        db.table("wiki_pages")
        .select("id, slug, title, page_type, parent_page_id")
        .eq("id", page_id)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        return None
    row = rows[0]
    return WikiPageIdentity(
        page_id=str(row["id"]),
        slug=row["slug"],
        title=row["title"],
        page_type=row["page_type"],
        parent_page_id=str(row["parent_page_id"]) if row.get("parent_page_id") else None,
    )

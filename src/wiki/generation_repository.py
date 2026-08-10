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


def filter_to_topic_page_ids(
    page_ids: list[str],
    *,
    workspace_id: str,
    supabase: Client | None = None,
) -> set[str]:
    """주어진 page_id 중 주제 페이지(industry/company/technology/term)인 것만 남긴다.

    자동 발행된 이슈 페이지(page_type='issue')가 다음 회차 주제 페이지 후보로 다시
    올라오는 자기 피드백 루프를 막기 위한 필터다.
    """
    unique_ids = [page_id for page_id in dict.fromkeys(page_ids) if page_id]
    if not unique_ids:
        return set()
    db = supabase or get_supabase()
    rows = (
        db.table("wiki_pages")
        .select("id, page_type")
        .eq("workspace_id", workspace_id)
        .in_("id", unique_ids)
        .in_("page_type", list(TOP_LEVEL_TOPIC_PAGE_TYPES))
        .execute()
        .data
    )
    return {str(row["id"]) for row in rows}


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

    # 아직 살아있는(archived가 아닌) 자식 페이지가 가리키는 부모는 아카이빙하지 않는다.
    # (un-archive 흐름이 없으므로 계층이 끊기면 되돌릴 수 없다.)
    active_parent_page_ids = _find_active_parent_page_ids(workspace_id, supabase=db)

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
        if created_at >= threshold:
            continue
        if str(page["id"]) in active_parent_page_ids:
            continue
        stale_page_ids.append(str(page["id"]))
    return stale_page_ids


def _find_active_parent_page_ids(workspace_id: str, *, supabase: Client) -> set[str]:
    """archived가 아닌 페이지가 parent_page_id로 참조하고 있는 page_id 집합."""
    rows = (
        supabase.table("wiki_pages")
        .select("parent_page_id, status")
        .eq("workspace_id", workspace_id)
        .execute()
        .data
    )
    return {
        str(row["parent_page_id"])
        for row in rows
        if row.get("parent_page_id") and row.get("status") != "archived"
    }


def archive_wiki_page(page_id: str, *, supabase: Client | None = None) -> None:
    db = supabase or get_supabase()
    db.table("wiki_pages").update({"status": "archived"}).eq("id", page_id).execute()


def get_wiki_page_identity(
    page_id: str,
    *,
    workspace_id: str,
    supabase: Client | None = None,
) -> WikiPageIdentity | None:
    """기존 페이지 갱신 시 create_wiki_version() 내부의 upsert_wiki_page() 재실행이
    같은 slug/title/page_type/parent_page_id로 멱등하게 맞아떨어지도록 조회한다.

    다른 workspace의 페이지이거나 주제 페이지가 아니면(예: page_type='issue')
    "찾지 못함"과 동일하게 None을 반환한다.
    """
    db = supabase or get_supabase()
    rows = (
        db.table("wiki_pages")
        .select("id, slug, title, page_type, parent_page_id")
        .eq("id", page_id)
        .eq("workspace_id", workspace_id)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        return None
    row = rows[0]
    if row.get("page_type") not in TOP_LEVEL_TOPIC_PAGE_TYPES:
        return None
    return WikiPageIdentity(
        page_id=str(row["id"]),
        slug=row["slug"],
        title=row["title"],
        page_type=row["page_type"],
        parent_page_id=str(row["parent_page_id"]) if row.get("parent_page_id") else None,
    )


def find_matching_issue_page(
    workspace_id: str,
    *,
    category: str,
    document_version_ids: list[str],
    within_days: int = 7,
    supabase: Client | None = None,
) -> WikiPageIdentity | None:
    """같은 사건이 여러 주기에 걸쳐 보도될 때 매번 새 이슈 페이지가 생기는 걸 막는다.
    최근 within_days 이내 발행된 issue 타입 페이지 중, 카테고리가 같고 이번 근거 문서와
    과반수 이상 겹치는 게 있으면 그 페이지를 반환한다.

    1차 필터로 이번 이슈 근거 문서와 겹치는 wiki_page_sources부터 좁혀서 시작한다 —
    이슈 페이지 전체를 항상 스캔하면 페이지 수가 늘어날수록(90일 아카이빙 전까지 계속
    누적) in_() 쿼리 URL이 무한정 커지고 결국 414/응답 잘림으로 이어진다.
    """
    if not document_version_ids:
        return None

    db = supabase or get_supabase()

    overlap_source_rows = (
        db.table("wiki_page_sources")
        .select("wiki_version_id, document_version_id")
        .in_("document_version_id", document_version_ids)
        .execute()
        .data
    )
    if not overlap_source_rows:
        return None
    overlap_version_ids = list({str(row["wiki_version_id"]) for row in overlap_source_rows})

    versions = (
        db.table("wiki_page_versions")
        .select("id, page_id, created_at")
        .in_("id", overlap_version_ids)
        .execute()
        .data
    )
    threshold = datetime.now(timezone.utc) - timedelta(days=within_days)
    recent_version_by_id: dict[str, dict] = {}
    for row in versions:
        created_at_raw = row.get("created_at")
        if not created_at_raw:
            continue
        created_at = datetime.fromisoformat(str(created_at_raw).replace("Z", "+00:00"))
        if created_at >= threshold:
            recent_version_by_id[str(row["id"])] = {**row, "created_at": created_at}
    if not recent_version_by_id:
        return None

    candidate_page_ids = list({str(row["page_id"]) for row in recent_version_by_id.values()})
    pages = (
        db.table("wiki_pages")
        .select("id, slug, title, page_type, parent_page_id, current_version_id")
        .eq("workspace_id", workspace_id)
        .eq("page_type", "issue")
        .eq("status", "published")
        .in_("id", candidate_page_ids)
        .execute()
        .data
    )
    candidate_pages = [
        p for p in pages
        if p.get("current_version_id") and str(p["current_version_id"]) in recent_version_by_id
    ]
    if not candidate_pages:
        return None

    candidate_version_ids = list({str(p["current_version_id"]) for p in candidate_pages})
    full_source_rows = (
        db.table("wiki_page_sources")
        .select("wiki_version_id, document_version_id")
        .in_("wiki_version_id", candidate_version_ids)
        .execute()
        .data
    )
    docs_by_version: dict[str, set[str]] = {}
    for row in full_source_rows:
        document_version_id = row["document_version_id"]
        if document_version_id is None:
            continue
        docs_by_version.setdefault(str(row["wiki_version_id"]), set()).add(document_version_id)

    all_candidate_doc_ids = list({did for docs in docs_by_version.values() for did in docs})
    if not all_candidate_doc_ids:
        return None
    analysis_rows = (
        db.table("document_analysis_results")
        .select("document_version_id, primary_category")
        .eq("workspace_id", workspace_id)
        .in_("document_version_id", all_candidate_doc_ids)
        .execute()
        .data
    )
    categories_by_doc: dict[str, set[str]] = {}
    for row in analysis_rows:
        primary_category = row.get("primary_category")
        if not primary_category:
            continue
        categories_by_doc.setdefault(row["document_version_id"], set()).add(primary_category)

    new_doc_ids = set(document_version_ids)
    best_page: dict | None = None
    best_ratio = -1.0
    best_created_at: datetime | None = None
    for page in candidate_pages:
        version_id = str(page["current_version_id"])
        candidate_docs = docs_by_version.get(version_id, set())
        if not candidate_docs:
            continue
        has_matching_category = any(
            category in categories_by_doc.get(did, ()) for did in candidate_docs
        )
        if not has_matching_category:
            continue
        overlap = len(candidate_docs & new_doc_ids)
        ratio = overlap / len(new_doc_ids)
        if ratio < 0.5:
            continue
        created_at = recent_version_by_id[version_id]["created_at"]
        if ratio > best_ratio or (ratio == best_ratio and (best_created_at is None or created_at > best_created_at)):
            best_page = page
            best_ratio = ratio
            best_created_at = created_at

    if best_page is None:
        return None

    return WikiPageIdentity(
        page_id=str(best_page["id"]),
        slug=best_page["slug"],
        title=best_page["title"],
        page_type=best_page["page_type"],
        parent_page_id=str(best_page["parent_page_id"]) if best_page.get("parent_page_id") else None,
    )

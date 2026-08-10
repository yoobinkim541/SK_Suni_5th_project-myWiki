"""
Wiki command 구현 — upsert·생성·검증·검수·게시·색인.

규칙:
  current_version_id 변경은 publish_wiki_version() 에서만 허용한다.
  create_wiki_version() 은 validation_status='pending', review_status='pending' 으로만 삽입한다.

SERVICE_ROLE_KEY 를 사용하며, 모든 쿼리에 workspace_id 필터를 명시한다.
"""
from __future__ import annotations

import datetime
import hashlib
from typing import Optional

from supabase import Client

from .query import WIKI_BUCKET, _get_client
from .interface import PageType, WikiDraftInput, WikiSourceInput


def upsert_wiki_page(
    workspace_id: str,
    slug: str,
    title: str,
    page_type: PageType,
    parent_page_id: Optional[str] = None,
    *,
    supabase: Client | None = None,
) -> str:
    db = supabase or _get_client()
    data = {
        "workspace_id": workspace_id,
        "slug": slug,
        "title": title,
        "page_type": page_type,
        "status": "draft",
        "review_policy": "review",
    }
    if parent_page_id is not None:
        data["parent_page_id"] = parent_page_id
    res = (
        db.table("wiki_pages")
        .upsert(data, on_conflict="workspace_id,slug", ignore_duplicates=True)
        .execute()
    )
    if res.data:
        return res.data[0]["id"]
    existing = (
        db.table("wiki_pages")
        .select("id")
        .eq("workspace_id", workspace_id)
        .eq("slug", slug)
        .single()
        .execute()
    )
    return existing.data["id"]


def update_wiki_page_title(page_id: str, title: str, *, supabase: Client | None = None) -> None:
    """이미 있는 페이지의 title을 덮어쓴다.

    upsert_wiki_page()는 ignore_duplicates=True라 기존 페이지의 title을 절대 안
    바꾼다(리포트 파이프라인의 이슈/토픽 페이지는 회차마다 같은 slug로 계속 갱신되므로
    의도된 동작). 하지만 챗봇 "위키에 저장"은 매번 새 LLM 제목을 만드는데, 같은
    메시지를 재저장하거나 소급 정리 배치가 본문만 다시 쓰면 사이드바에 보이는
    페이지 제목이 최초 저장 시점 값에 영구히 고정돼버린다 — 그래서 챗봇 저장 경로는
    upsert_wiki_page 뒤에 이 함수로 title을 명시적으로 맞춰준다.
    """
    db = supabase or _get_client()
    db.table("wiki_pages").update({"title": title}).eq("id", page_id).execute()


def create_wiki_version(draft: WikiDraftInput, *, supabase: Client | None = None) -> str:
    db = supabase or _get_client()

    page_id = upsert_wiki_page(
        draft.workspace_id,
        draft.slug,
        draft.title,
        draft.page_type,
        draft.parent_page_id,
        supabase=db,
    )

    ver_res = (
        db.table("wiki_page_versions")
        .select("version_no")
        .eq("page_id", page_id)
        .order("version_no", desc=True)
        .limit(1)
        .execute()
    )
    if ver_res.data:
        version_no = ver_res.data[0]["version_no"] + 1
    else:
        version_no = 1

    object_key = f"{draft.workspace_id}/{page_id}/{version_no}.md"

    db.storage.from_(WIKI_BUCKET).upload(
        object_key,
        draft.markdown.encode("utf-8"),
        {"content-type": "text/markdown"},
    )

    content_hash = hashlib.sha256(draft.markdown.encode()).hexdigest()[:64]
    insert_data = {
        "page_id": page_id,
        "version_no": version_no,
        "markdown_object_key": object_key,
        "content_hash": content_hash,
        "validation_status": "pending",
        "review_status": "pending",
        "generated_by": draft.generated_by,
    }
    if draft.change_summary is not None:
        insert_data["change_summary"] = draft.change_summary
    if draft.created_by is not None:
        insert_data["created_by"] = draft.created_by
    if draft.generator_model is not None:
        insert_data["generator_model"] = draft.generator_model
    if draft.generator_prompt_version is not None:
        insert_data["generator_prompt_version"] = draft.generator_prompt_version
    if draft.generation_run_id is not None:
        insert_data["generation_run_id"] = draft.generation_run_id

    version_res = (
        db.table("wiki_page_versions")
        .insert(insert_data)
        .execute()
    )
    version_id = version_res.data[0]["id"]

    sources_data = _build_source_rows(version_id, draft.sources)
    if sources_data:
        db.table("wiki_page_sources").insert(sources_data).execute()

    return version_id


def _build_source_rows(version_id: str, sources: list[WikiSourceInput]) -> list[dict[str, object]]:
    """Collapse to one row per source identity so the same source never renders
    twice in the "근거 문서" list — even when several distinct claims (e.g. from a
    wiki dedup-merge that carries claims over from two source pages) cite the same
    document. Distinct claim texts are merged into the row instead of dropped;
    exact-repeat claim texts collapse as before.

    document_version_id가 없는(웹검색 근거) 소스는 전부 None이 같은 값이라, 그것만
    묶음 키로 쓰면 서로 다른 웹 출처가 한 행으로 뭉개진다 — document_version_id가
    있으면 그걸, 없으면 source_url을 묶음 키로 쓴다.
    """

    rows_by_key: dict[str, dict[str, object]] = {}
    claim_texts_by_key: dict[str, set[str]] = {}
    order: list[str] = []

    for source in sources:
        key = source.document_version_id or f"web:{source.source_url}"
        if key not in rows_by_key:
            order.append(key)
            rows_by_key[key] = {
                "wiki_version_id": version_id,
                "document_version_id": source.document_version_id,
                "source_url": source.source_url,
                "source_title": source.source_title,
                "published_at": source.published_at,
                "claim_text": source.claim_text,
                "support_type": source.support_type,
                "source_start_line": source.source_start_line,
                "source_end_line": source.source_end_line,
                "citation_order": source.citation_order,
            }
            claim_texts_by_key[key] = {source.claim_text}
            continue

        seen_claims = claim_texts_by_key[key]
        if source.claim_text and source.claim_text not in seen_claims:
            seen_claims.add(source.claim_text)
            row = rows_by_key[key]
            row["claim_text"] = f"{row['claim_text']} / {source.claim_text}" if row["claim_text"] else source.claim_text
        if rows_by_key[key]["citation_order"] is None and source.citation_order is not None:
            rows_by_key[key]["citation_order"] = source.citation_order

    rows = [rows_by_key[key] for key in order]
    for index, row in enumerate(rows):
        if row["citation_order"] is None:
            row["citation_order"] = index + 1
    return rows


def record_wiki_validation(
    version_id: str,
    validation_status: str,
    confidence_score: Optional[float],
    *,
    supabase: Client | None = None,
) -> None:
    db = supabase or _get_client()
    db.table("wiki_page_versions").update(
        {"validation_status": validation_status, "confidence_score": confidence_score}
    ).eq("id", version_id).execute()


def review_wiki_version(
    version_id: str,
    reviewer_id: Optional[str],
    decision: str,
    *,
    supabase: Client | None = None,
) -> None:
    db = supabase or _get_client()
    db.table("wiki_page_versions").update(
        {
            "review_status": decision,
            "reviewed_by": reviewer_id,
            "reviewed_at": datetime.datetime.utcnow().isoformat() + "Z",
        }
    ).eq("id", version_id).execute()


def publish_wiki_version(page_id: str, version_id: str, *, supabase: Client | None = None) -> None:
    db = supabase or _get_client()
    ver = db.table("wiki_page_versions").select("validation_status,review_status").eq("id", version_id).single().execute()
    if ver.data["validation_status"] != "passed" or ver.data["review_status"] != "approved":
        raise ValueError(
            f"게시 조건 미충족: validation={ver.data['validation_status']}, review={ver.data['review_status']}"
        )
    page = db.table("wiki_pages").select("workspace_id").eq("id", page_id).single().execute()
    workspace_id = page.data["workspace_id"]
    db.table("wiki_pages").update(
        {
            "current_version_id": version_id,
            "published_at": datetime.datetime.utcnow().isoformat() + "Z",
            "status": "published",
        }
    ).eq("id", page_id).eq("workspace_id", workspace_id).execute()


def request_wiki_index(
    wiki_version_id: str,
    collection_name: str,
    requested_by: Optional[str] = None,
) -> str:
    db = _get_client()

    ver = db.table("wiki_page_versions").select("page_id").eq("id", wiki_version_id).single().execute()
    page_id = ver.data["page_id"]

    page = db.table("wiki_pages").select("workspace_id").eq("id", page_id).single().execute()
    workspace_id = page.data["workspace_id"]

    entry_res = db.table("qmd_index_entries").insert(
        {
            "wiki_version_id": wiki_version_id,
            "collection_name": collection_name,
            "status": "pending",
            "index_generation": 1,
        }
    ).execute()
    entry_id = entry_res.data[0]["id"]

    job_data = {
        "workspace_id": workspace_id,
        "job_type": "index_qmd",
        "target_type": "wiki_page",
        "target_id": wiki_version_id,
        "status": "pending",
        "progress": 0,
        "retry_count": 0,
        "payload": {
            "qmd_index_entry_id": entry_id,
            "collection_name": collection_name,
        },
    }
    if requested_by is not None:
        job_data["requested_by"] = requested_by
    job_res = db.table("pipeline_jobs").insert(job_data).execute()

    return job_res.data[0]["id"]

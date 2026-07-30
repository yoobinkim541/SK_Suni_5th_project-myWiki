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


def create_wiki_version(draft: WikiDraftInput) -> str:
    db = _get_client()

    page_id = upsert_wiki_page(
        draft.workspace_id,
        draft.slug,
        draft.title,
        draft.page_type,
        draft.parent_page_id,
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

    if draft.sources:
        sources_data = [
            {
                "wiki_version_id": version_id,
                "document_version_id": s.document_version_id,
                "claim_text": s.claim_text,
                "support_type": s.support_type,
                "source_start_line": s.source_start_line,
                "source_end_line": s.source_end_line,
                "citation_order": s.citation_order if s.citation_order is not None else idx + 1,
            }
            for idx, s in enumerate(draft.sources)
        ]
        db.table("wiki_page_sources").insert(sources_data).execute()

    return version_id


def record_wiki_validation(
    version_id: str,
    validation_status: str,
    confidence_score: Optional[float],
) -> None:
    db = _get_client()
    db.table("wiki_page_versions").update(
        {"validation_status": validation_status, "confidence_score": confidence_score}
    ).eq("id", version_id).execute()


def review_wiki_version(
    version_id: str,
    reviewer_id: str,
    decision: str,
) -> None:
    db = _get_client()
    db.table("wiki_page_versions").update(
        {
            "review_status": decision,
            "reviewed_by": reviewer_id,
            "reviewed_at": datetime.datetime.utcnow().isoformat() + "Z",
        }
    ).eq("id", version_id).execute()


def publish_wiki_version(page_id: str, version_id: str) -> None:
    db = _get_client()
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

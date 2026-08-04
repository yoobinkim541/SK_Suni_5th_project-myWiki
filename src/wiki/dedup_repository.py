from __future__ import annotations

import logging
from itertools import combinations

from supabase import Client

from ..analysis.repository import get_supabase
from .dedup_models import DedupCandidatePair, DedupPageInfo
from .text_similarity import DEFAULT_DUPLICATE_TITLE_THRESHOLD, title_similarity

logger = logging.getLogger(__name__)

DEFAULT_MAX_PAIRS = 20


def find_duplicate_candidate_pairs(
    workspace_id: str,
    *,
    max_pairs: int = DEFAULT_MAX_PAIRS,
    min_shared_source_count: int = 1,
    title_similarity_threshold: float = DEFAULT_DUPLICATE_TITLE_THRESHOLD,
    supabase: Client | None = None,
) -> list[DedupCandidatePair]:
    """공유 근거 문서 OR 제목 유사도, 둘 중 하나라도 걸리면 후보 쌍으로 올린다.

    최종 판단(진짜 중복인지, 병합할지)은 LLM에게 맡긴다 — 여기서는 후보만 좁히고
    점수(공유 근거 수 + 제목 유사도) 내림차순으로 상위 max_pairs개만 반환한다.
    """
    db = supabase or get_supabase()

    pages = (
        db.table("wiki_pages")
        .select("id, slug, title, page_type, parent_page_id, current_version_id")
        .eq("workspace_id", workspace_id)
        .eq("status", "published")
        .execute()
        .data
    )
    pages = [p for p in pages if p.get("current_version_id")]
    if len(pages) < 2:
        return []

    version_ids = list({str(p["current_version_id"]) for p in pages})
    source_rows = (
        db.table("wiki_page_sources")
        .select("wiki_version_id, document_version_id")
        .in_("wiki_version_id", version_ids)
        .execute()
        .data
    )
    docs_by_version: dict[str, set[str]] = {}
    for row in source_rows:
        docs_by_version.setdefault(str(row["wiki_version_id"]), set()).add(row["document_version_id"])

    scored: list[tuple[float, DedupCandidatePair]] = []
    for page_a, page_b in combinations(pages, 2):
        docs_a = docs_by_version.get(str(page_a["current_version_id"]), set())
        docs_b = docs_by_version.get(str(page_b["current_version_id"]), set())
        shared_count = len(docs_a & docs_b)
        similarity = title_similarity(page_a["title"], page_b["title"])
        if shared_count < min_shared_source_count and similarity < title_similarity_threshold:
            continue
        scored.append((
            shared_count + similarity,
            DedupCandidatePair(
                page_a=_to_page_info(page_a),
                page_b=_to_page_info(page_b),
                shared_source_count=shared_count,
                title_similarity=similarity,
            ),
        ))

    scored.sort(key=lambda item: item[0], reverse=True)
    if len(scored) > max_pairs:
        logger.info(
            "wiki_dedup_candidates_capped",
            extra={"workspace_id": workspace_id, "total_candidates": len(scored), "processed": max_pairs},
        )
    return [pair for _, pair in scored[:max_pairs]]


def _to_page_info(row: dict) -> DedupPageInfo:
    return DedupPageInfo(
        page_id=str(row["id"]),
        slug=row["slug"],
        title=row["title"],
        page_type=row["page_type"],
        parent_page_id=str(row["parent_page_id"]) if row.get("parent_page_id") else None,
    )

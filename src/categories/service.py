"""
카테고리 현황 집계 (GET /categories/stats).

src/dashboard/service.py와 같은 구조다 — supabase/now를 주입받아 테스트에서 시각을
고정할 수 있게 하고, PostgREST embedded join 대신 순차 조회 후 파이썬에서 대조한다
(src/wiki/query.py _enrich_sources와 같은 방침).

집계원은 document_analysis_results.primary_category다. 이미 분류가 끝나 있어서
분류 로직을 새로 만들 필요가 없고, 스키마도 건드리지 않는다.
"""
from __future__ import annotations

import collections
from datetime import datetime, timedelta, timezone

from supabase import Client

from ..analysis.repository import get_supabase
from ..dashboard.service import (
    RELIABILITY_LOW_THRESHOLD,
    RELIABILITY_MEDIUM_THRESHOLD,
    WINDOW_DAYS,
)
from ..pipeline_common.titles import normalize_title
from .keywords import CATEGORY_ORDER, CATEGORY_SLUGS, extract_tags
from .models import CategoryLevel, CategoryStat, CategoryStats

# 카드에 말줄임 처리가 없어서(globals.css .top-issue) 긴 제목이 오면 카드가 세로로
# 늘어나고 같은 행 카드까지 같이 늘어난다. 백엔드에서 잘라 보낸다.
TOP_ISSUE_MAX_LEN = 80

# 조회 상한. 워크스페이스 하나에 7일치라 현재는 수백 건 규모지만, 무한정 긁지 않는다.
_FETCH_LIMIT = 5000


def _level(avg_score: float | None) -> CategoryLevel:
    """reliability_score 평균 -> 카드가 아는 소문자 3종.

    임계값은 대시보드(dashboard/service.py)와 같은 값을 재사용한다. 두 화면이
    다른 기준으로 '보통'을 말하면 안 된다.

    점수가 하나도 없으면 'low'로 내린다 — 근거 없이 높게 보이는 쪽이 더 위험하다.
    """
    if avg_score is None:
        return "low"
    if avg_score < RELIABILITY_LOW_THRESHOLD:
        return "low"
    if avg_score < RELIABILITY_MEDIUM_THRESHOLD:
        return "mid"
    return "high"


def _display_title(text: str) -> str:
    """화면에 내보낼 제목 — 매체명 꼬리표를 벗기고 길이를 자른다.

    preprocess가 documents.title을 교정하지만(pipeline_common.titles), 그건 그 수정이
    들어간 뒤 정제된 문서부터다. 그 전에 수집된 문서는 DB에 '기사제목 - 매체명'이
    그대로 남아 있어서 표시 시점에도 한 번 더 벗긴다. 멱등이라 두 번 걸어도 안전하다.
    """
    text = normalize_title(text or "")
    if len(text) <= TOP_ISSUE_MAX_LEN:
        return text
    return text[: TOP_ISSUE_MAX_LEN - 1].rstrip() + "…"


def _titles_by_version(db: Client, workspace_id: str, version_ids: list[str]) -> dict[str, str]:
    """document_version_id -> documents.title.

    document_versions에는 workspace_id 컬럼이 없다. 그래서 documents 조회에
    workspace_id를 반드시 직접 건다 — 여기가 격리가 성립하는 유일한 지점이다.
    """
    if not version_ids:
        return {}

    versions = (
        db.table("document_versions")
        .select("id, document_id")
        .in_("id", version_ids)
        .execute()
        .data
    )
    document_ids = [str(v["document_id"]) for v in versions if v.get("document_id")]
    if not document_ids:
        return {}

    documents = (
        db.table("documents")
        .select("id, title")
        .eq("workspace_id", workspace_id)
        .in_("id", document_ids)
        .execute()
        .data
    )
    title_by_document = {str(d["id"]): (d.get("title") or "") for d in documents}

    # 다른 workspace의 문서는 위 조회에서 빠지므로 여기서 자연히 제외된다.
    return {
        str(v["id"]): title_by_document[str(v["document_id"])]
        for v in versions
        if str(v.get("document_id")) in title_by_document
    }


def get_category_stats(
    workspace_id: str,
    *,
    supabase: Client | None = None,
    now: datetime | None = None,
) -> CategoryStats:
    """최근 7일 분석분을 primary_category로 묶어 카드 6장을 만든다.

    필드별 산출
        count      해당 카테고리 문서 수
        top_issue  importance_score 최상위 문서의 제목. 점수가 없으면 최신 문서
        tags       제목에서 카테고리 키워드를 빈도순 3개
        level      reliability_score 평균을 대시보드와 같은 임계값으로 변환

    분류가 안 된 행(primary_category=None)은 어느 카드에도 넣지 않는다.
    분석 결과가 하나도 없는 카테고리도 카드는 만든다 — 화면이 6장 그리드를
    전제로 하고, 빈 자리가 생기면 오히려 오해를 부른다.
    """
    db = supabase or get_supabase()
    now = now or datetime.now(timezone.utc)
    window_start = (now - timedelta(days=WINDOW_DAYS)).isoformat()

    rows = (
        db.table("document_analysis_results")
        .select("primary_category, reliability_score, importance_score, document_version_id, created_at")
        .eq("workspace_id", workspace_id)
        .gte("created_at", window_start)
        .limit(_FETCH_LIMIT)
        .execute()
        .data
    )

    grouped: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        category = row.get("primary_category")
        if category in CATEGORY_SLUGS:
            grouped[category].append(row)

    version_ids = [
        str(row["document_version_id"])
        for group in grouped.values()
        for row in group
        if row.get("document_version_id")
    ]
    titles = _titles_by_version(db, workspace_id, version_ids)

    categories: list[CategoryStat] = []
    total = 0
    for name in CATEGORY_ORDER:
        group = grouped.get(name, [])
        total += len(group)

        scores = [r["reliability_score"] for r in group if r.get("reliability_score") is not None]
        avg = sum(scores) / len(scores) if scores else None

        group_titles = [
            titles[str(r["document_version_id"])]
            for r in group
            if str(r.get("document_version_id")) in titles
        ]

        categories.append(
            CategoryStat(
                id=CATEGORY_SLUGS[name],
                name=name,
                count=len(group),
                top_issue=_display_title(_pick_top_issue(group, titles)),
                tags=extract_tags(group_titles, name),
                level=_level(avg),
            )
        )

    return CategoryStats(total_documents=total, categories=categories)


def _pick_top_issue(group: list[dict], titles: dict[str, str]) -> str:
    """importance_score가 가장 높은 문서의 제목. 점수가 없으면 가장 최근 문서.

    importance_score는 분석 4단계 중 뒷단계라 결손이 크다(2026-08-05 기준 26%).
    그래서 점수 없는 행도 후보에서 빼지 않고, 정렬 키를 (점수 유무, 점수, 시각)으로
    둬서 점수가 있는 쪽이 먼저 오되 없으면 최신순으로 떨어지게 한다.
    """
    candidates = [r for r in group if str(r.get("document_version_id")) in titles]
    if not candidates:
        return ""

    def sort_key(row: dict) -> tuple:
        score = row.get("importance_score")
        return (score is not None, score or 0, str(row.get("created_at") or ""))

    best = max(candidates, key=sort_key)
    return titles[str(best["document_version_id"])]

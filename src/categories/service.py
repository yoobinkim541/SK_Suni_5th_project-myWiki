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
from .documents import (
    _IN_CLAUSE_CHUNK_SIZE,
    QUOTE_MAX_LEN,
    TOP_ISSUE_MAX_LEN,
    display_title,
    documents_by_version,
    quote_for,
    source_label,
    sources_by_id,
    unique_documents,
)
from .keywords import (
    CATEGORY_ORDER,
    CATEGORY_SLUGS,
    MAX_PIE_KEYWORDS,
    collection_keyword,
    extract_tags,
)
from .models import (
    CategoryDocument,
    CategoryKeyword,
    CategoryLevel,
    CategoryStat,
    CategoryStats,
)

# 위 세 값은 documents.py로 옮겼지만 여기서도 이름을 유지한다. 기존 테스트가
# service.QUOTE_MAX_LEN·service._IN_CLAUSE_CHUNK_SIZE로 참조하고, 앞의 둘은
# 카테고리 화면의 계약이다. 청크 상수 이름은 #156에서 다른 모듈과 맞춘 것이라 그대로 둔다.
__all__ = ["get_category_stats", "TOP_ISSUE_MAX_LEN", "QUOTE_MAX_LEN"]

# 모달 목록은 CSS(#catNewsRows)에 max-height + overflow-y가 걸려 있어 스크롤된다.
# 그 안에서 분류별 흐름이 읽히는 분량으로 잡았다. 6분류 × 10 = 60건이라 응답도 가볍다.
MAX_RECENT_DOCUMENTS = 10

# 조회 상한. 워크스페이스 하나에 7일치라 현재는 수백 건 규모지만, 무한정 긁지 않는다.
_FETCH_LIMIT = 5000
_PAGE_SIZE = 1000


def _fetch_analysis_rows(db: Client, workspace_id: str, window_start: str) -> list[dict]:
    """Fetch every recent analysis row instead of trusting PostgREST's 1,000 row cap."""
    rows: list[dict] = []
    offset = 0
    while offset < _FETCH_LIMIT:
        page = (
            db.table("document_analysis_results")
            .select(
                "primary_category, reliability_status, reliability_score, importance_score, "
                "document_version_id, created_at, reliability_evaluated_at, core_summary, "
                "summary_evidence_refs"
            )
            .eq("workspace_id", workspace_id)
            .gte("created_at", window_start)
            .order("id")
            .range(offset, min(offset + _PAGE_SIZE - 1, _FETCH_LIMIT - 1))
            .execute()
            .data
        )
        rows.extend(page)
        if len(page) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
    return rows


def _level(avg_score: float | None) -> CategoryLevel:
    """Map average reliability to the Category page display badge.

    Category status should reflect the actual reliability score bucket rather than
    hiding low values. Score calibration belongs in the reliability evaluator.
    """
    if avg_score is None:
        return "low"
    if avg_score < RELIABILITY_LOW_THRESHOLD:
        return "low"
    if avg_score < RELIABILITY_MEDIUM_THRESHOLD:
        return "mid"
    return "high"


def _keyword_counts(
    unique: dict[str, dict], sources: dict[str, dict]
) -> list[CategoryKeyword]:
    """카테고리 안에서 어떤 수집 키워드가 문서를 끌어왔는지 센다."""
    counter = collections.Counter(
        collection_keyword(sources.get(str(entry["document"].get("source_id") or "")))
        for entry in unique.values()
    )
    return [
        CategoryKeyword(word=word, count=count)
        for word, count in counter.most_common(MAX_PIE_KEYWORDS)
    ]


def _recent_documents(unique: dict[str, dict]) -> list[CategoryDocument]:
    """발행일 내림차순 상위 N건.

    quote는 25%만 채워져 있고(2026-08-05 실측) 그마저도 오래된 문서에 몰려 있다 —
    분석이 하루쯤 뒤처져서 최신 문서에는 인용문이 아직 없다. 최신순을 유지하는
    대신 quote는 대체로 빈칸이 되고, P1(스케줄러 timeout)이 풀리면 채워진다.
    """
    picked = sorted(
        unique.values(),
        key=lambda entry: str(entry["document"].get("published_at") or ""),
        reverse=True,
    )[:MAX_RECENT_DOCUMENTS]

    return [
        CategoryDocument(
            title=display_title(entry["document"].get("title") or ""),
            quote=quote_for(entry["row"]),
            source_label=source_label(entry["document"].get("canonical_url")),
            source_url=entry["document"].get("canonical_url") or "",
            published_at=entry["document"].get("published_at"),
        )
        for entry in picked
    ]


def _latest_reliability_scores_by_document(
    group: list[dict],
    documents: dict[str, dict],
) -> list[int | float]:
    """Return one latest completed reliability score per visible source document."""
    latest: dict[str, dict] = {}
    for row in group:
        if row.get("reliability_status") != "completed":
            continue
        if row.get("reliability_score") is None:
            continue
        document = documents.get(str(row.get("document_version_id")))
        if document is None:
            continue
        document_id = str(document["id"])
        current = latest.get(document_id)
        if current is None or _reliability_sort_key(row) > _reliability_sort_key(current):
            latest[document_id] = row
    return [row["reliability_score"] for row in latest.values()]


def _reliability_sort_key(row: dict) -> tuple[str, str]:
    return (
        str(row.get("reliability_evaluated_at") or ""),
        str(row.get("created_at") or ""),
    )


def get_category_stats(
    workspace_id: str,
    *,
    supabase: Client | None = None,
    now: datetime | None = None,
) -> CategoryStats:
    """최근 7일 분석분을 primary_category로 묶어 카드 6장을 만든다.

    필드별 산출
        count             해당 카테고리 문서 수 (원그래프 왼쪽도 이 값을 쓴다)
        top_issue         importance_score 최상위 문서의 제목. 점수가 없으면 최신 문서
        tags              제목에서 카테고리 키워드를 빈도순 3개
        level             reliability_score 평균을 대시보드와 같은 임계값으로 변환
        keywords          원그래프 오른쪽 — 문서를 끌어온 수집 키워드별 건수 상위 8개
        recent_documents  관련 뉴스 모달 — 문서 단위 중복 제거 후 발행일 내림차순 5건

    분류가 안 된 행(primary_category=None)은 어느 카드에도 넣지 않는다.
    분석 결과가 하나도 없는 카테고리도 카드는 만든다 — 화면이 6장 그리드를
    전제로 하고, 빈 자리가 생기면 오히려 오해를 부른다.
    """
    db = supabase or get_supabase()
    now = now or datetime.now(timezone.utc)
    window_start = (now - timedelta(days=WINDOW_DAYS)).isoformat()

    rows = _fetch_analysis_rows(db, workspace_id, window_start)

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
    documents = documents_by_version(db, workspace_id, version_ids)
    titles = {vid: (doc.get("title") or "") for vid, doc in documents.items()}
    sources = sources_by_id(db, workspace_id)

    categories: list[CategoryStat] = []
    total = 0
    for name in CATEGORY_ORDER:
        group = grouped.get(name, [])
        # 건수는 분석 행이 아니라 문서 단위로 센다. 재수집으로 버전이 늘어난 문서를
        # 두 번 세면 카드 숫자가 실제 기사 수보다 부푼다.
        unique = unique_documents(group, documents)
        total += len(unique)

        scores = _latest_reliability_scores_by_document(group, documents)
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
                count=len(unique),
                top_issue=display_title(_pick_top_issue(group, titles)),
                # 카드 태그는 내용 기반(제목에서 사전 매칭), 원그래프는 수집 경로 기반이다.
                # 둘은 다른 것을 보여주므로 값이 달라도 어긋난 게 아니다.
                tags=extract_tags(group_titles, name),
                level=_level(avg),
                keywords=_keyword_counts(unique, sources),
                recent_documents=_recent_documents(unique),
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

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
from urllib.parse import urlparse

from supabase import Client

from ..analysis.repository import get_supabase
from ..dashboard.service import (
    RELIABILITY_LOW_THRESHOLD,
    RELIABILITY_MEDIUM_THRESHOLD,
    WINDOW_DAYS,
)
from ..pipeline_common.titles import normalize_title
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

# 카드에 말줄임 처리가 없어서(globals.css .top-issue) 긴 제목이 오면 카드가 세로로
# 늘어나고 같은 행 카드까지 같이 늘어난다. 백엔드에서 잘라 보낸다.
TOP_ISSUE_MAX_LEN = 80

# 모달 카드가 길어지지 않게 자른다. quoted_text는 최대 500자까지 올 수 있다.
QUOTE_MAX_LEN = 200

# 모달 목록은 CSS(#catNewsRows)에 max-height + overflow-y가 걸려 있어 스크롤된다.
# 그 안에서 분류별 흐름이 읽히는 분량으로 잡았다. 6분류 × 10 = 60건이라 응답도 가볍다.
MAX_RECENT_DOCUMENTS = 10

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


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _display_title(text: str) -> str:
    """화면에 내보낼 제목 — 매체명 꼬리표를 벗기고 길이를 자른다.

    preprocess가 documents.title을 교정하지만(pipeline_common.titles), 그건 그 수정이
    들어간 뒤 정제된 문서부터다. 그 전에 수집된 문서는 DB에 '기사제목 - 매체명'이
    그대로 남아 있어서 표시 시점에도 한 번 더 벗긴다. 멱등이라 두 번 걸어도 안전하다.
    """
    return _truncate(normalize_title(text or ""), TOP_ISSUE_MAX_LEN)


def _documents_by_version(
    db: Client, workspace_id: str, version_ids: list[str]
) -> dict[str, dict]:
    """document_version_id -> documents 행(document_id/title/canonical_url/published_at).

    document_versions에는 workspace_id 컬럼이 없다. 그래서 documents 조회에
    workspace_id를 반드시 직접 건다 — 여기가 격리가 성립하는 유일한 지점이다.

    sources는 조인하지 않는다. 관련 뉴스의 출처는 sources.name('Google RSS - SK하이닉스'
    같은 수집 설정 이름)이 아니라 canonical_url의 도메인을 쓰기 때문이다.
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
        .select("id, title, canonical_url, published_at, source_id")
        .eq("workspace_id", workspace_id)
        .in_("id", document_ids)
        .execute()
        .data
    )
    by_document = {str(d["id"]): d for d in documents}

    # 다른 workspace의 문서는 위 조회에서 빠지므로 여기서 자연히 제외된다.
    return {
        str(v["id"]): by_document[str(v["document_id"])]
        for v in versions
        if str(v.get("document_id")) in by_document
    }


def _sources_by_id(db: Client, workspace_id: str) -> dict[str, dict]:
    """수집 소스 전체. 워크스페이스당 10여 개라 통째로 받아 파이썬에서 대조한다."""
    rows = (
        db.table("sources")
        .select("id, name, source_type, config, base_url")
        .eq("workspace_id", workspace_id)
        .execute()
        .data
    )
    return {str(r["id"]): r for r in rows}


def _unique_documents(group: list[dict], documents: dict[str, dict]) -> dict[str, dict]:
    """그룹을 문서 단위로 접는다 — document_id -> 그 문서의 최신 분석 행.

    분석 행과 문서는 1:1이 아니다. 재수집으로 버전이 늘면 같은 문서에 분석 행이
    여러 개 생긴다(2026-08-05 실측 459행 -> 고유 275문서). 이걸 안 접으면 카드의
    건수가 실제 기사 수보다 부풀고, 원그래프 조각 합과도 어긋난다.

    한 문서에서는 created_at이 가장 최근인 행을 남긴다 — 인용문이 최신 버전
    기준이 되게 하기 위해서다.
    """
    latest: dict[str, dict] = {}
    for row in group:
        document = documents.get(str(row.get("document_version_id")))
        if document is None:
            continue
        key = str(document["id"])
        current = latest.get(key)
        if current is None or str(row.get("created_at") or "") > str(
            current["row"].get("created_at") or ""
        ):
            latest[key] = {"row": row, "document": document}
    return latest


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


def _source_label(canonical_url: str | None) -> str:
    """canonical_url -> 표시용 출처. 'www.'만 떼고 도메인을 그대로 쓴다.

    sources.name을 쓰지 않는 이유: 그건 'Google RSS - SK하이닉스' 같은 우리 수집
    설정 이름이라 사용자에게 "출처: Google RSS"로 보인다. 도메인이 실제 매체에 가깝다.
    다만 v.daum.net 같은 중계 사이트는 그대로 노출된다 — 도메인->매체명 사전이
    있어야 해결되는데 관측된 도메인이 120종이라 이번 범위 밖이다.
    """
    host = urlparse(canonical_url or "").netloc
    return host[4:] if host.startswith("www.") else host


def _quote(row: dict) -> str:
    """모달에 보여줄 인용문. quoted_text -> core_summary -> 빈 문자열.

    summary_evidence_refs[].quoted_text는 기사 원문에서 그대로 뽑은 인용이라
    합성 요약인 core_summary보다 "인용문"에 맞는다. 둘 다 importance 단계 산출물이라
    커버리지가 25% 수준이다(2026-08-05 기준) — 없으면 빈 문자열을 주고, 모달은
    빈 <p>만 남아 깨지지 않는다.
    """
    refs = row.get("summary_evidence_refs") or []
    if isinstance(refs, list):
        for ref in refs:
            if isinstance(ref, dict) and (ref.get("quoted_text") or "").strip():
                return _truncate(ref["quoted_text"], QUOTE_MAX_LEN)
    return _truncate(row.get("core_summary") or "", QUOTE_MAX_LEN)


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
            title=_display_title(entry["document"].get("title") or ""),
            quote=_quote(entry["row"]),
            source_label=_source_label(entry["document"].get("canonical_url")),
            source_url=entry["document"].get("canonical_url") or "",
            published_at=entry["document"].get("published_at"),
        )
        for entry in picked
    ]


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

    rows = (
        db.table("document_analysis_results")
        .select(
            "primary_category, reliability_score, importance_score, document_version_id, "
            "created_at, core_summary, summary_evidence_refs"
        )
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
    documents = _documents_by_version(db, workspace_id, version_ids)
    titles = {vid: (doc.get("title") or "") for vid, doc in documents.items()}
    sources = _sources_by_id(db, workspace_id)

    categories: list[CategoryStat] = []
    total = 0
    for name in CATEGORY_ORDER:
        group = grouped.get(name, [])
        # 건수는 분석 행이 아니라 문서 단위로 센다. 재수집으로 버전이 늘어난 문서를
        # 두 번 세면 카드 숫자가 실제 기사 수보다 부푼다.
        unique = _unique_documents(group, documents)
        total += len(unique)

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
                count=len(unique),
                top_issue=_display_title(_pick_top_issue(group, titles)),
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

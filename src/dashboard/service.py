from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from supabase import Client

from ..analysis.repository import get_supabase
from ..categories.documents import (
    ANALYSIS_WINDOW_DAYS,
    PREFILTER_MARGIN_DAYS,
    display_title,
    documents_by_version,
    fetch_analysis_rows,
    in_published_window,
    parse_timestamp as _parse_timestamp,
    quote_for,
    source_label,
    truncate,
    unique_documents,
    window_start,
)
from ..categories.keywords import (
    CATEGORY_SLUGS,
    MAX_PIE_KEYWORDS,
    count_keywords,
    extract_tags,
)
from ..report.candidate_provider import get_report_time_range
from ..report.candidate_provider import REPORT_TIMEZONE
from ..report.models import ReportStatus
from .models import (
    DashboardIssue,
    DashboardIssues,
    DashboardKeyword,
    DashboardKeywords,
    DashboardNews,
    DashboardNewsItem,
    DashboardSummary,
    DashboardTrend,
    TrendDay,
)

RELIABILITY_LOW_THRESHOLD = 40
RELIABILITY_MEDIUM_THRESHOLD = 70

# 창 길이는 categories/documents.py가 단일 출처다 — 카테고리 현황과 대시보드가
# 같은 값을 봐야 한다. 이름은 유지한다(기존 import와 테스트가 이 이름을 참조한다).
WINDOW_DAYS = ANALYSIS_WINDOW_DAYS

# 문서가 "채택됐다"의 기준. 랭킹까지 끝나 보고서 후보로 확정된 상태다.
ADOPTED_RANKING_STATUS = "completed"

# sources.source_type -> 추이 차트의 계열. rss는 구글 뉴스 RSS라 뉴스로 묶는다.
NEWS_SOURCE_TYPES = frozenset({"news", "rss"})
DISCLOSURE_SOURCE_TYPES = frozenset({"disclosure"})
INDUSTRY_DISCLOSURE_TYPE_CODES = frozenset({"B", "I"})
EXCLUDED_DISCLOSURE_TYPE_CODES = frozenset({"D"})

# 최신 뉴스 카드 수. 화면은 기본 4장을 보여주고 '더보기'로 펼친다.
MAX_NEWS_ITEMS = 20

# 분석 행 조회 상한. 워크스페이스 하나에 7일치라 수백 건 규모지만 무한정 긁지 않는다.
# categories/service.py의 _FETCH_LIMIT과 같은 값.
_ANALYSIS_FETCH_LIMIT = 5000

_IN_CLAUSE_CHUNK_SIZE = 150
"""
.in_() 한 번에 넣을 id 개수 상한. id 목록이 수백 개가 되면 전부 한 URL의 .in_(...)에
담을 때 PostgREST가 400 Bad Request로 거부한다.

src/analysis/repository.py, src/pipeline_common/repository.py,
src/categories/service.py의 동일 상수와 같은 값이다. 값이 갈리면 안 되는 이유는
한도가 특정 테이블이 아니라 요청 URL 길이라는 서버 쪽 제약이기 때문이다.

2026-08-07 실측: 코드에 있는 네 가지 쿼리 모양이 전부 632~635개에서 깨진다
(UUID 39자 × 약 632개 ≈ 24,600자). select 컬럼이나 필터가 늘어도 편차가 3개뿐이라
쿼리별로 값을 달리 잡을 이유가 없다. 150이면 약 4.2배 여유다.
"""


_PAGE_SIZE = 1000


def _fetch_all(make_query) -> list[dict]:
    """
    PostgREST 1,000행 상한을 넘겨 전건을 받는다.

    ⚠ 이 계층은 목록을 받아 len()으로 세거나 평균을 낸다. 한 응답에 1,000행까지만
    오고 넘으면 **에러도 경고도 없이 잘리므로**, 페이지로 나눠 받지 않으면 KPI가
    조용히 틀린다. 2026-08-08 실측: 7일 수집 문서가 1,920건인데 화면에 1000으로
    떠 있었고, 매일 같은 값이라 눈에 띄지도 않았다. 오늘치 증가분은 더 나빴다 —
    ORDER BY 없이 임의의 1,000건이 오니 실제 407건 중 2건만 표본에 들어와 "+2"로 떴다.

    같은 버그를 repository.list_active_documents에서 먼저 고쳤는데(#176) 이 파일은
    repository를 거치지 않고 직접 질의해서 그대로 남아 있었다.

    make_query()는 매 페이지마다 새 빌더를 만들어야 한다 — postgrest 빌더는 재사용하면
    필터가 누적된다.
    """
    rows: list[dict] = []
    offset = 0
    while True:
        # 순서를 고정해야 페이지가 겹치거나 빠지지 않는다.
        page = (
            make_query()
            .order("id")
            .range(offset, offset + _PAGE_SIZE - 1)
            .execute()
            .data
        ) or []
        rows.extend(page)
        if len(page) < _PAGE_SIZE:
            return rows
        offset += _PAGE_SIZE


def _reliability_label(avg_score: float | None) -> str:
    if avg_score is None:
        return "데이터 없음"
    if avg_score < RELIABILITY_LOW_THRESHOLD:
        return "낮음"
    if avg_score < RELIABILITY_MEDIUM_THRESHOLD:
        return "보통"
    return "높음"


def _count_in_today_window(rows: list[dict], field: str, *, today_start: datetime, today_end: datetime) -> int:
    count = 0
    for row in rows:
        ts = _parse_timestamp(row.get(field))
        if ts is not None and today_start <= ts < today_end:
            count += 1
    return count


def get_dashboard_summary(
    workspace_id: str,
    *,
    supabase: Client | None = None,
    now: datetime | None = None,
) -> DashboardSummary:
    """대시보드 KPI 4종을 실제 데이터로 집계한다.

    수집 문서·생성 보고서는 최근 7일 누적(+오늘 신규), 위키 문서는 현재 published
    전체 누적(+오늘 신규 발행), 평균 신뢰도는 최근 7일 분석분의 reliability_score
    평균을 기존 프론트 라벨 기준(<40 낮음, <70 보통, 그 외 높음)으로 변환한다.

    ⚠ 평균 신뢰도의 창은 여기만 **created_at 기준**으로 남아 있다. 카테고리 카드
    배지와 아래 키워드·최신 뉴스는 발행일 기준으로 바뀌었으므로(2026-08-10), 같은
    임계값을 쓰면서도 표본이 다르다. KPI 라벨의 기준 변경은 별건으로 협의한다.
    """
    db = supabase or get_supabase()
    now = now or datetime.now(timezone.utc)
    window_start = (now - timedelta(days=WINDOW_DAYS)).isoformat()

    today_kst = now.astimezone(REPORT_TIMEZONE).date()
    today_start, today_end = get_report_time_range(today_kst)

    documents_rows = _fetch_all(
        lambda: db.table("documents")
        .select("id, created_at")
        .eq("workspace_id", workspace_id)
        .gte("created_at", window_start)
    )
    collected_docs = len(documents_rows)
    collected_docs_today = _count_in_today_window(
        documents_rows, "created_at", today_start=today_start, today_end=today_end
    )

    reports_rows = _fetch_all(
        lambda: db.table("reports")
        .select("id")
        .eq("workspace_id", workspace_id)
        .eq("status", ReportStatus.COMPLETED.value)
        .gte("created_at", window_start)
    )
    generated_reports = len(reports_rows)

    wiki_rows = _fetch_all(
        lambda: db.table("wiki_pages")
        .select("id, published_at")
        .eq("workspace_id", workspace_id)
        .eq("status", "published")
    )
    wiki_docs = len(wiki_rows)
    wiki_docs_new_today = _count_in_today_window(
        wiki_rows, "published_at", today_start=today_start, today_end=today_end
    )

    analysis_rows = _fetch_all(
        lambda: db.table("document_analysis_results")
        .select("reliability_score")
        .eq("workspace_id", workspace_id)
        .gte("created_at", window_start)
    )
    scores = [row["reliability_score"] for row in analysis_rows if row.get("reliability_score") is not None]
    avg_score = sum(scores) / len(scores) if scores else None

    return DashboardSummary(
        collected_docs=collected_docs,
        collected_docs_today=collected_docs_today,
        generated_reports=generated_reports,
        wiki_docs=wiki_docs,
        wiki_docs_new_today=wiki_docs_new_today,
        avg_reliability_label=_reliability_label(avg_score),
    )


# ---------------------------------------------------------------------------
# 일별 수집·채택 추이 — GET /dashboard/trend
# ---------------------------------------------------------------------------


def _source_types_by_id(db: Client, workspace_id: str) -> dict[str, str]:
    """source_id -> source_type. 워크스페이스당 10여 개라 통째로 받아 파이썬에서 대조한다."""
    rows = (
        db.table("sources")
        .select("id, source_type")
        .eq("workspace_id", workspace_id)
        .execute()
        .data
    )
    return {str(r["id"]): r.get("source_type") for r in rows}


def _adopted_document_ids(db: Client, workspace_id: str) -> set[str]:
    """랭킹까지 끝난 문서의 id 집합.

    분석 행은 document_versions를 가리키고 문서와 1:1이 아니다. 재수집으로 버전이
    늘면 같은 문서에 완료 행이 여러 개 생긴다(2026-08-06 실측 55행 -> 47문서).
    그래서 **문서 단위로 접어서** 센다 — 안 접으면 adopted가 collected를 넘을 수 있다.

    created_at으로 자르지 않는다. 분석은 수집보다 늦게 돌아서, 3일 전에 수집된
    문서가 오늘 채택될 수 있다. 날짜 버킷은 어디까지나 documents.created_at 기준이다.
    완료 행 자체가 많지 않아 전체를 받아도 부담이 없다.
    """
    analysis_rows = (
        db.table("document_analysis_results")
        .select("document_version_id")
        .eq("workspace_id", workspace_id)
        .eq("ranking_status", ADOPTED_RANKING_STATUS)
        .execute()
        .data
    )
    version_ids = sorted({str(r["document_version_id"]) for r in analysis_rows if r.get("document_version_id")})
    if not version_ids:
        return set()

    # document_versions에는 workspace_id 컬럼이 없다. 위 분석 행을 이미 workspace로
    # 걸렀으므로 여기서 나오는 document_id는 전부 그 workspace 것이다.
    document_ids: set[str] = set()
    for start in range(0, len(version_ids), _IN_CLAUSE_CHUNK_SIZE):
        rows = (
            db.table("document_versions")
            .select("id, document_id")
            .in_("id", version_ids[start : start + _IN_CLAUSE_CHUNK_SIZE])
            .execute()
            .data
        )
        document_ids.update(str(r["document_id"]) for r in rows if r.get("document_id"))
    return document_ids


def get_dashboard_trend(
    workspace_id: str,
    *,
    supabase: Client | None = None,
    now: datetime | None = None,
    days: int = WINDOW_DAYS,
) -> DashboardTrend:
    """일별 수집·채택 추이 (기본 7일).

    - collected  그날 수집된 문서 수 (documents.created_at, **KST 하루** 기준)
    - adopted    그 문서들 중 랭킹이 끝난 것. 문서 단위로 접어서 센다
    - news/disclosure  sources.source_type으로 나눈 collected의 내역

    날짜 경계는 UTC가 아니라 KST다. 보고서와 같은 기준을 써야 "8월 5일자 수집"이
    화면마다 다르게 보이지 않으므로 get_report_time_range()를 그대로 쓴다.

    ⚠ 오늘 버킷의 adopted는 구조적으로 0에 가깝다. 분석 배치가 수집보다 하루쯤
    뒤처지기 때문이고(스케줄러 timeout), 데이터 문제이지 집계 버그가 아니다.
    """
    db = supabase or get_supabase()
    now = now or datetime.now(timezone.utc)

    today_kst = now.astimezone(REPORT_TIMEZONE).date()
    first_day = today_kst - timedelta(days=days - 1)
    # 창 전체를 한 번에 받아 놓고 파이썬에서 날짜별로 가른다. 하루에 한 번씩
    # 부르면 7배 왕복이 된다.
    window_start, _ = get_report_time_range(first_day)
    _, window_end = get_report_time_range(today_kst)

    document_rows = _fetch_all(
        lambda: db.table("documents")
        .select("id, source_id, created_at")
        .eq("workspace_id", workspace_id)
        .gte("created_at", window_start.isoformat())
        .lt("created_at", window_end.isoformat())
    )

    source_types = _source_types_by_id(db, workspace_id)
    adopted_ids = _adopted_document_ids(db, workspace_id)

    buckets: dict[date, list[dict]] = {first_day + timedelta(days=i): [] for i in range(days)}
    for row in document_rows:
        created = _parse_timestamp(row.get("created_at"))
        if created is None:
            continue
        bucket = created.astimezone(REPORT_TIMEZONE).date()
        if bucket in buckets:
            buckets[bucket].append(row)

    return DashboardTrend(
        days=[_trend_day(day, rows, source_types, adopted_ids) for day, rows in sorted(buckets.items())]
    )


def _trend_day(
    day: date, rows: list[dict], source_types: dict[str, str], adopted_ids: set[str]
) -> TrendDay:
    types = [source_types.get(str(row.get("source_id"))) for row in rows]
    return TrendDay(
        date=day,
        collected=len(rows),
        adopted=sum(1 for row in rows if str(row["id"]) in adopted_ids),
        news=sum(1 for t in types if t in NEWS_SOURCE_TYPES),
        disclosure=sum(1 for t in types if t in DISCLOSURE_SOURCE_TYPES),
    )


# ------------------------------------------------------------
# 오늘의 키워드 · 최신 뉴스 (DashboardPage 하단 두 섹션)
#
# /categories/stats에 이미 같은 값이 있지만 대시보드가 그걸 부르지는 않는다.
#   - 화면 독립성: 2026-08-07에 /categories/stats가 .in_() 버그로 500을 냈을 때
#     /dashboard/*는 정상이라 대시보드는 멀쩡했다. 붙여 뒀으면 같이 죽었다.
#   - 응답 크기: 그쪽은 18,851 B인데 칩이 쓰는 건 상위 8개뿐이다.
#     현재 대시보드 전체 응답이 678 B라 28배가 된다.
#   - 카테고리 분류 체계가 3곳에서 다르고 아직 미합의다(CLAUDE.md 7). 대시보드를
#     그 계약에 묶어두면 합의가 끝날 때까지 같이 발이 묶인다.
# ------------------------------------------------------------


_NEWS_ANALYSIS_COLUMNS = (
    "primary_category, document_version_id, created_at, core_summary, summary_evidence_refs"
)

# 산업 이슈는 등급을 매겨야 해서 신뢰도 컬럼이 더 필요하다. 키워드·최신 뉴스가
# 쓰지 않는 컬럼을 그쪽 조회에까지 얹지 않으려고 목록을 나눠 둔다.
_ISSUE_ANALYSIS_COLUMNS = (
    "primary_category, document_version_id, created_at, core_summary, "
    "summary_evidence_refs, reliability_status, reliability_score"
)

# 이슈 행은 제목 아래 한 문단이다. 카드가 세로로 늘어나면 목록이 스크롤만 길어진다.
ISSUE_SUMMARY_MAX_LEN = 200


def _analysis_rows_with_titles(
    db: Client,
    workspace_id: str,
    now: datetime,
    *,
    columns: str = _NEWS_ANALYSIS_COLUMNS,
) -> tuple[list[dict], dict[str, dict]]:
    """최근 7일 **발행분** 분석 행 + document_version_id -> documents 행.

    카테고리 현황과 같은 창(WINDOW_DAYS)을, 같은 기준(발행일)으로 쓴다. 두 화면이
    다른 기간을 보면 같은 낱말에 다른 숫자가 붙는다. 그래서 창 판정도 카테고리와
    같은 함수(categories.documents.in_published_window)를 부른다.

    ⚠ 이 함수는 2026-08-10까지 pagination 없이 .limit()만 걸고 있어서 7일 분석 행
    1,306건 중 1,000건만 보고 있었다. 같은 파일의 _fetch_all은 #188에서 고쳐졌는데
    이 경로만 남아 있었다 — '오늘의 키워드' 칩과 '최신 뉴스' 카드가 조용히 300건을
    빼고 집계됐다는 뜻이다. 공용 fetch_analysis_rows가 페이지로 받는다.
    """
    start = window_start(now, days=WINDOW_DAYS)
    rows = fetch_analysis_rows(
        db,
        workspace_id,
        columns=columns,
        # created_at은 발행일 창의 prefilter다. categories/service.py와 같은 이유.
        since=start - timedelta(days=PREFILTER_MARGIN_DAYS),
        limit=_ANALYSIS_FETCH_LIMIT,
    )
    rows = [r for r in rows if r.get("primary_category") in CATEGORY_SLUGS]
    version_ids = [
        str(r["document_version_id"]) for r in rows if r.get("document_version_id")
    ]
    documents = documents_by_version(db, workspace_id, version_ids)

    in_window = [
        r
        for r in rows
        if (document := documents.get(str(r.get("document_version_id")))) is not None
        and in_published_window(document, start)
    ]
    return in_window, documents


def get_dashboard_keywords(
    workspace_id: str,
    *,
    supabase: Client | None = None,
    now: datetime | None = None,
) -> DashboardKeywords:
    """'오늘의 키워드' 칩 — 제목에서 사전 매칭한 낱말을 등장 문서 수 순으로.

    카테고리별로 count_keywords를 돌려 합산한다. CATEGORY_KEYWORDS가 카테고리별
    사전이라, 문서의 primary_category에 맞는 사전으로만 매칭해야 오탐이 안 난다
    (예: '수율'은 공급망 문서에서만 의미가 있다).

    수집 질의어(sources.config.query)를 쓰지 않는 이유는 DashboardKeyword 참조.
    횟수는 count_keywords가 이미 만들고 있다 — extract_tags가 그걸 버릴 뿐이다.
    """
    db = supabase or get_supabase()
    now = now or datetime.now(timezone.utc)

    rows, documents = _analysis_rows_with_titles(db, workspace_id, now)

    titles_by_category: dict[str, list[str]] = {}
    for row in rows:
        document = documents.get(str(row.get("document_version_id")))
        if document is None:
            continue
        titles_by_category.setdefault(row["primary_category"], []).append(
            document.get("title") or ""
        )

    totals: dict[str, int] = {}
    for category, titles in titles_by_category.items():
        for word, count in count_keywords(titles, category):
            totals[word] = totals.get(word, 0) + count

    # 빈도 내림차순, 동점이면 낱말 순 — 같은 데이터에 같은 순서가 나와야 한다.
    ranked = sorted(totals.items(), key=lambda pair: (-pair[1], pair[0]))
    return DashboardKeywords(
        keywords=[
            DashboardKeyword(word=word, count=count)
            for word, count in ranked[:MAX_PIE_KEYWORDS]
        ]
    )


def get_dashboard_news(
    workspace_id: str,
    *,
    supabase: Client | None = None,
    now: datetime | None = None,
    limit: int = MAX_NEWS_ITEMS,
) -> DashboardNews:
    """'최신 뉴스' 카드 — 발행일 내림차순.

    문서 단위로 접는다. 재수집으로 버전이 늘어난 문서를 두 번 세면 같은 기사가
    카드 두 장이 된다.

    tags는 그 문서의 제목 하나에 카테고리 사전을 적용해 뽑는다. 칩과 같은 사전을
    쓰는 게 핵심이다 — 화면의 키워드 필터(newsMatchesInterest)가 title+quote+
    category+sourceLabel+tags에 대한 텍스트 매칭이라, 사전이 다르면 칩을 눌렀을 때
    걸리는 카드가 없어 빈 화면이 된다.
    """
    db = supabase or get_supabase()
    now = now or datetime.now(timezone.utc)

    rows, documents = _analysis_rows_with_titles(db, workspace_id, now)
    unique = unique_documents(rows, documents)
    source_types = _source_types_by_id(db, workspace_id)

    candidates = [
        entry
        for entry in unique.values()
        if _is_dashboard_news_candidate(entry["document"], source_types)
    ]
    picked = sorted(
        candidates,
        key=lambda entry: str(entry["document"].get("published_at") or ""),
        reverse=True,
    )[:limit]

    return DashboardNews(
        items=[
            DashboardNewsItem(
                title=display_title(entry["document"].get("title") or ""),
                quote=quote_for(entry["row"]),
                category=entry["row"]["primary_category"],
                tags=extract_tags(
                    [entry["document"].get("title") or ""],
                    entry["row"]["primary_category"],
                ),
                source_label=source_label(entry["document"].get("canonical_url")),
                source_url=entry["document"].get("canonical_url") or "",
                published_at=entry["document"].get("published_at"),
                is_doc=source_types.get(str(entry["document"].get("source_id")))
                in DISCLOSURE_SOURCE_TYPES,
            )
            for entry in picked
        ]
    )


# ------------------------------------------------------------
# 최근 산업 이슈 — GET /dashboard/issues
#
# '최신 뉴스'와 같은 창·같은 조회를 쓰지만 담는 것이 다르다. 저쪽은 기사 흐름이고
# 이쪽은 **회사가 공식 신고한 사실**만 모은다. 공시 유형은 #276이 정한 기준을 그대로
# 쓴다(INDUSTRY_DISCLOSURE_TYPE_CODES) — 같은 판정을 두 곳에서 따로 정의하면
# '최신 뉴스에는 뜨는데 산업 이슈에는 없는' 공시가 생긴다.
# ------------------------------------------------------------

MAX_ISSUE_ITEMS = 20


def _issue_level(score: int | float | None) -> str:
    """신뢰도 점수 -> 화면 배지 3종.

    카테고리 현황(categories/service._level)과 같은 임계값을 쓴다. 두 화면이 다른
    기준으로 '보통'을 말하면 안 된다. 여기서 다시 정의하는 이유는 categories를
    import하면 순환이 되기 때문이고, 값은 같은 상수(RELIABILITY_*_THRESHOLD)에서 온다.
    """
    if score is None:
        return "low"
    if score < RELIABILITY_LOW_THRESHOLD:
        return "low"
    if score < RELIABILITY_MEDIUM_THRESHOLD:
        return "mid"
    return "high"


def get_dashboard_issues(
    workspace_id: str,
    *,
    supabase: Client | None = None,
    now: datetime | None = None,
    limit: int = MAX_ISSUE_ITEMS,
) -> DashboardIssues:
    """'최근 산업 이슈' — 최근 7일 발행 공시 중 분석이 끝난 것만 발행일 내림차순.

    목록에서 빼는 것과 그 이유
        기사(news/rss)      '최신 뉴스'가 이미 보여준다. 이 섹션은 공시 전용이다
        D(지분공시)          임원 주식 매매 신고라 산업 동향이 아니다 (#276 기준)
        분석 미완료 공시      level·summary가 분석 산출물이다. 넣으면 근거 없이 등급이
                            붙는다(절대원칙 1). 분석이 끝나면 자동으로 올라온다
        요약이 빈 공시        제목만 두 번 나오는 행이 된다

    ⚠ 그래서 이 목록은 수집된 공시 전부가 아니라 **분석까지 끝난 공시**만 보여준다.
    분석 백로그가 밀리면 건수가 적게 보이는데, 그건 집계 오류가 아니라 처리 진척도다.
    """
    db = supabase or get_supabase()
    now = now or datetime.now(timezone.utc)

    rows, documents = _analysis_rows_with_titles(
        db, workspace_id, now, columns=_ISSUE_ANALYSIS_COLUMNS
    )
    source_types = _source_types_by_id(db, workspace_id)
    unique = unique_documents(rows, documents)

    picked = []
    for entry in unique.values():
        document, row = entry["document"], entry["row"]
        if source_types.get(str(document.get("source_id"))) not in DISCLOSURE_SOURCE_TYPES:
            continue
        if not _is_dashboard_news_candidate(document, source_types):
            continue
        if row.get("reliability_status") != "completed":
            continue
        summary = (row.get("core_summary") or "").strip()
        if not summary:
            continue
        picked.append(entry)

    picked.sort(
        key=lambda e: str(e["document"].get("published_at") or ""), reverse=True
    )

    return DashboardIssues(
        items=[
            DashboardIssue(
                id=str(entry["document"]["id"]),
                level=_issue_level(entry["row"].get("reliability_score")),
                category=entry["row"]["primary_category"],
                title=display_title(entry["document"].get("title") or ""),
                summary=truncate(entry["row"]["core_summary"], ISSUE_SUMMARY_MAX_LEN),
                # 도메인(dart.fss.or.kr) 대신 공시 유형을 보여준다. 어느 사이트에서
                # 왔는지는 공시라는 것만으로 자명하고, '거래소공시'인지 '주요사항보고'
                # 인지가 사용자에게 실제 정보다.
                source_label=(entry["document"].get("disclosure_type_name") or "공시 원문"),
                source_url=entry["document"].get("canonical_url") or "",
                published_at=entry["document"].get("published_at"),
                is_doc=True,
            )
            for entry in picked[:limit]
        ]
    )


def _is_dashboard_news_candidate(document: dict, source_types: dict[str, str]) -> bool:
    source_type = source_types.get(str(document.get("source_id")))
    if source_type not in DISCLOSURE_SOURCE_TYPES:
        return True

    disclosure_type_code = str(document.get("disclosure_type_code") or "").strip().upper()
    # 기존 수집분은 backfill 전까지 유형 코드가 비어 있을 수 있다. 그런 레거시 공시는
    # 화면을 갑자기 비우지 않도록 남겨 두고, 코드가 채워진 공시부터 산업 이슈 필터를 적용한다.
    if not disclosure_type_code:
        return True
    if disclosure_type_code in EXCLUDED_DISCLOSURE_TYPE_CODES:
        return False
    return disclosure_type_code in INDUSTRY_DISCLOSURE_TYPE_CODES

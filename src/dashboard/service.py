from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from supabase import Client

from ..analysis.repository import get_supabase
from ..report.candidate_provider import get_report_time_range
from ..report.candidate_provider import REPORT_TIMEZONE
from ..report.models import ReportStatus
from .models import DashboardSummary, DashboardTrend, TrendDay

RELIABILITY_LOW_THRESHOLD = 40
RELIABILITY_MEDIUM_THRESHOLD = 70

WINDOW_DAYS = 7

# 문서가 "채택됐다"의 기준. 랭킹까지 끝나 보고서 후보로 확정된 상태다.
ADOPTED_RANKING_STATUS = "completed"

# sources.source_type -> 추이 차트의 계열. rss는 구글 뉴스 RSS라 뉴스로 묶는다.
NEWS_SOURCE_TYPES = frozenset({"news", "rss"})
DISCLOSURE_SOURCE_TYPES = frozenset({"disclosure"})

# .in_() 한 번에 넣을 id 개수. URL 길이 제한에 걸리지 않게 나눠 부른다.
_IN_CHUNK = 200


def _reliability_label(avg_score: float | None) -> str:
    if avg_score is None:
        return "데이터 없음"
    if avg_score < RELIABILITY_LOW_THRESHOLD:
        return "낮음"
    if avg_score < RELIABILITY_MEDIUM_THRESHOLD:
        return "보통"
    return "높음"


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


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
    """
    db = supabase or get_supabase()
    now = now or datetime.now(timezone.utc)
    window_start = (now - timedelta(days=WINDOW_DAYS)).isoformat()

    today_kst = now.astimezone(REPORT_TIMEZONE).date()
    today_start, today_end = get_report_time_range(today_kst)

    documents_rows = (
        db.table("documents")
        .select("id, created_at")
        .eq("workspace_id", workspace_id)
        .gte("created_at", window_start)
        .execute()
        .data
    )
    collected_docs = len(documents_rows)
    collected_docs_today = _count_in_today_window(
        documents_rows, "created_at", today_start=today_start, today_end=today_end
    )

    reports_rows = (
        db.table("reports")
        .select("id")
        .eq("workspace_id", workspace_id)
        .eq("status", ReportStatus.COMPLETED.value)
        .gte("created_at", window_start)
        .execute()
        .data
    )
    generated_reports = len(reports_rows)

    wiki_rows = (
        db.table("wiki_pages")
        .select("id, published_at")
        .eq("workspace_id", workspace_id)
        .eq("status", "published")
        .execute()
        .data
    )
    wiki_docs = len(wiki_rows)
    wiki_docs_new_today = _count_in_today_window(
        wiki_rows, "published_at", today_start=today_start, today_end=today_end
    )

    analysis_rows = (
        db.table("document_analysis_results")
        .select("reliability_score")
        .eq("workspace_id", workspace_id)
        .gte("created_at", window_start)
        .execute()
        .data
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
    for start in range(0, len(version_ids), _IN_CHUNK):
        rows = (
            db.table("document_versions")
            .select("id, document_id")
            .in_("id", version_ids[start : start + _IN_CHUNK])
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

    document_rows = (
        db.table("documents")
        .select("id, source_id, created_at")
        .eq("workspace_id", workspace_id)
        .gte("created_at", window_start.isoformat())
        .lt("created_at", window_end.isoformat())
        .execute()
        .data
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

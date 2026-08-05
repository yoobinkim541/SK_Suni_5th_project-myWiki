from __future__ import annotations

from datetime import datetime, timedelta, timezone

from supabase import Client

from ..analysis.repository import get_supabase
from ..report.candidate_provider import get_report_time_range
from ..report.candidate_provider import REPORT_TIMEZONE
from ..report.models import ReportStatus
from .models import DashboardSummary

RELIABILITY_LOW_THRESHOLD = 40
RELIABILITY_MEDIUM_THRESHOLD = 70

WINDOW_DAYS = 7


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

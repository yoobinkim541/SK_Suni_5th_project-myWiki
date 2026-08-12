from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from supabase import Client

from ..analysis.importance_models import AnalysisResultForReport
from ..analysis.models import DOCUMENT_ANALYSIS_RESULTS_TABLE
from ..analysis.repository import (
    _chunked,
    _row_has_report_summary,
    _row_is_ranking_candidate_ready,
    _select_analysis_row_for_ranking,
    get_supabase,
)
from .models import ReportCandidate

try:
    REPORT_TIMEZONE = ZoneInfo("Asia/Seoul")
except ZoneInfoNotFoundError:
    REPORT_TIMEZONE = timezone(timedelta(hours=9))

SUPABASE_PAGE_SIZE = 1000


def get_report_time_range(report_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(report_date, datetime.min.time(), tzinfo=REPORT_TIMEZONE)
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def get_report_candidates(
    *,
    workspace_id: str,
    report_date: date,
    document_version_ids: Sequence[str] | None = None,
    published_from: datetime | None = None,
    published_to: datetime | None = None,
    supabase: Client | None = None,
) -> list[ReportCandidate]:
    """Load report-ready results from an explicit batch or publication window.

    The date-based path remains for manual/API reports. Supplying a publication
    window lets scheduled reports use an operational day that does not begin at
    midnight. Supplying document IDs pins a report to one exact analysis batch.
    """
    db = supabase or get_supabase()
    if (published_from is None) != (published_to is None):
        raise ValueError("published_from and published_to must be supplied together.")
    if published_from is not None and published_to is not None and published_from >= published_to:
        raise ValueError("published_from must be earlier than published_to.")

    if document_version_ids is not None:
        fixed_version_ids = list(dict.fromkeys(str(value) for value in document_version_ids if str(value).strip()))
        if not fixed_version_ids:
            return []
        version_rows = []
        for chunk in _chunked(fixed_version_ids):
            version_rows.extend(
                db.table("document_versions").select("id, document_id").in_("id", chunk).execute().data
            )
    else:
        window_start, window_end = (
            (published_from, published_to)
            if published_from is not None and published_to is not None
            else get_report_time_range(report_date)
        )
        document_rows = _fetch_documents_in_publication_window(
            db=db,
            workspace_id=workspace_id,
            window_start=window_start,
            window_end=window_end,
            fields="id, title, canonical_url, published_at, source_id",
        )
        if not document_rows:
            return []
        document_ids = [row["id"] for row in document_rows]
        version_rows = []
        for chunk in _chunked(document_ids):
            version_rows.extend(
                db.table("document_versions").select("id, document_id").in_("document_id", chunk).execute().data
            )

    if published_from is not None and published_to is not None:
        batch_document_ids = list({row["document_id"] for row in version_rows})
        published_document_rows = []
        for chunk in _chunked(batch_document_ids):
            published_document_rows.extend(
                _fetch_documents_in_publication_window(
                    db=db,
                    window_start=published_from,
                    window_end=published_to,
                    fields="id",
                    document_ids=chunk,
                )
            )
        published_document_ids = {row["id"] for row in published_document_rows}
        version_rows = [
            row for row in version_rows if row["document_id"] in published_document_ids
        ]
        if not version_rows:
            return []

    if not version_rows:
        return []

    version_to_document = {row["id"]: row["document_id"] for row in version_rows}
    analysis_rows = []
    for chunk in _chunked(list(version_to_document)):
        analysis_rows.extend(
            db.table(DOCUMENT_ANALYSIS_RESULTS_TABLE)
            .select("*")
            .eq("workspace_id", workspace_id)
            .in_("document_version_id", chunk)
            .eq("status", "completed")
            .eq("reliability_status", "completed")
            .eq("importance_status", "completed")
            .eq("ranking_status", "completed")
            .eq("selected_for_report", True)
            .execute()
            .data
        )
    # 청크별로 실행해서 order가 못 걸리므로 합친 뒤 여기서 정렬한다.
    analysis_rows.sort(key=lambda row: row.get("id") or "")
    analysis_rows.sort(key=lambda row: row.get("classified_at") or "", reverse=True)
    analysis_rows.sort(key=lambda row: row.get("reliability_evaluated_at") or "", reverse=True)
    analysis_rows.sort(key=lambda row: row.get("importance_evaluated_at") or "", reverse=True)
    if not analysis_rows:
        return []

    return _build_candidates_from_analysis_rows(
        db, analysis_rows=analysis_rows, workspace_id=workspace_id,
    )


def _fetch_documents_in_publication_window(
    *,
    db: Client,
    window_start: datetime,
    window_end: datetime,
    fields: str,
    workspace_id: str | None = None,
    document_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        query = db.table("documents").select(fields)
        if workspace_id is not None:
            query = query.eq("workspace_id", workspace_id)
        if document_ids is not None:
            query = query.in_("id", document_ids)
        page = (
            query.gte("published_at", window_start.isoformat())
            .lt("published_at", window_end.isoformat())
            .range(start, start + SUPABASE_PAGE_SIZE - 1)
            .execute()
            .data
        )
        rows.extend(page)
        if len(page) < SUPABASE_PAGE_SIZE:
            break
        start += SUPABASE_PAGE_SIZE
    return rows


def to_report_candidate(*, result: AnalysisResultForReport, document_id: str) -> ReportCandidate:
    return ReportCandidate(
        analysis_result_id=result.analysis_result_id,
        workspace_id=result.workspace_id,
        document_id=document_id,
        document_version_id=result.document_version_id,
        category=result.primary_category,
        title=result.title,
        summary=result.core_summary,
        reliability_score=result.reliability_score,
        importance_score=result.importance_score,
        ranking_score=Decimal(str(result.ranking_score)) if result.ranking_score is not None else None,
        source_name=result.source_name,
        source_type=result.source_type,
        canonical_url=result.canonical_url,
        published_at=result.published_at,
        impact_direction=result.impact_direction,
        time_horizon=result.time_horizon,
    )


def build_report_candidates(candidates: Sequence[ReportCandidate]) -> list[ReportCandidate]:
    ordered = list(candidates)
    ordered.sort(key=lambda item: item.analysis_result_id, reverse=True)
    ordered.sort(
        key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    ordered.sort(
        key=lambda item: item.ranking_score if item.ranking_score is not None else Decimal("-1"),
        reverse=True,
    )
    return ordered


def _row_is_report_candidate_ready(row: dict[str, Any]) -> bool:
    return bool(
        row.get("ranking_status") == "completed"
        and row.get("selected_for_report") is True
        and row.get("ranking_score") is not None
        and _row_is_ranking_candidate_ready(row)
        and _row_has_report_summary(row)
    )


def get_recently_analyzed_candidates(
    *,
    workspace_id: str,
    since: datetime,
    supabase: Client | None = None,
) -> list[ReportCandidate]:
    """report_date 하루 단위가 아니라 '최근 since 이후 분석 완료된 것' 기준으로
    candidate를 가져온다 — 2시간 주기 위키 갱신 배치 전용."""
    db = supabase or get_supabase()
    analysis_rows = (
        db.table(DOCUMENT_ANALYSIS_RESULTS_TABLE)
        .select("*")
        .eq("workspace_id", workspace_id)
        .eq("status", "completed")
        .eq("reliability_status", "completed")
        .eq("importance_status", "completed")
        .eq("ranking_status", "completed")
        .eq("selected_for_report", True)
        .gte("importance_evaluated_at", since.isoformat())
        .order("importance_evaluated_at", desc=True)
        .execute()
        .data
    )
    if not analysis_rows:
        return []

    return _build_candidates_from_analysis_rows(
        db, analysis_rows=analysis_rows, workspace_id=workspace_id,
    )


def _build_candidates_from_analysis_rows(
    db: Client,
    *,
    analysis_rows: list[dict[str, Any]],
    workspace_id: str,
) -> list[ReportCandidate]:
    """analysis_rows(document_analysis_results 행들)로부터 document_versions/documents/sources를
    조회해 ReportCandidate 리스트로 변환한다. get_report_candidates와
    get_recently_analyzed_candidates가 공유한다.

    documents는 workspace_id로 직접 필터링하지 않고, analysis_rows(이미 workspace_id로
    필터링됨) -> document_versions -> documents 경로로 전이적으로만 도달한다. 두 호출부의
    "어떤 문서/분석 행이 대상인지" 결정 로직은 각자 다르므로 이 함수에 들어오지 않는다.
    """
    document_version_ids = list({row["document_version_id"] for row in analysis_rows if row.get("document_version_id")})
    version_rows = []
    for chunk in _chunked(document_version_ids):
        version_rows.extend(
            db.table("document_versions").select("id, document_id").in_("id", chunk).execute().data
        )
    if not version_rows:
        return []
    version_to_document = {row["id"]: row["document_id"] for row in version_rows}

    document_ids = list(set(version_to_document.values()))
    document_rows = []
    for chunk in _chunked(document_ids):
        document_rows.extend(
            db.table("documents")
            .select("id, title, canonical_url, published_at, source_id")
            .in_("id", chunk)
            .execute()
            .data
        )
    documents_by_id = {row["id"]: row for row in document_rows}

    source_ids = list({row.get("source_id") for row in document_rows if row.get("source_id")})
    source_rows = []
    for chunk in _chunked(source_ids):
        source_rows.extend(
            db.table("sources").select("id, name, source_type").in_("id", chunk).execute().data
        )
    sources_by_id = {row["id"]: row for row in source_rows}

    rows_by_document_version: dict[str, list[dict[str, Any]]] = {}
    for row in analysis_rows:
        document_version_id = row.get("document_version_id")
        if not document_version_id:
            continue
        rows_by_document_version.setdefault(document_version_id, []).append(row)

    selected_results: list[tuple[AnalysisResultForReport, str]] = []
    for document_version_id in document_version_ids:
        document_id = version_to_document.get(document_version_id)
        document = documents_by_id.get(document_id) if document_id else None
        if document_id is None or document is None:
            continue

        ready_rows = [
            row
            for row in rows_by_document_version.get(document_version_id, [])
            if _row_is_report_candidate_ready(row)
        ]
        selected_row = _select_analysis_row_for_ranking(
            rows=ready_rows,
            workspace_id=workspace_id,
            document_version_id=document_version_id,
        )
        if selected_row is None:
            continue

        source = sources_by_id.get(document.get("source_id"), {}) if document.get("source_id") else {}
        payload = dict(selected_row)
        payload["analysis_result_id"] = payload.get("id")
        payload["title"] = document.get("title") or ""
        payload["canonical_url"] = document.get("canonical_url")
        payload["published_at"] = document.get("published_at")
        payload["source_name"] = source.get("name")
        payload["source_type"] = source.get("source_type")
        selected_results.append((AnalysisResultForReport.model_validate(payload), document_id))

    candidates = [
        to_report_candidate(result=result, document_id=document_id)
        for result, document_id in selected_results
    ]
    return build_report_candidates(candidates)

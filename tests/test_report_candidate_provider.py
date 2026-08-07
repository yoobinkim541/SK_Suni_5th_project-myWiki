from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from src.report.candidate_provider import get_report_candidates, get_report_time_range


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, supabase, name):
        self.supabase = supabase
        self.name = name
        self.rows = supabase.tables.setdefault(name, [])
        self.filters = []
        self.in_filters = []
        self.ordering = []
        self.lower_bounds = []
        self.upper_bounds = []

    def select(self, _fields):
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def in_(self, field, values):
        self.in_filters.append((field, set(values)))
        return self

    def gte(self, field, value):
        self.lower_bounds.append((field, value))
        return self

    def lt(self, field, value):
        self.upper_bounds.append((field, value))
        return self

    def order(self, field, desc=False):
        self.ordering.append((field, desc))
        return self

    def execute(self):
        rows = [dict(row) for row in self.rows]
        for field, value in self.filters:
            rows = [row for row in rows if row.get(field) == value]
        for field, values in self.in_filters:
            rows = [row for row in rows if row.get(field) in values]
        for field, value in self.lower_bounds:
            rows = [row for row in rows if _coerce_value(row.get(field)) >= _coerce_value(value)]
        for field, value in self.upper_bounds:
            rows = [row for row in rows if _coerce_value(row.get(field)) < _coerce_value(value)]
        for field, desc in reversed(self.ordering):
            rows.sort(key=lambda row: _coerce_value(row.get(field)), reverse=desc)
        return FakeResult(rows)


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return FakeTable(self, name)


def test_get_report_time_range_uses_seoul_half_open_window() -> None:
    start, end = get_report_time_range(date(2026, 8, 2))

    assert start == datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 8, 2, 15, 0, tzinfo=timezone.utc)


def test_get_report_candidates_applies_seoul_date_range_and_metadata_mapping() -> None:
    supabase = FakeSupabase(
        _tables_for_candidates(
            published_ats={
                "doc-start": "2026-08-01T15:00:00+00:00",
                "doc-end-minus": "2026-08-02T14:59:59.999999+00:00",
                "doc-end": "2026-08-02T15:00:00+00:00",
            }
        )
    )

    candidates = get_report_candidates(
        workspace_id="ws-1",
        report_date=date(2026, 8, 2),
        supabase=supabase,
    )

    assert [candidate.document_id for candidate in candidates] == ["doc-end-minus", "doc-start"]
    assert candidates[0].analysis_result_id == "analysis-doc-end-minus-current"
    assert candidates[0].document_version_id == "ver-doc-end-minus-v1"
    assert candidates[0].source_name == "연합뉴스"
    assert candidates[0].source_type == "rss"
    assert candidates[0].canonical_url == "https://example.com/doc-end-minus"
    assert candidates[0].ranking_score == Decimal("90.2")


def test_get_report_candidates_uses_fixed_document_ids_instead_of_report_date() -> None:
    tables = _tables_for_candidates(
        published_ats={
            "doc-in-batch": "2026-08-01T01:00:00+00:00",
            "doc-outside-batch": "2026-08-02T03:00:00+00:00",
        }
    )

    candidates = get_report_candidates(
        workspace_id="ws-1",
        report_date=date(2026, 8, 2),
        document_version_ids=["ver-doc-in-batch-v1"],
        supabase=FakeSupabase(tables),
    )

    assert [candidate.document_id for candidate in candidates] == ["doc-in-batch"]


def test_get_report_candidates_accepts_a_custom_publication_window() -> None:
    candidates = get_report_candidates(
        workspace_id="ws-1",
        report_date=date(2026, 8, 7),
        published_from=datetime(2026, 8, 5, 23, tzinfo=timezone.utc),
        published_to=datetime(2026, 8, 6, 23, tzinfo=timezone.utc),
        supabase=FakeSupabase(
            _tables_for_candidates(
                published_ats={
                    "doc-start": "2026-08-05T23:00:00+00:00",
                    "doc-end-minus": "2026-08-06T22:59:59+00:00",
                    "doc-end": "2026-08-06T23:00:00+00:00",
                }
            )
        ),
    )

    assert [candidate.document_id for candidate in candidates] == ["doc-end-minus", "doc-start"]

def test_get_report_candidates_maps_disclosure_source_type() -> None:
    """selector.py의 공시 예외(analysis/README.md 참조)가 source_type을 보고
    판단하므로, sources.source_type이 candidate까지 그대로 전달돼야 한다."""
    tables = _tables_for_candidates(published_ats={"doc-1": "2026-08-02T03:00:00+00:00"})
    tables["sources"] = [{"id": "source-1", "name": "DART - SK하이닉스", "source_type": "disclosure"}]

    candidates = get_report_candidates(
        workspace_id="ws-1",
        report_date=date(2026, 8, 2),
        supabase=FakeSupabase(tables),
    )

    assert len(candidates) == 1
    assert candidates[0].source_type == "disclosure"


def test_get_report_candidates_uses_single_complete_analysis_row() -> None:
    tables = _tables_for_candidates(published_ats={"doc-1": "2026-08-02T03:00:00+00:00"})
    tables["document_analysis_results"] = [
        _analysis_row(
            analysis_result_id="analysis-doc-1-a",
            document_version_id="ver-doc-1-v1",
            prompt_version="classification-v1",
            reliability_prompt_version="reliability-v1",
            importance_prompt_version="importance-v2",
            ranking_status="completed",
            ranking_score="88.0",
            reliability_status="pending",
        ),
        _analysis_row(
            analysis_result_id="analysis-doc-1-b",
            document_version_id="ver-doc-1-v1",
            prompt_version="classification-v1",
            reliability_prompt_version="reliability-v1",
            importance_prompt_version="importance-v2",
            ranking_status="completed",
            ranking_score="88.0",
            importance_status="pending",
        ),
        _analysis_row(
            analysis_result_id="analysis-doc-1-c",
            document_version_id="ver-doc-1-v1",
            prompt_version="classification-v1",
            reliability_prompt_version="reliability-v1",
            importance_prompt_version="importance-v2",
            ranking_status="completed",
            ranking_score="88.0",
        ),
    ]

    candidates = get_report_candidates(
        workspace_id="ws-1",
        report_date=date(2026, 8, 2),
        supabase=FakeSupabase(tables),
    )

    assert len(candidates) == 1
    assert candidates[0].analysis_result_id == "analysis-doc-1-c"


def test_get_report_candidates_prefers_current_prompt_versions() -> None:
    tables = _tables_for_candidates(published_ats={"doc-1": "2026-08-02T03:00:00+00:00"})
    tables["document_analysis_results"] = [
        _analysis_row(
            analysis_result_id="analysis-doc-1-old",
            document_version_id="ver-doc-1-v1",
            prompt_version="classification-v0",
            reliability_prompt_version="reliability-v0",
            importance_prompt_version="importance-v1",
            ranking_status="completed",
            ranking_score="95.0",
            importance_evaluated_at="2026-08-02T04:00:00+00:00",
        ),
        _analysis_row(
            analysis_result_id="analysis-doc-1-current",
            document_version_id="ver-doc-1-v1",
            prompt_version="classification-v1",
            reliability_prompt_version="reliability-v1",
            importance_prompt_version="importance-v2",
            ranking_status="completed",
            ranking_score="90.0",
            importance_evaluated_at="2026-08-02T03:00:00+00:00",
        ),
    ]

    candidates = get_report_candidates(
        workspace_id="ws-1",
        report_date=date(2026, 8, 2),
        supabase=FakeSupabase(tables),
    )

    assert len(candidates) == 1
    assert candidates[0].analysis_result_id == "analysis-doc-1-current"


def test_get_report_candidates_keeps_analyzed_document_version() -> None:
    tables = _tables_for_candidates(published_ats={"doc-1": "2026-08-02T03:00:00+00:00"})
    tables["document_versions"].append({"id": "ver-doc-1-v2", "document_id": "doc-1"})

    candidates = get_report_candidates(
        workspace_id="ws-1",
        report_date=date(2026, 8, 2),
        supabase=FakeSupabase(tables),
    )

    assert len(candidates) == 1
    assert candidates[0].document_version_id == "ver-doc-1-v1"


def test_get_report_candidates_returns_empty_list_when_no_matching_rows() -> None:
    candidates = get_report_candidates(
        workspace_id="ws-1",
        report_date=date(2026, 8, 2),
        supabase=FakeSupabase(_tables_for_candidates(published_ats={})),
    )

    assert candidates == []


def test_get_report_candidates_excludes_incomplete_rows() -> None:
    tables = _tables_for_candidates(published_ats={"doc-1": "2026-08-02T03:00:00+00:00"})
    tables["document_analysis_results"] = [
        _analysis_row(
            analysis_result_id="missing-category",
            document_version_id="ver-doc-1-v1",
            prompt_version="classification-v1",
            reliability_prompt_version="reliability-v1",
            importance_prompt_version="importance-v2",
            ranking_status="completed",
            ranking_score="80.0",
            primary_category=None,
        ),
        _analysis_row(
            analysis_result_id="missing-reliability",
            document_version_id="ver-doc-1-v1",
            prompt_version="classification-v1",
            reliability_prompt_version="reliability-v1",
            importance_prompt_version="importance-v2",
            ranking_status="completed",
            ranking_score="80.0",
            reliability_score=None,
        ),
        _analysis_row(
            analysis_result_id="missing-importance",
            document_version_id="ver-doc-1-v1",
            prompt_version="classification-v1",
            reliability_prompt_version="reliability-v1",
            importance_prompt_version="importance-v2",
            ranking_status="completed",
            ranking_score="80.0",
            importance_score=None,
        ),
        _analysis_row(
            analysis_result_id="missing-summary",
            document_version_id="ver-doc-1-v1",
            prompt_version="classification-v1",
            reliability_prompt_version="reliability-v1",
            importance_prompt_version="importance-v2",
            ranking_status="completed",
            ranking_score="80.0",
            core_summary="",
        ),
        _analysis_row(
            analysis_result_id="missing-ranking",
            document_version_id="ver-doc-1-v1",
            prompt_version="classification-v1",
            reliability_prompt_version="reliability-v1",
            importance_prompt_version="importance-v2",
            ranking_status="completed",
            ranking_score=None,
        ),
    ]

    candidates = get_report_candidates(
        workspace_id="ws-1",
        report_date=date(2026, 8, 2),
        supabase=FakeSupabase(tables),
    )

    assert candidates == []


def test_get_report_candidates_does_not_limit_candidate_count() -> None:
    published_ats = {
        f"doc-{index}": (datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=index)).isoformat()
        for index in range(25)
    }
    candidates = get_report_candidates(
        workspace_id="ws-1",
        report_date=date(2026, 8, 2),
        supabase=FakeSupabase(_tables_for_candidates(published_ats=published_ats)),
    )

    assert len(candidates) == 25


def _tables_for_candidates(*, published_ats: dict[str, str]) -> dict[str, list[dict[str, object]]]:
    sources = [{"id": "source-1", "name": "연합뉴스", "source_type": "rss"}]
    documents: list[dict[str, object]] = []
    versions: list[dict[str, object]] = []
    rows: list[dict[str, object]] = []
    for index, (document_id, published_at) in enumerate(published_ats.items(), start=1):
        documents.append(
            {
                "id": document_id,
                "workspace_id": "ws-1",
                "title": f"title-{document_id}",
                "canonical_url": f"https://example.com/{document_id}",
                "published_at": published_at,
                "source_id": "source-1",
            }
        )
        version_id = f"ver-{document_id}-v1"
        versions.append({"id": version_id, "document_id": document_id})
        rows.append(
            _analysis_row(
                analysis_result_id=f"analysis-{document_id}-current",
                document_version_id=version_id,
                prompt_version="classification-v1",
                reliability_prompt_version="reliability-v1",
                importance_prompt_version="importance-v2",
                ranking_status="completed",
                ranking_score=str(90 + index / 10),
                importance_evaluated_at=(datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=index)).isoformat(),
            )
        )
    return {
        "sources": sources,
        "documents": documents,
        "document_versions": versions,
        "document_analysis_results": rows,
    }


def _analysis_row(
    *,
    analysis_result_id: str,
    document_version_id: str,
    prompt_version: str,
    reliability_prompt_version: str,
    importance_prompt_version: str,
    ranking_status: str,
    ranking_score: str | None,
    importance_evaluated_at: str | None = None,
    status: str = "completed",
    primary_category: str | None = "제품·기술",
    reliability_status: str = "completed",
    reliability_score: int | None = 80,
    importance_status: str = "completed",
    importance_score: int | None = 85,
    core_summary: str = "핵심 요약",
) -> dict[str, object]:
    return {
        "id": analysis_result_id,
        "workspace_id": "ws-1",
        "document_version_id": document_version_id,
        "status": status,
        "model_name": "classification-model-a",
        "prompt_version": prompt_version,
        "classified_at": "2026-08-02T00:00:00+00:00",
        "primary_category": primary_category,
        "secondary_categories": [],
        "reliability_status": reliability_status,
        "reliability_score": reliability_score,
        "reliability_level": "높음" if reliability_score is not None else None,
        "reliability_model_name": "reliability-model-a",
        "reliability_prompt_version": reliability_prompt_version,
        "reliability_evaluated_at": "2026-08-02T00:10:00+00:00",
        "importance_status": importance_status,
        "importance_score": importance_score,
        "importance_level": "높음" if importance_score is not None else None,
        "importance_model_name": "importance-model-a",
        "importance_prompt_version": importance_prompt_version,
        "importance_evaluated_at": importance_evaluated_at or "2026-08-02T00:20:00+00:00",
        "impact_direction": "중립",
        "time_horizon": "단기",
        "core_summary": core_summary,
        "key_points": ["a", "b", "c"],
        "key_numbers": [],
        "sk_hynix_implication": "시사점",
        "opportunities": [],
        "risks": [],
        "watch_points": [],
        "summary_evidence_refs": [{"document_version_id": document_version_id, "quoted_text": "quote", "supports": ["core_summary"]}],
        "ranking_status": ranking_status,
        "ranking_score": ranking_score,
        "recency_score": 100,
        "ranking_position": 1,
        "selected_for_report": True,
        "report_selection_position": 1,
        "selection_reason": "SELECTED",
        "ranking_formula_version": "ranking-v1",
        "ranking_reference_time": "2026-08-02T00:00:00+00:00",
        "ranking_batch_date": "2026-08-02",
        "ranked_at": "2026-08-02T00:30:00+00:00",
        "ranking_detail": {},
        "created_at": "2026-08-02T00:00:00+00:00",
        "updated_at": "2026-08-02T00:00:00+00:00",
    }


def _coerce_value(value):
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    return value


# Tests for get_recently_analyzed_candidates


def _completed_analysis_row_for_recent(*, document_version_id: str, importance_evaluated_at: str, ranking_score: str = "80.00") -> dict:
    return {
        "id": f"analysis-{document_version_id}",
        "workspace_id": "ws-1",
        "document_version_id": document_version_id,
        "status": "completed",
        "reliability_status": "completed",
        "importance_status": "completed",
        "ranking_status": "completed",
        "ranking_score": ranking_score,
        "reliability_score": 80,
        "reliability_level": "높음",
        "importance_score": 85,
        "importance_level": "높음",
        "importance_evaluated_at": importance_evaluated_at,
        "reliability_evaluated_at": importance_evaluated_at,
        "classified_at": importance_evaluated_at,
        "primary_category": "제품·기술",
        "secondary_categories": [],
        "core_summary": "핵심 요약",
        "sk_hynix_implication": "시사점",
        "impact_direction": "중립",
        "time_horizon": "단기",
        "prompt_version": "classification-v1",
        "model_name": "classification-model-a",
        "reliability_prompt_version": "reliability-v1",
        "reliability_model_name": "reliability-model-a",
        "importance_prompt_version": "importance-v2",
        "importance_model_name": "importance-model-a",
        "key_points": ["포인트1", "포인트2", "포인트3"],
        "key_numbers": [],
        "summary_evidence_refs": [{"document_version_id": document_version_id, "quoted_text": "인용문", "supports": ["core_summary"]}],
        "affected_areas": [],
        "opportunities": [],
        "risks": [],
        "watch_points": [],
        "importance_missing_information": [],
        "reliability_detail": {},
        "importance_detail": {},
        "selected_for_report": True,
        "report_selection_position": 1,
        "selection_reason": "SELECTED",
        "ranking_detail": {},
        "ranking_formula_version": "ranking-v1",
        "ranking_reference_time": importance_evaluated_at,
        "ranking_batch_date": "2026-08-02",
        "ranked_at": importance_evaluated_at,
        "recency_score": 100,
        "ranking_position": 1,
        "created_at": importance_evaluated_at,
        "updated_at": importance_evaluated_at,
    }


def _tables_for_recent(analysis_rows: list[dict]) -> dict:
    document_version_ids = [row["document_version_id"] for row in analysis_rows]
    return {
        "document_analysis_results": analysis_rows,
        "document_versions": [
            {"id": dvid, "document_id": f"doc-{dvid}"} for dvid in document_version_ids
        ],
        "documents": [
            {"id": f"doc-{dvid}", "title": f"제목-{dvid}", "canonical_url": None, "published_at": None, "source_id": None}
            for dvid in document_version_ids
        ],
        "sources": [],
    }


def test_get_recently_analyzed_candidates_excludes_rows_before_since():
    from src.report.candidate_provider import get_recently_analyzed_candidates

    now = datetime.now(timezone.utc)
    recent = (now - timedelta(hours=1)).isoformat()
    old = (now - timedelta(hours=5)).isoformat()
    analysis_rows = [
        _completed_analysis_row_for_recent(document_version_id="dv-recent", importance_evaluated_at=recent),
        _completed_analysis_row_for_recent(document_version_id="dv-old", importance_evaluated_at=old),
    ]
    supabase = FakeSupabase(_tables_for_recent(analysis_rows))

    candidates = get_recently_analyzed_candidates(
        workspace_id="ws-1", since=now - timedelta(hours=2), supabase=supabase,
    )

    assert [c.document_version_id for c in candidates] == ["dv-recent"]


def test_get_recently_analyzed_candidates_excludes_incomplete_status():
    from src.report.candidate_provider import get_recently_analyzed_candidates

    now = datetime.now(timezone.utc)
    recent = (now - timedelta(hours=1)).isoformat()
    incomplete_row = _completed_analysis_row_for_recent(document_version_id="dv-incomplete", importance_evaluated_at=recent)
    incomplete_row["ranking_status"] = "pending"
    incomplete_row["ranking_score"] = None
    analysis_rows = [incomplete_row]
    supabase = FakeSupabase(_tables_for_recent(analysis_rows))

    candidates = get_recently_analyzed_candidates(
        workspace_id="ws-1", since=now - timedelta(hours=2), supabase=supabase,
    )

    assert candidates == []


def test_get_recently_analyzed_candidates_returns_empty_when_no_rows():
    from src.report.candidate_provider import get_recently_analyzed_candidates

    supabase = FakeSupabase({"document_analysis_results": [], "document_versions": [], "documents": [], "sources": []})
    candidates = get_recently_analyzed_candidates(
        workspace_id="ws-1", since=datetime.now(timezone.utc) - timedelta(hours=2), supabase=supabase,
    )
    assert candidates == []

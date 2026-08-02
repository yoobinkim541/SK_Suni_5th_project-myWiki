from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.analysis.repository import (
    get_ranked_results_for_report,
    get_ranking_candidates,
    get_ranking_results,
    save_ranking_results,
)
from src.analysis.ranking import get_ranked_results_for_report_data, rank_analysis_results
from src.analysis.ranking_models import RankingCandidate, RankedAnalysisResult


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
        self._limit = None
        self._action = "select"
        self._payload = None

    def select(self, _fields):
        self._action = "select"
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def in_(self, field, values):
        self.in_filters.append((field, set(values)))
        return self

    def order(self, field, desc=False):
        self.ordering.append((field, desc))
        return self

    def limit(self, value):
        self._limit = value
        return self

    def update(self, payload):
        self._action = "update"
        self._payload = dict(payload)
        return self

    def execute(self):
        if self._action == "update":
            rows = self.rows
            for field, value in self.filters:
                rows = [row for row in rows if row.get(field) == value]
            updated = []
            for row in rows:
                row.update(self._payload)
                updated.append(dict(row))
            return FakeResult(updated)

        rows = [dict(row) for row in self.rows]
        for field, value in self.filters:
            rows = [row for row in rows if row.get(field) == value]
        for field, values in self.in_filters:
            rows = [row for row in rows if row.get(field) in values]
        for field, desc in reversed(self.ordering):
            rows.sort(key=lambda row: row.get(field) or "", reverse=desc)
        if self._limit is not None:
            rows = rows[: self._limit]
        return FakeResult(rows)


class FakeSupabase:
    def __init__(self):
        self.tables = {
            "sources": [{"id": "source-1", "name": "??? ??"}],
            "documents": [{"id": "doc-1", "workspace_id": "ws-1", "title": "HBM ??", "canonical_url": "https://example.com/1", "published_at": "2026-08-02T00:00:00+09:00", "source_id": "source-1"}],
            "document_versions": [{"id": "ver-1", "document_id": "doc-1"}],
            "document_analysis_results": [
                {
                    "id": "analysis-1",
                    "workspace_id": "ws-1",
                    "document_version_id": "ver-1",
                    "status": "completed",
                    "model_name": "classification-model-a",
                    "prompt_version": "classification-v1",
                    "classified_at": "2026-08-02T00:00:00+00:00",
                    "primary_category": "?????",
                    "secondary_categories": ["???????"],
                    "reliability_status": "completed",
                    "reliability_score": 80,
                    "reliability_level": "높음",
                    "reliability_model_name": "reliability-model-a",
                    "reliability_prompt_version": "reliability-v1",
                    "reliability_evaluated_at": "2026-08-02T00:10:00+00:00",
                    "importance_status": "completed",
                    "importance_score": 85,
                    "importance_level": "높음",
                    "importance_model_name": "importance-model-a",
                    "importance_prompt_version": "importance-v2",
                    "importance_evaluated_at": "2026-08-02T00:20:00+00:00",
                    "impact_direction": "중립",
                    "time_horizon": "단기",
                    "core_summary": "??",
                    "key_points": ["a", "b", "c"],
                    "key_numbers": [],
                    "sk_hynix_implication": "??",
                    "opportunities": ["??"],
                    "risks": ["??"],
                    "watch_points": ["??"],
                    "summary_evidence_refs": [{"document_version_id": "ver-1", "quoted_text": "quote", "supports": ["core_summary"]}],
                    "ranking_status": "pending",
                    "ranking_detail": {},
                    "created_at": "2026-08-02T00:00:00+00:00",
                    "updated_at": "2026-08-02T00:00:00+00:00",
                }
            ],
        }

    def table(self, name):
        return FakeTable(self, name)


@pytest.fixture
def fake_supabase() -> FakeSupabase:
    return FakeSupabase()


def test_get_ranking_candidates(fake_supabase: FakeSupabase) -> None:
    candidates = get_ranking_candidates(workspace_id="ws-1", document_version_ids=["ver-1"], supabase=fake_supabase)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.analysis_result_id == "analysis-1"
    assert candidate.title == "HBM ??"
    assert candidate.reliability_score == 80
    assert candidate.importance_score == 85
    assert candidate.core_summary == "??"


def test_get_ranking_candidates_selects_same_completed_analysis_row(fake_supabase: FakeSupabase) -> None:
    fake_supabase.tables["document_analysis_results"].append(
        {
            "id": "analysis-2",
            "workspace_id": "ws-1",
            "document_version_id": "ver-1",
            "status": "completed",
            "model_name": "classification-model-a",
            "prompt_version": "classification-v1",
            "classified_at": "2026-08-02T00:30:00+00:00",
            "primary_category": "?????",
            "secondary_categories": ["???????"],
            "reliability_status": "pending",
            "importance_status": "pending",
            "ranking_status": "pending",
            "ranking_detail": {},
            "created_at": "2026-08-02T00:30:00+00:00",
            "updated_at": "2026-08-02T00:30:00+00:00",
        }
    )
    candidates = get_ranking_candidates(workspace_id="ws-1", document_version_ids=["ver-1"], supabase=fake_supabase)
    assert len(candidates) == 1
    assert candidates[0].analysis_result_id == "analysis-1"


def test_save_and_get_ranking_results(fake_supabase: FakeSupabase) -> None:
    ranked = RankedAnalysisResult(
        analysis_result_id="analysis-1",
        workspace_id="ws-1",
        document_version_id="ver-1",
        title="HBM ??",
        primary_category="?????",
        ranking_status="completed",
        ranking_score=Decimal("85.00"),
        recency_score=100,
        ranking_position=1,
        selected_for_report=True,
        report_selection_position=1,
        selection_reason="SELECTED",
        ranking_formula_version="ranking-v1",
        ranking_reference_time=datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc),
        ranking_batch_date=date(2026, 8, 2),
        ranked_at=datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc),
        ranking_detail={"components": {"importance_score": 85, "reliability_score": 80, "recency_score": 100}},
    )
    save_ranking_results(workspace_id="ws-1", results=[ranked], supabase=fake_supabase)
    results = get_ranking_results(workspace_id="ws-1", ranking_batch_date=date(2026, 8, 2), supabase=fake_supabase)
    assert len(results) == 1
    assert results[0].analysis_result_id == "analysis-1"
    assert results[0].ranking_score == Decimal("85.00")
    assert results[0].selected_for_report is True


def test_get_ranking_results_ignores_newer_unranked_row(fake_supabase: FakeSupabase) -> None:
    fake_supabase.tables["document_analysis_results"][0].update(
        {
            "ranking_status": "completed",
            "ranking_score": "85.00",
            "recency_score": 100,
            "ranking_position": 1,
            "selected_for_report": True,
            "report_selection_position": 1,
            "selection_reason": "SELECTED",
            "ranking_formula_version": "ranking-v1",
            "ranking_reference_time": "2026-08-02T00:00:00+00:00",
            "ranking_batch_date": "2026-08-02",
            "ranked_at": "2026-08-02T00:00:00+00:00",
            "ranking_detail": {"components": {"importance_score": 85, "reliability_score": 80, "recency_score": 100}},
        }
    )
    fake_supabase.tables["document_analysis_results"].append(
        {
            "id": "analysis-2",
            "workspace_id": "ws-1",
            "document_version_id": "ver-1",
            "status": "completed",
            "model_name": "classification-model-a",
            "prompt_version": "classification-v1",
            "classified_at": "2026-08-02T00:30:00+00:00",
            "primary_category": "?????",
            "secondary_categories": ["???????"],
            "reliability_status": "completed",
            "reliability_score": 81,
            "reliability_level": "??",
            "reliability_model_name": "reliability-model-a",
            "reliability_prompt_version": "reliability-v1",
            "reliability_evaluated_at": "2026-08-02T00:31:00+00:00",
            "importance_status": "completed",
            "importance_score": 86,
            "importance_level": "??",
            "importance_model_name": "importance-model-a",
            "importance_prompt_version": "importance-v2",
            "importance_evaluated_at": "2026-08-02T00:32:00+00:00",
            "impact_direction": "??",
            "time_horizon": "??",
            "core_summary": "?? ??",
            "key_points": ["x", "y", "z"],
            "key_numbers": [],
            "sk_hynix_implication": "?? ??",
            "opportunities": [],
            "risks": [],
            "watch_points": [],
            "summary_evidence_refs": [{"document_version_id": "ver-1", "quoted_text": "other", "supports": ["core_summary"]}],
            "ranking_status": "pending",
            "ranking_score": None,
            "recency_score": None,
            "ranking_position": None,
            "selected_for_report": False,
            "report_selection_position": None,
            "selection_reason": None,
            "ranking_exclusion_reason": None,
            "ranking_formula_version": None,
            "ranking_reference_time": None,
            "ranking_batch_date": None,
            "ranked_at": None,
            "ranking_detail": {},
            "created_at": "2026-08-02T00:30:00+00:00",
            "updated_at": "2026-08-02T00:30:00+00:00",
        }
    )
    results = get_ranking_results(workspace_id="ws-1", ranking_batch_date=date(2026, 8, 2), supabase=fake_supabase)
    assert len(results) == 1
    assert results[0].analysis_result_id == "analysis-1"
    assert results[0].ranking_status == "completed"
    assert results[0].ranking_position == 1

def test_save_ranking_results_updates_only_selected_analysis_row(fake_supabase: FakeSupabase) -> None:
    fake_supabase.tables["document_analysis_results"].append(
        {
            "id": "analysis-2",
            "workspace_id": "ws-1",
            "document_version_id": "ver-1",
            "status": "completed",
            "model_name": "classification-model-a",
            "prompt_version": "classification-v1",
            "classified_at": "2026-08-02T00:30:00+00:00",
            "primary_category": "?????",
            "secondary_categories": ["???????"],
            "reliability_status": "pending",
            "importance_status": "pending",
            "ranking_status": "pending",
            "ranking_detail": {"untouched": True},
            "created_at": "2026-08-02T00:30:00+00:00",
            "updated_at": "2026-08-02T00:30:00+00:00",
        }
    )
    ranked = RankedAnalysisResult(
        analysis_result_id="analysis-1",
        workspace_id="ws-1",
        document_version_id="ver-1",
        title="HBM ??",
        primary_category="?????",
        ranking_status="completed",
        ranking_score=Decimal("85.00"),
        recency_score=100,
        ranking_position=1,
        selected_for_report=True,
        report_selection_position=1,
        selection_reason="SELECTED",
        ranking_formula_version="ranking-v1",
        ranking_reference_time=datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc),
        ranking_batch_date=date(2026, 8, 2),
        ranked_at=datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc),
        ranking_detail={"components": {"importance_score": 85, "reliability_score": 80, "recency_score": 100}},
    )
    save_ranking_results(workspace_id="ws-1", results=[ranked], supabase=fake_supabase)
    row_a = next(row for row in fake_supabase.tables["document_analysis_results"] if row["id"] == "analysis-1")
    row_b = next(row for row in fake_supabase.tables["document_analysis_results"] if row["id"] == "analysis-2")
    assert row_a["ranking_status"] == "completed"
    assert row_b["ranking_status"] == "pending"
    assert row_b["ranking_detail"] == {"untouched": True}


class FakeTableNumericRoundTrip(FakeTable):
    """PostgREST가 numeric 컬럼을 JSON number로 돌려줄 때처럼, update 후 저장된
    ranking_score를 문자열이 아닌 float로 코어스해서 반환한다 (예: "85.00" -> 85.0)."""

    def execute(self):
        result = super().execute()
        if self._action == "update":
            for row in result.data:
                if row.get("ranking_score") is not None:
                    row["ranking_score"] = float(row["ranking_score"])
        return result


class FakeSupabaseNumericRoundTrip(FakeSupabase):
    def table(self, name):
        return FakeTableNumericRoundTrip(self, name)


def test_save_ranking_results_tolerates_postgrest_numeric_round_trip() -> None:
    fake_supabase = FakeSupabaseNumericRoundTrip()
    ranked = RankedAnalysisResult(
        analysis_result_id="analysis-1",
        workspace_id="ws-1",
        document_version_id="ver-1",
        title="HBM ??",
        primary_category="?????",
        ranking_status="completed",
        ranking_score=Decimal("85.00"),
        recency_score=100,
        ranking_position=1,
        selected_for_report=True,
        report_selection_position=1,
        selection_reason="SELECTED",
        ranking_formula_version="ranking-v1",
        ranking_reference_time=datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc),
        ranking_batch_date=date(2026, 8, 2),
        ranked_at=datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc),
        ranking_detail={"components": {"importance_score": 85, "reliability_score": 80, "recency_score": 100}},
    )
    # ranking_score="85.00"(str)로 보냈지만 응답은 85.0(float)로 오는 경우에도
    # RANKING_RESULT_INCONSISTENT 없이 저장이 성공해야 한다.
    saved = save_ranking_results(workspace_id="ws-1", results=[ranked], supabase=fake_supabase)
    assert saved[0].ranking_score == Decimal("85.00")


def test_save_ranking_results_missing_analysis_result_id_fails(fake_supabase: FakeSupabase) -> None:
    ranked = RankedAnalysisResult(
        analysis_result_id="missing-analysis",
        workspace_id="ws-1",
        document_version_id="ver-1",
        title="HBM ??",
        primary_category="?????",
        ranking_status="completed",
        ranking_score=Decimal("85.00"),
        recency_score=100,
        ranking_position=1,
        selected_for_report=True,
        report_selection_position=1,
        selection_reason="SELECTED",
        ranking_formula_version="ranking-v1",
        ranking_reference_time=datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc),
        ranking_batch_date=date(2026, 8, 2),
        ranked_at=datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc),
        ranking_detail={"components": {"importance_score": 85, "reliability_score": 80, "recency_score": 100}},
    )
    with pytest.raises(Exception, match="ANALYSIS_RESULT_NOT_FOUND"):
        save_ranking_results(workspace_id="ws-1", results=[ranked], supabase=fake_supabase)


def test_get_ranked_results_for_report(fake_supabase: FakeSupabase) -> None:
    fake_supabase.tables["document_analysis_results"][0].update(
        {
            "ranking_status": "completed",
            "ranking_score": "85.00",
            "recency_score": 100,
            "ranking_position": 1,
            "selected_for_report": True,
            "report_selection_position": 1,
            "selection_reason": "SELECTED",
            "ranking_formula_version": "ranking-v1",
            "ranking_reference_time": "2026-08-02T00:00:00+00:00",
            "ranking_batch_date": "2026-08-02",
            "ranked_at": "2026-08-02T00:00:00+00:00",
            "ranking_detail": {"components": {"importance_score": 85, "reliability_score": 80, "recency_score": 100}},
        }
    )
    results = get_ranked_results_for_report(workspace_id="ws-1", ranking_batch_date=date(2026, 8, 2), supabase=fake_supabase)
    assert len(results) == 1
    assert results[0].analysis_result_id == "analysis-1"
    assert results[0].report_selection_position == 1
    assert "markdown" not in results[0].model_dump()


def test_get_ranked_results_for_report_keeps_same_ranked_row(fake_supabase: FakeSupabase) -> None:
    fake_supabase.tables["document_analysis_results"][0].update(
        {
            "ranking_status": "completed",
            "ranking_score": "85.00",
            "recency_score": 100,
            "ranking_position": 1,
            "selected_for_report": True,
            "report_selection_position": 1,
            "selection_reason": "SELECTED",
            "ranking_formula_version": "ranking-v1",
            "ranking_reference_time": "2026-08-02T00:00:00+00:00",
            "ranking_batch_date": "2026-08-02",
            "ranked_at": "2026-08-02T00:00:00+00:00",
            "ranking_detail": {"components": {"importance_score": 85, "reliability_score": 80, "recency_score": 100}},
        }
    )
    fake_supabase.tables["document_analysis_results"].append(
        {
            "id": "analysis-2",
            "workspace_id": "ws-1",
            "document_version_id": "ver-1",
            "status": "completed",
            "model_name": "classification-model-a",
            "prompt_version": "classification-v1",
            "classified_at": "2026-08-02T00:30:00+00:00",
            "primary_category": "?????",
            "secondary_categories": ["???????"],
            "reliability_status": "completed",
            "reliability_score": 81,
            "reliability_level": "높음",
            "reliability_model_name": "reliability-model-a",
            "reliability_prompt_version": "reliability-v1",
            "reliability_evaluated_at": "2026-08-02T00:31:00+00:00",
            "importance_status": "completed",
            "importance_score": 86,
            "importance_level": "높음",
            "importance_model_name": "importance-model-a",
            "importance_prompt_version": "importance-v2",
            "importance_evaluated_at": "2026-08-02T00:32:00+00:00",
            "impact_direction": "중립",
            "time_horizon": "단기",
            "core_summary": "?? ??",
            "key_points": ["x", "y", "z"],
            "key_numbers": [],
            "sk_hynix_implication": "?? ??",
            "opportunities": [],
            "risks": [],
            "watch_points": [],
            "summary_evidence_refs": [{"document_version_id": "ver-1", "quoted_text": "other", "supports": ["core_summary"]}],
            "ranking_status": "completed",
            "ranking_score": "10.00",
            "recency_score": 20,
            "ranking_position": 9,
            "selected_for_report": False,
            "report_selection_position": None,
            "selection_reason": "CATEGORY_LIMIT",
            "ranking_formula_version": "ranking-v1",
            "ranking_reference_time": "2026-08-02T00:00:00+00:00",
            "ranking_batch_date": "2026-08-02",
            "ranked_at": "2026-08-02T00:00:00+00:00",
            "ranking_detail": {"components": {"importance_score": 86, "reliability_score": 81, "recency_score": 20}},
            "created_at": "2026-08-02T00:30:00+00:00",
            "updated_at": "2026-08-02T00:30:00+00:00",
        }
    )
    results = get_ranked_results_for_report(workspace_id="ws-1", ranking_batch_date=date(2026, 8, 2), supabase=fake_supabase)
    assert len(results) == 1
    assert results[0].analysis_result_id == "analysis-1"
    assert results[0].core_summary == "??"


def test_rank_analysis_results_persists_without_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    candidate = RankingCandidate(
        analysis_result_id="analysis-1",
        workspace_id="ws-1",
        document_version_id="ver-1",
        title="HBM ??",
        primary_category="?????",
        secondary_categories=[],
        canonical_url="https://example.com/1",
        source_name="??? ??",
        published_at=datetime(2026, 8, 2, 7, 0, tzinfo=timezone(timedelta(hours=9))),
        reliability_score=80,
        reliability_level="높음",
        importance_score=85,
        importance_level="높음",
        core_summary="??",
        key_points=["a", "b", "c"],
        key_numbers=[],
        sk_hynix_implication="??",
        opportunities=[],
        risks=[],
        watch_points=[],
        summary_evidence_refs=[{"document_version_id": "ver-1", "quoted_text": "quote", "supports": ["core_summary"]}],
    )
    captured = {}
    monkeypatch.setattr("src.analysis.ranking.get_ranking_candidates", lambda **_: [candidate])
    monkeypatch.setattr("src.analysis.ranking.save_ranking_results", lambda **kwargs: captured.setdefault("results", kwargs["results"]))
    results = rank_analysis_results(
        workspace_id="ws-1",
        document_version_ids=["ver-1"],
        ranking_reference_time=datetime(2026, 8, 2, 8, 0, tzinfo=timezone(timedelta(hours=9))),
    )
    assert len(results) == 1
    assert captured["results"][0].analysis_result_id == "analysis-1"
    assert captured["results"][0].ranking_status == "completed"


def test_report_data_helper_uses_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.analysis.ranking.get_ranked_results_for_report",
        lambda **_: [type("Report", (), {"document_version_id": "ver-1"})()],
    )
    results = get_ranked_results_for_report_data(workspace_id="ws-1", ranking_batch_date=date(2026, 8, 2))
    assert len(results) == 1

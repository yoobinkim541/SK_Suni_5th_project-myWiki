from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.analysis.exceptions import InvalidScoreError
from src.analysis.ranking import rank_analysis_results
from src.analysis.ranking_models import RankingCandidate
from src.analysis.ranking_scoring import calculate_ranking_score, calculate_recency_score, validate_ranking_weights


REFERENCE_TIME = datetime(2026, 8, 2, 8, 0, tzinfo=timezone(timedelta(hours=9)))


def _candidate(
    *,
    document_version_id: str,
    title: str = "title",
    primary_category: str = "제품·기술",
    published_at: datetime | None = None,
    reliability_score: int = 80,
    importance_score: int = 85,
) -> RankingCandidate:
    return RankingCandidate(
        analysis_result_id=f"analysis-{document_version_id}",
        workspace_id="ws-1",
        document_version_id=document_version_id,
        title=title,
        primary_category=primary_category,
        secondary_categories=[],
        canonical_url=f"https://example.com/{document_version_id}",
        source_name="source",
        published_at=published_at,
        reliability_score=reliability_score,
        reliability_level="높음" if reliability_score >= 70 else "보통",
        importance_score=importance_score,
        importance_level="높음" if importance_score >= 70 else "보통",
        core_summary="summary",
        key_points=["a", "b", "c"],
        key_numbers=[],
        sk_hynix_implication="implication",
        opportunities=[],
        risks=[],
        watch_points=[],
        summary_evidence_refs=[{"document_version_id": document_version_id, "quoted_text": "quote", "supports": ["core_summary"]}],
    )


def test_calculate_ranking_score_uses_required_weights() -> None:
    assert calculate_ranking_score(importance_score=85, reliability_score=80, recency_score=100) == Decimal("85.00")


def test_decimal_round_half_up_applied() -> None:
    assert calculate_ranking_score(importance_score=84, reliability_score=80, recency_score=100) == Decimal("84.40")


def test_weight_sum_validation() -> None:
    validate_ranking_weights()


def test_final_score_range_validation() -> None:
    with pytest.raises(InvalidScoreError):
        calculate_ranking_score(importance_score=101, reliability_score=80, recency_score=100)


def test_recency_24_hour_boundary() -> None:
    published_at = REFERENCE_TIME - timedelta(hours=24)
    assert calculate_recency_score(published_at=published_at, reference_time=REFERENCE_TIME).score == 100


def test_recency_48_hour_boundary() -> None:
    published_at = REFERENCE_TIME - timedelta(hours=48)
    assert calculate_recency_score(published_at=published_at, reference_time=REFERENCE_TIME).score == 80


def test_recency_72_hour_boundary() -> None:
    published_at = REFERENCE_TIME - timedelta(hours=72)
    assert calculate_recency_score(published_at=published_at, reference_time=REFERENCE_TIME).score == 60


def test_recency_120_hour_boundary() -> None:
    published_at = REFERENCE_TIME - timedelta(hours=120)
    assert calculate_recency_score(published_at=published_at, reference_time=REFERENCE_TIME).score == 40


def test_missing_published_at_returns_warning() -> None:
    result = calculate_recency_score(published_at=None, reference_time=REFERENCE_TIME)
    assert result.score == 0
    assert result.warnings == ["MISSING_PUBLISHED_AT"]


def test_future_published_at_returns_warning() -> None:
    result = calculate_recency_score(published_at=REFERENCE_TIME + timedelta(hours=1), reference_time=REFERENCE_TIME)
    assert result.score == 100
    assert result.warnings == ["FUTURE_PUBLISHED_AT"]


def test_low_reliability_article_is_excluded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.analysis.ranking.get_ranking_candidates",
        lambda **_: [_candidate(document_version_id="doc-1", reliability_score=39, importance_score=90, published_at=REFERENCE_TIME - timedelta(hours=1))],
    )
    monkeypatch.setattr("src.analysis.ranking.save_ranking_results", lambda **kwargs: kwargs["results"])
    results = rank_analysis_results(workspace_id="ws-1", document_version_ids=["doc-1"], ranking_reference_time=REFERENCE_TIME)
    assert results[0].ranking_status == "excluded"
    assert results[0].ranking_exclusion_reason == "LOW_RELIABILITY"
    assert results[0].ranking_position is None


def test_ranking_does_not_call_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("Ranking must not call OpenRouter")

    monkeypatch.setattr("src.analysis.classifier.create_json_completion", fail_if_called)
    monkeypatch.setattr(
        "src.analysis.ranking.get_ranking_candidates",
        lambda **_: [_candidate(document_version_id="doc-1", reliability_score=80, importance_score=90, published_at=REFERENCE_TIME - timedelta(hours=1))],
    )
    monkeypatch.setattr("src.analysis.ranking.save_ranking_results", lambda **kwargs: kwargs["results"])
    results = rank_analysis_results(workspace_id="ws-1", document_version_ids=["doc-1"], ranking_reference_time=REFERENCE_TIME)
    assert len(results) == 1
    assert results[0].ranking_status == "completed"


def test_reliability_40_included() -> None:
    candidate = _candidate(document_version_id="doc-1", reliability_score=40, importance_score=85, published_at=REFERENCE_TIME - timedelta(hours=1))
    results = _run_rank([candidate])
    assert results[0].ranking_status == "completed"


def test_reliability_69_adds_review_warning() -> None:
    candidate = _candidate(document_version_id="doc-1", reliability_score=69, importance_score=85, published_at=REFERENCE_TIME - timedelta(hours=1))
    results = _run_rank([candidate])
    assert "REVIEW_RECOMMENDED" in results[0].ranking_detail["warnings"]


def test_reliability_70_normal_inclusion() -> None:
    candidate = _candidate(document_version_id="doc-1", reliability_score=70, importance_score=85, published_at=REFERENCE_TIME - timedelta(hours=1))
    results = _run_rank([candidate])
    assert results[0].ranking_status == "completed"
    assert "REVIEW_RECOMMENDED" not in results[0].ranking_detail["warnings"]


def test_tie_breaker_prefers_importance_then_reliability_then_recency_then_document_id() -> None:
    doc_a = _candidate(document_version_id="a", importance_score=80, reliability_score=80, published_at=REFERENCE_TIME - timedelta(hours=1))
    doc_b = _candidate(document_version_id="b", importance_score=85, reliability_score=70, published_at=REFERENCE_TIME - timedelta(hours=1))
    doc_c = _candidate(document_version_id="c", importance_score=85, reliability_score=80, published_at=REFERENCE_TIME - timedelta(hours=30))
    doc_d = _candidate(document_version_id="d", importance_score=85, reliability_score=80, published_at=REFERENCE_TIME - timedelta(hours=1))
    results = _run_rank([doc_a, doc_b, doc_c, doc_d])
    assert [item.document_version_id for item in results if item.ranking_status == "completed"] == ["d", "c", "b", "a"]


def test_category_limit_and_report_limit_are_applied() -> None:
    candidates = [
        _candidate(document_version_id="doc-1", primary_category="제품·기술", published_at=REFERENCE_TIME - timedelta(hours=1)),
        _candidate(document_version_id="doc-2", primary_category="제품·기술", published_at=REFERENCE_TIME - timedelta(hours=2)),
        _candidate(document_version_id="doc-3", primary_category="제품·기술", published_at=REFERENCE_TIME - timedelta(hours=3)),
    ]
    results = _run_rank(candidates, report_limit=2, category_limits={"제품·기술": 1})
    assert results[0].selected_for_report is True
    assert results[0].report_selection_position == 1
    assert results[1].selection_reason == "CATEGORY_LIMIT"
    assert results[2].selection_reason == "CATEGORY_LIMIT"


def test_reuse_existing_results_when_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    candidate = _candidate(document_version_id="doc-1", published_at=REFERENCE_TIME - timedelta(hours=1))
    candidate.existing_ranking_status = "completed"
    candidate.existing_ranking_score = Decimal("85.00")
    candidate.existing_recency_score = 100
    candidate.existing_ranking_position = 1
    candidate.existing_selected_for_report = True
    candidate.existing_report_selection_position = 1
    candidate.existing_selection_reason = "SELECTED"
    candidate.existing_ranking_formula_version = "ranking-v1"
    candidate.existing_ranking_reference_time = REFERENCE_TIME.astimezone(timezone.utc)
    candidate.existing_ranking_batch_date = REFERENCE_TIME.astimezone(timezone.utc).date()
    candidate.existing_ranked_at = REFERENCE_TIME.astimezone(timezone.utc)
    candidate.existing_ranking_detail = {
        "batch_document_version_ids": ["doc-1"],
        "components": {"importance_score": 85, "reliability_score": 80, "recency_score": 100},
        "published_at": candidate.published_at.isoformat(),
    }
    monkeypatch.setattr("src.analysis.ranking.get_ranking_candidates", lambda **_: [candidate])
    monkeypatch.setattr("src.analysis.ranking.save_ranking_results", lambda **_: (_ for _ in ()).throw(AssertionError("should not save")))
    results = rank_analysis_results(workspace_id="ws-1", document_version_ids=["doc-1"], ranking_reference_time=REFERENCE_TIME)
    assert results[0].ranking_score == Decimal("85.00")
    assert results[0].selected_for_report is True


def test_force_true_reranks(monkeypatch: pytest.MonkeyPatch) -> None:
    candidate = _candidate(document_version_id="doc-1", published_at=REFERENCE_TIME - timedelta(hours=1))
    candidate.existing_ranking_status = "completed"
    candidate.existing_ranking_formula_version = "ranking-v1"
    candidate.existing_ranking_reference_time = REFERENCE_TIME.astimezone(timezone.utc)
    candidate.existing_ranking_batch_date = REFERENCE_TIME.astimezone(timezone.utc).date()
    candidate.existing_ranking_detail = {
        "batch_document_version_ids": ["doc-1"],
        "components": {"importance_score": 85, "reliability_score": 80, "recency_score": 100},
        "published_at": candidate.published_at.isoformat(),
    }
    monkeypatch.setattr("src.analysis.ranking.get_ranking_candidates", lambda **_: [candidate])
    monkeypatch.setattr("src.analysis.ranking.save_ranking_results", lambda **kwargs: kwargs["results"])
    results = rank_analysis_results(workspace_id="ws-1", document_version_ids=["doc-1"], ranking_reference_time=REFERENCE_TIME, force=True)
    assert results[0].ranking_status == "completed"


def _run_rank(candidates: list[RankingCandidate], report_limit: int = 20, category_limits: dict[str, int] | None = None):
    from unittest.mock import patch

    with patch("src.analysis.ranking.get_ranking_candidates", return_value=candidates), patch("src.analysis.ranking.save_ranking_results", side_effect=lambda **kwargs: kwargs["results"]):
        return rank_analysis_results(
            workspace_id="ws-1",
            document_version_ids=[candidate.document_version_id for candidate in candidates],
            ranking_reference_time=REFERENCE_TIME,
            report_limit=report_limit,
            category_limits=category_limits,
        )


from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from scripts.refresh_data_scheduled import is_refresh_due, run_scheduled_refresh
from scripts.run_analysis_pipeline import get_adaptive_analysis_limit, run_analysis_pipeline

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"


def test_is_refresh_due_true_when_never_refreshed():
    assert is_refresh_due(None, 120, now=datetime.now(timezone.utc)) is True


def test_is_refresh_due_false_when_cycle_not_elapsed():
    now = datetime.now(timezone.utc)
    last = (now - timedelta(minutes=30)).isoformat()
    assert is_refresh_due(last, 120, now=now) is False


def test_is_refresh_due_true_when_cycle_elapsed():
    now = datetime.now(timezone.utc)
    last = (now - timedelta(minutes=150)).isoformat()
    assert is_refresh_due(last, 120, now=now) is True


def test_is_refresh_due_true_within_grace_window():
    now = datetime.now(timezone.utc)
    last = (now - timedelta(minutes=105)).isoformat()
    assert is_refresh_due(last, 120, now=now) is True


def test_is_refresh_due_false_just_outside_grace_window():
    now = datetime.now(timezone.utc)
    last = (now - timedelta(minutes=104)).isoformat()
    assert is_refresh_due(last, 120, now=now) is False


def test_adaptive_analysis_limit_expands_only_when_backlog_exceeds_normal_capacity(monkeypatch):
    for function_name in (
        "get_documents_ready_for_ranking",
        "get_documents_ready_for_importance",
        "get_documents_ready_for_reliability",
        "get_documents_ready_for_classification",
    ):
        monkeypatch.setattr(
            f"scripts.run_analysis_pipeline.{function_name}",
            lambda **kwargs: [f"doc-{index}" for index in range(25)],
        )

    assert get_adaptive_analysis_limit("ws-1") == 25

    monkeypatch.setattr(
        "scripts.run_analysis_pipeline.get_documents_ready_for_classification",
        lambda **kwargs: [f"doc-{index}" for index in range(75)],
    )

    assert get_adaptive_analysis_limit("ws-1") == 50

def test_run_analysis_pipeline_prioritizes_report_ready_backlog(monkeypatch):
    calls: list[tuple[str, tuple[str, ...], int]] = []

    monkeypatch.setattr(
        "scripts.run_analysis_pipeline.get_documents_ready_for_ranking",
        lambda *, workspace_id, limit: ["rank-old"] if len([c for c in calls if c[0] == "ranking"]) == 0 else ["rank-new"],
    )
    monkeypatch.setattr(
        "scripts.run_analysis_pipeline.get_documents_ready_for_importance",
        lambda *, workspace_id, limit: ["importance-old"] if len([c for c in calls if c[0] == "importance"]) == 0 else ["importance-new"],
    )
    monkeypatch.setattr(
        "scripts.run_analysis_pipeline.get_documents_ready_for_reliability",
        lambda *, workspace_id, limit: ["reliability-old"] if len([c for c in calls if c[0] == "reliability"]) == 0 else ["reliability-new"],
    )
    monkeypatch.setattr(
        "scripts.run_analysis_pipeline.get_documents_ready_for_classification",
        lambda *, workspace_id, limit: ["classify-new"],
    )
    selected_ids = ["rank-old", "importance-old", "reliability-old", "classify-new"]
    monkeypatch.setattr(
        "scripts.run_analysis_pipeline.select_analysis_candidates",
        lambda workspace_id, *, limit: selected_ids,
    )

    monkeypatch.setattr(
        "scripts.run_analysis_pipeline.rank_analysis_results",
        lambda *, workspace_id, document_version_ids: calls.append(("ranking", tuple(document_version_ids), len(document_version_ids))) or [SimpleNamespace(selected_for_report=True)],
    )
    monkeypatch.setattr(
        "scripts.run_analysis_pipeline.evaluate_and_save_importances",
        lambda *, workspace_id, document_version_ids: calls.append(("importance", tuple(document_version_ids), len(document_version_ids))) or [SimpleNamespace(importance_status="completed")],
    )
    monkeypatch.setattr(
        "scripts.run_analysis_pipeline.evaluate_reliability_for_documents",
        lambda *, workspace_id, document_version_ids: calls.append(("reliability", tuple(document_version_ids), len(document_version_ids))) or [SimpleNamespace(reliability_status="completed")],
    )
    monkeypatch.setattr(
        "scripts.run_analysis_pipeline.classify_document_versions",
        lambda *, workspace_id, document_version_ids: calls.append(("classification", tuple(document_version_ids), len(document_version_ids))) or [SimpleNamespace(status="completed")],
    )

    result = run_analysis_pipeline("ws-1", limit=5)

    assert [name for name, _, _ in calls] == ["classification", "reliability", "importance", "ranking"]
    expected_ids = ("rank-old", "importance-old", "reliability-old", "classify-new")
    assert all(document_version_ids == expected_ids for _, document_version_ids, _ in calls)
    assert result == list(expected_ids)


def test_run_scheduled_refresh_leaves_daily_report_for_08_kst_schedule(monkeypatch):
    steps: list[tuple[str, object]] = []
    now = datetime(2026, 8, 6, 0, 30, tzinfo=timezone.utc)

    monkeypatch.setattr("scripts.refresh_data_scheduled.get_workspace_id", lambda: WORKSPACE_ID)
    monkeypatch.setattr(
        "scripts.refresh_data_scheduled.get_workspace_settings",
        lambda workspace_id: SimpleNamespace(last_data_refresh_at=None, data_refresh_cycle_minutes=120),
    )
    monkeypatch.setattr(
        "scripts.refresh_data_scheduled.run_collect",
        lambda workspace_id, limit, source_id: steps.append(("collect", str(workspace_id))) or {"collected": 1},
    )
    monkeypatch.setattr(
        "scripts.refresh_data_scheduled.run_preprocess",
        lambda workspace_id: steps.append(("preprocess", str(workspace_id))) or {"processed": 1},
    )
    monkeypatch.setattr(
        "scripts.refresh_data_scheduled.get_adaptive_analysis_limit",
        lambda workspace_id: 20,
    )
    monkeypatch.setattr(
        "scripts.refresh_data_scheduled.run_analysis_pipeline",
        lambda workspace_id, limit: steps.append(("analysis", (str(workspace_id), limit))) or ["doc-1"],
    )
    monkeypatch.setattr(
        "scripts.refresh_data_scheduled.mark_data_refreshed",
        lambda workspace_id, at: steps.append(("mark", at.isoformat())),
    )

    assert run_scheduled_refresh(now=now) is True
    assert steps == [
        ("collect", WORKSPACE_ID),
        ("preprocess", WORKSPACE_ID),
        ("analysis", (WORKSPACE_ID, 20)),
        ("mark", now.isoformat()),
    ]


def test_run_analysis_pipeline_returns_none_when_a_stage_fails(monkeypatch):
    monkeypatch.setattr(
        "scripts.run_analysis_pipeline.select_analysis_candidates",
        lambda workspace_id, *, limit: ["candidate-1"],
    )
    monkeypatch.setattr(
        "scripts.run_analysis_pipeline.classify_document_versions",
        lambda **kwargs: [SimpleNamespace(status="completed")],
    )
    monkeypatch.setattr(
        "scripts.run_analysis_pipeline.evaluate_reliability_for_documents",
        lambda **kwargs: [SimpleNamespace(reliability_status="failed")],
    )
    monkeypatch.setattr(
        "scripts.run_analysis_pipeline.evaluate_and_save_importances",
        lambda **kwargs: [SimpleNamespace(importance_status="failed")],
    )
    monkeypatch.setattr(
        "scripts.run_analysis_pipeline.rank_analysis_results",
        lambda **kwargs: [SimpleNamespace(ranking_status="failed", selected_for_report=False)],
    )

    assert run_analysis_pipeline("ws-1", limit=20) is None

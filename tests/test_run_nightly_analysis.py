from datetime import datetime, timedelta, timezone

import pytest

from scripts import run_nightly_analysis as nightly

WORKSPACE_ID = "workspace-1"


def test_case_a_report_window_fills_batch_before_backlog():
    report_window = [f"window-{index}" for index in range(20)]
    backlog = [f"backlog-{index}" for index in range(100)]

    selected = nightly._merge_priority_candidates(report_window, backlog, limit=10)

    assert selected == report_window[:10]


def test_case_b_backlog_fills_remaining_capacity_after_report_window():
    report_window = [f"window-{index}" for index in range(3)]
    backlog = [f"backlog-{index}" for index in range(100)]

    selected = nightly._merge_priority_candidates(report_window, backlog, limit=10)

    assert selected == [*report_window, *backlog[:7]]


def test_case_e_backlog_never_precedes_report_window_candidates():
    report_window = ["window-1", "window-2"]
    backlog = ["backlog-old", "window-2", "backlog-new", "window-1"]

    selected = nightly._merge_priority_candidates(report_window, backlog, limit=4)

    assert selected == ["window-1", "window-2", "backlog-old", "backlog-new"]


@pytest.fixture
def stage_mocks(monkeypatch):
    monkeypatch.setattr(nightly, "STAGE_LIMIT", 10)
    monkeypatch.setattr(nightly, "get_documents_ready_for_reliability", lambda **kwargs: [])
    monkeypatch.setattr(nightly, "get_documents_ready_for_importance", lambda **kwargs: [])
    monkeypatch.setattr(nightly, "get_documents_ready_for_ranking", lambda **kwargs: [])
    monkeypatch.setattr(nightly, "evaluate_reliability_for_documents", lambda **kwargs: [])
    monkeypatch.setattr(nightly, "evaluate_and_save_importances", lambda **kwargs: [])
    monkeypatch.setattr(nightly, "rank_analysis_results", lambda **kwargs: [])

    classified = []

    def fake_classify(*, workspace_id, document_version_ids):
        classified.extend(document_version_ids)
        return []

    monkeypatch.setattr(nightly, "classify_document_versions", fake_classify)
    return classified


def _deadline():
    return datetime.now(timezone.utc) + timedelta(minutes=1)


def test_case_c_completed_report_window_documents_are_not_reanalyzed(monkeypatch, stage_mocks):
    report_pending = ["window-pending"]
    backlog_pending = []

    def fake_ready_for_classification(**kwargs):
        if kwargs.get("restrict_to_document_ids") is not None:
            pending = report_pending[:]
            report_pending.clear()
            return pending
        pending = backlog_pending[:]
        backlog_pending.clear()
        return pending

    monkeypatch.setattr(nightly, "get_documents_ready_for_classification", fake_ready_for_classification)

    stats = nightly.run_prioritized_stages_until_exhausted(
        WORKSPACE_ID,
        _deadline(),
        report_window_document_ids=["window-doc"],
        report_window_version_ids=["window-completed", "window-pending"],
    )

    assert stage_mocks == ["window-pending"]
    assert "window-completed" not in stage_mocks
    assert stats.processed_report_window == 1
    assert stats.processed_backlog == 0


def test_case_d_backlog_is_preserved_when_report_window_has_no_candidates(monkeypatch, stage_mocks):
    report_pending = []
    backlog_pending = [f"backlog-{index}" for index in range(3)]

    def fake_ready_for_classification(**kwargs):
        if kwargs.get("restrict_to_document_ids") is not None:
            return report_pending
        pending = backlog_pending[:]
        backlog_pending.clear()
        return pending

    monkeypatch.setattr(nightly, "get_documents_ready_for_classification", fake_ready_for_classification)

    stats = nightly.run_prioritized_stages_until_exhausted(
        WORKSPACE_ID,
        _deadline(),
        report_window_document_ids=[],
        report_window_version_ids=[],
    )

    assert stage_mocks == ["backlog-0", "backlog-1", "backlog-2"]
    assert stats.processed_report_window == 0
    assert stats.processed_backlog == 3


def test_daily_report_window_helper_is_reused_for_nightly_priority(monkeypatch):
    now = datetime(2026, 8, 8, 15, 36, 37, tzinfo=timezone.utc)
    start, end = nightly.get_daily_report_window(now)

    assert start == datetime(2026, 8, 7, 23, tzinfo=timezone.utc)
    assert end == datetime(2026, 8, 8, 23, tzinfo=timezone.utc)

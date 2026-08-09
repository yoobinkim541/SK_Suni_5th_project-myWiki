from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from scripts.run_daily_report_analysis_catchup import run_daily_report_analysis_catchup

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"
RUN_TIME = datetime(2026, 8, 8, 21, 0, tzinfo=timezone.utc)  # 2026-08-09 06:00 KST


def _ranked(index: int):
    return SimpleNamespace(document_version_id=f"ranked-{index}")


def _candidate(document_version_id: str):
    return SimpleNamespace(document_version_id=document_version_id)


def _candidates(prefix: str, count: int):
    return [_candidate(f"{prefix}-{index}") for index in range(count)]


@pytest.fixture
def base_mocks(monkeypatch):
    monkeypatch.setattr("scripts.run_daily_report_analysis_catchup.get_workspace_id", lambda: WORKSPACE_ID)
    monkeypatch.setattr("scripts.run_daily_report_analysis_catchup.get_adaptive_analysis_limit", lambda workspace_id: 20)

    saved_batches = []
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.save_analysis_batch",
        lambda **kwargs: saved_batches.append(kwargs),
    )
    completed = []
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.mark_analysis_batch_completed",
        lambda **kwargs: completed.append(kwargs),
    )
    insufficient = []
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.mark_analysis_batch_insufficient",
        lambda **kwargs: insufficient.append(kwargs),
    )
    return {"saved_batches": saved_batches, "completed": completed, "insufficient": insufficient}


def _stub_ranking_selected(monkeypatch, count: int = 152):
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_selected_results",
        lambda workspace_id, ranking_batch_date: [_ranked(index) for index in range(count)],
    )


def _stub_window_candidates(monkeypatch, rounds):
    calls = {"n": 0}

    def fake_window_candidates(**kwargs):
        index = min(calls["n"], len(rounds) - 1)
        calls["n"] += 1
        value = rounds[index]
        return value() if callable(value) else value

    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_window_report_candidates",
        fake_window_candidates,
    )
    return calls


def test_case_a_ranking_152_but_window_3_continues_and_does_not_complete(base_mocks, monkeypatch, capsys):
    _stub_ranking_selected(monkeypatch, 152)
    window_three = _candidates("window", 3)
    _stub_window_candidates(monkeypatch, [window_three, window_three, window_three])
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.select_window_analysis_candidates",
        lambda **kwargs: ["window-pending-1", "window-pending-2"],
    )
    pipeline_calls = []
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.run_analysis_pipeline",
        lambda workspace_id, *, limit, document_version_ids: pipeline_calls.append(document_version_ids),
    )

    result = run_daily_report_analysis_catchup(
        now=RUN_TIME,
        min_candidates=6,
        clock=lambda: RUN_TIME,
    )

    assert result == [candidate.document_version_id for candidate in window_three]
    assert pipeline_calls == [["window-pending-1", "window-pending-2"]]
    assert base_mocks["completed"] == []
    assert base_mocks["insufficient"][-1]["workspace_id"] == WORKSPACE_ID
    assert base_mocks["saved_batches"][-1]["document_version_ids"] == result
    output = capsys.readouterr().out
    assert "ranking_selected_total=152" in output
    assert "window_selected=3" in output
    assert "target_candidates=6" in output
    assert "missing_candidates=3" in output
    assert "status=insufficient" in output


def test_case_b_window_7_completes_without_extra_analysis(base_mocks, monkeypatch):
    _stub_ranking_selected(monkeypatch, 152)
    window_seven = _candidates("window", 7)
    _stub_window_candidates(monkeypatch, [window_seven, window_seven])
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.select_window_analysis_candidates",
        lambda **kwargs: pytest.fail("window already has enough candidates"),
    )
    pipeline_calls = []
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.run_analysis_pipeline",
        lambda *args, **kwargs: pipeline_calls.append(kwargs),
    )

    result = run_daily_report_analysis_catchup(now=RUN_TIME, min_candidates=6, clock=lambda: RUN_TIME)

    assert result == [candidate.document_version_id for candidate in window_seven]
    assert pipeline_calls == []
    assert base_mocks["completed"][-1]["workspace_id"] == WORKSPACE_ID
    assert base_mocks["insufficient"] == []


def test_case_c_initial_window_3_then_analysis_reaches_6_completed(base_mocks, monkeypatch):
    _stub_ranking_selected(monkeypatch, 152)
    window_three = _candidates("before", 3)
    window_six = _candidates("after", 6)
    _stub_window_candidates(monkeypatch, [window_three, window_six, window_six])
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.select_window_analysis_candidates",
        lambda **kwargs: ["window-pending-1", "window-pending-2", "window-pending-3"],
    )
    pipeline_calls = []
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.run_analysis_pipeline",
        lambda workspace_id, *, limit, document_version_ids: pipeline_calls.append(document_version_ids),
    )

    result = run_daily_report_analysis_catchup(now=RUN_TIME, min_candidates=6, clock=lambda: RUN_TIME)

    assert pipeline_calls == [["window-pending-1", "window-pending-2", "window-pending-3"]]
    assert result == [candidate.document_version_id for candidate in window_six]
    assert base_mocks["completed"][-1]["workspace_id"] == WORKSPACE_ID
    assert base_mocks["insufficient"] == []


def test_case_d_deadline_with_window_5_is_not_success(base_mocks, monkeypatch):
    _stub_ranking_selected(monkeypatch, 152)
    window_five = _candidates("window", 5)
    _stub_window_candidates(monkeypatch, [window_five])
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.select_window_analysis_candidates",
        lambda **kwargs: pytest.fail("deadline already passed"),
    )

    deadline = RUN_TIME
    result = run_daily_report_analysis_catchup(
        now=RUN_TIME,
        deadline=deadline,
        min_candidates=6,
        clock=lambda: deadline + timedelta(seconds=1),
    )

    assert result == [candidate.document_version_id for candidate in window_five]
    assert base_mocks["completed"] == []
    assert base_mocks["insufficient"][-1]["workspace_id"] == WORKSPACE_ID


def test_case_e_selected_past_documents_outside_window_are_not_counted_or_saved(base_mocks, monkeypatch):
    _stub_ranking_selected(monkeypatch, 152)
    window_three = _candidates("current-window", 3)
    _stub_window_candidates(monkeypatch, [window_three, window_three, window_three])
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.select_window_analysis_candidates",
        lambda **kwargs: ["current-window-pending"],
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.run_analysis_pipeline",
        lambda *args, **kwargs: None,
    )

    result = run_daily_report_analysis_catchup(now=RUN_TIME, min_candidates=6, clock=lambda: RUN_TIME)

    assert result == ["current-window-0", "current-window-1", "current-window-2"]
    assert all(not value.startswith("ranked-") for value in result)
    assert base_mocks["saved_batches"][-1]["document_version_ids"] == result
    assert base_mocks["completed"] == []


def test_selects_only_analysis_candidates_inside_report_window(monkeypatch):
    from scripts.run_daily_report_analysis_catchup import select_window_analysis_candidates

    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_report_window_document_version_ids",
        lambda **kwargs: (["doc-in"], ["v-in", "v-ready"]),
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.select_analysis_candidates",
        lambda workspace_id, limit: ["v-old", "v-in"],
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_documents_ready_for_ranking",
        lambda **kwargs: ["v-ready", "v-old-ready"],
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_documents_ready_for_importance",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_documents_ready_for_reliability",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_documents_ready_for_classification",
        lambda **kwargs: [],
    )

    result = select_window_analysis_candidates(
        workspace_id=WORKSPACE_ID,
        limit=5,
        window_start=RUN_TIME,
        window_end=RUN_TIME + timedelta(hours=1),
    )

    assert result == ["v-in", "v-ready"]

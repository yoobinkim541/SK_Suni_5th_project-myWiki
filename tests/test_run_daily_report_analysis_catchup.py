from datetime import date, datetime, timezone

import pytest

from scripts.run_daily_report_analysis_catchup import (
    _ranking_batch_date_for,
    run_daily_report_analysis_catchup,
)

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"


def _result(doc_id):
    return type("Result", (), {"document_version_id": doc_id})()


@pytest.fixture
def base_mocks(monkeypatch):
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_workspace_id", lambda: WORKSPACE_ID
    )
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
    return {"saved_batches": saved_batches, "completed": completed}


def test_ranking_batch_date_is_one_day_before_report_date():
    assert _ranking_batch_date_for(date(2026, 8, 9)) == date(2026, 8, 8)


def test_skips_pipeline_when_already_enough_candidates(base_mocks, monkeypatch):
    """nightly-analysis만으로 이미 6건 이상 선정돼 있으면 LLM 호출 없이 바로 종료해야 한다
    (구조적 버그 수정 확인 — 여기 후보들은 이 스크립트가 처리한 게 아니라 이미 선정돼 있던 것들)."""
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_selected_results",
        lambda workspace_id, report_date: [_result(f"doc-{i}") for i in range(6)],
    )
    pipeline_calls = []
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.run_analysis_pipeline",
        lambda *a, **k: pipeline_calls.append((a, k)),
    )

    result = run_daily_report_analysis_catchup(
        now=datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc),  # 06:00 KST
        min_candidates=6,
    )

    assert len(result) == 6
    assert pipeline_calls == []
    assert base_mocks["saved_batches"][0]["document_version_ids"] == []  # 시작 시 "running" 마커
    assert base_mocks["saved_batches"][-1]["document_version_ids"] == [f"doc-{i}" for i in range(6)]
    assert base_mocks["completed"][-1]["workspace_id"] == WORKSPACE_ID
    assert base_mocks["completed"][-1]["report_date"] == date(2026, 8, 10)


def test_loops_until_min_candidates_reached(base_mocks, monkeypatch):
    """부족하면 매 라운드 다시 확인하면서 백로그를 이어 처리한다. 최종 결과(6건) 중 2건("a","b")은
    이 실행이 직접 처리하지 않은 것 — nightly-analysis 등 다른 소스에서 이미 선정된 걸 그대로
    포함시키는지(구조적 버그 수정) 확인한다."""
    results_by_round = [
        [_result("a"), _result("b")],
        [_result("a"), _result("b"), _result("c"), _result("d")],
        [_result(f"x{i}") for i in range(6)],
    ]
    call_count = {"n": 0}

    def fake_get_selected(workspace_id, report_date):
        idx = min(call_count["n"], len(results_by_round) - 1)
        call_count["n"] += 1
        return results_by_round[idx]

    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_selected_results", fake_get_selected
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_adaptive_analysis_limit", lambda workspace_id: 20
    )
    candidate_rounds = [["doc-1", "doc-2"], ["doc-3", "doc-4"]]
    select_calls = {"n": 0}

    def fake_select(workspace_id, limit):
        i = select_calls["n"]
        select_calls["n"] += 1
        return candidate_rounds[i] if i < len(candidate_rounds) else []

    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.select_analysis_candidates", fake_select
    )
    pipeline_calls = []
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.run_analysis_pipeline",
        lambda workspace_id, *, limit, document_version_ids: pipeline_calls.append(document_version_ids),
    )

    result = run_daily_report_analysis_catchup(
        now=datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc),
        min_candidates=6,
    )

    assert pipeline_calls == [["doc-1", "doc-2"], ["doc-3", "doc-4"]]
    assert len(result) == 6


def test_stops_when_no_more_candidates(base_mocks, monkeypatch):
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_selected_results",
        lambda workspace_id, report_date: [_result("a")],
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_adaptive_analysis_limit", lambda workspace_id: 20
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.select_analysis_candidates",
        lambda workspace_id, limit: [],
    )
    pipeline_calls = []
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.run_analysis_pipeline",
        lambda *a, **k: pipeline_calls.append(1),
    )

    result = run_daily_report_analysis_catchup(
        now=datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc),
        min_candidates=6,
    )

    assert pipeline_calls == []
    assert len(result) == 1


def test_stops_when_candidates_do_not_change(base_mocks, monkeypatch):
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_selected_results",
        lambda workspace_id, report_date: [_result("a")],
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_adaptive_analysis_limit", lambda workspace_id: 20
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.select_analysis_candidates",
        lambda workspace_id, limit: ["doc-1", "doc-2"],  # 매번 똑같은 후보 — 진행 없음
    )
    pipeline_calls = []
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.run_analysis_pipeline",
        lambda *a, **k: pipeline_calls.append(1),
    )

    run_daily_report_analysis_catchup(
        now=datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc),
        min_candidates=6,
    )

    assert pipeline_calls == [1]  # 첫 라운드만 실행, 두 번째 라운드에서 반복 감지되어 멈춤


def test_stops_at_explicit_deadline(base_mocks, monkeypatch):
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_selected_results",
        lambda workspace_id, report_date: [_result("a")],
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.select_analysis_candidates",
        lambda *a, **k: pytest.fail("마감이 지났으면 호출되면 안 됨"),
    )

    now = datetime(2026, 8, 9, 21, 30, tzinfo=timezone.utc)
    deadline = datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc)  # 이미 지난 마감
    result = run_daily_report_analysis_catchup(now=now, deadline=deadline, min_candidates=6)

    assert len(result) == 1


def test_default_deadline_is_kst_0715_of_report_date(base_mocks, monkeypatch):
    """deadline을 명시하지 않으면 report_date(KST) 07:15가 기본 마감이어야 한다."""
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_selected_results",
        lambda workspace_id, report_date: [_result("a")],
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.select_analysis_candidates",
        lambda *a, **k: pytest.fail("마감이 지났으면 호출되면 안 됨"),
    )

    # UTC 2026-08-09 22:20 = KST 2026-08-10 07:20 — 그날 기본 마감(07:15 KST)을 5분 넘김
    now = datetime(2026, 8, 9, 22, 20, tzinfo=timezone.utc)
    result = run_daily_report_analysis_catchup(now=now, min_candidates=6)

    assert len(result) == 1


def test_falls_back_gracefully_when_ranking_load_fails(base_mocks, monkeypatch):
    """get_ranked_results_for_report가 RankingLoadFailedError를 던지면(DB 조회 실패),
    무한 재시도하지 않고 그 시점까지 알고 있던 상태로 종료해야 한다."""
    from src.analysis.exceptions import RankingLoadFailedError

    call_count = {"n": 0}

    def fake_get_selected(workspace_id, report_date):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return [_result("a"), _result("b")]  # 첫 확인은 성공(2건, 부족)
        raise RankingLoadFailedError("RANKED_REPORT_RESULTS_LOAD_FAILED")  # 이후 실패

    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_selected_results", fake_get_selected
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_adaptive_analysis_limit", lambda workspace_id: 20
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.select_analysis_candidates",
        lambda workspace_id, limit: ["doc-1"],
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.run_analysis_pipeline", lambda *a, **k: None
    )

    result = run_daily_report_analysis_catchup(
        now=datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc),
        min_candidates=6,
    )

    # 두 번째 조회(라운드 처리 후 재확인)에서 실패 -> 첫 조회 때 알고 있던 2건으로 종료
    assert len(result) == 2

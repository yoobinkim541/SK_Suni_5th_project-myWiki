from datetime import date, datetime, timedelta, timezone

import pytest

from scripts.run_daily_report_analysis_catchup import run_daily_report_analysis_catchup

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


def test_skips_pipeline_when_already_enough_candidates(base_mocks, monkeypatch):
    """nightly-analysis만으로 이미 6건 이상 선정돼 있으면 LLM 호출 없이 바로 종료해야 한다
    (구조적 버그 수정 확인 — 여기 후보들은 이 스크립트가 처리한 게 아니라 이미 선정돼 있던 것들)."""
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_selected_results",
        lambda workspace_id, ranking_batch_date: [_result(f"doc-{i}") for i in range(6)],
    )
    pipeline_calls = []
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.run_analysis_pipeline",
        lambda *a, **k: pipeline_calls.append((a, k)),
    )

    result = run_daily_report_analysis_catchup(
        now=datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc),  # 06:00 KST
        min_candidates=6,
        clock=lambda: datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc),  # 마감 전 고정 시간
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

    def fake_get_selected(workspace_id, ranking_batch_date):
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
        clock=lambda: datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc),  # 마감 전 고정 시간 — 여러 라운드 실행
    )

    assert pipeline_calls == [["doc-1", "doc-2"], ["doc-3", "doc-4"]]
    assert len(result) == 6


def test_stops_when_no_more_candidates(base_mocks, monkeypatch):
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_selected_results",
        lambda workspace_id, ranking_batch_date: [_result("a")],
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
        clock=lambda: datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc),  # 마감 전 고정 시간
    )

    assert pipeline_calls == []
    assert len(result) == 1


def test_stops_when_candidates_do_not_change(base_mocks, monkeypatch):
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_selected_results",
        lambda workspace_id, ranking_batch_date: [_result("a")],
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
        clock=lambda: datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc),  # 마감 전 고정 시간 — 두 번째 라운드 진행 후 반복 감지
    )

    assert pipeline_calls == [1]  # 첫 라운드만 실행, 두 번째 라운드에서 반복 감지되어 멈춤


def test_stops_when_candidate_set_is_same_but_order_differs(base_mocks, monkeypatch):
    """select_analysis_candidates 결과가 회차마다 순서만 바뀌어도(집합은 동일) "진행 없음"으로
    감지해서 멈춰야 한다. 후보 스코어링에 매 호출 시각 기준 recency 항이 섞여 있어 내용은
    그대로인데 정렬 순서만 흔들릴 수 있다 — 리스트 동등성 비교였다면 이 경우를 놓쳐 불필요한
    라운드를 한 번 더 돌았을 것(Finding 6)."""
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_selected_results",
        lambda workspace_id, ranking_batch_date: [_result("a")],
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_adaptive_analysis_limit", lambda workspace_id: 20
    )
    candidate_rounds = [["doc-1", "doc-2"], ["doc-2", "doc-1"]]  # 두 번째 라운드: 순서만 반전
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

    run_daily_report_analysis_catchup(
        now=datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc),
        min_candidates=6,
        clock=lambda: datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc),
    )

    # 두 번째 라운드는 첫 라운드와 같은 집합(순서만 다름)이므로 진행 없음으로 감지되어 멈춰야 한다.
    assert pipeline_calls == [["doc-1", "doc-2"]]


def test_stops_at_explicit_deadline(base_mocks, monkeypatch):
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_selected_results",
        lambda workspace_id, ranking_batch_date: [_result("a")],
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.select_analysis_candidates",
        lambda *a, **k: pytest.fail("마감이 지났으면 호출되면 안 됨"),
    )

    deadline = datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc)  # 마감은 고정
    result = run_daily_report_analysis_catchup(
        now=datetime(2026, 8, 9, 20, 30, tzinfo=timezone.utc),  # now는 seed만 역할
        deadline=deadline,
        min_candidates=6,
        clock=lambda: deadline + timedelta(minutes=1),  # 실제 로직에서 사용되는 시간은 마감을 넘김
    )

    assert len(result) == 1


def test_default_deadline_is_kst_0715_of_report_date(base_mocks, monkeypatch):
    """deadline을 명시하지 않으면 report_date(KST) 07:15가 기본 마감이어야 한다."""
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_selected_results",
        lambda workspace_id, ranking_batch_date: [_result("a")],
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.select_analysis_candidates",
        lambda *a, **k: pytest.fail("마감이 지났으면 호출되면 안 됨"),
    )

    # UTC 2026-08-09 22:20 = KST 2026-08-10 07:20 — 그날 기본 마감(07:15 KST)을 5분 넘김
    now = datetime(2026, 8, 9, 22, 20, tzinfo=timezone.utc)
    result = run_daily_report_analysis_catchup(
        now=now,
        min_candidates=6,
        clock=lambda: now + timedelta(minutes=1),  # report_date seed 이후 실제 로직에선 시간이 지나감
    )

    assert len(result) == 1


def test_falls_back_gracefully_when_ranking_load_fails(base_mocks, monkeypatch):
    """get_ranked_results_for_report가 RankingLoadFailedError를 던지면(DB 조회 실패),
    무한 재시도하지 않고 그 시점까지 알고 있던 상태로 종료해야 한다."""
    from src.analysis.exceptions import RankingLoadFailedError

    call_count = {"n": 0}

    def fake_get_selected(workspace_id, ranking_batch_date):
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
        clock=lambda: datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc),  # 마감 전 고정 시간
    )

    # 두 번째(라운드 처리 후 재확인) 및 세 번째(최종 조회) 호출에서 실패 -> 첫 조회 때 알고 있던 2건으로 종료
    assert len(result) == 2


def test_does_not_start_round_without_enough_remaining_budget(base_mocks, monkeypatch):
    """라운드 예산(30분)보다 마감까지 남은 시간이 적으면 run_analysis_pipeline을 아예
    호출하면 안 된다 — 한 라운드가 실측 30분+ 걸릴 수 있어(Finding 2), 시작해버리면
    scheduled-daily-report.yml과 공유하는 concurrency group을 07:30 KST 전에 비우지
    못할 수 있다."""
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_selected_results",
        lambda workspace_id, ranking_batch_date: [_result("a")],
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_adaptive_analysis_limit", lambda workspace_id: 20
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.select_analysis_candidates",
        lambda workspace_id, limit: ["doc-1", "doc-2"],
    )
    pipeline_calls = []
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.run_analysis_pipeline",
        lambda *a, **k: pipeline_calls.append(1),
    )

    now = datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc)
    deadline = now + timedelta(minutes=20)  # 마감까지 20분 — 라운드 예산(30분)보다 적음

    result = run_daily_report_analysis_catchup(
        now=now,
        deadline=deadline,
        min_candidates=6,
        clock=lambda: now,  # 마감 전(20분 남음)이지만 라운드 예산보다는 적은 시점
    )

    assert pipeline_calls == []
    assert len(result) == 1


def test_does_not_mark_completed_when_final_selection_is_empty(base_mocks, monkeypatch):
    """최종 selected_for_report 조회가 빈 목록이면 배치를 completed로 표시하면 안 된다.
    completed로 표시해버리면 generate_daily_report_scheduled.py가
    get_completed_analysis_batch_document_ids()에서 LookupError를 못 받아
    get_recently_analyzed_candidates() 폴백을 못 타고, document_version_ids=[]로
    조용히 빈 리포트를 만들게 된다(Finding 3)."""
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_selected_results",
        lambda workspace_id, ranking_batch_date: [],
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
        clock=lambda: datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc),
    )

    assert result == []
    assert pipeline_calls == []
    assert base_mocks["completed"] == []  # mark_analysis_batch_completed는 절대 호출되면 안 됨
    # "running" 시작 마커 + 최종(빈) 상태 저장은 여전히 일어난다 — save_analysis_batch는 무조건 호출.
    assert len(base_mocks["saved_batches"]) == 2
    assert base_mocks["saved_batches"][-1]["document_version_ids"] == []


def test_finalizes_batch_when_run_analysis_pipeline_raises(base_mocks, monkeypatch):
    """run_analysis_pipeline이 예외를 던져도(예: 랭킹 단계의 AMBIGUOUS_ANALYSIS_RESULT 같은,
    _try_get_selected_results가 이미 처리하는 읽기 경로와 무관한 예외) 함수 전체가 죽지
    않고, 그 라운드까지 DB에 실제로 반영된 상태를 다시 조회해서 배치를 저장/완료해야
    한다(Finding 4) — 그래야 이전 라운드들의 진행 상황이 유실되지 않는다."""

    call_count = {"n": 0}

    def fake_get_selected(workspace_id, ranking_batch_date):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return [_result("a"), _result("b")]  # 라운드 시작 전 확인: 부족(2건)
        # 최종(라운드 실패 이후) 재확인 시점 — 예외 전에 이미 DB에 반영된 진행 상황
        return [_result("a"), _result("b"), _result("c")]

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

    def raise_pipeline(*args, **kwargs):
        raise RuntimeError("AMBIGUOUS_ANALYSIS_RESULT: boom")

    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.run_analysis_pipeline", raise_pipeline
    )

    result = run_daily_report_analysis_catchup(
        now=datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc),
        min_candidates=6,
        clock=lambda: datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc),
    )

    assert result == ["a", "b", "c"]
    assert base_mocks["saved_batches"][-1]["document_version_ids"] == ["a", "b", "c"]
    assert base_mocks["completed"][-1]["workspace_id"] == WORKSPACE_ID


def test_ranking_batch_date_uses_current_utc_date_not_kst_report_date_minus_one(base_mocks, monkeypatch):
    """report_date(KST)에서 하루를 빼는 옛 방식은 이 배치가 KST 00:00~07:15 구간에서 실행된다는
    가정에서만 맞다(Finding 5). workflow_dispatch로 그 구간 밖(예: KST 23:00)에 수동 실행하면
    report_date-1일은 틀린 UTC 날짜가 된다 — 실제로 조회에 쓰인 날짜는 그 순간의 진짜 UTC
    캘린더 날짜(오늘)와 같아야 한다."""
    observed_dates: list[date] = []

    def fake_get_selected(workspace_id, ranking_batch_date):
        observed_dates.append(ranking_batch_date)
        return [_result(f"doc-{i}") for i in range(6)]

    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_selected_results", fake_get_selected
    )

    # UTC 2026-08-09 14:00 = KST 2026-08-09 23:00 — KST 00:00~07:15 창 밖의 수동 실행 시나리오.
    # report_date(KST)는 8/9이므로 옛 방식(report_date - 1일)이면 8/8을 조회했을 것이다.
    now = datetime(2026, 8, 9, 14, 0, tzinfo=timezone.utc)
    result = run_daily_report_analysis_catchup(
        now=now,
        min_candidates=6,
        clock=lambda: now,
    )

    assert len(result) == 6
    assert date(2026, 8, 8) not in observed_dates  # 옛 방식(report_date - 1일)의 결과가 아니어야 함
    assert observed_dates == [date(2026, 8, 9)]  # 그 순간의 실제 UTC 날짜

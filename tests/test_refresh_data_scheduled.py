"""scripts/refresh_data_scheduled.py의 야간 분석 창(NIGHTLY_ANALYSIS_WINDOW_KST) 테스트.

daily-report-analysis-catchup.yml이 06:00 KST 시작, 07:15 KST 내부 마감으로 바뀌면서
(2026-08-09), refresh 쪽이 06:00부터 다시 분석 단계를 켜면 catchup과 같은 문서를
동시에 분석해 LLM 호출을 낭비할 위험이 생겼다 — 창을 07:15 KST까지 넓혀서 막는다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from scripts.refresh_data_scheduled import KST, is_within_nightly_analysis_window, run_scheduled_refresh


@pytest.mark.parametrize(
    "hour,minute,expected",
    [
        (0, 0, True),
        (5, 59, True),
        (6, 0, True),  # 이전 창(00:00-06:00)에서는 여기서 끝났음 — catchup과 겹치던 지점
        (7, 0, True),
        (7, 14, True),
        (7, 15, False),  # 마감(exclusive) — daily-report-analysis-catchup.yml 내부 마감과 동일 시각
        (23, 59, False),
    ],
)
def test_is_within_nightly_analysis_window_covers_extended_end_boundary(hour, minute, expected):
    now_utc = datetime(2026, 8, 9, hour, minute, tzinfo=KST).astimezone(timezone.utc)
    assert is_within_nightly_analysis_window(now_utc) is expected


def test_run_scheduled_refresh_skips_analysis_during_catchup_window(monkeypatch):
    """07:00 KST는 daily-report-analysis-catchup.yml(06:00~07:15 KST)이 아직 돌고 있을
    시간대라 refresh 쪽 분석 단계는 건너뛰어야 한다 — 이전 창(00:00-06:00)에서는
    여기서 실행됐었다(이번에 고친 버그)."""
    monkeypatch.setattr("scripts.refresh_data_scheduled.get_workspace_id", lambda: "00000000-0000-0000-0000-000000000001")
    monkeypatch.setattr(
        "scripts.refresh_data_scheduled.get_workspace_settings",
        lambda workspace_id: SimpleNamespace(
            workspace_id=workspace_id,
            data_refresh_cycle_minutes=30,
            last_data_refresh_at=None,
        ),
    )
    monkeypatch.setattr("scripts.refresh_data_scheduled.run_collect", lambda *a, **k: "collected")
    monkeypatch.setattr("scripts.refresh_data_scheduled.run_preprocess", lambda *a, **k: "preprocessed")
    monkeypatch.setattr("scripts.refresh_data_scheduled.mark_data_refreshed", lambda *a, **k: None)

    analysis_calls = []
    monkeypatch.setattr(
        "scripts.refresh_data_scheduled.run_analysis_pipeline",
        lambda *a, **k: analysis_calls.append(1),
    )

    now = datetime(2026, 8, 9, 7, 0, tzinfo=KST).astimezone(timezone.utc)
    result = run_scheduled_refresh(now=now)

    assert result is True
    assert analysis_calls == []


def test_run_scheduled_refresh_runs_analysis_outside_the_window(monkeypatch):
    """대조군 — 창 밖(예: 12:00 KST)에서는 그대로 분석 단계가 돈다."""
    monkeypatch.setattr("scripts.refresh_data_scheduled.get_workspace_id", lambda: "00000000-0000-0000-0000-000000000001")
    monkeypatch.setattr(
        "scripts.refresh_data_scheduled.get_workspace_settings",
        lambda workspace_id: SimpleNamespace(
            workspace_id=workspace_id,
            data_refresh_cycle_minutes=30,
            last_data_refresh_at=None,
        ),
    )
    monkeypatch.setattr("scripts.refresh_data_scheduled.run_collect", lambda *a, **k: "collected")
    monkeypatch.setattr("scripts.refresh_data_scheduled.run_preprocess", lambda *a, **k: "preprocessed")
    monkeypatch.setattr("scripts.refresh_data_scheduled.mark_data_refreshed", lambda *a, **k: None)
    monkeypatch.setattr("scripts.refresh_data_scheduled.get_adaptive_analysis_limit", lambda workspace_id: 20)

    analysis_calls = []
    monkeypatch.setattr(
        "scripts.refresh_data_scheduled.run_analysis_pipeline",
        lambda workspace_id, *, limit: analysis_calls.append((workspace_id, limit)) or ["doc-1"],
    )

    now = datetime(2026, 8, 9, 12, 0, tzinfo=KST).astimezone(timezone.utc)
    result = run_scheduled_refresh(now=now)

    assert result is True
    assert analysis_calls == [("00000000-0000-0000-0000-000000000001", 20)]

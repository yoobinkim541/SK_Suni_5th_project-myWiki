from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.refresh_data_scheduled import is_refresh_due, is_within_nightly_analysis_window


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
    # elapsed == cycle - GRACE_MINUTES(15): grace 덕분에 이제 due.
    now = datetime.now(timezone.utc)
    last = (now - timedelta(minutes=105)).isoformat()
    assert is_refresh_due(last, 120, now=now) is True


def test_is_refresh_due_false_just_outside_grace_window():
    now = datetime.now(timezone.utc)
    last = (now - timedelta(minutes=104)).isoformat()
    assert is_refresh_due(last, 120, now=now) is False


def test_is_within_nightly_analysis_window_true_at_kst_midnight():
    # KST 00:00 == UTC 전날 15:00
    now_utc = datetime(2026, 8, 6, 15, 0, tzinfo=timezone.utc)
    assert is_within_nightly_analysis_window(now_utc) is True


def test_is_within_nightly_analysis_window_true_just_before_kst_6am():
    # KST 05:59 == UTC 20:59
    now_utc = datetime(2026, 8, 6, 20, 59, tzinfo=timezone.utc)
    assert is_within_nightly_analysis_window(now_utc) is True


def test_is_within_nightly_analysis_window_false_at_kst_6am():
    # KST 06:00 == UTC 21:00 — 야간 배치 창 종료 시각, 낮 스크립트가 다시 분석을 맡는다.
    now_utc = datetime(2026, 8, 6, 21, 0, tzinfo=timezone.utc)
    assert is_within_nightly_analysis_window(now_utc) is False


def test_is_within_nightly_analysis_window_false_during_daytime():
    # KST 오후 2시 == UTC 05:00
    now_utc = datetime(2026, 8, 6, 5, 0, tzinfo=timezone.utc)
    assert is_within_nightly_analysis_window(now_utc) is False

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.refresh_wiki_scheduled import is_refresh_due, is_within_report_critical_window


def test_is_refresh_due_true_when_never_refreshed():
    assert is_refresh_due(None, 360, now=datetime.now(timezone.utc)) is True


def test_is_refresh_due_false_when_cycle_not_elapsed():
    now = datetime.now(timezone.utc)
    last = (now - timedelta(minutes=100)).isoformat()
    assert is_refresh_due(last, 360, now=now) is False


def test_is_refresh_due_true_when_cycle_elapsed():
    now = datetime.now(timezone.utc)
    last = (now - timedelta(minutes=400)).isoformat()
    assert is_refresh_due(last, 360, now=now) is True


def test_is_refresh_due_true_at_exact_boundary():
    now = datetime.now(timezone.utc)
    last = (now - timedelta(minutes=360)).isoformat()
    # GRACE_MINUTES(15)이 있어도 이 케이스는 원래도 True였고 여전히 True — 영향 없음.
    assert is_refresh_due(last, 360, now=now) is True


def test_is_refresh_due_true_within_grace_window():
    # elapsed == cycle - GRACE_MINUTES: grace 덕분에 이제 due.
    now = datetime.now(timezone.utc)
    last = (now - timedelta(minutes=345)).isoformat()
    assert is_refresh_due(last, 360, now=now) is True


def test_is_refresh_due_false_just_outside_grace_window():
    # elapsed == cycle - GRACE_MINUTES - 1: grace 범위 바로 밖이라 아직 not due.
    now = datetime.now(timezone.utc)
    last = (now - timedelta(minutes=344)).isoformat()
    assert is_refresh_due(last, 360, now=now) is False


def test_is_within_report_critical_window_false_just_before_kst_6am():
    # KST 05:59 = UTC 전날 20:59
    now = datetime(2026, 8, 8, 20, 59, tzinfo=timezone.utc)
    assert is_within_report_critical_window(now) is False


def test_is_within_report_critical_window_true_at_kst_6am():
    # KST 06:00 = UTC 전날 21:00 — 구간 시작(포함)
    now = datetime(2026, 8, 8, 21, 0, tzinfo=timezone.utc)
    assert is_within_report_critical_window(now) is True


def test_is_within_report_critical_window_true_just_before_kst_830am():
    # KST 08:29 = UTC 전날 23:29
    now = datetime(2026, 8, 8, 23, 29, tzinfo=timezone.utc)
    assert is_within_report_critical_window(now) is True


def test_is_within_report_critical_window_false_at_kst_830am():
    # KST 08:30 = UTC 전날 23:30 — 구간 끝(제외)
    now = datetime(2026, 8, 8, 23, 30, tzinfo=timezone.utc)
    assert is_within_report_critical_window(now) is False


def test_is_within_report_critical_window_false_at_midday_kst():
    # KST 15:00 = UTC 06:00 — 구간과 무관한 시각
    now = datetime(2026, 8, 9, 6, 0, tzinfo=timezone.utc)
    assert is_within_report_critical_window(now) is False

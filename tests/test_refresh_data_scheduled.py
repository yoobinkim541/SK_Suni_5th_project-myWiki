from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.refresh_data_scheduled import is_refresh_due


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

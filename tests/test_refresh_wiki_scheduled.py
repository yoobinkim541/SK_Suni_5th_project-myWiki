from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.refresh_wiki_scheduled import is_refresh_due


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
    assert is_refresh_due(last, 360, now=now) is True

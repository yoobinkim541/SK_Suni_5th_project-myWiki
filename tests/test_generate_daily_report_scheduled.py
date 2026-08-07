from datetime import datetime, timezone

from scripts.generate_daily_report_scheduled import get_daily_report_window, run_scheduled_daily_report


def test_scheduled_daily_report_uses_korean_date(monkeypatch):
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        "scripts.generate_daily_report_scheduled.get_workspace_id",
        lambda: "00000000-0000-0000-0000-000000000001",
    )
    monkeypatch.setattr(
        "scripts.generate_daily_report_scheduled.get_completed_analysis_batch_document_ids",
        lambda **kwargs: ["doc-version-1"],
    )
    monkeypatch.setattr(
        "scripts.generate_daily_report_scheduled.get_report_candidates",
        lambda **kwargs: [type("Candidate", (), {"document_version_id": "doc-version-1"})()],
    )
    monkeypatch.setattr(
        "scripts.generate_daily_report_scheduled.generate_daily_report_artifacts",
        lambda **kwargs: calls.append(kwargs)
        or {"report_id": "report-1", "version": 1, "status": "completed"},
    )

    result = run_scheduled_daily_report(now=datetime(2026, 8, 6, 23, tzinfo=timezone.utc))

    assert result["report_id"] == "report-1"
    assert calls == [
        {
            "workspace_id": "00000000-0000-0000-0000-000000000001",
            "report_date": datetime(2026, 8, 7, 8, tzinfo=timezone.utc).date(),
            "requested_by": None,
            "analysis_document_version_ids": ["doc-version-1"],
        }
    ]


def test_daily_report_window_is_previous_24_hours_ending_at_08_kst():
    start, end = get_daily_report_window(datetime(2026, 8, 6, 23, tzinfo=timezone.utc))

    assert start == datetime(2026, 8, 5, 23, tzinfo=timezone.utc)
    assert end == datetime(2026, 8, 6, 23, tzinfo=timezone.utc)


def test_scheduled_daily_report_falls_back_to_recent_analysis_when_batch_missing(monkeypatch):
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        "scripts.generate_daily_report_scheduled.get_workspace_id",
        lambda: "00000000-0000-0000-0000-000000000001",
    )
    monkeypatch.setattr(
        "scripts.generate_daily_report_scheduled.get_completed_analysis_batch_document_ids",
        lambda **kwargs: (_ for _ in ()).throw(LookupError("missing batch")),
    )
    monkeypatch.setattr(
        "scripts.generate_daily_report_scheduled.get_recently_analyzed_candidates",
        lambda **kwargs: [type("Candidate", (), {"document_version_id": "doc-version-1"})()],
    )
    monkeypatch.setattr(
        "scripts.generate_daily_report_scheduled.generate_daily_report_artifacts",
        lambda **kwargs: calls.append(kwargs)
        or {"report_id": "report-1", "version": 1, "status": "completed"},
    )

    result = run_scheduled_daily_report(now=datetime(2026, 8, 6, 23, tzinfo=timezone.utc))

    assert result["report_id"] == "report-1"
    assert calls[0]["analysis_document_version_ids"] == ["doc-version-1"]

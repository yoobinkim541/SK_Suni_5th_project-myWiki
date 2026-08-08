from datetime import datetime, timezone

from scripts.generate_daily_report_scheduled import run_scheduled_daily_report


def test_scheduled_report_uses_only_the_completed_analysis_batch(monkeypatch):
    calls: list[dict[str, object]] = []
    now = datetime(2026, 8, 6, 23, tzinfo=timezone.utc)

    monkeypatch.setattr(
        "scripts.generate_daily_report_scheduled.get_workspace_id",
        lambda: "ws-1",
    )
    monkeypatch.setattr(
        "scripts.generate_daily_report_scheduled.get_completed_analysis_batch_document_ids",
        lambda **kwargs: ["batch-document"],
    )
    monkeypatch.setattr(
        "scripts.generate_daily_report_scheduled.get_report_candidates",
        lambda **kwargs: calls.append(kwargs)
        or [type("Candidate", (), {"document_version_id": "batch-document"})()],
    )
    monkeypatch.setattr(
        "scripts.generate_daily_report_scheduled.generate_daily_report_artifacts",
        lambda **kwargs: {"report_id": "report-1", "version": 1, "status": "completed"},
    )

    run_scheduled_daily_report(now=now)

    assert calls == [
        {
            "workspace_id": "ws-1",
            "report_date": datetime(2026, 8, 7, 8, tzinfo=timezone.utc).date(),
            "document_version_ids": ["batch-document"],
            "published_from": datetime(2026, 8, 5, 23, tzinfo=timezone.utc),
            "published_to": datetime(2026, 8, 6, 23, tzinfo=timezone.utc),
        }
    ]


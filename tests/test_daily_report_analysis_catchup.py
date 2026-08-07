from datetime import datetime, timezone

from scripts.run_daily_report_analysis_catchup import run_daily_report_analysis_catchup
from scripts.generate_daily_report_scheduled import run_scheduled_daily_report


def test_daily_report_catchup_records_and_completes_the_selected_batch(monkeypatch):
    events: list[tuple[str, object]] = []
    now = datetime(2026, 8, 6, 22, tzinfo=timezone.utc)

    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_workspace_id",
        lambda: "ws-1",
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_adaptive_analysis_limit",
        lambda workspace_id: 34,
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.select_analysis_candidates",
        lambda workspace_id, *, limit: ["old-pending", "new-document"],
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.save_analysis_batch",
        lambda **kwargs: events.append(("saved", kwargs)),
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.run_analysis_pipeline",
        lambda workspace_id, *, limit, document_version_ids: events.append(
            ("analyzed", (workspace_id, limit, document_version_ids))
        )
        or document_version_ids,
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.mark_analysis_batch_completed",
        lambda **kwargs: events.append(("completed", kwargs)),
    )

    assert run_daily_report_analysis_catchup(now=now) == ["old-pending", "new-document"]
    assert events[0][1]["document_version_ids"] == ["old-pending", "new-document"]
    assert events[1] == ("analyzed", ("ws-1", 34, ["old-pending", "new-document"]))
    assert events[2][0] == "completed"


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


from __future__ import annotations

import sys
import types
from datetime import date

import pytest
from fastapi.testclient import TestClient

if "pywebpush" not in sys.modules:
    pywebpush_stub = types.ModuleType("pywebpush")
    pywebpush_stub.WebPushException = Exception
    pywebpush_stub.webpush = lambda *args, **kwargs: None
    sys.modules["pywebpush"] = pywebpush_stub

from src.api import db
from src.api.auth import get_current_user
from src.api.main import app
from src.report import service as report_service
from src.report.models import ArtifactType

WORKSPACE_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def client(monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: {"id": "user-1"}
    monkeypatch.setattr(db, "get_default_workspace_id", lambda user_id: WORKSPACE_ID)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_get_daily_report_returns_service_result(client, monkeypatch):
    monkeypatch.setattr(
        report_service,
        "get_daily_report",
        lambda workspace_id, report_date, **kwargs: {
            "report_id": "report-1",
            "workspace_id": workspace_id,
            "report_key": "daily:11111111-1111-1111-1111-111111111111:2026-08-05",
            "version": 1,
            "title": "일일 산업 동향 보고서",
            "report_type": "daily",
            "status": "completed",
            "date": report_date.isoformat(),
            "created_at": "2026-08-05T09:00:00+09:00",
            "completed_at": "2026-08-05T09:05:00+09:00",
            "sections": [],
        },
    )

    res = client.get("/reports/daily?date=2026-08-05")

    assert res.status_code == 200
    assert res.json()["report_id"] == "report-1"
    assert res.json()["date"] == "2026-08-05"


def test_get_daily_report_returns_404_when_missing(client, monkeypatch):
    monkeypatch.setattr(report_service, "get_daily_report", lambda workspace_id, report_date, **kwargs: None)

    res = client.get("/reports/daily?date=2026-08-05")

    assert res.status_code == 404


def test_generate_daily_report_returns_generation_result(client, monkeypatch):
    def fake_generate(**kwargs):
        assert kwargs["workspace_id"] == WORKSPACE_ID
        assert kwargs["report_date"] == date(2026, 8, 5)
        assert kwargs["max_sections"] == 3
        assert kwargs["language"] == "ko"
        assert kwargs["requested_by"] == "user-1"
        assert kwargs["formats"] is None
        return {
            "report_id": "report-1",
            "workspace_id": WORKSPACE_ID,
            "report_key": f"daily:{WORKSPACE_ID}:2026-08-05",
            "version": 1,
            "title": "일일 산업 동향 보고서",
            "report_type": "daily",
            "status": "completed",
            "date": "2026-08-05",
            "artifact_id": "artifact-pdf",
            "artifact_type": "pdf",
            "artifact_object_key": "ws/reports/report-1/pdf/v1.pdf",
            "artifacts": [
                {
                    "artifact_id": "artifact-pdf",
                    "report_id": "report-1",
                    "artifact_type": "pdf",
                    "object_key": "ws/reports/report-1/pdf/v1.pdf",
                    "version": 1,
                    "mime_type": "application/pdf",
                    "file_size": 100,
                    "created_at": None,
                },
                {
                    "artifact_id": "artifact-docx",
                    "report_id": "report-1",
                    "artifact_type": "docx",
                    "object_key": "ws/reports/report-1/docx/v1.docx",
                    "version": 1,
                    "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "file_size": 100,
                    "created_at": None,
                },
                {
                    "artifact_id": "artifact-pptx",
                    "report_id": "report-1",
                    "artifact_type": "pptx",
                    "object_key": "ws/reports/report-1/pptx/v1.pptx",
                    "version": 1,
                    "mime_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    "file_size": 100,
                    "created_at": None,
                },
            ],
        }

    monkeypatch.setattr(report_service, "generate_daily_report_artifacts", fake_generate)

    res = client.post("/reports/daily/generate", json={"date": "2026-08-05", "max_sections": 3})

    assert res.status_code == 200
    assert res.json()["report_id"] == "report-1"
    assert [artifact["artifact_type"] for artifact in res.json()["artifacts"]] == ["pdf", "docx", "pptx"]


def test_generate_daily_report_returns_400_for_bad_format(client, monkeypatch):
    def fake_generate(**kwargs):
        raise ValueError("Unsupported report format: csv")

    monkeypatch.setattr(report_service, "generate_daily_report_artifacts", fake_generate)

    res = client.post("/reports/daily/generate", json={"date": "2026-08-05", "formats": ["csv"]})

    assert res.status_code == 400
    assert "Unsupported report format" in res.json()["detail"]


def test_generate_daily_report_returns_502_when_generation_fails(client, monkeypatch):
    def fake_generate(**kwargs):
        raise RuntimeError("pipeline failed")

    monkeypatch.setattr(report_service, "generate_daily_report_artifacts", fake_generate)

    res = client.post("/reports/daily/generate", json={"date": "2026-08-05"})

    assert res.status_code == 502
    assert res.json()["detail"] == "failed to generate daily report"


def test_download_daily_report_returns_artifact_response(client, monkeypatch):
    def fake_download(workspace_id: str, report_date: date, artifact_format: str, **kwargs):
        assert workspace_id == WORKSPACE_ID
        assert report_date == date(2026, 8, 5)
        assert artifact_format == "pdf"
        return report_service.DailyReportDownload(
            report_id="report-1",
            version=2,
            artifact_type=ArtifactType.PDF,
            filename="daily-report-2026-08-05-v2.pdf",
            mime_type="application/pdf",
            payload=b"%PDF-report-bytes",
        )

    monkeypatch.setattr(report_service, "get_daily_report_download", fake_download)

    res = client.get("/reports/daily/download?date=2026-08-05&format=pdf")

    assert res.status_code == 200
    assert res.content == b"%PDF-report-bytes"
    assert res.headers["content-type"].startswith("application/pdf")
    assert 'filename="daily-report-2026-08-05-v2.pdf"' in res.headers["content-disposition"]


def test_download_daily_report_returns_400_for_unsupported_format(client, monkeypatch):
    def fake_download(*args, **kwargs):
        raise ValueError("Unsupported report format: csv")

    monkeypatch.setattr(report_service, "get_daily_report_download", fake_download)

    res = client.get("/reports/daily/download?date=2026-08-05&format=csv")

    assert res.status_code == 400
    assert "Unsupported report format" in res.json()["detail"]


def test_download_daily_report_returns_404_when_artifact_missing(client, monkeypatch):
    monkeypatch.setattr(report_service, "get_daily_report_download", lambda *args, **kwargs: None)

    res = client.get("/reports/daily/download?date=2026-08-05&format=pdf")

    assert res.status_code == 404


def test_download_daily_report_returns_502_when_storage_download_fails(client, monkeypatch):
    def fake_download(*args, **kwargs):
        raise report_service.ReportDownloadError("storage failed")

    monkeypatch.setattr(report_service, "get_daily_report_download", fake_download)

    res = client.get("/reports/daily/download?date=2026-08-05&format=pdf")

    assert res.status_code == 502
    assert res.json()["detail"] == "failed to download daily report artifact"

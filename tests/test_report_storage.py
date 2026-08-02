from src.report.storage import (
    DEFAULT_REPORT_ARTIFACT_BUCKET,
    build_report_artifact_object_key,
    build_report_artifact_storage_key,
)


def test_report_artifact_bucket_and_keys() -> None:
    assert DEFAULT_REPORT_ARTIFACT_BUCKET == "reports"
    assert build_report_artifact_object_key(
        workspace_id="ws-1",
        report_id="report-1",
        artifact_type="markdown",
        version=3,
    ) == "ws-1/report-1/markdown/v3.markdown"
    assert build_report_artifact_storage_key(
        workspace_id="ws-1",
        report_id="report-1",
        artifact_type="markdown",
        version=3,
        extension="md",
    ) == "reports/ws-1/report-1/markdown/v3.md"

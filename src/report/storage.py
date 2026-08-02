from __future__ import annotations

DEFAULT_REPORT_ARTIFACT_BUCKET = "reports"


def build_report_artifact_object_key(
    *,
    workspace_id: str,
    report_id: str,
    artifact_type: str,
    version: int,
    extension: str | None = None,
) -> str:
    """Build the object path stored inside the reports bucket."""

    normalized_type = artifact_type.strip().lower()
    normalized_ext = (extension or normalized_type).lstrip('.').lower()
    return f"{workspace_id}/{report_id}/{normalized_type}/v{version}.{normalized_ext}"


def build_report_artifact_storage_key(
    *,
    workspace_id: str,
    report_id: str,
    artifact_type: str,
    version: int,
    extension: str | None = None,
) -> str:
    """Build the full storage key including the bucket prefix."""

    object_key = build_report_artifact_object_key(
        workspace_id=workspace_id,
        report_id=report_id,
        artifact_type=artifact_type,
        version=version,
        extension=extension,
    )
    return f"{DEFAULT_REPORT_ARTIFACT_BUCKET}/{object_key}"

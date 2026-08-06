from __future__ import annotations

from copy import deepcopy
from io import BytesIO
from datetime import date, datetime, timezone

import pytest
from pypdf import PdfReader

from src.analysis.importance_models import ImpactDirection, TimeHorizon
from src.analysis.models import Category
from src.report.artifact_service import (
    DEFAULT_REPORT_ARTIFACT_BUCKET,
    MARKDOWN_CONTENT_TYPE,
    ReportArtifactConflictError,
    ReportArtifactError,
    ReportArtifactUploadError,
    build_report_artifact_object_key,
    compute_markdown_content_hash,
    _render_generated_report_pdf,
    create_and_save_markdown_artifact,
    encode_markdown_payload,
    save_markdown_report_artifact,
)
from src.report.models import (
    GeneratedReport,
    ReportCitationDraft,
    ReportSectionDraft,
    ReportSectionStatus,
    ReportStatus,
    ReportType,
    ReportWikiReferenceDraft,
)
from src.report.repository import get_report_artifact


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, supabase: "FakeSupabase", name: str):
        self.supabase = supabase
        self.name = name
        self.rows = supabase.tables.setdefault(name, [])
        self.eq_filters: list[tuple[str, object]] = []
        self.insert_rows: list[dict[str, object]] | None = None

    def select(self, _fields: str) -> "FakeTable":
        return self

    def eq(self, field: str, value: object) -> "FakeTable":
        self.eq_filters.append((field, value))
        return self

    def insert(self, rows):
        if isinstance(rows, dict):
            rows = [rows]
        self.insert_rows = [dict(row) for row in rows]
        self.supabase.operations.append(("insert", self.name))
        return self

    def execute(self) -> FakeResult:
        if self.insert_rows is not None:
            if self.name in self.supabase.fail_on_insert_tables:
                raise RuntimeError(f"insert failed for {self.name}")
            inserted: list[dict[str, object]] = []
            for row in self.insert_rows:
                self.supabase._enforce_unique_constraints(self.name, row)
                new_row = dict(row)
                new_row.setdefault("id", f"{self.name}-{len(self.rows) + 1}")
                self.rows.append(new_row)
                inserted.append(dict(new_row))
            return FakeResult(inserted)
        rows = self.rows
        for field, value in self.eq_filters:
            rows = [row for row in rows if row.get(field) == value]
        return FakeResult([dict(row) for row in rows])


class FakeStorageBucket:
    def __init__(self, supabase: "FakeSupabase", bucket_name: str):
        self.supabase = supabase
        self.bucket_name = bucket_name

    def upload(self, *, path: str, file: bytes, file_options: dict[str, object] | None = None):
        if self.supabase.fail_upload:
            raise RuntimeError("upload failed")
        self.supabase.operations.append(("upload", self.bucket_name, path))
        self.supabase.last_upload = {
            "bucket": self.bucket_name,
            "path": path,
            "file": file,
            "file_options": dict(file_options or {}),
        }
        bucket_objects = self.supabase.storage_objects.setdefault(self.bucket_name, {})
        if path in bucket_objects:
            raise RuntimeError("duplicate object")
        bucket_objects[path] = file
        return {"path": path}

    def download(self, path: str) -> bytes:
        self.supabase.operations.append(("download", self.bucket_name, path))
        return self.supabase.storage_objects[self.bucket_name][path]

    def remove(self, paths: list[str]):
        self.supabase.operations.append(("remove", self.bucket_name, tuple(paths)))
        if self.supabase.fail_remove:
            raise RuntimeError("remove failed")
        bucket_objects = self.supabase.storage_objects.setdefault(self.bucket_name, {})
        for path in paths:
            bucket_objects.pop(path, None)
        return {"paths": paths}


class FakeStorage:
    def __init__(self, supabase: "FakeSupabase"):
        self.supabase = supabase

    def from_(self, bucket_name: str) -> FakeStorageBucket:
        self.supabase.used_buckets.append(bucket_name)
        self.supabase.storage_objects.setdefault(bucket_name, {})
        return FakeStorageBucket(self.supabase, bucket_name)


class FakeSupabase:
    def __init__(self):
        self.tables: dict[str, list[dict[str, object]]] = {
            "artifacts": [],
        }
        self.storage = FakeStorage(self)
        self.storage_objects: dict[str, dict[str, bytes]] = {}
        self.fail_on_insert_tables: set[str] = set()
        self.fail_upload = False
        self.fail_remove = False
        self.operations: list[tuple[object, ...]] = []
        self.used_buckets: list[str] = []
        self.last_upload: dict[str, object] | None = None

    def table(self, name: str) -> FakeTable:
        return FakeTable(self, name)

    def _enforce_unique_constraints(self, table_name: str, row: dict[str, object]) -> None:
        if table_name != "artifacts":
            return
        report_key = (row.get("report_id"), row.get("artifact_type"), row.get("version"))
        object_key = row.get("object_key")
        for existing in self.tables["artifacts"]:
            existing_report_key = (
                existing.get("report_id"),
                existing.get("artifact_type"),
                existing.get("version"),
            )
            if existing_report_key == report_key:
                raise RuntimeError("duplicate artifact report/version")
            if existing.get("object_key") == object_key:
                raise RuntimeError("duplicate artifact object_key")


def make_section(issue_key: str = "issue-1") -> ReportSectionDraft:
    return ReportSectionDraft(
        issue_key=issue_key,
        representative_analysis_result_id=f"analysis-{issue_key}",
        category=Category.PRODUCT_TECHNOLOGY,
        importance_score=90,
        impact_direction=ImpactDirection.RISK,
        time_horizon=TimeHorizon.MID_TERM,
        title=f"title-{issue_key}",
        current_summary="summary",
        key_facts=["fact"],
        historical_context=["history"],
        implications=["implication"],
        watch_points=["watch"],
        news_citations=[
            ReportCitationDraft(
                analysis_result_id=f"analysis-{issue_key}",
                document_version_id=f"doc-ver-{issue_key}",
                citation_order=1,
            )
        ],
        wiki_references=[
            ReportWikiReferenceDraft(
                wiki_page_id=f"wiki-page-{issue_key}",
                wiki_version_id=f"wiki-ver-{issue_key}",
                reference_order=1,
            )
        ],
    )


def make_report() -> GeneratedReport:
    return GeneratedReport(
        report_id="report-1",
        workspace_id="ws-001",
        report_date=date(2026, 8, 2),
        report_type=ReportType.DAILY,
        title="Daily report",
        language="ko",
        version=3,
        status=ReportStatus.COMPLETED,
        sections=[make_section()],
        created_at=datetime(2026, 8, 2, 8, 15, tzinfo=timezone.utc),
        generated_at=datetime(2026, 8, 2, 8, 15, tzinfo=timezone.utc),
    )


def test_build_report_artifact_object_key_uses_project_path_rule() -> None:
    object_key = build_report_artifact_object_key(
        workspace_id="ws-001",
        report_id="report-id",
        report_version=3,
    )

    assert object_key == "ws-001/reports/report-id/markdown/v3.md"


def test_encode_markdown_payload_uses_utf8_bytes() -> None:
    markdown = "# 보고서\n한글 본문"

    payload = encode_markdown_payload(markdown)

    assert payload == markdown.encode("utf-8")


def test_compute_markdown_content_hash_is_deterministic() -> None:
    markdown = "# report\nbody"

    assert compute_markdown_content_hash(markdown) == compute_markdown_content_hash(markdown)
    assert compute_markdown_content_hash(markdown) != compute_markdown_content_hash("# report\nchanged")


def test_save_markdown_report_artifact_uploads_and_persists_metadata() -> None:
    supabase = FakeSupabase()
    markdown = "# 보고서\n본문"

    artifact = save_markdown_report_artifact(
        report_id="report-1",
        workspace_id="ws-001",
        report_version=3,
        report_date=date(2026, 8, 2),
        markdown=markdown,
        supabase=supabase,
    )

    assert artifact.report_id == "report-1"
    assert artifact.object_key == "ws-001/reports/report-1/markdown/v3.md"
    assert artifact.mime_type == MARKDOWN_CONTENT_TYPE
    assert artifact.file_size == len(markdown.encode("utf-8"))
    assert artifact.content_hash == compute_markdown_content_hash(markdown)
    assert artifact.storage_bucket == DEFAULT_REPORT_ARTIFACT_BUCKET
    assert supabase.last_upload == {
        "bucket": DEFAULT_REPORT_ARTIFACT_BUCKET,
        "path": "ws-001/reports/report-1/markdown/v3.md",
        "file": markdown.encode("utf-8"),
        "file_options": {
            "content-type": MARKDOWN_CONTENT_TYPE,
            "upsert": "false",
        },
    }
    assert supabase.operations[:2] == [
        ("upload", DEFAULT_REPORT_ARTIFACT_BUCKET, "ws-001/reports/report-1/markdown/v3.md"),
        ("insert", "artifacts"),
    ]


def test_get_report_artifact_reads_saved_metadata() -> None:
    supabase = FakeSupabase()
    save_markdown_report_artifact(
        report_id="report-1",
        workspace_id="ws-001",
        report_version=3,
        report_date=date(2026, 8, 2),
        markdown="# report",
        supabase=supabase,
    )

    artifact = get_report_artifact(
        report_id="report-1",
        artifact_type="markdown",
        version=3,
        supabase=supabase,
    )

    assert artifact is not None
    assert artifact.object_key == "ws-001/reports/report-1/markdown/v3.md"


def test_save_markdown_report_artifact_skips_reupload_for_same_content() -> None:
    supabase = FakeSupabase()
    markdown = "# report\nsame"
    first = save_markdown_report_artifact(
        report_id="report-1",
        workspace_id="ws-001",
        report_version=3,
        report_date=date(2026, 8, 2),
        markdown=markdown,
        supabase=supabase,
    )
    supabase.operations.clear()

    second = save_markdown_report_artifact(
        report_id="report-1",
        workspace_id="ws-001",
        report_version=3,
        report_date=date(2026, 8, 2),
        markdown=markdown,
        supabase=supabase,
    )

    assert second.artifact_id == first.artifact_id
    assert second.content_hash == first.content_hash
    assert supabase.operations == [
        ("download", DEFAULT_REPORT_ARTIFACT_BUCKET, "ws-001/reports/report-1/markdown/v3.md"),
    ]


def test_save_markdown_report_artifact_raises_conflict_for_different_content() -> None:
    supabase = FakeSupabase()
    save_markdown_report_artifact(
        report_id="report-1",
        workspace_id="ws-001",
        report_version=3,
        report_date=date(2026, 8, 2),
        markdown="# report\nsame",
        supabase=supabase,
    )

    with pytest.raises(ReportArtifactConflictError):
        save_markdown_report_artifact(
            report_id="report-1",
            workspace_id="ws-001",
            report_version=3,
            report_date=date(2026, 8, 2),
            markdown="# report\nchanged",
            supabase=supabase,
        )


def test_save_markdown_report_artifact_rejects_blank_markdown() -> None:
    with pytest.raises(ReportArtifactError):
        save_markdown_report_artifact(
            report_id="report-1",
            workspace_id="ws-001",
            report_version=3,
            report_date=date(2026, 8, 2),
            markdown="   ",
            supabase=FakeSupabase(),
        )


def test_save_markdown_report_artifact_stops_before_insert_when_upload_fails() -> None:
    supabase = FakeSupabase()
    supabase.fail_upload = True

    with pytest.raises(ReportArtifactUploadError):
        save_markdown_report_artifact(
            report_id="report-1",
            workspace_id="ws-001",
            report_version=3,
            report_date=date(2026, 8, 2),
            markdown="# report",
            supabase=supabase,
        )

    assert supabase.tables["artifacts"] == []


def test_save_markdown_report_artifact_cleans_up_when_insert_fails() -> None:
    supabase = FakeSupabase()
    supabase.fail_on_insert_tables.add("artifacts")

    with pytest.raises(Exception):
        save_markdown_report_artifact(
            report_id="report-1",
            workspace_id="ws-001",
            report_version=3,
            report_date=date(2026, 8, 2),
            markdown="# report",
            supabase=supabase,
        )

    assert supabase.operations[-1] == (
        "remove",
        DEFAULT_REPORT_ARTIFACT_BUCKET,
        ("ws-001/reports/report-1/markdown/v3.md",),
    )
    assert supabase.storage_objects[DEFAULT_REPORT_ARTIFACT_BUCKET] == {}


def test_save_markdown_report_artifact_preserves_original_insert_error_when_cleanup_fails() -> None:
    supabase = FakeSupabase()
    supabase.fail_on_insert_tables.add("artifacts")
    supabase.fail_remove = True

    with pytest.raises(Exception) as exc_info:
        save_markdown_report_artifact(
            report_id="report-1",
            workspace_id="ws-001",
            report_version=3,
            report_date=date(2026, 8, 2),
            markdown="# report",
            supabase=supabase,
        )

    assert "persist report artifact metadata" in str(exc_info.value).lower()


def test_create_and_save_markdown_artifact_uses_renderer_when_markdown_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    supabase = FakeSupabase()
    report = make_report()

    monkeypatch.setattr(
        "src.report.artifact_service.render_generated_report_markdown",
        lambda value: f"# rendered {value.report_id}",
    )

    artifact = create_and_save_markdown_artifact(report=report, supabase=supabase)

    assert artifact.content_hash == compute_markdown_content_hash("# rendered report-1")
    assert supabase.last_upload is not None
    assert supabase.last_upload["file"] == "# rendered report-1".encode("utf-8")


def test_create_and_save_markdown_artifact_does_not_mutate_inputs() -> None:
    supabase = FakeSupabase()
    report = make_report()
    original_report = deepcopy(report)
    markdown = "# custom markdown"

    create_and_save_markdown_artifact(
        report=report,
        markdown=markdown,
        supabase=supabase,
    )

    assert report == original_report
    assert markdown == "# custom markdown"


def test_different_report_versions_use_different_object_keys() -> None:
    first = build_report_artifact_object_key(
        workspace_id="ws-001",
        report_id="report-1",
        report_version=1,
    )
    second = build_report_artifact_object_key(
        workspace_id="ws-001",
        report_id="report-1",
        report_version=2,
    )

    assert first != second
    assert first.endswith("v1.md")
    assert second.endswith("v2.md")


def test_save_markdown_report_artifact_does_not_create_urls() -> None:
    supabase = FakeSupabase()

    artifact = save_markdown_report_artifact(
        report_id="report-1",
        workspace_id="ws-001",
        report_version=3,
        report_date=date(2026, 8, 2),
        markdown="# report",
        supabase=supabase,
    )

    assert not hasattr(artifact, "signed_url")
    assert not hasattr(artifact, "public_url")


def test_render_generated_report_pdf_includes_llm_analysis_blocks() -> None:
    report = make_report()
    section = report.sections[0]
    section.status = ReportSectionStatus.COMPLETED

    payload = _render_generated_report_pdf(report)
    extracted = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(payload)).pages)

    assert "summary" in extracted
    assert "fact" in extracted
    assert "implication" in extracted
    assert "watch" in extracted

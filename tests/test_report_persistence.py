from __future__ import annotations

import json

import pytest

from src.analysis.importance_models import ImpactDirection, TimeHorizon
from src.analysis.models import Category
from src.report.models import (
    ReportCitationDraft,
    ReportSectionDraft,
    ReportStatus,
    ReportType,
    ReportWikiReferenceDraft,
)
from src.report.repository import (
    ReportPersistenceError,
    create_report_version,
    get_latest_completed_report,
    mark_report_completed,
    save_report_citations,
    save_report_sections,
    save_report_wiki_references,
)


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, supabase: "FakeSupabase", name: str):
        self.supabase = supabase
        self.name = name
        self.rows = supabase.tables.setdefault(name, [])
        self.eq_filters: list[tuple[str, object]] = []
        self.in_filters: list[tuple[str, set[object]]] = []
        self.insert_rows: list[dict[str, object]] | None = None
        self.update_payload: dict[str, object] | None = None
        self.delete_requested = False

    def select(self, _fields: str) -> "FakeTable":
        return self

    def eq(self, field: str, value: object) -> "FakeTable":
        self.eq_filters.append((field, value))
        return self

    def in_(self, field: str, values) -> "FakeTable":
        self.in_filters.append((field, set(values)))
        return self

    def insert(self, rows):
        if isinstance(rows, dict):
            rows = [rows]
        self.insert_rows = [dict(row) for row in rows]
        return self

    def update(self, payload: dict[str, object]) -> "FakeTable":
        self.update_payload = dict(payload)
        return self

    def delete(self) -> "FakeTable":
        self.delete_requested = True
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

        if self.update_payload is not None:
            updated_rows: list[dict[str, object]] = []
            for row in self._filtered_rows():
                row.update(self.update_payload)
                updated_rows.append(dict(row))
            return FakeResult(updated_rows)

        if self.delete_requested:
            to_delete = self._filtered_rows()
            for row in to_delete:
                self.rows.remove(row)
            return FakeResult(to_delete)

        return FakeResult([dict(row) for row in self._filtered_rows()])

    def _filtered_rows(self) -> list[dict[str, object]]:
        rows = self.rows
        for field, value in self.eq_filters:
            rows = [row for row in rows if row.get(field) == value]
        for field, values in self.in_filters:
            rows = [row for row in rows if row.get(field) in values]
        return rows


class FakeSupabase:
    def __init__(self):
        self.tables: dict[str, list[dict[str, object]]] = {
            "reports": [],
            "report_sections": [],
            "report_citations": [],
            "report_wiki_references": [],
        }
        self.fail_on_insert_tables: set[str] = set()

    def table(self, name: str) -> FakeTable:
        return FakeTable(self, name)

    def _enforce_unique_constraints(self, table_name: str, row: dict[str, object]) -> None:
        if table_name == "reports":
            key = (row.get("workspace_id"), row.get("report_key"), row.get("version"))
            for existing in self.tables["reports"]:
                existing_key = (
                    existing.get("workspace_id"),
                    existing.get("report_key"),
                    existing.get("version"),
                )
                if existing_key == key:
                    raise RuntimeError("duplicate report version")
        if table_name == "report_sections":
            issue_key = row.get("issue_key")
            if issue_key is None:
                return
            key = (row.get("report_id"), issue_key)
            for existing in self.tables["report_sections"]:
                existing_issue_key = existing.get("issue_key")
                existing_key = (existing.get("report_id"), existing_issue_key)
                if existing_issue_key is not None and existing_key == key:
                    raise RuntimeError("duplicate report section issue key")
        if table_name == "report_wiki_references":
            key = (row.get("section_id"), row.get("wiki_version_id"))
            for existing in self.tables["report_wiki_references"]:
                existing_key = (existing.get("section_id"), existing.get("wiki_version_id"))
                if existing_key == key:
                    raise RuntimeError("duplicate wiki reference")


def make_section(issue_key: str = "issue-1", *, title: str | None = None) -> ReportSectionDraft:
    return ReportSectionDraft(
        issue_key=issue_key,
        representative_analysis_result_id=f"analysis-{issue_key}",
        category=Category.PRODUCT_TECHNOLOGY,
        importance_score=88,
        impact_direction=ImpactDirection.OPPORTUNITY,
        time_horizon=TimeHorizon.MID_TERM,
        title=title or f"title-{issue_key}",
        current_summary="Current summary",
        key_facts=["Fact"],
        historical_context=["History"],
        implications=["Implication"],
        watch_points=["Watch"],
        news_citations=[
            ReportCitationDraft(
                analysis_result_id=f"analysis-{issue_key}",
                document_version_id=f"doc-ver-{issue_key}",
                citation_order=1,
            )
        ],
        wiki_references=[
            ReportWikiReferenceDraft(
                wiki_page_id=f"wiki-{issue_key}",
                wiki_version_id=f"wiki-ver-{issue_key}",
                reference_order=1,
                similarity_score=0.8,
            )
        ],
    )


def test_create_first_report_version_starts_at_one() -> None:
    supabase = FakeSupabase()

    report = create_report_version(
        workspace_id="ws-1",
        report_key="daily:ws-1:2026-08-02",
        title="Daily report",
        report_type=ReportType.DAILY,
        request_config={"report_date": "2026-08-02"},
        supabase=supabase,
    )

    assert report.version == 1
    assert report.status == ReportStatus.PENDING


def test_create_next_report_version_increments_without_mutating_previous() -> None:
    supabase = FakeSupabase()
    first = create_report_version(
        workspace_id="ws-1",
        report_key="daily:ws-1:2026-08-02",
        title="Daily report v1",
        report_type=ReportType.DAILY,
        request_config={"report_date": "2026-08-02"},
        supabase=supabase,
    )
    second = create_report_version(
        workspace_id="ws-1",
        report_key="daily:ws-1:2026-08-02",
        title="Daily report v2",
        report_type=ReportType.DAILY,
        request_config={"report_date": "2026-08-02"},
        supabase=supabase,
    )

    assert first.version == 1
    assert second.version == 2
    assert first.report_id != second.report_id


def test_failed_version_still_advances_next_version() -> None:
    supabase = FakeSupabase()
    first = create_report_version(
        workspace_id="ws-1",
        report_key="daily:ws-1:2026-08-02",
        title="Daily report v1",
        report_type=ReportType.DAILY,
        request_config={"report_date": "2026-08-02"},
        supabase=supabase,
    )
    mark_report_completed(report_id=first.report_id, supabase=supabase)
    second = create_report_version(
        workspace_id="ws-1",
        report_key="daily:ws-1:2026-08-02",
        title="Daily report v2",
        report_type=ReportType.DAILY,
        request_config={"report_date": "2026-08-02"},
        supabase=supabase,
    )
    supabase.table("reports").update({"status": ReportStatus.FAILED.value}).eq("id", second.report_id).execute()
    third = create_report_version(
        workspace_id="ws-1",
        report_key="daily:ws-1:2026-08-02",
        title="Daily report v3",
        report_type=ReportType.DAILY,
        request_config={"report_date": "2026-08-02"},
        supabase=supabase,
    )

    assert third.version == 3


def test_get_latest_completed_report_ignores_failed_versions() -> None:
    supabase = FakeSupabase()
    first = create_report_version(
        workspace_id="ws-1",
        report_key="daily:ws-1:2026-08-02",
        title="Daily report v1",
        report_type=ReportType.DAILY,
        request_config={"report_date": "2026-08-02"},
        supabase=supabase,
    )
    mark_report_completed(report_id=first.report_id, supabase=supabase)
    second = create_report_version(
        workspace_id="ws-1",
        report_key="daily:ws-1:2026-08-02",
        title="Daily report v2",
        report_type=ReportType.DAILY,
        request_config={"report_date": "2026-08-02"},
        supabase=supabase,
    )
    supabase.table("reports").update({"status": ReportStatus.FAILED.value}).eq("id", second.report_id).execute()
    third = create_report_version(
        workspace_id="ws-1",
        report_key="daily:ws-1:2026-08-02",
        title="Daily report v3",
        report_type=ReportType.DAILY,
        request_config={"report_date": "2026-08-02"},
        supabase=supabase,
    )
    mark_report_completed(report_id=third.report_id, supabase=supabase)

    latest = get_latest_completed_report(
        workspace_id="ws-1",
        report_key="daily:ws-1:2026-08-02",
        supabase=supabase,
    )

    assert latest is not None
    assert latest.version == 3


def test_save_report_sections_persists_issue_key_and_refs() -> None:
    supabase = FakeSupabase()
    saved = save_report_sections(
        report_id="report-1",
        sections=[make_section()],
        supabase=supabase,
        model_name="openai/gpt-4.1-mini",
        prompt_version="report-section-v1",
    )

    assert len(saved) == 1
    section_row = supabase.tables["report_sections"][0]
    content = json.loads(section_row["content"])
    assert section_row["issue_key"] == "issue-1"
    assert section_row["section_order"] == 1
    assert content["issue_key"] == "issue-1"
    assert len(supabase.tables["report_citations"]) == 1
    assert len(supabase.tables["report_wiki_references"]) == 1


def test_same_order_different_issue_does_not_reuse_section() -> None:
    supabase = FakeSupabase()
    save_report_sections(
        report_id="report-1",
        sections=[make_section("issue-a")],
        supabase=supabase,
    )
    save_report_sections(
        report_id="report-1",
        sections=[make_section("issue-b")],
        supabase=supabase,
    )

    assert len(supabase.tables["report_sections"]) == 2
    assert {row["issue_key"] for row in supabase.tables["report_sections"]} == {"issue-a", "issue-b"}


def test_same_issue_different_order_updates_existing_section() -> None:
    supabase = FakeSupabase()
    save_report_sections(
        report_id="report-1",
        sections=[make_section("issue-a"), make_section("issue-b")],
        supabase=supabase,
    )
    save_report_sections(
        report_id="report-1",
        sections=[make_section("issue-b"), make_section("issue-a", title="retitled-issue-a")],
        supabase=supabase,
    )

    assert len(supabase.tables["report_sections"]) == 2
    section_a = next(row for row in supabase.tables["report_sections"] if row["issue_key"] == "issue-a")
    section_b = next(row for row in supabase.tables["report_sections"] if row["issue_key"] == "issue-b")
    assert section_a["section_order"] == 2
    assert section_a["title"] == "retitled-issue-a"
    assert section_b["section_order"] == 1


def test_same_issue_key_in_different_report_versions_creates_new_section() -> None:
    supabase = FakeSupabase()
    save_report_sections(report_id="report-1", sections=[make_section("issue-a")], supabase=supabase)
    save_report_sections(report_id="report-2", sections=[make_section("issue-a")], supabase=supabase)

    assert len(supabase.tables["report_sections"]) == 2
    assert supabase.tables["report_sections"][0]["id"] != supabase.tables["report_sections"][1]["id"]


def test_citations_and_wiki_refs_follow_issue_key_mapping_after_reorder() -> None:
    supabase = FakeSupabase()
    save_report_sections(
        report_id="report-1",
        sections=[make_section("issue-a"), make_section("issue-b")],
        supabase=supabase,
    )
    save_report_sections(
        report_id="report-1",
        sections=[make_section("issue-b"), make_section("issue-a")],
        supabase=supabase,
    )

    section_a = next(row for row in supabase.tables["report_sections"] if row["issue_key"] == "issue-a")
    section_b = next(row for row in supabase.tables["report_sections"] if row["issue_key"] == "issue-b")

    citations_by_section = {row["section_id"]: row["document_version_id"] for row in supabase.tables["report_citations"]}
    wiki_by_section = {row["section_id"]: row["wiki_version_id"] for row in supabase.tables["report_wiki_references"]}

    assert citations_by_section[section_a["id"]] == "doc-ver-issue-a"
    assert citations_by_section[section_b["id"]] == "doc-ver-issue-b"
    assert wiki_by_section[section_a["id"]] == "wiki-ver-issue-a"
    assert wiki_by_section[section_b["id"]] == "wiki-ver-issue-b"


def test_save_report_sections_rejects_missing_wiki_version_id() -> None:
    supabase = FakeSupabase()
    section = make_section()
    section.wiki_references[0].wiki_version_id = None

    with pytest.raises(ReportPersistenceError):
        save_report_sections(report_id="report-1", sections=[section], supabase=supabase)


def test_failed_current_version_does_not_mutate_previous_completed_report() -> None:
    supabase = FakeSupabase()
    previous = create_report_version(
        workspace_id="ws-1",
        report_key="daily:ws-1:2026-08-02",
        title="Daily report v1",
        report_type=ReportType.DAILY,
        request_config={"report_date": "2026-08-02"},
        supabase=supabase,
    )
    mark_report_completed(report_id=previous.report_id, supabase=supabase)
    save_report_sections(report_id=previous.report_id, sections=[make_section("issue-a")], supabase=supabase)

    current = create_report_version(
        workspace_id="ws-1",
        report_key="daily:ws-1:2026-08-02",
        title="Daily report v2",
        report_type=ReportType.DAILY,
        request_config={"report_date": "2026-08-02"},
        supabase=supabase,
    )
    supabase.fail_on_insert_tables.add("report_citations")

    with pytest.raises(ReportPersistenceError):
        save_report_sections(report_id=current.report_id, sections=[make_section("issue-b")], supabase=supabase)

    previous_report_row = next(row for row in supabase.tables["reports"] if row["id"] == previous.report_id)
    current_report_row = next(row for row in supabase.tables["reports"] if row["id"] == current.report_id)
    assert previous_report_row["status"] == ReportStatus.COMPLETED.value
    assert current_report_row["status"] == ReportStatus.FAILED.value


def test_save_report_sections_preserves_display_order_in_return_value() -> None:
    supabase = FakeSupabase()
    saved = save_report_sections(
        report_id="report-1",
        sections=[make_section("issue-b"), make_section("issue-a")],
        supabase=supabase,
    )

    assert [(item.issue_key, item.section_order) for item in saved] == [
        ("issue-b", 1),
        ("issue-a", 2),
    ]


def _section_with_citations(
    issue_key: str,
    citations: list[ReportCitationDraft],
    wiki_references: list[ReportWikiReferenceDraft] | None = None,
) -> ReportSectionDraft:
    section = make_section(issue_key)
    return section.model_copy(update={"news_citations": citations, "wiki_references": wiki_references or []})


def test_save_report_citations_inserts_new_rows() -> None:
    supabase = FakeSupabase()
    saved_sections = save_report_sections(report_id="report-1", sections=[make_section("issue-a")], supabase=supabase)

    save_report_citations(
        section_map=saved_sections,
        sections=[
            _section_with_citations(
                "issue-a",
                [ReportCitationDraft(analysis_result_id="a1", document_version_id="doc-1", citation_order=1)],
            )
        ],
        supabase=supabase,
    )

    assert len(supabase.tables["report_citations"]) == 1
    assert supabase.tables["report_citations"][0]["document_version_id"] == "doc-1"


def test_save_report_citations_removes_stale_rows_on_regeneration() -> None:
    supabase = FakeSupabase()
    saved_sections = save_report_sections(report_id="report-1", sections=[make_section("issue-a")], supabase=supabase)
    save_report_citations(
        section_map=saved_sections,
        sections=[
            _section_with_citations(
                "issue-a",
                [
                    ReportCitationDraft(analysis_result_id="a1", document_version_id="doc-1", citation_order=1),
                    ReportCitationDraft(analysis_result_id="a1", document_version_id="doc-2", citation_order=2),
                ],
            )
        ],
        supabase=supabase,
    )
    assert len(supabase.tables["report_citations"]) == 2

    # 재생성: doc-2는 더 이상 근거가 아니고, doc-3가 새로 추가됨
    save_report_citations(
        section_map=saved_sections,
        sections=[
            _section_with_citations(
                "issue-a",
                [
                    ReportCitationDraft(analysis_result_id="a1", document_version_id="doc-1", citation_order=1),
                    ReportCitationDraft(analysis_result_id="a1", document_version_id="doc-3", citation_order=2),
                ],
            )
        ],
        supabase=supabase,
    )

    remaining = {row["document_version_id"] for row in supabase.tables["report_citations"]}
    assert remaining == {"doc-1", "doc-3"}


def test_save_report_citations_keeps_two_citations_of_same_document() -> None:
    supabase = FakeSupabase()
    saved_sections = save_report_sections(report_id="report-1", sections=[make_section("issue-a")], supabase=supabase)

    save_report_citations(
        section_map=saved_sections,
        sections=[
            _section_with_citations(
                "issue-a",
                [
                    ReportCitationDraft(
                        analysis_result_id="a1", document_version_id="doc-1", citation_order=1, evidence_text="첫 번째 인용"
                    ),
                    ReportCitationDraft(
                        analysis_result_id="a1", document_version_id="doc-1", citation_order=2, evidence_text="두 번째 인용"
                    ),
                ],
            )
        ],
        supabase=supabase,
    )

    quoted_texts = {row["quoted_text"] for row in supabase.tables["report_citations"]}
    assert quoted_texts == {"첫 번째 인용", "두 번째 인용"}


def test_save_report_wiki_references_removes_stale_rows_on_regeneration() -> None:
    supabase = FakeSupabase()
    saved_sections = save_report_sections(report_id="report-1", sections=[make_section("issue-a")], supabase=supabase)
    save_report_wiki_references(
        section_map=saved_sections,
        sections=[
            _section_with_citations(
                "issue-a",
                [],
                [
                    ReportWikiReferenceDraft(
                        wiki_page_id="wiki-1", wiki_version_id="wiki-ver-1", reference_order=1, similarity_score=0.9
                    )
                ],
            )
        ],
        supabase=supabase,
    )
    assert len(supabase.tables["report_wiki_references"]) == 1

    # 재생성: wiki-ver-1이 더 이상 근거가 아니고 wiki-ver-2로 교체됨
    save_report_wiki_references(
        section_map=saved_sections,
        sections=[
            _section_with_citations(
                "issue-a",
                [],
                [
                    ReportWikiReferenceDraft(
                        wiki_page_id="wiki-2", wiki_version_id="wiki-ver-2", reference_order=1, similarity_score=0.7
                    )
                ],
            )
        ],
        supabase=supabase,
    )

    remaining = {row["wiki_version_id"] for row in supabase.tables["report_wiki_references"]}
    assert remaining == {"wiki-ver-2"}

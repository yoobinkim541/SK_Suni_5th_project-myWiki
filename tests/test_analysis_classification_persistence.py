from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.analysis.exceptions import (
    ClassificationSaveFailedError,
    MissingApiKeyError,
)
from src.analysis.interface import classify_document_version
from src.analysis.models import Category, ClassificationResult
from src.analysis.repository import (
    get_classification_result,
    get_classification_results,
    get_latest_classification_result,
    save_classification_failure,
    save_classification_result,
)


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, supabase, name):
        self.supabase = supabase
        self.name = name
        self.rows = supabase.tables.setdefault(name, [])
        self.filters = []
        self.in_filters = []
        self.ordering = []
        self._limit = None
        self._action = "select"
        self._payload = None
        self._on_conflict = None

    def select(self, _fields):
        self._action = "select"
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def in_(self, field, values):
        self.in_filters.append((field, set(values)))
        return self

    def order(self, field, desc=False):
        self.ordering.append((field, desc))
        return self

    def limit(self, value):
        self._limit = value
        return self

    def upsert(self, payload, on_conflict):
        self._action = "upsert"
        self._payload = dict(payload)
        self._on_conflict = [item.strip() for item in on_conflict.split(",")]
        return self

    def execute(self):
        if self._action == "upsert":
            if self.supabase.fail_upsert:
                raise RuntimeError("db failure")
            existing = None
            for row in self.rows:
                if all(row.get(key) == self._payload.get(key) for key in self._on_conflict):
                    existing = row
                    break
            now = datetime.now(timezone.utc).isoformat()
            if existing is None:
                row = dict(self._payload)
                row.setdefault("id", f"analysis-{len(self.rows)+1}")
                row.setdefault("created_at", now)
                row.setdefault("updated_at", now)
                self.rows.append(row)
                return FakeResult([dict(row)])
            existing.update(self._payload)
            existing["updated_at"] = now
            return FakeResult([dict(existing)])

        rows = [dict(row) for row in self.rows]
        for field, value in self.filters:
            rows = [row for row in rows if row.get(field) == value]
        for field, values in self.in_filters:
            rows = [row for row in rows if row.get(field) in values]
        for field, desc in reversed(self.ordering):
            rows.sort(key=lambda row: row.get(field) or "", reverse=desc)
        if self._limit is not None:
            rows = rows[: self._limit]
        return FakeResult(rows)


class FakeSupabase:
    def __init__(self):
        self.tables = {
            "documents": [
                {"id": "doc-1", "workspace_id": "ws-1"},
                {"id": "doc-2", "workspace_id": "ws-2"},
            ],
            "document_versions": [
                {"id": "ver-1", "document_id": "doc-1"},
                {"id": "ver-2", "document_id": "doc-2"},
            ],
            "document_analysis_results": [],
        }
        self.fail_upsert = False

    def table(self, name):
        return FakeTable(self, name)



def _classification_result(primary=Category.PRODUCT_TECHNOLOGY, secondary=None, confidence=0.91, reason="ok"):
    return ClassificationResult(
        primary_category=primary,
        secondary_categories=secondary or [],
        confidence=confidence,
        reason=reason,
    )



def test_insert_and_reload_classification_result() -> None:
    fake = FakeSupabase()
    stored = save_classification_result(
        workspace_id="ws-1",
        document_version_id="ver-1",
        result=_classification_result(),
        model_name="model-a",
        prompt_version="classification-v1",
        supabase=fake,
    )
    loaded = get_classification_result(
        workspace_id="ws-1",
        document_version_id="ver-1",
        model_name="model-a",
        prompt_version="classification-v1",
        supabase=fake,
    )
    assert stored.id == loaded.id
    assert loaded.primary_category == Category.PRODUCT_TECHNOLOGY



def test_upsert_same_document_model_prompt() -> None:
    fake = FakeSupabase()
    first = save_classification_result(
        workspace_id="ws-1",
        document_version_id="ver-1",
        result=_classification_result(confidence=0.8),
        model_name="model-a",
        prompt_version="classification-v1",
        supabase=fake,
    )
    second = save_classification_result(
        workspace_id="ws-1",
        document_version_id="ver-1",
        result=_classification_result(confidence=0.95, reason="updated"),
        model_name="model-a",
        prompt_version="classification-v1",
        supabase=fake,
    )
    assert first.id == second.id
    assert len(fake.tables["document_analysis_results"]) == 1
    assert second.classification_confidence == 0.95



def test_get_latest_classification_result() -> None:
    fake = FakeSupabase()
    save_classification_result(workspace_id="ws-1", document_version_id="ver-1", result=_classification_result(reason="first"), model_name="model-a", prompt_version="v1", supabase=fake)
    save_classification_result(workspace_id="ws-1", document_version_id="ver-1", result=_classification_result(reason="second"), model_name="model-b", prompt_version="v2", supabase=fake)
    fake.tables["document_analysis_results"][0]["classified_at"] = "2026-08-02T00:00:00+00:00"
    fake.tables["document_analysis_results"][1]["classified_at"] = "2026-08-02T00:00:01+00:00"
    latest = get_latest_classification_result(workspace_id="ws-1", document_version_id="ver-1", supabase=fake)
    assert latest is not None
    assert latest.model_name == "model-b"



def test_get_classification_results_returns_latest_per_document() -> None:
    fake = FakeSupabase()
    save_classification_result(workspace_id="ws-1", document_version_id="ver-1", result=_classification_result(reason="first"), model_name="model-a", prompt_version="v1", supabase=fake)
    save_classification_result(workspace_id="ws-1", document_version_id="ver-1", result=_classification_result(reason="second"), model_name="model-b", prompt_version="v2", supabase=fake)
    fake.tables["document_analysis_results"][0]["classified_at"] = "2026-08-02T00:00:00+00:00"
    fake.tables["document_analysis_results"][1]["classified_at"] = "2026-08-02T00:00:01+00:00"
    results = get_classification_results(workspace_id="ws-1", document_version_ids=["ver-1"], supabase=fake)
    assert len(results) == 1
    assert results[0].model_name == "model-b"



def test_completed_result_skips_api_recall(monkeypatch: pytest.MonkeyPatch) -> None:
    existing = type("Stored", (), {"status": "completed"})()
    monkeypatch.setattr("src.analysis.interface.validate_document_workspace", lambda **_: {"document_id": "doc-1"})
    monkeypatch.setattr("src.analysis.interface.get_classification_result", lambda **_: existing)
    monkeypatch.setattr("src.analysis.interface.classify_document", lambda **_: (_ for _ in ()).throw(AssertionError("should not call api")))
    monkeypatch.setattr("src.analysis.interface.get_openrouter_settings", lambda: type("S", (), {"model": "model-a"})())
    result = classify_document_version(workspace_id="ws-1", document_version_id="ver-1", force=False)
    assert result is existing



def test_force_true_reclassifies(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}
    monkeypatch.setattr("src.analysis.interface.validate_document_workspace", lambda **_: {"document_id": "doc-1"})
    monkeypatch.setattr("src.analysis.interface.get_classification_result", lambda **_: type("Stored", (), {"status": "completed"})())
    monkeypatch.setattr("src.analysis.interface.get_document_refs", lambda **_: [type("Ref", (), {"title": "title", "source_name": "source", "published_at": "2026-08-02"})()])
    monkeypatch.setattr("src.analysis.interface.get_markdown", lambda **_: "markdown")
    monkeypatch.setattr("src.analysis.interface.get_openrouter_settings", lambda: type("S", (), {"model": "model-a"})())
    monkeypatch.setattr("src.analysis.interface.classify_document", lambda **_: _classification_result(reason="re-run"))

    def fake_save(**kwargs):
        calls["count"] += 1
        return type("Stored", (), {"status": "completed", "classification_reason": "re-run"})()

    monkeypatch.setattr("src.analysis.interface.save_classification_result", fake_save)
    result = classify_document_version(workspace_id="ws-1", document_version_id="ver-1", force=True)
    assert calls["count"] == 1
    assert result.classification_reason == "re-run"



def test_different_model_creates_separate_row() -> None:
    fake = FakeSupabase()
    save_classification_result(workspace_id="ws-1", document_version_id="ver-1", result=_classification_result(), model_name="model-a", prompt_version="v1", supabase=fake)
    save_classification_result(workspace_id="ws-1", document_version_id="ver-1", result=_classification_result(), model_name="model-b", prompt_version="v1", supabase=fake)
    assert len(fake.tables["document_analysis_results"]) == 2



def test_different_prompt_version_creates_separate_row() -> None:
    fake = FakeSupabase()
    save_classification_result(workspace_id="ws-1", document_version_id="ver-1", result=_classification_result(), model_name="model-a", prompt_version="v1", supabase=fake)
    save_classification_result(workspace_id="ws-1", document_version_id="ver-1", result=_classification_result(), model_name="model-a", prompt_version="v2", supabase=fake)
    assert len(fake.tables["document_analysis_results"]) == 2



def test_invalid_category_rejected() -> None:
    with pytest.raises(ValueError):
        ClassificationResult(primary_category="기타", secondary_categories=[], confidence=0.5, reason="x")



def test_confidence_out_of_range_rejected() -> None:
    with pytest.raises(ValueError):
        ClassificationResult(primary_category=Category.COMPETITOR, secondary_categories=[], confidence=1.5, reason="x")



def test_secondary_more_than_two_rejected() -> None:
    with pytest.raises(ValueError):
        ClassificationResult(primary_category=Category.COMPETITOR, secondary_categories=[Category.MARKET_MANAGEMENT, Category.CUSTOMER_DEMAND, Category.POLICY_REGULATION], confidence=0.5, reason="x")



def test_primary_secondary_duplicate_rejected() -> None:
    with pytest.raises(ValueError):
        ClassificationResult(primary_category=Category.COMPETITOR, secondary_categories=[Category.COMPETITOR], confidence=0.5, reason="x")



def test_workspace_mismatch_rejected() -> None:
    fake = FakeSupabase()
    with pytest.raises(Exception, match="DOCUMENT_WORKSPACE_MISMATCH"):
        save_classification_result(workspace_id="ws-1", document_version_id="ver-2", result=_classification_result(), model_name="model-a", supabase=fake)



def test_missing_document_version_rejected() -> None:
    fake = FakeSupabase()
    with pytest.raises(Exception, match="DOCUMENT_VERSION_NOT_FOUND"):
        save_classification_result(workspace_id="ws-1", document_version_id="missing", result=_classification_result(), model_name="model-a", supabase=fake)



def test_db_save_failure_handled() -> None:
    fake = FakeSupabase()
    fake.fail_upsert = True
    with pytest.raises(ClassificationSaveFailedError):
        save_classification_result(workspace_id="ws-1", document_version_id="ver-1", result=_classification_result(), model_name="model-a", supabase=fake)



def test_failure_message_redacts_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSupabase()
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret-key")
    stored = save_classification_failure(
        workspace_id="ws-1",
        document_version_id="ver-1",
        model_name="model-a",
        error_message="failed with secret-key and markdown body",
        supabase=fake,
    )
    assert "secret-key" not in (stored.error_message or "")



def test_missing_api_key_returns_failure_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("src.analysis.interface.validate_document_workspace", lambda **_: {"document_id": "doc-1"})
    monkeypatch.setattr("src.analysis.interface.get_classification_result", lambda **_: None)
    monkeypatch.setattr("src.analysis.interface.get_document_refs", lambda **_: [type("Ref", (), {"title": "title", "source_name": "source", "published_at": "2026-08-02"})()])
    monkeypatch.setattr("src.analysis.interface.get_markdown", lambda **_: "markdown")
    result = classify_document_version(workspace_id="ws-1", document_version_id="ver-1")
    assert result.error_code == "MISSING_API_KEY"
    assert isinstance(result.error_message, str)

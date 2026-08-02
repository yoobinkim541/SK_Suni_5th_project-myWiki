from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.analysis.exceptions import DocumentWorkspaceMismatchError, OpenRouterApiError
from src.analysis.importance import evaluate_importance_for_documents
from src.analysis.importance_models import ImportanceDocument, ImportanceEvaluationFailure
from src.analysis.models import Category
from src.analysis.reliability import evaluate_and_save_reliability
from src.analysis.reliability_models import (
    EvidenceDocument,
    MachineSignals,
    ReliabilityCriterionResult,
    ReliabilityEvaluationResult,
    ReliabilityLLMResult,
    ReliabilityLevel,
)
from src.analysis.reliability_scoring import apply_machine_score_caps, build_final_result
from src.analysis.repository import (
    get_documents_ready_for_reliability,
    get_reliability_result,
    get_reliability_results,
    save_classification_result,
    save_reliability_failure,
    save_reliability_result,
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

    def update(self, payload):
        self._action = "update"
        self._payload = dict(payload)
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

        if self._action == "update":
            if self.supabase.fail_update:
                raise RuntimeError("db failure")
            rows = self.rows
            for field, value in self.filters:
                rows = [row for row in rows if row.get(field) == value]
            if not rows:
                return FakeResult([])
            now = datetime.now(timezone.utc).isoformat()
            updated = []
            for row in rows:
                row.update(self._payload)
                row["updated_at"] = now
                updated.append(dict(row))
            return FakeResult(updated)

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
        self.fail_update = False

    def table(self, name):
        return FakeTable(self, name)


@pytest.fixture
def fake_supabase() -> FakeSupabase:
    return FakeSupabase()


@pytest.fixture
def seeded_classification(fake_supabase: FakeSupabase):
    return save_classification_result(
        workspace_id="ws-1",
        document_version_id="ver-1",
        result=_classification_result(),
        model_name="classification-model",
        prompt_version="classification-v1",
        supabase=fake_supabase,
    )


def _classification_result():
    from src.analysis.models import ClassificationResult

    return ClassificationResult(
        primary_category=Category.PRODUCT_TECHNOLOGY,
        secondary_categories=[Category.CUSTOMER_DEMAND],
        confidence=0.92,
        reason="제품 기술 이슈로 분류",
    )


def _criterion(score: int, reason: str) -> ReliabilityCriterionResult:
    return ReliabilityCriterionResult(
        score=score,
        reason=reason,
        evidence_document_ids=["ver-1"],
        warnings=[],
    )


def _evidence_document() -> EvidenceDocument:
    return EvidenceDocument(
        document_version_id="ver-1",
        document_id="doc-1",
        title="기사",
        canonical_url="https://example.com/1",
        source_name="공식 출처",
        source_type="official_press",
        source_reliability_score=0.9,
        published_at="2026-08-01T00:00:00+09:00",
        markdown="본문",
        version_no=1,
        source_id="source-1",
        markdown_object_key="processed/ws-1/ver-1.md",
    )


def _reliability_result(score_offset: int = 0) -> ReliabilityEvaluationResult:
    return ReliabilityEvaluationResult(
        issue_id="ver-1",
        issue_title="테스트 이슈",
        reliability_score=80 + score_offset,
        reliability_level=ReliabilityLevel.HIGH,
        traceability_score=18,
        source_authority_score=17,
        current_validity_score=16,
        independent_evidence_score=15,
        factual_consistency_score=14 + score_offset,
        summary_reason="공식 출처와 본문 추적이 가능하고 핵심 사실이 대체로 일치합니다.",
        criteria={
            "traceability": _criterion(18, "원문 URL과 본문 추적 가능"),
            "source_authority": _criterion(17, "공식 출처 포함"),
            "current_validity": _criterion(16, "현재 시점 유효"),
            "independent_evidence": _criterion(15, "복수 근거 확보"),
            "factual_consistency": _criterion(14 + score_offset, "핵심 사실 일치"),
        },
        conflicting_claims=[],
        missing_information=[],
        evaluated_document_version_ids=["ver-1"],
        warnings=["단일 출처 기반 평가"],
    )


def test_save_and_load_reliability_result(fake_supabase: FakeSupabase, seeded_classification) -> None:
    stored = save_reliability_result(
        workspace_id="ws-1",
        document_version_id="ver-1",
        result=_reliability_result(),
        model_name="reliability-model",
        prompt_version="reliability-v1",
        supabase=fake_supabase,
    )

    loaded = get_reliability_result(
        workspace_id="ws-1",
        document_version_id="ver-1",
        supabase=fake_supabase,
    )

    assert stored.analysis_result_id == seeded_classification.id
    assert loaded is not None
    assert loaded.reliability_status == "completed"
    assert loaded.reliability_score == 80
    assert loaded.reliability_level == ReliabilityLevel.HIGH
    assert loaded.traceability_score == 18
    assert loaded.source_authority_score == 17
    assert loaded.current_validity_score == 16
    assert loaded.independent_evidence_score == 15
    assert loaded.factual_consistency_score == 14
    assert loaded.reliability_detail["criteria"]["traceability"]["reason"] == "원문 URL과 본문 추적 가능"
    assert loaded.reliability_detail["source_signals"]["document_count"] == 1


def test_get_reliability_results_and_ready_documents(fake_supabase: FakeSupabase, seeded_classification) -> None:
    save_reliability_failure(
        workspace_id="ws-1",
        document_version_id="ver-1",
        model_name="reliability-model",
        prompt_version="reliability-v1",
        error_code="OPENROUTER_API_ERROR",
        error_message="failed",
        supabase=fake_supabase,
    )

    results = get_reliability_results(
        workspace_id="ws-1",
        document_version_ids=["ver-1"],
        supabase=fake_supabase,
    )
    ready = get_documents_ready_for_reliability(
        workspace_id="ws-1",
        supabase=fake_supabase,
    )

    assert len(results) == 1
    assert results[0].reliability_status == "failed"
    assert ready == ["ver-1"]


def test_completed_result_skips_api_recall(monkeypatch: pytest.MonkeyPatch) -> None:
    existing = type(
        "Stored",
        (),
        {
            "reliability_status": "completed",
            "reliability_model_name": "model-a",
            "reliability_prompt_version": "reliability-v1",
        },
    )()
    monkeypatch.setattr("src.analysis.reliability.validate_document_workspace", lambda **_: {"document_id": "doc-1"})
    monkeypatch.setattr("src.analysis.reliability.get_latest_classification_result", lambda **_: type("Cls", (), {"status": "completed", "primary_category": Category.PRODUCT_TECHNOLOGY})())
    monkeypatch.setattr("src.analysis.reliability.get_reliability_result", lambda **_: existing)
    monkeypatch.setattr("src.analysis.reliability.evaluate_reliability", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not call api")))
    monkeypatch.setattr("src.analysis.reliability.get_openrouter_settings", lambda: type("S", (), {"model": "model-a"})())

    result = evaluate_and_save_reliability(workspace_id="ws-1", document_version_id="ver-1", force=False)
    assert result is existing


def test_force_true_reruns_and_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"saved": 0}
    monkeypatch.setattr("src.analysis.reliability.validate_document_workspace", lambda **_: {"document_id": "doc-1"})
    monkeypatch.setattr("src.analysis.reliability.get_latest_classification_result", lambda **_: type("Cls", (), {"status": "completed", "primary_category": Category.PRODUCT_TECHNOLOGY})())
    monkeypatch.setattr("src.analysis.reliability.get_reliability_result", lambda **_: type("Stored", (), {"reliability_status": "completed", "reliability_model_name": "model-a", "reliability_prompt_version": "reliability-v1"})())
    monkeypatch.setattr("src.analysis.reliability.build_evidence_documents", lambda **_: [_evidence_document()])
    monkeypatch.setattr("src.analysis.reliability.evaluate_reliability", lambda *_args, **_kwargs: _reliability_result())
    monkeypatch.setattr("src.analysis.reliability.get_openrouter_settings", lambda: type("S", (), {"model": "model-a"})())

    def fake_save(**kwargs):
        calls["saved"] += 1
        return type("Stored", (), {"reliability_status": "completed", "reliability_score": 80})()

    monkeypatch.setattr("src.analysis.reliability.save_reliability_result", fake_save)

    result = evaluate_and_save_reliability(workspace_id="ws-1", document_version_id="ver-1", force=True)
    assert calls["saved"] == 1
    assert result.reliability_status == "completed"


def test_classification_not_completed_returns_runtime_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.analysis.reliability.validate_document_workspace", lambda **_: {"document_id": "doc-1"})
    monkeypatch.setattr("src.analysis.reliability.get_latest_classification_result", lambda **_: type("Cls", (), {"status": "failed", "primary_category": None})())
    monkeypatch.setattr("src.analysis.reliability.get_openrouter_settings", lambda: type("S", (), {"model": "model-a"})())

    result = evaluate_and_save_reliability(workspace_id="ws-1", document_version_id="ver-1")
    assert result.error_code == "CLASSIFICATION_NOT_COMPLETED"
    assert result.reliability_status == "failed"


def test_workspace_mismatch_returns_runtime_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.analysis.reliability.validate_document_workspace",
        lambda **_: (_ for _ in ()).throw(DocumentWorkspaceMismatchError("DOCUMENT_WORKSPACE_MISMATCH")),
    )
    monkeypatch.setattr("src.analysis.reliability.get_openrouter_settings", lambda: type("S", (), {"model": "model-a"})())

    result = evaluate_and_save_reliability(workspace_id="ws-1", document_version_id="ver-1")
    assert result.reliability_status == "failed"
    assert result.error_code == "DOCUMENT_WORKSPACE_MISMATCH"


def test_force_rerun_failure_preserves_existing_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    existing = type(
        "Stored",
        (),
        {
            "reliability_status": "completed",
            "reliability_model_name": "model-a",
            "reliability_prompt_version": "reliability-v1",
            "reliability_score": 80,
        },
    )()
    monkeypatch.setattr("src.analysis.reliability.validate_document_workspace", lambda **_: {"document_id": "doc-1"})
    monkeypatch.setattr("src.analysis.reliability.get_latest_classification_result", lambda **_: type("Cls", (), {"status": "completed", "primary_category": Category.PRODUCT_TECHNOLOGY})())
    monkeypatch.setattr("src.analysis.reliability.get_reliability_result", lambda **_: existing)
    monkeypatch.setattr("src.analysis.reliability.build_evidence_documents", lambda **_: [_evidence_document()])
    monkeypatch.setattr("src.analysis.reliability.evaluate_reliability", lambda *_args, **_kwargs: (_ for _ in ()).throw(OpenRouterApiError("upstream failed")))
    monkeypatch.setattr("src.analysis.reliability.get_openrouter_settings", lambda: type("S", (), {"model": "model-a"})())

    result = evaluate_and_save_reliability(workspace_id="ws-1", document_version_id="ver-1", force=True)
    assert result is existing


def test_failure_message_redacts_secrets(fake_supabase: FakeSupabase, seeded_classification, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret-key")
    stored = save_reliability_failure(
        workspace_id="ws-1",
        document_version_id="ver-1",
        model_name="reliability-model",
        prompt_version="reliability-v1",
        error_code="OPENROUTER_API_ERROR",
        error_message="failed with secret-key in payload",
        supabase=fake_supabase,
    )
    assert "secret-key" not in (stored.reliability_error_message or "")


def test_importance_uses_stored_reliability(monkeypatch: pytest.MonkeyPatch) -> None:
    document = ImportanceDocument(
        document_version_id="ver-1",
        title="중요도 기사",
        source_name="출처",
        source_type="official_press",
        canonical_url="https://example.com/1",
        published_at="2026-08-01T00:00:00+09:00",
        markdown="SK하이닉스 HBM 증설 기사",
        source_id="source-1",
    )
    stored = type(
        "StoredReliability",
        (),
        {
            "reliability_status": "completed",
            "reliability_score": 80,
            "reliability_level": ReliabilityLevel.HIGH,
        },
    )()

    monkeypatch.setattr("src.analysis.importance.build_importance_documents", lambda **_: [document])
    monkeypatch.setattr("src.analysis.importance.get_reliability_result", lambda **_: stored)
    monkeypatch.setattr("src.analysis.importance.evaluate_importance", lambda request: request)

    request = evaluate_importance_for_documents(
        workspace_id="ws-1",
        document_version_ids=["ver-1"],
        primary_category="제품·기술",
    )

    assert request.reliability_score == 80
    assert request.reliability_level == ReliabilityLevel.HIGH


def test_importance_fails_when_stored_reliability_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    document = ImportanceDocument(
        document_version_id="ver-1",
        title="중요도 기사",
        source_name="출처",
        source_type="official_press",
        canonical_url="https://example.com/1",
        published_at="2026-08-01T00:00:00+09:00",
        markdown="기사 본문",
        source_id="source-1",
    )
    monkeypatch.setattr("src.analysis.importance.build_importance_documents", lambda **_: [document])
    monkeypatch.setattr("src.analysis.importance.get_reliability_result", lambda **_: None)

    result = evaluate_importance_for_documents(
        workspace_id="ws-1",
        document_version_ids=["ver-1"],
        primary_category="제품·기술",
    )

    assert isinstance(result, ImportanceEvaluationFailure)
    assert result.error_code == "RELIABILITY_NOT_COMPLETED"


def test_final_level_cap_keeps_score_and_level_db_consistent() -> None:
    llm_result = ReliabilityLLMResult(
        traceability=_criterion(18, "원문 URL과 본문 추적 가능"),
        source_authority=_criterion(17, "공식 출처 포함"),
        current_validity=_criterion(16, "현재 시점 유효"),
        independent_evidence=_criterion(15, "복수 근거 확보"),
        factual_consistency=_criterion(14, "핵심 사실 일치"),
        conflicting_claims=[],
        missing_information=[],
    )
    signals = MachineSignals(
        has_any_url=True,
        has_any_markdown=True,
        has_complete_metadata=True,
        document_count=2,
        unique_source_count=2,
        unique_canonical_url_count=2,
        has_official_source=True,
        single_source_only=False,
        duplicated_republish_detected=False,
        missing_markdown_documents=["ver-2"],
        missing_url_documents=[],
        missing_metadata_documents=[],
    )

    breakdown, caps = apply_machine_score_caps(llm_result=llm_result, signals=signals)
    result = build_final_result(
        issue_id="ver-1",
        issue_title="테스트 이슈",
        llm_result=llm_result,
        breakdown=breakdown,
        caps=caps,
        evaluated_document_version_ids=["ver-1", "ver-2"],
    )

    assert result.reliability_level == ReliabilityLevel.MEDIUM
    assert result.reliability_score == 69
    assert result.reliability_score == (
        result.traceability_score
        + result.source_authority_score
        + result.current_validity_score
        + result.independent_evidence_score
        + result.factual_consistency_score
    )



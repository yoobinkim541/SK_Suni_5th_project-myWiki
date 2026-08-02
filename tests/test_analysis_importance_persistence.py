from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.analysis.exceptions import DocumentWorkspaceMismatchError, OpenRouterApiError
from src.analysis.importance import evaluate_and_save_importance
from src.analysis.importance_models import (
    ImpactDirection,
    ImportanceDocument,
    ImportanceCriterionResult,
    ImportanceEvaluationResult,
    ImportanceLevel,
    ImportanceMachineSignals,
    TimeHorizon,
)
from src.analysis.importance_scoring import apply_importance_caps, build_importance_final_result
from src.analysis.models import Category
from src.analysis.reliability_models import ReliabilityCriterionResult, ReliabilityEvaluationResult, ReliabilityLevel
from src.analysis.repository import (
    get_analysis_results_for_report,
    get_documents_ready_for_importance,
    get_importance_result,
    get_importance_results,
    save_classification_result,
    save_importance_failure,
    save_importance_result,
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
            "sources": [
                {"id": "source-1", "name": "테스트 출처", "source_type": "official_press", "reliability_score": 0.9},
                {"id": "source-2", "name": "보조 출처", "source_type": "news", "reliability_score": 0.7},
            ],
            "documents": [
                {"id": "doc-1", "workspace_id": "ws-1", "title": "HBM 기사", "canonical_url": "https://example.com/1", "published_at": "2026-08-01T00:00:00+09:00", "source_id": "source-1"},
                {"id": "doc-2", "workspace_id": "ws-2", "title": "다른 워크스페이스 기사", "canonical_url": "https://example.com/2", "published_at": "2026-08-01T00:00:00+09:00", "source_id": "source-2"},
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
def seeded_reliability(fake_supabase: FakeSupabase):
    save_classification_result(
        workspace_id="ws-1",
        document_version_id="ver-1",
        result=_classification_result(),
        model_name="classification-model",
        prompt_version="classification-v1",
        supabase=fake_supabase,
    )
    return save_reliability_result(
        workspace_id="ws-1",
        document_version_id="ver-1",
        result=_reliability_result(),
        model_name="reliability-model",
        prompt_version="reliability-v1",
        supabase=fake_supabase,
    )


def _classification_result():
    from src.analysis.models import ClassificationResult

    return ClassificationResult(
        primary_category=Category.PRODUCT_TECHNOLOGY,
        secondary_categories=[Category.CUSTOMER_DEMAND],
        confidence=0.91,
        reason="제품 기술 이슈",
    )


def _reliability_criterion(score: int, reason: str) -> ReliabilityCriterionResult:
    return ReliabilityCriterionResult(score=score, reason=reason, evidence_document_ids=["ver-1"], warnings=[])


def _reliability_result() -> ReliabilityEvaluationResult:
    return ReliabilityEvaluationResult(
        issue_id="ver-1",
        issue_title="신뢰도 테스트 이슈",
        reliability_score=80,
        reliability_level=ReliabilityLevel.HIGH,
        traceability_score=18,
        source_authority_score=17,
        current_validity_score=16,
        independent_evidence_score=15,
        factual_consistency_score=14,
        summary_reason="공식 출처와 사실 일치",
        criteria={
            "traceability": _reliability_criterion(18, "원문 추적 가능"),
            "source_authority": _reliability_criterion(17, "공식 출처 포함"),
            "current_validity": _reliability_criterion(16, "현재 유효"),
            "independent_evidence": _reliability_criterion(15, "복수 근거"),
            "factual_consistency": _reliability_criterion(14, "핵심 사실 일치"),
        },
        conflicting_claims=[],
        missing_information=[],
        evaluated_document_version_ids=["ver-1"],
        warnings=[],
    )


def _importance_criterion(score: int, reason: str) -> ImportanceCriterionResult:
    return ImportanceCriterionResult(score=score, reason=reason, evidence_document_ids=["ver-1"], uncertainties=[])


def _importance_result() -> ImportanceEvaluationResult:
    return ImportanceEvaluationResult(
        issue_id="ver-1",
        issue_title="중요도 테스트 이슈",
        importance_score=79,
        importance_level=ImportanceLevel.HIGH,
        direct_relevance_score=20,
        business_impact_score=22,
        urgency_score=10,
        industry_impact_score=12,
        duration_score=8,
        external_attention_score=7,
        impact_direction=ImpactDirection.MIXED,
        time_horizon=TimeHorizon.MID_TERM,
        summary_reason="사업 영향이 크고 직접 관련성이 높음",
        criteria={
            "direct_relevance": _importance_criterion(20, "직접 관련"),
            "business_impact": _importance_criterion(22, "사업 영향 큼"),
            "urgency": _importance_criterion(10, "단기 대응 필요"),
            "industry_impact": _importance_criterion(12, "시장 파급"),
            "duration": _importance_criterion(8, "중장기 영향"),
            "external_attention": _importance_criterion(7, "복수 보도"),
        },
        applied_caps=[],
        code_signals={
            "sk_hynix_explicitly_mentioned": True,
            "core_memory_business_mentioned": True,
            "numeric_evidence_present": True,
            "forecast_only": False,
            "promotional_content": False,
            "republication_detected": False,
        },
        core_summary="SK하이닉스가 HBM 생산 확대 계획을 공개했다.",
        key_points=["HBM 생산 확대", "고객 대응 일정 유지", "연내 양산 계획 지속", "HBM 수요 대응"],
        key_numbers=[{
            "label": "증설 규모",
            "value": "20",
            "unit": "%",
            "context": "HBM 생산능력 확대",
            "information_type": "fact",
            "evidence_document_version_id": "ver-1",
            "quoted_text": "생산능력을 20% 늘린다",
        }],
        sk_hynix_implication="HBM 공급 경쟁력 확보와 주요 고객 대응 속도에 직접 연결된다.",
        summary_evidence_refs=[{
            "document_version_id": "ver-1",
            "quoted_text": "생산능력을 20% 늘린다",
            "supports": ["core_summary", "key_points[0]", "key_numbers[0]", "sk_hynix_implication"],
        }],
        affected_areas=["HBM", "HBM", " "],
        opportunities=["점유율 확대", "점유율 확대"],
        risks=["경쟁 심화"],
        watch_points=["고객 채택", ""],
        missing_information=["정량 수요 전망", "정량 수요 전망"],
        evaluated_document_version_ids=["ver-1"],
        warnings=[],
    )


def test_save_and_load_importance_result(fake_supabase: FakeSupabase, seeded_reliability) -> None:
    stored = save_importance_result(
        workspace_id="ws-1",
        document_version_id="ver-1",
        result=_importance_result(),
        model_name="importance-model",
        prompt_version="importance-v2",
        supabase=fake_supabase,
    )
    loaded = get_importance_result(workspace_id="ws-1", document_version_id="ver-1", supabase=fake_supabase)

    assert stored.analysis_result_id == seeded_reliability.analysis_result_id
    assert loaded is not None
    assert loaded.importance_status == "completed"
    assert loaded.importance_score == 79
    assert loaded.importance_level == ImportanceLevel.HIGH
    assert loaded.core_summary == "SK하이닉스가 HBM 생산 확대 계획을 공개했다."
    assert loaded.key_points[:3] == ["HBM 생산 확대", "고객 대응 일정 유지", "연내 양산 계획 지속"]
    assert loaded.key_numbers[0].evidence_document_version_id == "ver-1"
    assert loaded.summary_evidence_refs[0].supports[0] == "core_summary"


def test_importance_arrays_and_detail_are_normalized(fake_supabase: FakeSupabase, seeded_reliability) -> None:
    stored = save_importance_result(
        workspace_id="ws-1",
        document_version_id="ver-1",
        result=_importance_result(),
        model_name="importance-model",
        prompt_version="importance-v2",
        supabase=fake_supabase,
    )
    assert stored.affected_areas == ["HBM"]
    assert stored.opportunities == ["점유율 확대"]
    assert stored.watch_points == ["고객 채택"]
    assert stored.importance_missing_information == ["정량 수요 전망"]
    assert len(stored.key_points) == 4
    assert "본문" not in str(stored.importance_detail)


def test_get_importance_results_and_ready_documents(fake_supabase: FakeSupabase, seeded_reliability) -> None:
    save_importance_failure(
        workspace_id="ws-1",
        document_version_id="ver-1",
        model_name="importance-model",
        prompt_version="importance-v2",
        error_code="OPENROUTER_API_ERROR",
        error_message="failed",
        supabase=fake_supabase,
    )
    results = get_importance_results(workspace_id="ws-1", document_version_ids=["ver-1"], supabase=fake_supabase)
    ready = get_documents_ready_for_importance(workspace_id="ws-1", supabase=fake_supabase)
    assert len(results) == 1
    assert results[0].importance_status == "failed"
    assert ready == ["ver-1"]


def test_report_query_returns_completed_rows_with_summary(fake_supabase: FakeSupabase, seeded_reliability) -> None:
    save_importance_result(
        workspace_id="ws-1",
        document_version_id="ver-1",
        result=_importance_result(),
        model_name="importance-model",
        prompt_version="importance-v2",
        supabase=fake_supabase,
    )
    reports = get_analysis_results_for_report(workspace_id="ws-1", document_version_ids=["ver-1"], supabase=fake_supabase)
    assert len(reports) == 1
    report = reports[0]
    assert report.title == "HBM 기사"
    assert report.source_name == "테스트 출처"
    assert report.core_summary
    assert report.key_points
    assert report.summary_evidence_refs


def test_completed_result_skips_api_recall(monkeypatch: pytest.MonkeyPatch) -> None:
    existing = type("Stored", (), {"importance_status": "completed", "importance_model_name": "model-a", "importance_prompt_version": "importance-v2"})()
    monkeypatch.setattr("src.analysis.importance.validate_document_workspace", lambda **_: {"document_id": "doc-1"})
    monkeypatch.setattr("src.analysis.importance.get_latest_classification_result", lambda **_: type("Cls", (), {"status": "completed", "primary_category": Category.PRODUCT_TECHNOLOGY, "secondary_categories": []})())
    monkeypatch.setattr("src.analysis.importance.get_reliability_result", lambda **_: type("Rel", (), {"reliability_status": "completed", "reliability_score": 80, "reliability_level": ReliabilityLevel.HIGH})())
    monkeypatch.setattr("src.analysis.importance.get_importance_result", lambda **_: existing)
    monkeypatch.setattr("src.analysis.importance.evaluate_importance", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not call api")))
    monkeypatch.setattr("src.analysis.importance.get_openrouter_settings", lambda: type("S", (), {"model": "model-a"})())

    result = evaluate_and_save_importance(workspace_id="ws-1", document_version_id="ver-1", force=False)
    assert result is existing


def test_force_true_reruns_and_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"saved": 0}
    monkeypatch.setattr("src.analysis.importance.validate_document_workspace", lambda **_: {"document_id": "doc-1"})
    monkeypatch.setattr("src.analysis.importance.get_latest_classification_result", lambda **_: type("Cls", (), {"status": "completed", "primary_category": Category.PRODUCT_TECHNOLOGY, "secondary_categories": [Category.CUSTOMER_DEMAND]})())
    monkeypatch.setattr("src.analysis.importance.get_reliability_result", lambda **_: type("Rel", (), {"reliability_status": "completed", "reliability_score": 80, "reliability_level": ReliabilityLevel.HIGH})())
    monkeypatch.setattr("src.analysis.importance.get_importance_result", lambda **_: type("Stored", (), {"importance_status": "completed", "importance_model_name": "model-a", "importance_prompt_version": "importance-v2"})())
    monkeypatch.setattr("src.analysis.importance.build_importance_documents", lambda **_: [ImportanceDocument(document_version_id="ver-1", title="기사", source_name="출처", source_type="official_press", canonical_url="https://example.com/1", published_at="2026-08-01T00:00:00+09:00", markdown="기사 본문", source_id="source-1")])
    monkeypatch.setattr("src.analysis.importance.evaluate_importance", lambda *_args, **_kwargs: _importance_result())
    monkeypatch.setattr("src.analysis.importance.get_openrouter_settings", lambda: type("S", (), {"model": "model-a"})())

    def fake_save(**kwargs):
        calls["saved"] += 1
        return type("Stored", (), {"importance_status": "completed", "importance_score": 79, "core_summary": "요약"})()

    monkeypatch.setattr("src.analysis.importance.save_importance_result", fake_save)
    result = evaluate_and_save_importance(workspace_id="ws-1", document_version_id="ver-1", force=True)
    assert calls["saved"] == 1
    assert result.importance_status == "completed"


def test_force_rerun_failure_preserves_existing_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    existing = type("Stored", (), {"importance_status": "completed", "importance_model_name": "model-a", "importance_prompt_version": "importance-v2", "importance_score": 79})()
    monkeypatch.setattr("src.analysis.importance.validate_document_workspace", lambda **_: {"document_id": "doc-1"})
    monkeypatch.setattr("src.analysis.importance.get_latest_classification_result", lambda **_: type("Cls", (), {"status": "completed", "primary_category": Category.PRODUCT_TECHNOLOGY, "secondary_categories": []})())
    monkeypatch.setattr("src.analysis.importance.get_reliability_result", lambda **_: type("Rel", (), {"reliability_status": "completed", "reliability_score": 80, "reliability_level": ReliabilityLevel.HIGH})())
    monkeypatch.setattr("src.analysis.importance.get_importance_result", lambda **_: existing)
    monkeypatch.setattr("src.analysis.importance.build_importance_documents", lambda **_: [ImportanceDocument(document_version_id="ver-1", title="기사", source_name="출처", source_type="official_press", canonical_url="https://example.com/1", published_at="2026-08-01T00:00:00+09:00", markdown="기사 본문", source_id="source-1")])
    monkeypatch.setattr("src.analysis.importance.evaluate_importance", lambda *_args, **_kwargs: (_ for _ in ()).throw(OpenRouterApiError("upstream failed")))
    monkeypatch.setattr("src.analysis.importance.get_openrouter_settings", lambda: type("S", (), {"model": "model-a"})())

    result = evaluate_and_save_importance(workspace_id="ws-1", document_version_id="ver-1", force=True)
    assert result is existing


def test_reliability_not_completed_blocks_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.analysis.importance.validate_document_workspace", lambda **_: {"document_id": "doc-1"})
    monkeypatch.setattr("src.analysis.importance.get_latest_classification_result", lambda **_: type("Cls", (), {"status": "completed", "primary_category": Category.PRODUCT_TECHNOLOGY, "secondary_categories": []})())
    monkeypatch.setattr("src.analysis.importance.get_reliability_result", lambda **_: None)
    monkeypatch.setattr("src.analysis.importance.get_openrouter_settings", lambda: type("S", (), {"model": "model-a"})())

    result = evaluate_and_save_importance(workspace_id="ws-1", document_version_id="ver-1")
    assert result.error_code == "RELIABILITY_NOT_COMPLETED"
    assert result.importance_status == "failed"


def test_workspace_mismatch_returns_runtime_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.analysis.importance.validate_document_workspace", lambda **_: (_ for _ in ()).throw(DocumentWorkspaceMismatchError("DOCUMENT_WORKSPACE_MISMATCH")))
    monkeypatch.setattr("src.analysis.importance.get_openrouter_settings", lambda: type("S", (), {"model": "model-a"})())
    result = evaluate_and_save_importance(workspace_id="ws-1", document_version_id="ver-1")
    assert result.error_code == "DOCUMENT_WORKSPACE_MISMATCH"


def test_failure_message_redacts_secrets(fake_supabase: FakeSupabase, seeded_reliability, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret-key")
    stored = save_importance_failure(
        workspace_id="ws-1",
        document_version_id="ver-1",
        model_name="importance-model",
        prompt_version="importance-v2",
        error_code="OPENROUTER_API_ERROR",
        error_message="failed with secret-key in payload",
        supabase=fake_supabase,
    )
    assert "secret-key" not in (stored.importance_error_message or "")


def test_final_level_cap_keeps_score_and_level_db_consistent_with_summary() -> None:
    base_result = _importance_result()
    signals = ImportanceMachineSignals(
        document_count=2,
        unique_source_count=2,
        unique_canonical_url_count=2,
        independent_source_count=2,
        has_official_source=True,
        duplicated_republish_detected=False,
        sk_hynix_explicitly_mentioned=True,
        core_business_mentioned=True,
        quantitative_impact_present=True,
        forecast_only=False,
        promotional_or_event_only=True,
        event_already_ended=False,
    )

    llm_result = type("Tmp", (), {
        "direct_relevance": _importance_criterion(24, "직접 관련"),
        "business_impact": _importance_criterion(22, "사업 영향 큼"),
        "urgency": _importance_criterion(11, "긴급 대응 필요"),
        "industry_impact": _importance_criterion(13, "시장 파급"),
        "duration": _importance_criterion(9, "지속성 높음"),
        "external_attention": _importance_criterion(7, "복수 보도"),
        "impact_direction": ImpactDirection.RISK,
        "time_horizon": TimeHorizon.MID_TERM,
        "core_summary": base_result.core_summary,
        "key_points": base_result.key_points,
        "key_numbers": base_result.key_numbers,
        "sk_hynix_implication": base_result.sk_hynix_implication,
        "summary_evidence_refs": base_result.summary_evidence_refs,
        "affected_areas": base_result.affected_areas,
        "opportunities": base_result.opportunities,
        "risks": base_result.risks,
        "watch_points": base_result.watch_points,
        "missing_information": base_result.missing_information,
    })()

    breakdown, caps = apply_importance_caps(llm_result=llm_result, signals=signals)
    result = build_importance_final_result(
        issue_id="ver-1",
        issue_title="중요도 테스트",
        llm_result=llm_result,
        breakdown=breakdown,
        caps=caps,
        signals=signals,
        evaluated_document_version_ids=["ver-1"],
    )

    assert result.importance_level == ImportanceLevel.MEDIUM
    assert result.importance_score == 69
    assert result.importance_score == (
        result.direct_relevance_score
        + result.business_impact_score
        + result.urgency_score
        + result.industry_impact_score
        + result.duration_score
        + result.external_attention_score
    )
    assert result.summary_evidence_refs


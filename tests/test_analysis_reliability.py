from __future__ import annotations

import pytest

from src.analysis.classifier import parse_json_response
from src.analysis.exceptions import InvalidJsonResponseError, InvalidScoreError, MissingApiKeyError
from src.analysis.reliability import evaluate_reliability
from src.analysis.reliability_models import (
    EvidenceDocument,
    MachineSignals,
    ReliabilityCriterionResult,
    ReliabilityEvaluationRequest,
    ReliabilityLLMResult,
    ReliabilityLevel,
)
from src.analysis.reliability_scoring import apply_machine_score_caps, compute_total_score, get_reliability_level


def _criterion(score: int, reason: str = "ok") -> ReliabilityCriterionResult:
    return ReliabilityCriterionResult(
        score=score,
        reason=reason,
        evidence_document_ids=["doc-1"],
        warnings=[],
    )


def _llm_result() -> ReliabilityLLMResult:
    return ReliabilityLLMResult(
        traceability=_criterion(18, "추적 가능"),
        source_authority=_criterion(17, "공식 출처 포함"),
        current_validity=_criterion(16, "현재 유효"),
        independent_evidence=_criterion(15, "복수 근거"),
        factual_consistency=_criterion(14, "핵심 사실 일치"),
        conflicting_claims=[],
        missing_information=[],
    )


def _signals() -> MachineSignals:
    return MachineSignals(
        has_any_url=True,
        has_any_markdown=True,
        has_complete_metadata=True,
        document_count=2,
        unique_source_count=2,
        unique_canonical_url_count=2,
        has_official_source=True,
        single_source_only=False,
        duplicated_republish_detected=False,
    )


def _request() -> ReliabilityEvaluationRequest:
    return ReliabilityEvaluationRequest(
        workspace_id="ws-1",
        issue_id="issue-1",
        issue_title="테스트 이슈",
        category="제품·기술",
        documents=[
            EvidenceDocument(
                document_version_id="doc-1",
                document_id="d-1",
                title="기사 제목",
                canonical_url="https://example.com/1",
                source_name="공식 출처",
                source_type="official_press",
                source_reliability_score=0.9,
                published_at="2026-08-01T00:00:00+09:00",
                markdown="본문",
                version_no=1,
                source_id="source-1",
                markdown_object_key="processed/ws/d/1.md",
            )
        ],
    )


def test_compute_total_score() -> None:
    assert compute_total_score(_llm_result()) == 80


def test_low_level_mapping() -> None:
    assert get_reliability_level(39) == ReliabilityLevel.LOW


def test_medium_level_mapping() -> None:
    assert get_reliability_level(40) == ReliabilityLevel.MEDIUM
    assert get_reliability_level(69) == ReliabilityLevel.MEDIUM


def test_high_level_mapping() -> None:
    assert get_reliability_level(70) == ReliabilityLevel.HIGH
    assert get_reliability_level(100) == ReliabilityLevel.HIGH


def test_invalid_criterion_score_rejected() -> None:
    with pytest.raises(ValueError):
        ReliabilityCriterionResult(score=21, reason="x", evidence_document_ids=[])


def test_invalid_total_score_rejected() -> None:
    with pytest.raises(InvalidScoreError):
        get_reliability_level(101)


def test_single_source_cap_rule() -> None:
    signals = _signals().model_copy(update={"single_source_only": True})
    breakdown, caps = apply_machine_score_caps(llm_result=_llm_result(), signals=signals)
    assert breakdown.independent_evidence_score == 8
    assert any("단일 출처" in warning for warning in caps.warnings)


def test_duplicate_republish_cap_rule() -> None:
    llm_result = _llm_result().model_copy(update={"independent_evidence": _criterion(19, "여러 기사")})
    signals = _signals().model_copy(update={"duplicated_republish_detected": True})
    breakdown, caps = apply_machine_score_caps(llm_result=llm_result, signals=signals)
    assert breakdown.independent_evidence_score == 10
    assert any("재배포" in warning for warning in caps.warnings)


def test_official_correction_caps_current_validity() -> None:
    llm_result = _llm_result().model_copy(
        update={
            "current_validity": ReliabilityCriterionResult(
                score=19,
                reason="정정 보도가 확인됨",
                evidence_document_ids=["doc-1"],
                warnings=["정정 공시 확인"],
            )
        }
    )
    signals = _signals().model_copy(update={"official_correction_detected": True})
    breakdown, caps = apply_machine_score_caps(llm_result=llm_result, signals=signals)
    assert breakdown.current_validity_score == 5
    assert any("정정" in warning for warning in caps.warnings)


def test_invalid_json_response() -> None:
    with pytest.raises(InvalidJsonResponseError):
        parse_json_response("not-json")


def test_missing_api_key_fails_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_MODEL", "")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

    with pytest.raises(MissingApiKeyError, match="OPENROUTER_API_KEY"):
        evaluate_reliability(_request())

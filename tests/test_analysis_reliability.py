from __future__ import annotations

import pytest

from src.analysis.classifier import parse_json_response
from src.analysis.exceptions import InvalidJsonResponseError, InvalidScoreError, MissingApiKeyError
from src.analysis.reliability import _detect_official_correction, build_machine_signals, evaluate_reliability
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
    assert breakdown.independent_evidence_score == 12
    assert any("단일 출처" in warning for warning in caps.warnings)


def test_no_official_source_caps_source_authority_to_16() -> None:
    signals = _signals().model_copy(update={"has_official_source": False})
    breakdown, caps = apply_machine_score_caps(llm_result=_llm_result(), signals=signals)
    assert breakdown.source_authority_score == 16
    assert any("\uacf5\uc2dd \ub610\ub294 1\ucc28 \ucd9c\ucc98" in warning for warning in caps.warnings)


def test_disclosure_source_type_counts_as_official_source() -> None:
    document = EvidenceDocument(
        document_version_id="doc-1",
        document_id="d-1",
        title="Disclosure title",
        canonical_url="https://dart.fss.or.kr/1",
        source_name="DART",
        source_type="disclosure",
        source_reliability_score=0.95,
        published_at="2026-08-01T00:00:00+09:00",
        markdown="Disclosure body",
        version_no=1,
        source_id="source-1",
        markdown_object_key="processed/ws/d/1.md",
    )

    signals = build_machine_signals([document])

    assert signals.has_official_source is True


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


@pytest.mark.parametrize(
    "reason",
    [
        "후속 정정이나 반박은 확인되지 않음",
        "공식적인 정정은 없었다",
        "철회 사실을 확인할 수 없음",
        "반박 내용 없음",
        "후속 정정 또는 취소 여부는 확인되지 않았다",
    ],
)
def test_official_correction_detection_ignores_negated_context(reason: str) -> None:
    llm_result = _llm_result().model_copy(
        update={
            "current_validity": ReliabilityCriterionResult(
                score=18,
                reason=reason,
                evidence_document_ids=["doc-1"],
                warnings=[],
            )
        }
    )

    assert _detect_official_correction(llm_result) is False


@pytest.mark.parametrize(
    "reason",
    [
        "회사는 해당 발표를 공식 정정했다",
        "기존 보도 내용을 철회했다",
        "정부가 해당 수치를 정정했다",
        "당사자가 기존 주장을 공식 반박했다",
    ],
)
def test_official_correction_detection_keeps_positive_context(reason: str) -> None:
    llm_result = _llm_result().model_copy(
        update={
            "current_validity": ReliabilityCriterionResult(
                score=18,
                reason=reason,
                evidence_document_ids=["doc-1"],
                warnings=[],
            )
        }
    )

    assert _detect_official_correction(llm_result) is True


def test_invalid_json_response() -> None:
    with pytest.raises(InvalidJsonResponseError):
        parse_json_response("not-json")


def test_missing_api_key_fails_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("OPENROUTER_MODEL", "")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

    with pytest.raises(MissingApiKeyError, match="OPENROUTER_API_KEY"):
        evaluate_reliability(_request())

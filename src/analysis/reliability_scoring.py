from __future__ import annotations

from .exceptions import InvalidScoreError
from .reliability_models import (
    CriterionCaps,
    MachineSignals,
    ReliabilityCriterionResult,
    ReliabilityEvaluationResult,
    ReliabilityLevel,
    ReliabilityLLMResult,
    ReliabilityScoreBreakdown,
    RELIABILITY_LEVELS,
)


_FINAL_LEVEL_MAX_SCORE = {
    ReliabilityLevel.LOW: 39,
    ReliabilityLevel.MEDIUM: 69,
    ReliabilityLevel.HIGH: 100,
}


def compute_total_score(llm_result: ReliabilityLLMResult) -> int:
    return (
        llm_result.traceability.score
        + llm_result.source_authority.score
        + llm_result.current_validity.score
        + llm_result.independent_evidence.score
        + llm_result.factual_consistency.score
    )


def get_reliability_level(score: int) -> ReliabilityLevel:
    validate_total_score(score)
    for level_name, (minimum, maximum) in RELIABILITY_LEVELS.items():
        if minimum <= score <= maximum:
            return ReliabilityLevel(level_name)
    raise InvalidScoreError("신뢰도 등급 경계값이 잘못되었습니다.")


def validate_total_score(score: int) -> None:
    if score < 0 or score > 100:
        raise InvalidScoreError("최종 신뢰도 점수는 0~100 사이여야 합니다.")


def apply_machine_score_caps(*, llm_result: ReliabilityLLMResult, signals: MachineSignals) -> tuple[ReliabilityScoreBreakdown, CriterionCaps]:
    caps = build_criterion_caps(signals=signals)

    traceability_score = min(llm_result.traceability.score, caps.traceability_max)
    source_authority_score = min(llm_result.source_authority.score, caps.source_authority_max)
    current_validity_score = min(llm_result.current_validity.score, caps.current_validity_max)
    independent_evidence_score = min(llm_result.independent_evidence.score, caps.independent_evidence_max)
    factual_consistency_score = min(llm_result.factual_consistency.score, caps.factual_consistency_max)

    total_score = (
        traceability_score
        + source_authority_score
        + current_validity_score
        + independent_evidence_score
        + factual_consistency_score
    )
    validate_total_score(total_score)

    return (
        ReliabilityScoreBreakdown(
            traceability_score=traceability_score,
            source_authority_score=source_authority_score,
            current_validity_score=current_validity_score,
            independent_evidence_score=independent_evidence_score,
            factual_consistency_score=factual_consistency_score,
            total_score=total_score,
        ),
        caps,
    )


def build_criterion_caps(*, signals: MachineSignals) -> CriterionCaps:
    caps = CriterionCaps()

    if not signals.has_any_url or not signals.has_any_markdown:
        caps.traceability_max = min(caps.traceability_max, 5)
        caps.warnings.append("원문 URL 또는 본문이 부족하여 원문 추적 가능성 상한이 적용되었습니다.")

    if not signals.has_official_source:
        caps.source_authority_max = min(caps.source_authority_max, 16)
        caps.warnings.append("공식 또는 1차 출처가 없어 출처 권위성 상한이 적용되었습니다.")

    if signals.single_source_only:
        caps.independent_evidence_max = min(caps.independent_evidence_max, 8)
        caps.warnings.append("단일 출처 기반 평가입니다.")

    if signals.duplicated_republish_detected:
        caps.independent_evidence_max = min(caps.independent_evidence_max, 10)
        caps.warnings.append("동일 원문 재배포가 감지되어 독립 근거 상한이 적용되었습니다.")

    if signals.conflicting_claims_present:
        caps.factual_consistency_max = min(caps.factual_consistency_max, 10)
        caps.warnings.append("핵심 사실 또는 수치 충돌이 있어 사실 일치성 상한이 적용되었습니다.")

    if signals.official_correction_detected:
        caps.current_validity_max = min(caps.current_validity_max, 5)
        caps.warnings.append("공식 정정 또는 철회 정황이 있어 현재 유효성 상한이 적용되었습니다.")

    if signals.missing_markdown_documents:
        caps.final_level_cap = ReliabilityLevel.MEDIUM
        caps.warnings.append("본문이 없는 문서가 있어 최종 등급은 높음을 초과할 수 없습니다.")

    return caps


def merge_summary_reason(llm_result: ReliabilityLLMResult, breakdown: ReliabilityScoreBreakdown) -> str:
    strongest = max(
        [
            (breakdown.traceability_score, llm_result.traceability.reason),
            (breakdown.source_authority_score, llm_result.source_authority.reason),
            (breakdown.current_validity_score, llm_result.current_validity.reason),
            (breakdown.independent_evidence_score, llm_result.independent_evidence.reason),
            (breakdown.factual_consistency_score, llm_result.factual_consistency.reason),
        ],
        key=lambda item: item[0],
    )
    return strongest[1]


def build_final_result(
    *,
    issue_id: str | None,
    issue_title: str,
    llm_result: ReliabilityLLMResult,
    breakdown: ReliabilityScoreBreakdown,
    caps: CriterionCaps,
    evaluated_document_version_ids: list[str],
    additional_warnings: list[str] | None = None,
) -> ReliabilityEvaluationResult:
    adjusted_breakdown = _apply_final_level_cap(breakdown=breakdown, caps=caps)
    level = get_reliability_level(adjusted_breakdown.total_score)

    warnings = list(caps.warnings)
    for criterion in [
        llm_result.traceability,
        llm_result.source_authority,
        llm_result.current_validity,
        llm_result.independent_evidence,
        llm_result.factual_consistency,
    ]:
        warnings.extend(criterion.warnings)
    if additional_warnings:
        warnings.extend(additional_warnings)

    criteria: dict[str, ReliabilityCriterionResult] = {
        "traceability": llm_result.traceability,
        "source_authority": llm_result.source_authority,
        "current_validity": llm_result.current_validity,
        "independent_evidence": llm_result.independent_evidence,
        "factual_consistency": llm_result.factual_consistency,
    }

    return ReliabilityEvaluationResult(
        issue_id=issue_id,
        issue_title=issue_title,
        reliability_score=adjusted_breakdown.total_score,
        reliability_level=level,
        traceability_score=adjusted_breakdown.traceability_score,
        source_authority_score=adjusted_breakdown.source_authority_score,
        current_validity_score=adjusted_breakdown.current_validity_score,
        independent_evidence_score=adjusted_breakdown.independent_evidence_score,
        factual_consistency_score=adjusted_breakdown.factual_consistency_score,
        summary_reason=merge_summary_reason(llm_result, adjusted_breakdown),
        criteria=criteria,
        conflicting_claims=llm_result.conflicting_claims,
        missing_information=llm_result.missing_information,
        evaluated_document_version_ids=evaluated_document_version_ids,
        warnings=list(dict.fromkeys(warnings)),
    )


def _apply_final_level_cap(*, breakdown: ReliabilityScoreBreakdown, caps: CriterionCaps) -> ReliabilityScoreBreakdown:
    if caps.final_level_cap is None:
        return breakdown

    max_score = _FINAL_LEVEL_MAX_SCORE[caps.final_level_cap]
    if breakdown.total_score <= max_score:
        return breakdown

    adjusted_scores = {
        "traceability_score": breakdown.traceability_score,
        "source_authority_score": breakdown.source_authority_score,
        "current_validity_score": breakdown.current_validity_score,
        "independent_evidence_score": breakdown.independent_evidence_score,
        "factual_consistency_score": breakdown.factual_consistency_score,
    }
    overflow = breakdown.total_score - max_score

    for field_name, score in sorted(adjusted_scores.items(), key=lambda item: item[1], reverse=True):
        if overflow <= 0:
            break
        reduction = min(score, overflow)
        adjusted_scores[field_name] = score - reduction
        overflow -= reduction

    adjusted_total = sum(adjusted_scores.values())
    validate_total_score(adjusted_total)
    return ReliabilityScoreBreakdown(total_score=adjusted_total, **adjusted_scores)

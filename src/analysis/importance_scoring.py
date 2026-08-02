from __future__ import annotations

from .exceptions import InvalidCategoryError, InvalidScoreError
from .importance_models import (
    IMPORTANCE_LEVEL_LOW_MAX,
    IMPORTANCE_LEVEL_MEDIUM_MAX,
    ImportanceCaps,
    ImportanceCriterionResult,
    ImportanceEvaluationResult,
    ImportanceLevel,
    ImportanceLLMResult,
    ImportanceMachineSignals,
    ImportanceScoreBreakdown,
)


_FINAL_LEVEL_MAX_SCORE = {
    ImportanceLevel.LOW: 39,
    ImportanceLevel.MEDIUM: 69,
    ImportanceLevel.HIGH: 100,
}


def compute_importance_total_score(llm_result: ImportanceLLMResult) -> int:
    return (
        llm_result.direct_relevance.score
        + llm_result.business_impact.score
        + llm_result.urgency.score
        + llm_result.industry_impact.score
        + llm_result.duration.score
        + llm_result.external_attention.score
    )


def get_importance_level(score: int) -> ImportanceLevel:
    validate_importance_total_score(score)
    if score > IMPORTANCE_LEVEL_MEDIUM_MAX:
        return ImportanceLevel.HIGH
    if score > IMPORTANCE_LEVEL_LOW_MAX:
        return ImportanceLevel.MEDIUM
    return ImportanceLevel.LOW


def validate_importance_total_score(score: int) -> None:
    if score < 0 or score > 100:
        raise InvalidScoreError("최종 중요도 점수는 0~100 사이여야 합니다.")


def apply_importance_caps(*, llm_result: ImportanceLLMResult, signals: ImportanceMachineSignals) -> tuple[ImportanceScoreBreakdown, ImportanceCaps]:
    caps = build_importance_caps(signals=signals)

    direct_relevance_score = min(llm_result.direct_relevance.score, caps.direct_relevance_max)
    business_impact_score = min(llm_result.business_impact.score, caps.business_impact_max)
    urgency_score = min(llm_result.urgency.score, caps.urgency_max)
    industry_impact_score = min(llm_result.industry_impact.score, caps.industry_impact_max)
    duration_score = min(llm_result.duration.score, caps.duration_max)
    external_attention_score = min(llm_result.external_attention.score, caps.external_attention_max)

    total_score = (
        direct_relevance_score
        + business_impact_score
        + urgency_score
        + industry_impact_score
        + duration_score
        + external_attention_score
    )
    validate_importance_total_score(total_score)

    return (
        ImportanceScoreBreakdown(
            direct_relevance_score=direct_relevance_score,
            business_impact_score=business_impact_score,
            urgency_score=urgency_score,
            industry_impact_score=industry_impact_score,
            duration_score=duration_score,
            external_attention_score=external_attention_score,
            total_score=total_score,
        ),
        caps,
    )


def build_importance_caps(*, signals: ImportanceMachineSignals) -> ImportanceCaps:
    caps = ImportanceCaps()

    if not signals.sk_hynix_explicitly_mentioned and not signals.core_business_mentioned:
        caps.direct_relevance_max = min(caps.direct_relevance_max, 8)
        caps.warnings.append("SK하이닉스 또는 핵심 사업 연결이 불명확하여 직접 관련성 상한이 적용되었습니다.")
        caps.applied_caps.append({"field": "direct_relevance", "max": 8, "reason": "sk_hynix_or_core_business_missing"})

    if signals.forecast_only:
        caps.business_impact_max = min(caps.business_impact_max, 15)
        caps.urgency_max = min(caps.urgency_max, 8)
        caps.external_attention_max = min(caps.external_attention_max, 5)
        caps.warnings.append("전망 단계 이슈로 판단되어 사업 영향, 긴급성, 외부 관심도 상한이 적용되었습니다.")
        caps.applied_caps.extend([
            {"field": "business_impact", "max": 15, "reason": "forecast_only"},
            {"field": "urgency", "max": 8, "reason": "forecast_only"},
            {"field": "external_attention", "max": 5, "reason": "forecast_only"},
        ])

    if not signals.quantitative_impact_present:
        caps.business_impact_max = min(caps.business_impact_max, 15)
        caps.warnings.append("영향 규모의 구체적 근거가 부족하여 사업 영향 규모 상한이 적용되었습니다.")
        caps.applied_caps.append({"field": "business_impact", "max": 15, "reason": "numeric_evidence_missing"})

    if signals.promotional_or_event_only:
        caps.final_level_cap = ImportanceLevel.MEDIUM
        caps.warnings.append("행사성 또는 홍보성 이슈로 판단되어 최종 등급은 높음을 초과할 수 없습니다.")
        caps.applied_caps.append({"field": "final_level", "max_level": ImportanceLevel.MEDIUM.value, "reason": "promotional_or_event_only"})

    if signals.duplicated_republish_detected:
        caps.external_attention_max = min(caps.external_attention_max, 5)
        caps.warnings.append("동일 원문 재배포가 감지되어 외부 관심도 상한이 적용되었습니다.")
        caps.applied_caps.append({"field": "external_attention", "max": 5, "reason": "duplicated_republish_detected"})

    if signals.event_already_ended:
        caps.urgency_max = min(caps.urgency_max, 4)
        caps.duration_max = min(caps.duration_max, 3)
        caps.warnings.append("이미 종료된 사건으로 판단되어 긴급성과 지속성 상한이 적용되었습니다.")
        caps.applied_caps.extend([
            {"field": "urgency", "max": 4, "reason": "event_already_ended"},
            {"field": "duration", "max": 3, "reason": "event_already_ended"},
        ])

    if signals.document_count == 1:
        caps.external_attention_max = min(caps.external_attention_max, 6)
        caps.warnings.append("단일 출처 기반 평가이므로 외부 관심도 과대평가를 제한합니다.")
        caps.applied_caps.append({"field": "external_attention", "max": 6, "reason": "single_document"})

    return caps


def validate_importance_enums(llm_result: ImportanceLLMResult) -> None:
    if llm_result.impact_direction.value not in {"기회", "위험", "혼합", "중립"}:
        raise InvalidCategoryError("허용되지 않은 impact_direction입니다.")
    if llm_result.time_horizon.value not in {"즉시", "단기", "중기", "장기"}:
        raise InvalidCategoryError("허용되지 않은 time_horizon입니다.")


def merge_importance_summary_reason(llm_result: ImportanceLLMResult, breakdown: ImportanceScoreBreakdown) -> str:
    strongest = max(
        [
            (breakdown.direct_relevance_score, llm_result.direct_relevance.reason),
            (breakdown.business_impact_score, llm_result.business_impact.reason),
            (breakdown.urgency_score, llm_result.urgency.reason),
            (breakdown.industry_impact_score, llm_result.industry_impact.reason),
            (breakdown.duration_score, llm_result.duration.reason),
            (breakdown.external_attention_score, llm_result.external_attention.reason),
        ],
        key=lambda item: item[0],
    )
    return strongest[1]


def build_importance_final_result(
    *,
    issue_id: str | None,
    issue_title: str,
    llm_result: ImportanceLLMResult,
    breakdown: ImportanceScoreBreakdown,
    caps: ImportanceCaps,
    signals: ImportanceMachineSignals,
    evaluated_document_version_ids: list[str],
    additional_warnings: list[str] | None = None,
) -> ImportanceEvaluationResult:
    adjusted_breakdown, adjusted_caps = _apply_final_level_cap(breakdown=breakdown, caps=caps)
    level = get_importance_level(adjusted_breakdown.total_score)

    warnings = list(adjusted_caps.warnings)
    for criterion in [
        llm_result.direct_relevance,
        llm_result.business_impact,
        llm_result.urgency,
        llm_result.industry_impact,
        llm_result.duration,
        llm_result.external_attention,
    ]:
        warnings.extend(criterion.uncertainties)
    if additional_warnings:
        warnings.extend(additional_warnings)

    criteria: dict[str, ImportanceCriterionResult] = {
        "direct_relevance": llm_result.direct_relevance,
        "business_impact": llm_result.business_impact,
        "urgency": llm_result.urgency,
        "industry_impact": llm_result.industry_impact,
        "duration": llm_result.duration,
        "external_attention": llm_result.external_attention,
    }
    code_signals = {
        "sk_hynix_explicitly_mentioned": signals.sk_hynix_explicitly_mentioned,
        "core_memory_business_mentioned": signals.core_business_mentioned,
        "numeric_evidence_present": signals.quantitative_impact_present,
        "forecast_only": signals.forecast_only,
        "promotional_content": signals.promotional_or_event_only,
        "republication_detected": signals.duplicated_republish_detected,
    }

    return ImportanceEvaluationResult(
        issue_id=issue_id,
        issue_title=issue_title,
        importance_score=adjusted_breakdown.total_score,
        importance_level=level,
        direct_relevance_score=adjusted_breakdown.direct_relevance_score,
        business_impact_score=adjusted_breakdown.business_impact_score,
        urgency_score=adjusted_breakdown.urgency_score,
        industry_impact_score=adjusted_breakdown.industry_impact_score,
        duration_score=adjusted_breakdown.duration_score,
        external_attention_score=adjusted_breakdown.external_attention_score,
        impact_direction=llm_result.impact_direction,
        time_horizon=llm_result.time_horizon,
        summary_reason=merge_importance_summary_reason(llm_result, adjusted_breakdown),
        criteria=criteria,
        applied_caps=adjusted_caps.applied_caps,
        code_signals=code_signals,
        core_summary=llm_result.core_summary,
        key_points=list(llm_result.key_points),
        key_numbers=list(llm_result.key_numbers),
        sk_hynix_implication=llm_result.sk_hynix_implication,
        summary_evidence_refs=list(llm_result.summary_evidence_refs),
        affected_areas=llm_result.affected_areas,
        opportunities=llm_result.opportunities,
        risks=llm_result.risks,
        watch_points=llm_result.watch_points,
        missing_information=llm_result.missing_information,
        evaluated_document_version_ids=evaluated_document_version_ids,
        warnings=list(dict.fromkeys(warnings)),
    )


def _apply_final_level_cap(*, breakdown: ImportanceScoreBreakdown, caps: ImportanceCaps) -> tuple[ImportanceScoreBreakdown, ImportanceCaps]:
    if caps.final_level_cap is None:
        return breakdown, caps

    max_score = _FINAL_LEVEL_MAX_SCORE[caps.final_level_cap]
    if breakdown.total_score <= max_score:
        return breakdown, caps

    adjusted_scores = {
        "direct_relevance_score": breakdown.direct_relevance_score,
        "business_impact_score": breakdown.business_impact_score,
        "urgency_score": breakdown.urgency_score,
        "industry_impact_score": breakdown.industry_impact_score,
        "duration_score": breakdown.duration_score,
        "external_attention_score": breakdown.external_attention_score,
    }
    overflow = breakdown.total_score - max_score
    for field_name, score in sorted(adjusted_scores.items(), key=lambda item: item[1], reverse=True):
        if overflow <= 0:
            break
        reduction = min(score, overflow)
        adjusted_scores[field_name] = score - reduction
        overflow -= reduction

    adjusted_total = sum(adjusted_scores.values())
    validate_importance_total_score(adjusted_total)
    adjusted_caps = caps.model_copy(deep=True)
    adjusted_caps.applied_caps.append({
        "field": "final_level",
        "max_level": caps.final_level_cap.value,
        "score_before_cap": breakdown.total_score,
        "score_after_cap": adjusted_total,
        "reason": "final_level_cap_applied",
    })
    return ImportanceScoreBreakdown(total_score=adjusted_total, **adjusted_scores), adjusted_caps


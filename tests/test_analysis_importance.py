from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from src.analysis.classifier import parse_json_response
from src.analysis.exceptions import InvalidJsonResponseError, InvalidScoreError, MissingApiKeyError
from src.analysis.importance import (
    evaluate_and_save_importances,
    evaluate_importance,
    parse_importance_response,
)
from src.analysis.importance_models import (
    ImpactDirection,
    ImportanceCriterionResult,
    ImportanceEvaluationRequest,
    ImportanceLLMResult,
    ImportanceLevel,
    ImportanceMachineSignals,
    TimeHorizon,
)
from src.analysis.importance_scoring import apply_importance_caps, build_importance_final_result, compute_importance_total_score, get_importance_level


def _criterion(score: int, reason: str = "ok") -> ImportanceCriterionResult:
    return ImportanceCriterionResult(
        score=score,
        reason=reason,
        evidence_document_ids=["doc-1"],
        uncertainties=[],
    )


def _llm_result() -> ImportanceLLMResult:
    return ImportanceLLMResult(
        direct_relevance=_criterion(20, "직접 관련"),
        business_impact=_criterion(22, "사업 영향 큼"),
        urgency=_criterion(10, "단기 대응 필요"),
        industry_impact=_criterion(12, "시장 파급"),
        duration=_criterion(8, "중장기 영향"),
        external_attention=_criterion(7, "복수 보도"),
        impact_direction=ImpactDirection.MIXED,
        time_horizon=TimeHorizon.MID_TERM,
        core_summary="HBM 공급 확대와 고객 대응 계획이 공개됐다.",
        key_points=["HBM 공급 확대", "고객 대응 계획 발표", "연내 양산 일정 유지"],
        key_numbers=[{
            "label": "증설 규모",
            "value": "20",
            "unit": "%",
            "context": "HBM 생산능력 확대",
            "information_type": "fact",
            "evidence_document_version_id": "doc-1",
            "quoted_text": "생산능력을 20% 늘린다",
        }],
        sk_hynix_implication="HBM 공급 경쟁력과 고객 대응 속도에 직접 영향이 있다.",
        summary_evidence_refs=[{
            "document_version_id": "doc-1",
            "quoted_text": "생산능력을 20% 늘린다",
            "supports": ["core_summary", "key_points[0]", "key_numbers[0]"],
        }],
        affected_areas=["HBM"],
        opportunities=["점유율 확대"],
        risks=["경쟁 심화"],
        watch_points=["고객 채택"],
        missing_information=[],
    )


def _signals() -> ImportanceMachineSignals:
    return ImportanceMachineSignals(
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
        promotional_or_event_only=False,
        event_already_ended=False,
    )


def _request() -> ImportanceEvaluationRequest:
    return ImportanceEvaluationRequest(
        workspace_id="ws-1",
        issue_id="issue-1",
        issue_title="테스트 중요도 이슈",
        primary_category="제품·기술",
        secondary_categories=["고객·수요산업"],
        reliability_score=80,
        reliability_level="높음",
        independent_source_count=1,
        documents=[{
            "document_version_id": "doc-1",
            "title": "SK하이닉스 HBM 기사",
            "source_name": "테스트 출처",
            "source_type": "official_press",
            "canonical_url": "https://example.com/1",
            "published_at": "2026-08-01T00:00:00+09:00",
            "markdown": "SK하이닉스가 HBM 생산 확대를 발표했다. 생산능력을 20% 늘린다.",
            "source_id": "source-1",
        }],
    )


def _raw_payload(**overrides: object) -> str:
    payload = _llm_result().model_dump(mode="json")
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def test_compute_importance_total_score() -> None:
    assert compute_importance_total_score(_llm_result()) == 79


def test_validate_importance_total_score_range() -> None:
    with pytest.raises(InvalidScoreError):
        get_importance_level(101)


def test_low_importance_level() -> None:
    assert get_importance_level(39) == ImportanceLevel.LOW


def test_medium_importance_level() -> None:
    assert get_importance_level(40) == ImportanceLevel.MEDIUM
    assert get_importance_level(69) == ImportanceLevel.MEDIUM


def test_high_importance_level() -> None:
    assert get_importance_level(70) == ImportanceLevel.HIGH
    assert get_importance_level(100) == ImportanceLevel.HIGH


def test_direct_relevance_over_limit_rejected() -> None:
    with pytest.raises(ValueError):
        ImportanceLLMResult.model_validate({**_llm_result().model_dump(mode="json"), "direct_relevance": {**_llm_result().direct_relevance.model_dump(mode="json"), "score": 26}})


def test_summary_fields_are_parsed_and_normalized() -> None:
    result = parse_importance_response(
        _raw_payload(
            core_summary="  HBM 공급 확대 발표  ",
            key_points=["핵심 1", "핵심 1", " ", "핵심 2", "핵심 3"],
        ),
        allowed_document_version_ids=["doc-1"],
    )
    assert result.core_summary == "HBM 공급 확대 발표"
    assert result.key_points == ["핵심 1", "핵심 2", "핵심 3"]


def test_invalid_key_points_rejected() -> None:
    with pytest.raises(ValueError, match="INVALID_KEY_POINTS"):
        parse_importance_response(
            _raw_payload(key_points=["하나", "하나"]),
            allowed_document_version_ids=["doc-1"],
        )


def test_invalid_summary_evidence_document_id_rejected() -> None:
    payload = _llm_result().model_dump(mode="json")
    payload["summary_evidence_refs"][0]["document_version_id"] = "doc-x"
    with pytest.raises(ValueError, match="INVALID_SUMMARY_EVIDENCE"):
        parse_importance_response(json.dumps(payload, ensure_ascii=False), allowed_document_version_ids=["doc-1"])


def test_invalid_key_numbers_document_id_rejected() -> None:
    payload = _llm_result().model_dump(mode="json")
    payload["key_numbers"][0]["evidence_document_version_id"] = "doc-x"
    with pytest.raises(ValueError, match="INVALID_KEY_NUMBERS"):
        parse_importance_response(json.dumps(payload, ensure_ascii=False), allowed_document_version_ids=["doc-1"])


def test_single_openrouter_call_generates_importance_and_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setenv("OPENROUTER_API_KEY", "key")
    monkeypatch.setenv("OPENROUTER_MODEL", "model-a")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

    def fake_completion(*, system_prompt: str, user_prompt: str, model: str) -> str:
        calls.append(model)
        assert "core_summary" in user_prompt
        assert model == "model-a"
        return _raw_payload()

    monkeypatch.setattr("src.analysis.importance.create_json_completion", fake_completion)
    result = evaluate_importance(_request())
    assert len(calls) == 1
    assert result.core_summary
    assert result.sk_hynix_implication
    assert result.key_points


def test_missing_api_key_fails_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    # delenv가 아니라 setenv("")를 쓴다 — get_openrouter_settings()가 매번 load_dotenv()를
    # 호출하는데, 기본 override=False라 "아예 없는" 값만 .env로 채워 넣고 "빈 문자열로
    # 이미 설정된" 값은 안 건드린다. delenv로 지우면 이 worktree 상위 경로의 실제 .env
    # (레포 루트)에서 진짜 키가 다시 채워져 "키 없음" 시나리오 자체가 깨진다.
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("OPENROUTER_MODEL", "")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    with pytest.raises(MissingApiKeyError, match="OPENROUTER_API_KEY"):
        evaluate_importance(_request())


def test_non_json_response_rejected() -> None:
    with pytest.raises(InvalidJsonResponseError):
        parse_json_response("not-json")


def test_final_level_cap_keeps_score_level_and_summary() -> None:
    llm_result = _llm_result().model_copy(
        update={
            "direct_relevance": _criterion(24, "직접 관련"),
            "business_impact": _criterion(22, "사업 영향 큼"),
            "urgency": _criterion(11, "긴급 대응 필요"),
            "industry_impact": _criterion(13, "시장 파급"),
            "duration": _criterion(9, "지속성 높음"),
        }
    )
    signals = _signals().model_copy(update={"promotional_or_event_only": True})
    breakdown, caps = apply_importance_caps(llm_result=llm_result, signals=signals)
    result = build_importance_final_result(
        issue_id="ver-1",
        issue_title="중요도 테스트",
        llm_result=llm_result,
        breakdown=breakdown,
        caps=caps,
        signals=signals,
        evaluated_document_version_ids=["doc-1"],
    )
    assert result.importance_level == ImportanceLevel.MEDIUM
    assert result.importance_score == 69
    assert result.core_summary
    assert result.summary_evidence_refs


def test_evaluate_and_save_importances_preserves_order(monkeypatch):
    def fake_evaluate(*, workspace_id, document_version_id, force=False):
        return document_version_id

    monkeypatch.setattr("src.analysis.importance.evaluate_and_save_importance", fake_evaluate)

    results = evaluate_and_save_importances(
        workspace_id="ws-1",
        document_version_ids=["doc-1", "doc-2", "doc-3"],
    )

    assert results == ["doc-1", "doc-2", "doc-3"]


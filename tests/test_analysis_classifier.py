from __future__ import annotations

import pytest

from src.analysis.classifier import classify_document, parse_classification_response
from src.analysis.exceptions import InvalidCategoryError, InvalidJsonResponseError, MissingApiKeyError
from src.analysis.interface import classify_document_versions
from src.analysis.models import ClassificationResult


def test_parse_valid_json_response() -> None:
    result = parse_classification_response(
        """
        {
          "primary_category": "제품·기술",
          "secondary_categories": ["시장·경영"],
          "confidence": 0.91,
          "reason": "HBM 신제품과 기술 특성이 기사 중심이다."
        }
        """
    )

    assert isinstance(result, ClassificationResult)
    assert result.primary_category.value == "제품·기술"
    assert [item.value for item in result.secondary_categories] == ["시장·경영"]


def test_reject_invalid_category() -> None:
    with pytest.raises(InvalidCategoryError, match="허용되지 않은 카테고리"):
        parse_classification_response(
            """
            {
              "primary_category": "기타",
              "secondary_categories": [],
              "confidence": 0.5,
              "reason": "허용되지 않은 값"
            }
            """
        )


def test_reject_duplicate_primary_secondary() -> None:
    with pytest.raises(ValueError, match="중복"):
        parse_classification_response(
            """
            {
              "primary_category": "경쟁사",
              "secondary_categories": ["경쟁사"],
              "confidence": 0.5,
              "reason": "경쟁사 기사"
            }
            """
        )


def test_reject_confidence_out_of_range() -> None:
    with pytest.raises(ValueError, match="less than or equal to 1"):
        parse_classification_response(
            """
            {
              "primary_category": "시장·경영",
              "secondary_categories": [],
              "confidence": 1.5,
              "reason": "시장 전망 기사"
            }
            """
        )


def test_missing_api_key_fails_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    # delenv가 아니라 setenv("")를 쓴다 — get_openrouter_settings()가 매번 load_dotenv()를
    # 호출하는데, 기본 override=False라 "아예 없는" 값만 .env로 채워 넣고 "빈 문자열로
    # 이미 설정된" 값은 안 건드린다. delenv로 지우면 이 worktree 상위 경로의 실제 .env
    # (레포 루트)에서 진짜 키가 다시 채워져 "키 없음" 시나리오 자체가 깨진다.
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("OPENROUTER_MODEL", "")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

    with pytest.raises(MissingApiKeyError, match="OPENROUTER_API_KEY"):
        classify_document(title="t", markdown="m")


def test_reject_more_than_two_secondary_categories() -> None:
    with pytest.raises(ValueError, match="최대 2개"):
        parse_classification_response(
            """
            {
              "primary_category": "공급망·생산",
              "secondary_categories": ["시장·경영", "경쟁사", "정책·규제"],
              "confidence": 0.7,
              "reason": "공급망 기사"
            }
            """
        )


def test_non_json_response_raises() -> None:
    with pytest.raises(InvalidJsonResponseError):
        parse_classification_response("not-json")


def test_classify_document_versions_preserves_order_and_runs_concurrently(monkeypatch):
    import time

    call_order: list[str] = []

    def fake_classify(*, workspace_id, document_version_id, force=False):
        if document_version_id == "doc-slow":
            time.sleep(0.05)
        call_order.append(document_version_id)
        return document_version_id  # 실제 StoredClassificationResult 대신 id를 그대로 반환해 순서만 확인

    monkeypatch.setattr("src.analysis.interface.classify_document_version", fake_classify)

    results = classify_document_versions(
        workspace_id="ws-1",
        document_version_ids=["doc-slow", "doc-fast-1", "doc-fast-2"],
    )

    assert results == ["doc-slow", "doc-fast-1", "doc-fast-2"]
    assert set(call_order) == {"doc-slow", "doc-fast-1", "doc-fast-2"}

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from .exceptions import InvalidScoreError
from .ranking_models import (
    IMPORTANCE_WEIGHT,
    RECENCY_WEIGHT,
    RELIABILITY_WEIGHT,
    RecencyScoreResult,
)

_SCORE_QUANTIZE = Decimal("0.01")
_HOURS_24 = Decimal("24")
_HOURS_48 = Decimal("48")
_HOURS_72 = Decimal("72")
_HOURS_120 = Decimal("120")


def validate_ranking_weights() -> None:
    total = IMPORTANCE_WEIGHT + RELIABILITY_WEIGHT + RECENCY_WEIGHT
    if total != Decimal("1.00"):
        raise ValueError("ranking weights must sum to 1.00")


def calculate_recency_score(*, published_at: datetime | None, reference_time: datetime) -> RecencyScoreResult:
    if reference_time.tzinfo is None or reference_time.utcoffset() is None:
        raise ValueError("reference_time must be timezone-aware")

    reference_utc = reference_time.astimezone(timezone.utc)
    if published_at is None:
        return RecencyScoreResult(score=0, age_hours=None, bucket="MISSING_PUBLISHED_AT", warnings=["MISSING_PUBLISHED_AT"])

    if published_at.tzinfo is None or published_at.utcoffset() is None:
        raise ValueError("published_at must be timezone-aware")

    published_utc = published_at.astimezone(timezone.utc)
    age_seconds = Decimal(str((reference_utc - published_utc).total_seconds()))
    age_hours = (age_seconds / Decimal("3600")).quantize(_SCORE_QUANTIZE, rounding=ROUND_HALF_UP)

    if age_seconds < 0:
        return RecencyScoreResult(score=100, age_hours=age_hours, bucket="FUTURE_PUBLISHED_AT", warnings=["FUTURE_PUBLISHED_AT"])
    if age_hours <= _HOURS_24:
        return RecencyScoreResult(score=100, age_hours=age_hours, bucket="WITHIN_24_HOURS")
    if age_hours <= _HOURS_48:
        return RecencyScoreResult(score=80, age_hours=age_hours, bucket="WITHIN_48_HOURS")
    if age_hours <= _HOURS_72:
        return RecencyScoreResult(score=60, age_hours=age_hours, bucket="WITHIN_72_HOURS")
    if age_hours <= _HOURS_120:
        return RecencyScoreResult(score=40, age_hours=age_hours, bucket="WITHIN_120_HOURS")
    return RecencyScoreResult(score=20, age_hours=age_hours, bucket="OLDER_THAN_120_HOURS")


def calculate_ranking_score(*, importance_score: int, reliability_score: int, recency_score: int) -> Decimal:
    validate_ranking_weights()
    _validate_component_score(importance_score, "importance_score")
    _validate_component_score(reliability_score, "reliability_score")
    _validate_component_score(recency_score, "recency_score")

    total = (
        Decimal(importance_score) * IMPORTANCE_WEIGHT
        + Decimal(reliability_score) * RELIABILITY_WEIGHT
        + Decimal(recency_score) * RECENCY_WEIGHT
    ).quantize(_SCORE_QUANTIZE, rounding=ROUND_HALF_UP)

    if total < Decimal("0.00") or total > Decimal("100.00"):
        raise InvalidScoreError("최종 랭킹 점수는 0.00~100.00 범위여야 합니다.")
    return total


def _validate_component_score(score: int, field_name: str) -> None:
    if score < 0 or score > 100:
        raise InvalidScoreError(f"{field_name}는 0~100 범위여야 합니다.")

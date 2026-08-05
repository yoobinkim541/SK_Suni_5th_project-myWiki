from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.analysis.models import Category
from src.report.models import ReportCandidate
from src.report.selector import select_report_candidates


def make_candidate(
    *,
    analysis_result_id: str,
    category: Category = Category.PRODUCT_TECHNOLOGY,
    reliability_score: int = 80,
    importance_score: int = 85,
    ranking_score: Decimal | None = Decimal("90.0"),
    published_at: datetime | None = None,
    source_type: str | None = None,
) -> ReportCandidate:
    return ReportCandidate(
        analysis_result_id=analysis_result_id,
        workspace_id="ws-1",
        document_id=f"doc-{analysis_result_id}",
        document_version_id=f"ver-{analysis_result_id}",
        category=category,
        title=f"title-{analysis_result_id}",
        summary="summary",
        reliability_score=reliability_score,
        importance_score=importance_score,
        ranking_score=ranking_score,
        source_name="source",
        source_type=source_type,
        canonical_url=f"https://example.com/{analysis_result_id}",
        published_at=published_at or datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc),
    )


def test_excludes_candidates_below_reliability_threshold() -> None:
    selected = select_report_candidates(
        [
            make_candidate(analysis_result_id="a", reliability_score=70),
            make_candidate(analysis_result_id="b", reliability_score=69),
        ],
        max_candidates=10,
        min_reliability_score=70,
        min_importance_score=0,
    )

    assert [item.analysis_result_id for item in selected] == ["a"]


def test_excludes_candidates_below_importance_threshold() -> None:
    selected = select_report_candidates(
        [
            make_candidate(analysis_result_id="a", importance_score=70),
            make_candidate(analysis_result_id="b", importance_score=69),
        ],
        max_candidates=10,
        min_reliability_score=0,
        min_importance_score=70,
    )

    assert [item.analysis_result_id for item in selected] == ["a"]


def test_optional_ranking_threshold_filters_only_when_provided() -> None:
    candidates = [
        make_candidate(analysis_result_id="a", ranking_score=Decimal("70.0")),
        make_candidate(analysis_result_id="b", ranking_score=Decimal("69.9")),
    ]

    selected_without_threshold = select_report_candidates(
        candidates,
        max_candidates=10,
        min_reliability_score=0,
        min_importance_score=0,
    )
    selected_with_threshold = select_report_candidates(
        candidates,
        max_candidates=10,
        min_reliability_score=0,
        min_importance_score=0,
        min_ranking_score=Decimal("70.0"),
    )

    assert [item.analysis_result_id for item in selected_without_threshold] == ["a", "b"]
    assert [item.analysis_result_id for item in selected_with_threshold] == ["a"]


def test_boundary_scores_are_included() -> None:
    selected = select_report_candidates(
        [
            make_candidate(
                analysis_result_id="a",
                reliability_score=70,
                importance_score=80,
                ranking_score=Decimal("90.0"),
            )
        ],
        max_candidates=10,
        min_reliability_score=70,
        min_importance_score=80,
        min_ranking_score=Decimal("90.0"),
    )

    assert [item.analysis_result_id for item in selected] == ["a"]


def test_sorts_by_ranking_then_importance_then_reliability_then_published_at_then_id() -> None:
    candidates = [
        make_candidate(
            analysis_result_id="d",
            ranking_score=Decimal("90.0"),
            importance_score=80,
            reliability_score=80,
            published_at=datetime(2026, 8, 2, 2, 0, tzinfo=timezone.utc),
        ),
        make_candidate(
            analysis_result_id="c",
            ranking_score=Decimal("90.0"),
            importance_score=80,
            reliability_score=85,
            published_at=datetime(2026, 8, 2, 1, 0, tzinfo=timezone.utc),
        ),
        make_candidate(
            analysis_result_id="b",
            ranking_score=Decimal("90.0"),
            importance_score=85,
            reliability_score=80,
            published_at=datetime(2026, 8, 2, 1, 0, tzinfo=timezone.utc),
        ),
        make_candidate(
            analysis_result_id="a",
            ranking_score=Decimal("95.0"),
            importance_score=70,
            reliability_score=70,
            published_at=datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc),
        ),
    ]

    selected = select_report_candidates(
        candidates,
        max_candidates=10,
        min_reliability_score=0,
        min_importance_score=0,
    )

    assert [item.analysis_result_id for item in selected] == ["a", "b", "c", "d"]


def test_fully_tied_candidates_have_deterministic_order() -> None:
    candidates_a = [
        make_candidate(analysis_result_id="b"),
        make_candidate(analysis_result_id="a"),
        make_candidate(analysis_result_id="c"),
    ]
    candidates_b = [
        make_candidate(analysis_result_id="c"),
        make_candidate(analysis_result_id="b"),
        make_candidate(analysis_result_id="a"),
    ]

    selected_a = select_report_candidates(
        candidates_a,
        max_candidates=10,
        min_reliability_score=0,
        min_importance_score=0,
    )
    selected_b = select_report_candidates(
        candidates_b,
        max_candidates=10,
        min_reliability_score=0,
        min_importance_score=0,
    )

    assert [item.analysis_result_id for item in selected_a] == ["a", "b", "c"]
    assert [item.analysis_result_id for item in selected_b] == ["a", "b", "c"]


def test_applies_category_limit() -> None:
    candidates = [
        make_candidate(analysis_result_id="a1", category=Category.PRODUCT_TECHNOLOGY),
        make_candidate(analysis_result_id="a2", category=Category.PRODUCT_TECHNOLOGY),
        make_candidate(analysis_result_id="a3", category=Category.PRODUCT_TECHNOLOGY),
    ]

    selected = select_report_candidates(
        candidates,
        max_candidates=10,
        min_reliability_score=0,
        min_importance_score=0,
        category_limits={Category.PRODUCT_TECHNOLOGY: 2},
    )

    assert [item.analysis_result_id for item in selected] == ["a1", "a2"]


def test_continues_after_skipping_category_limited_candidate() -> None:
    candidates = [
        make_candidate(analysis_result_id="a1", category=Category.PRODUCT_TECHNOLOGY, ranking_score=Decimal("95.0")),
        make_candidate(analysis_result_id="a2", category=Category.PRODUCT_TECHNOLOGY, ranking_score=Decimal("94.0")),
        make_candidate(analysis_result_id="a3", category=Category.PRODUCT_TECHNOLOGY, ranking_score=Decimal("93.0")),
        make_candidate(analysis_result_id="b1", category=Category.COMPETITOR, ranking_score=Decimal("92.0")),
        make_candidate(analysis_result_id="c1", category=Category.CUSTOMER_DEMAND, ranking_score=Decimal("91.0")),
    ]

    selected = select_report_candidates(
        candidates,
        max_candidates=4,
        min_reliability_score=0,
        min_importance_score=0,
        category_limits={Category.PRODUCT_TECHNOLOGY: 2},
    )

    assert [item.analysis_result_id for item in selected] == ["a1", "a2", "b1", "c1"]


def test_category_limits_none_means_no_category_cap() -> None:
    candidates = [
        make_candidate(analysis_result_id="a1", category=Category.PRODUCT_TECHNOLOGY),
        make_candidate(analysis_result_id="a2", category=Category.PRODUCT_TECHNOLOGY),
        make_candidate(analysis_result_id="a3", category=Category.PRODUCT_TECHNOLOGY),
    ]

    selected = select_report_candidates(
        candidates,
        max_candidates=10,
        min_reliability_score=0,
        min_importance_score=0,
        category_limits=None,
    )

    assert len(selected) == 3


def test_partial_category_limits_only_apply_to_listed_categories() -> None:
    candidates = [
        make_candidate(analysis_result_id="a1", category=Category.PRODUCT_TECHNOLOGY, ranking_score=Decimal("95.0")),
        make_candidate(analysis_result_id="a2", category=Category.PRODUCT_TECHNOLOGY, ranking_score=Decimal("94.0")),
        make_candidate(analysis_result_id="b1", category=Category.COMPETITOR, ranking_score=Decimal("93.0")),
        make_candidate(analysis_result_id="b2", category=Category.COMPETITOR, ranking_score=Decimal("92.0")),
    ]

    selected = select_report_candidates(
        candidates,
        max_candidates=10,
        min_reliability_score=0,
        min_importance_score=0,
        category_limits={Category.PRODUCT_TECHNOLOGY: 1},
    )

    assert [item.analysis_result_id for item in selected] == ["a1", "b1", "b2"]


def test_applies_overall_max_candidates() -> None:
    candidates = [make_candidate(analysis_result_id=f"id-{index}") for index in range(30)]

    selected = select_report_candidates(
        candidates,
        max_candidates=20,
        min_reliability_score=0,
        min_importance_score=0,
    )

    assert len(selected) == 20


def test_returns_all_available_when_fewer_than_max_candidates() -> None:
    candidates = [make_candidate(analysis_result_id=f"id-{index}") for index in range(4)]

    selected = select_report_candidates(
        candidates,
        max_candidates=20,
        min_reliability_score=0,
        min_importance_score=0,
    )

    assert len(selected) == 4


def test_empty_input_returns_empty_list() -> None:
    assert select_report_candidates(
        [],
        max_candidates=10,
        min_reliability_score=0,
        min_importance_score=0,
    ) == []


def test_returns_empty_when_all_candidates_fail_thresholds() -> None:
    selected = select_report_candidates(
        [
            make_candidate(analysis_result_id="a", reliability_score=10),
            make_candidate(analysis_result_id="b", importance_score=10),
        ],
        max_candidates=10,
        min_reliability_score=70,
        min_importance_score=70,
    )

    assert selected == []


def test_does_not_mutate_input_list_or_candidates() -> None:
    candidates = [
        make_candidate(analysis_result_id="b", ranking_score=Decimal("80.0")),
        make_candidate(analysis_result_id="a", ranking_score=Decimal("90.0")),
    ]
    original_order = [item.analysis_result_id for item in candidates]
    original_dump = [item.model_dump() for item in candidates]

    selected = select_report_candidates(
        candidates,
        max_candidates=10,
        min_reliability_score=0,
        min_importance_score=0,
    )

    assert [item.analysis_result_id for item in candidates] == original_order
    assert [item.model_dump() for item in candidates] == original_dump
    assert [item.analysis_result_id for item in selected] == ["a", "b"]


def test_keeps_identifiers_intact() -> None:
    candidate = make_candidate(analysis_result_id="a")

    selected = select_report_candidates(
        [candidate],
        max_candidates=10,
        min_reliability_score=0,
        min_importance_score=0,
    )

    assert selected[0].analysis_result_id == candidate.analysis_result_id
    assert selected[0].workspace_id == candidate.workspace_id
    assert selected[0].document_id == candidate.document_id
    assert selected[0].document_version_id == candidate.document_version_id


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_candidates": 0, "min_reliability_score": 0, "min_importance_score": 0}, "max_candidates"),
        ({"max_candidates": -1, "min_reliability_score": 0, "min_importance_score": 0}, "max_candidates"),
        ({"max_candidates": 10, "min_reliability_score": -1, "min_importance_score": 0}, "min_reliability_score"),
        ({"max_candidates": 10, "min_reliability_score": 0, "min_importance_score": 101}, "min_importance_score"),
        ({"max_candidates": 10, "min_reliability_score": 0, "min_importance_score": 0, "min_ranking_score": Decimal("101")}, "min_ranking_score"),
        (
            {
                "max_candidates": 10,
                "min_reliability_score": 0,
                "min_importance_score": 0,
                "category_limits": {Category.PRODUCT_TECHNOLOGY: -1},
            },
            "category limit",
        ),
    ],
)
def test_invalid_configuration_raises_value_error(kwargs: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        select_report_candidates([make_candidate(analysis_result_id="a")], **kwargs)


def test_does_not_force_minimum_per_category() -> None:
    candidates = [
        make_candidate(analysis_result_id="a", category=Category.PRODUCT_TECHNOLOGY, reliability_score=80),
        make_candidate(analysis_result_id="b", category=Category.COMPETITOR, reliability_score=10),
        make_candidate(analysis_result_id="c", category=Category.POLICY_REGULATION, reliability_score=10),
    ]

    selected = select_report_candidates(
        candidates,
        max_candidates=10,
        min_reliability_score=70,
        min_importance_score=0,
    )

    assert [item.category for item in selected] == [Category.PRODUCT_TECHNOLOGY]


# ------------------------------------------------------------
# DART 공시(disclosure) 예외 — analysis/README.md "위키 페이지 후보 선정 기준의 예외" 참조.
# 공시는 1차 공식 기록이라 신뢰도(교차검증) 기준만 면제된다. importance_score(중요도)는
# "이 내용이 사업적으로 중요한가"를 재는 별개 축이라 공시라도 그대로 적용한다 —
# 그래야 사소한 행정 공시가 전부 위키 후보가 되는 걸 막을 수 있다.
# ------------------------------------------------------------


def test_disclosure_candidate_bypasses_reliability_threshold_only() -> None:
    """공시는 reliability_score가 기준치보다 낮아도(단일 출처라 낮게 나온 것) 통과하지만,
    importance_score 기준은 그대로 적용받는다."""
    selected = select_report_candidates(
        [
            make_candidate(
                analysis_result_id="disclosure-1",
                source_type="disclosure",
                reliability_score=0,
                importance_score=70,
            ),
            make_candidate(analysis_result_id="news-1", reliability_score=10, importance_score=70),
        ],
        max_candidates=10,
        min_reliability_score=70,
        min_importance_score=70,
    )

    assert [item.analysis_result_id for item in selected] == ["disclosure-1"]


def test_disclosure_candidate_still_excluded_when_importance_score_is_low() -> None:
    """실측 예시: 임원 소액 지분 매수 공시는 importance_score=2였다 — 단일 출처
    여부와 무관하게 사업적으로 무의미해서 낮은 것이므로, 공시라도 걸러져야 한다."""
    selected = select_report_candidates(
        [
            make_candidate(
                analysis_result_id="disclosure-1",
                source_type="disclosure",
                reliability_score=0,
                importance_score=2,
            ),
        ],
        max_candidates=10,
        min_reliability_score=70,
        min_importance_score=40,
    )

    assert selected == []


def test_disclosure_candidate_still_requires_ranking_threshold() -> None:
    selected = select_report_candidates(
        [
            make_candidate(analysis_result_id="disclosure-1", source_type="disclosure", ranking_score=None),
        ],
        max_candidates=10,
        min_reliability_score=0,
        min_importance_score=0,
        min_ranking_score=Decimal("90.0"),
    )

    assert selected == []


def test_disclosure_candidates_still_subject_to_category_limit_and_max_candidates() -> None:
    """예외는 신뢰도(근거가 부족하다는 판단) 기준에만 적용된다 — 리포트/위키 용량 제한
    (category_limits, max_candidates)은 공시도 뉴스와 똑같이 받는다."""
    candidates = [
        make_candidate(
            analysis_result_id=f"disclosure-{i}",
            source_type="disclosure",
            category=Category.MARKET_MANAGEMENT,
            reliability_score=0,
            importance_score=70,
        )
        for i in range(3)
    ]

    selected = select_report_candidates(
        candidates,
        max_candidates=10,
        min_reliability_score=70,
        min_importance_score=70,
        category_limits={Category.MARKET_MANAGEMENT: 2},
    )

    assert len(selected) == 2


def test_non_disclosure_source_type_still_requires_thresholds() -> None:
    """source_type이 disclosure가 아니면(뉴스/RSS 등) 예외가 적용되지 않는다."""
    selected = select_report_candidates(
        [
            make_candidate(analysis_result_id="rss-1", source_type="rss", reliability_score=10, importance_score=10),
        ],
        max_candidates=10,
        min_reliability_score=70,
        min_importance_score=70,
    )

    assert selected == []

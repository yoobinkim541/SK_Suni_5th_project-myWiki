from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.analysis.models import Category
from src.report.grouper import IssueGroupingConfig, group_report_candidates
from src.report.models import ReportCandidate


def make_candidate(
    *,
    analysis_result_id: str,
    workspace_id: str = "ws-1",
    document_id: str | None = None,
    document_version_id: str | None = None,
    category: Category = Category.PRODUCT_TECHNOLOGY,
    title: str = "Samsung HBM4 production expansion plan",
    summary: str | None = "Samsung expands HBM4 production capacity and supply planning for next year.",
    published_at: datetime | None = None,
    reliability_score: int = 80,
    importance_score: int = 80,
    ranking_score: Decimal | None = Decimal("80.0"),
) -> ReportCandidate:
    return ReportCandidate(
        analysis_result_id=analysis_result_id,
        workspace_id=workspace_id,
        document_id=document_id or f"doc-{analysis_result_id}",
        document_version_id=document_version_id or f"ver-{analysis_result_id}",
        category=category,
        title=title,
        summary=summary,
        reliability_score=reliability_score,
        importance_score=importance_score,
        ranking_score=ranking_score,
        source_name="source",
        canonical_url=f"https://example.com/{analysis_result_id}",
        published_at=published_at or datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc),
    )


def make_config(**overrides) -> IssueGroupingConfig:
    payload = {
        "max_time_gap_hours": 24,
        "min_title_similarity": 0.4,
        "min_summary_similarity": 0.2,
        "min_shared_title_tokens": 2,
        "require_same_category": True,
    }
    payload.update(overrides)
    return IssueGroupingConfig(**payload)


def test_empty_input_returns_empty_list() -> None:
    assert group_report_candidates([], config=make_config()) == []


def test_single_candidate_becomes_single_group() -> None:
    candidate = make_candidate(analysis_result_id="a")

    groups = group_report_candidates([candidate], config=make_config())

    assert len(groups) == 1
    assert groups[0].representative_analysis_result_id == "a"
    assert [item.analysis_result_id for item in groups[0].candidates] == ["a"]


def test_groups_candidates_with_explicit_group_keys() -> None:
    a = make_candidate(analysis_result_id="a", document_id="doc-a")
    b = make_candidate(analysis_result_id="b", document_id="doc-b")
    c = make_candidate(analysis_result_id="c", document_id="doc-c", title="Micron HBM expansion")

    groups = group_report_candidates(
        [a, b, c],
        config=make_config(),
        explicit_group_keys={"doc-a": "group-1", "doc-b": "group-1", "doc-c": "group-2"},
    )

    grouped_ids = [sorted(item.analysis_result_id for item in group.candidates) for group in groups]
    assert grouped_ids == [["a", "b"], ["c"]]


def test_candidates_without_explicit_group_keys_are_processed_normally() -> None:
    a = make_candidate(analysis_result_id="a")
    b = make_candidate(
        analysis_result_id="b",
        title="Samsung HBM4 supply expansion plan",
        summary="Samsung expands HBM4 supply capacity and production planning for next year.",
        published_at=datetime(2026, 8, 2, 1, 0, tzinfo=timezone.utc),
    )

    groups = group_report_candidates([a, b], config=make_config())

    assert len(groups) == 1
    assert sorted(item.analysis_result_id for item in groups[0].candidates) == ["a", "b"]


def test_mixed_workspace_input_raises_value_error() -> None:
    with pytest.raises(ValueError, match="workspace"):
        group_report_candidates(
            [
                make_candidate(analysis_result_id="a", workspace_id="ws-1"),
                make_candidate(analysis_result_id="b", workspace_id="ws-2"),
            ],
            config=make_config(),
        )


def test_different_categories_do_not_group() -> None:
    groups = group_report_candidates(
        [
            make_candidate(analysis_result_id="a", category=Category.PRODUCT_TECHNOLOGY),
            make_candidate(
                analysis_result_id="b",
                category=Category.COMPETITOR,
                title="Samsung HBM4 production expansion plan",
                summary="Samsung expands HBM4 production capacity and supply planning for next year.",
            ),
        ],
        config=make_config(),
    )

    assert len(groups) == 2


def test_groups_same_issue_by_text_when_category_and_time_match() -> None:
    groups = group_report_candidates(
        [
            make_candidate(
                analysis_result_id="a",
                title="Samsung HBM4 production expansion plan",
                summary="Samsung expands HBM4 production capacity and supply planning for next year.",
            ),
            make_candidate(
                analysis_result_id="b",
                title="Samsung HBM4 supply expansion plan",
                summary="Samsung expands HBM4 supply capacity and production planning for next year.",
                published_at=datetime(2026, 8, 2, 2, 0, tzinfo=timezone.utc),
            ),
        ],
        config=make_config(),
    )

    assert len(groups) == 1
    assert sorted(item.analysis_result_id for item in groups[0].candidates) == ["a", "b"]


def test_same_company_but_different_issue_stays_separate() -> None:
    groups = group_report_candidates(
        [
            make_candidate(
                analysis_result_id="a",
                title="Samsung HBM4 production expansion plan",
                summary="Samsung expands HBM4 production capacity and supply planning for next year.",
            ),
            make_candidate(
                analysis_result_id="b",
                title="Samsung foundry investment reduction review",
                summary="Samsung reviews foundry investment reduction and capex adjustments.",
            ),
        ],
        config=make_config(),
    )

    assert len(groups) == 2


def test_similar_title_but_different_summary_stays_separate() -> None:
    groups = group_report_candidates(
        [
            make_candidate(
                analysis_result_id="a",
                title="Samsung HBM4 expansion plan",
                summary="HBM4 production capacity and supply expansion details were announced.",
            ),
            make_candidate(
                analysis_result_id="b",
                title="Samsung HBM4 expansion plan",
                summary="A legal dispute over export licensing penalties is under review.",
            ),
        ],
        config=make_config(min_summary_similarity=0.3),
    )

    assert len(groups) == 2


def test_candidates_outside_time_window_stay_separate() -> None:
    groups = group_report_candidates(
        [
            make_candidate(analysis_result_id="a"),
            make_candidate(
                analysis_result_id="b",
                published_at=datetime(2026, 8, 4, 1, 0, tzinfo=timezone.utc),
            ),
        ],
        config=make_config(max_time_gap_hours=24),
    )

    assert len(groups) == 2


def test_time_window_boundary_is_inclusive() -> None:
    groups = group_report_candidates(
        [
            make_candidate(
                analysis_result_id="a",
                published_at=datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc),
            ),
            make_candidate(
                analysis_result_id="b",
                title="Samsung HBM4 supply expansion plan",
                summary="Samsung expands HBM4 supply capacity and production planning for next year.",
                published_at=datetime(2026, 8, 3, 0, 0, tzinfo=timezone.utc),
            ),
        ],
        config=make_config(max_time_gap_hours=24),
    )

    assert len(groups) == 1


def test_shared_title_token_requirement_blocks_weak_match() -> None:
    groups = group_report_candidates(
        [
            make_candidate(
                analysis_result_id="a",
                title="HBM4 production plan",
                summary="HBM4 production capacity and supply expansion were announced.",
            ),
            make_candidate(
                analysis_result_id="b",
                title="HBM4 roadmap",
                summary="HBM4 production capacity and supply expansion were announced.",
            ),
        ],
        config=make_config(min_shared_title_tokens=2),
    )

    assert len(groups) == 2


def test_transitive_chaining_is_avoided() -> None:
    groups = group_report_candidates(
        [
            make_candidate(
                analysis_result_id="a",
                title="Samsung HBM4 production expansion plan",
                summary="Samsung expands HBM4 production capacity and supply planning for next year.",
            ),
            make_candidate(
                analysis_result_id="b",
                title="Samsung HBM4 supply expansion plan",
                summary="Samsung expands HBM4 supply capacity and production planning for next year.",
                published_at=datetime(2026, 8, 2, 1, 0, tzinfo=timezone.utc),
            ),
            make_candidate(
                analysis_result_id="c",
                title="Samsung HBM4 customer certification schedule",
                summary="Customer certification timing and approval checks are being discussed.",
                published_at=datetime(2026, 8, 2, 2, 0, tzinfo=timezone.utc),
            ),
        ],
        config=make_config(min_summary_similarity=0.25),
    )

    grouped_sets = [sorted(item.analysis_result_id for item in group.candidates) for group in groups]
    assert ["a", "b"] in grouped_sets
    assert ["c"] in grouped_sets


def test_candidate_matching_multiple_groups_joins_best_similarity_group() -> None:
    groups = group_report_candidates(
        [
            make_candidate(
                analysis_result_id="a",
                title="Samsung HBM4 production expansion plan",
                summary="Samsung expands HBM4 production capacity and supply planning for next year.",
            ),
            make_candidate(
                analysis_result_id="b",
                title="Micron DRAM package review",
                summary="Micron reviews DRAM package sourcing and packaging cost changes.",
            ),
            make_candidate(
                analysis_result_id="c",
                title="Samsung HBM4 supply expansion plan",
                summary="Samsung expands HBM4 supply capacity and production planning for next year.",
                published_at=datetime(2026, 8, 2, 1, 0, tzinfo=timezone.utc),
            ),
        ],
        config=make_config(),
    )

    grouped_sets = [sorted(item.analysis_result_id for item in group.candidates) for group in groups]
    assert ["a", "c"] in grouped_sets


def test_representative_candidate_selection_is_deterministic() -> None:
    groups = group_report_candidates(
        [
            make_candidate(analysis_result_id="c", reliability_score=70, importance_score=90, ranking_score=Decimal("91.0")),
            make_candidate(analysis_result_id="b", reliability_score=80, importance_score=85, ranking_score=Decimal("90.0")),
            make_candidate(analysis_result_id="a", reliability_score=80, importance_score=85, ranking_score=Decimal("90.0"), published_at=datetime(2026, 8, 2, 1, 0, tzinfo=timezone.utc)),
        ],
        config=make_config(min_summary_similarity=0.0, min_title_similarity=0.0, min_shared_title_tokens=0),
    )

    assert len(groups) == 1
    assert groups[0].representative_analysis_result_id == "a"
    assert groups[0].candidates[0].analysis_result_id == "a"


def test_groups_are_sorted_by_representative_priority() -> None:
    groups = group_report_candidates(
        [
            make_candidate(analysis_result_id="a", ranking_score=Decimal("95.0"), title="Alpha launch milestone", summary="Alpha launch milestone and production readiness were updated."),
            make_candidate(analysis_result_id="b", ranking_score=Decimal("85.0"), title="Beta capacity review", summary="Beta capacity review and sourcing update were discussed."),
        ],
        config=make_config(min_title_similarity=0.8, min_summary_similarity=0.8, min_shared_title_tokens=2),
    )

    assert [group.representative_analysis_result_id for group in groups] == ["a", "b"]


def test_input_order_does_not_change_grouping_result() -> None:
    candidates_a = [
        make_candidate(analysis_result_id="a"),
        make_candidate(
            analysis_result_id="b",
            title="Samsung HBM4 supply expansion plan",
            summary="Samsung expands HBM4 supply capacity and production planning for next year.",
        ),
        make_candidate(
            analysis_result_id="c",
            title="Micron package review",
            summary="Micron package sourcing and capacity review for the next quarter.",
        ),
    ]
    candidates_b = [candidates_a[2], candidates_a[0], candidates_a[1]]

    groups_a = group_report_candidates(candidates_a, config=make_config())
    groups_b = group_report_candidates(candidates_b, config=make_config())

    assert [(group.issue_key, sorted(item.analysis_result_id for item in group.candidates), group.representative_analysis_result_id) for group in groups_a] == [
        (group.issue_key, sorted(item.analysis_result_id for item in group.candidates), group.representative_analysis_result_id)
        for group in groups_b
    ]


def test_every_candidate_appears_exactly_once() -> None:
    candidates = [
        make_candidate(analysis_result_id="a"),
        make_candidate(
            analysis_result_id="b",
            title="Samsung HBM4 supply expansion plan",
            summary="Samsung expands HBM4 supply capacity and production planning for next year.",
        ),
        make_candidate(
            analysis_result_id="c",
            title="Micron package review",
            summary="Micron package sourcing and capacity review for the next quarter.",
        ),
    ]

    groups = group_report_candidates(candidates, config=make_config())
    grouped_ids = [item.analysis_result_id for group in groups for item in group.candidates]

    assert sorted(grouped_ids) == ["a", "b", "c"]
    assert len(grouped_ids) == len(set(grouped_ids))


def test_unmatched_candidate_remains_singleton_group() -> None:
    groups = group_report_candidates(
        [
            make_candidate(analysis_result_id="a"),
            make_candidate(
                analysis_result_id="b",
                title="TSMC packaging expansion update",
                summary="TSMC packaging expansion and CoWoS capacity plan were updated.",
            ),
        ],
        config=make_config(min_title_similarity=0.8, min_summary_similarity=0.8, min_shared_title_tokens=2),
    )

    assert len(groups) == 2
    assert all(len(group.candidates) == 1 for group in groups)


def test_does_not_mutate_input_list_or_candidates() -> None:
    candidates = [
        make_candidate(analysis_result_id="b"),
        make_candidate(analysis_result_id="a"),
    ]
    original_order = [item.analysis_result_id for item in candidates]
    original_dump = [item.model_dump() for item in candidates]

    groups = group_report_candidates(candidates, config=make_config())

    assert [item.analysis_result_id for item in candidates] == original_order
    assert [item.model_dump() for item in candidates] == original_dump
    assert len(groups) >= 1


def test_identifiers_are_preserved_after_grouping() -> None:
    candidate = make_candidate(analysis_result_id="a")

    groups = group_report_candidates([candidate], config=make_config())
    grouped_candidate = groups[0].candidates[0]

    assert grouped_candidate.analysis_result_id == candidate.analysis_result_id
    assert grouped_candidate.workspace_id == candidate.workspace_id
    assert grouped_candidate.document_id == candidate.document_id
    assert grouped_candidate.document_version_id == candidate.document_version_id


def test_duplicate_analysis_result_id_raises_value_error() -> None:
    candidate = make_candidate(analysis_result_id="a")
    with pytest.raises(ValueError, match="Duplicate analysis_result_id"):
        group_report_candidates([candidate, candidate], config=make_config())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_time_gap_hours": -1},
        {"min_title_similarity": 1.5},
        {"min_title_similarity": -0.1},
        {"min_summary_similarity": 1.5},
        {"min_shared_title_tokens": -1},
    ],
)
def test_invalid_grouping_config_raises_validation_error(kwargs: dict[str, object]) -> None:
    with pytest.raises(Exception):
        make_config(**kwargs)


def test_issue_key_is_deterministic_for_same_group() -> None:
    candidates = [
        make_candidate(analysis_result_id="a"),
        make_candidate(
            analysis_result_id="b",
            title="Samsung HBM4 supply expansion plan",
            summary="Samsung expands HBM4 supply capacity and production planning for next year.",
        ),
    ]

    first = group_report_candidates(candidates, config=make_config())
    second = group_report_candidates(list(reversed(candidates)), config=make_config())

    assert [group.issue_key for group in first] == [group.issue_key for group in second]

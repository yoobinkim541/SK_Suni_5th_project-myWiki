from __future__ import annotations

import argparse
import sys

from src.analysis.importance import evaluate_and_save_importance


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate and save importance for one grouped industry issue.")
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--document-version-id", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    result = evaluate_and_save_importance(
        workspace_id=args.workspace_id,
        document_version_id=args.document_version_id,
        force=args.force,
    )

    print(f"analysis_result_id: {result.analysis_result_id or result.id}")
    print(f"document_version_id: {result.document_version_id}")
    print(f"importance_status: {result.importance_status}")
    print(f"model_name: {result.importance_model_name}")
    print(f"prompt_version: {result.importance_prompt_version}")
    print("saved_to_database: true" if not result.id.startswith("runtime-") else "saved_to_database: false")

    if result.importance_status != "completed":
        print(f"error_code: {result.error_code}")
        print(f"error_message: {result.importance_error_message or result.error_message}")
        return 1

    print(f"importance_score: {result.importance_score}")
    print(f"importance_level: {result.importance_level.value if result.importance_level else ''}")
    print(f"direct_relevance_score: {result.direct_relevance_score}")
    print(f"business_impact_score: {result.business_impact_score}")
    print(f"urgency_score: {result.urgency_score}")
    print(f"industry_impact_score: {result.industry_impact_score}")
    print(f"duration_score: {result.duration_score}")
    print(f"external_attention_score: {result.external_attention_score}")
    print(f"impact_direction: {result.impact_direction.value if result.impact_direction else ''}")
    print(f"time_horizon: {result.time_horizon.value if result.time_horizon else ''}")
    print(f"core_summary: {result.core_summary or ''}")
    print(f"key_points: {result.key_points}")
    print(f"key_numbers_count: {len(result.key_numbers)}")
    print(f"sk_hynix_implication: {result.sk_hynix_implication or ''}")
    print(f"summary_evidence_count: {len(result.summary_evidence_refs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


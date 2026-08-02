from __future__ import annotations

import argparse
import sys

from src.analysis.reliability import evaluate_and_save_reliability


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate reliability for one issue or grouped evidence documents.")
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--document-version-id", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    result = evaluate_and_save_reliability(
        workspace_id=args.workspace_id,
        document_version_id=args.document_version_id,
        force=args.force,
    )

    print(f"analysis_result_id: {result.analysis_result_id or result.id}")
    print(f"document_version_id: {result.document_version_id}")
    print(f"reliability_status: {result.reliability_status}")
    print(f"model_name: {result.reliability_model_name}")
    print(f"prompt_version: {result.reliability_prompt_version}")
    print("saved_to_database: true" if not result.id.startswith("runtime-") else "saved_to_database: false")

    if result.reliability_status != "completed":
        print(f"error_code: {result.error_code}")
        print(f"error_message: {result.reliability_error_message or result.error_message}")
        return 1

    print(f"reliability_score: {result.reliability_score}")
    print(f"reliability_level: {result.reliability_level.value if result.reliability_level else ''}")
    print(f"traceability_score: {result.traceability_score}")
    print(f"source_authority_score: {result.source_authority_score}")
    print(f"current_validity_score: {result.current_validity_score}")
    print(f"independent_evidence_score: {result.independent_evidence_score}")
    print(f"factual_consistency_score: {result.factual_consistency_score}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

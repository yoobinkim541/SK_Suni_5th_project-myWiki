from __future__ import annotations

import argparse
import sys

from src.analysis.interface import classify_document_version


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify one processed document with OpenRouter.")
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--document-version-id", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    result = classify_document_version(
        workspace_id=args.workspace_id,
        document_version_id=args.document_version_id,
        force=args.force,
    )

    print(f"analysis_result_id: {result.id}")
    print(f"document_version_id: {result.document_version_id}")
    print(f"status: {result.status}")
    if result.status == "failed":
        print(f"error_code: {result.error_code}")
        print(f"error_message: {result.error_message}")
        return 1

    print(f"primary_category: {result.primary_category.value if result.primary_category else ''}")
    print(f"secondary_categories: {[category.value for category in result.secondary_categories]}")
    print(f"classification_confidence: {result.classification_confidence}")
    print(f"model_name: {result.model_name}")
    print(f"prompt_version: {result.prompt_version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

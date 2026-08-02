from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.analysis.ranking import rank_analysis_results


def _load_document_version_ids(file_path: str | None, inline_ids: list[str]) -> list[str]:
    document_version_ids = list(inline_ids)
    if file_path:
        lines = Path(file_path).read_text(encoding="utf-8").splitlines()
        document_version_ids.extend(line.strip() for line in lines if line.strip())
    return document_version_ids


def main() -> int:
    parser = argparse.ArgumentParser(description="Rank stored analysis results for reporting.")
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--document-version-id", action="append", default=[])
    parser.add_argument("--document-version-ids-file")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    document_version_ids = _load_document_version_ids(args.document_version_ids_file, args.document_version_id)
    results = rank_analysis_results(
        workspace_id=args.workspace_id,
        document_version_ids=document_version_ids,
        force=args.force,
    )

    if not results:
        print("results: 0")
        return 0

    first = results[0]
    print(f"ranking_batch_date: {first.ranking_batch_date}")
    print(f"ranking_reference_time: {first.ranking_reference_time.isoformat() if first.ranking_reference_time else ''}")
    print(f"ranking_formula_version: {first.ranking_formula_version}")
    print(f"input_documents: {len(document_version_ids)}")
    print(f"ranked_documents: {len([item for item in results if item.ranking_status == 'completed'])}")
    print(f"excluded_low_reliability: {len([item for item in results if item.ranking_status == 'excluded'])}")
    print(f"selected_for_report: {len([item for item in results if item.selected_for_report])}")

    for item in results:
        print("---")
        print(f"ranking_position: {item.ranking_position}")
        print(f"report_selection_position: {item.report_selection_position}")
        print(f"title: {item.title}")
        print(f"primary_category: {item.primary_category}")
        print(f"ranking_score: {item.ranking_score}")
        print(f"importance_score: {item.importance_score}")
        print(f"reliability_score: {item.reliability_score}")
        print(f"recency_score: {item.recency_score}")
        print(f"selected_for_report: {item.selected_for_report}")
        print(f"selection_reason: {item.selection_reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

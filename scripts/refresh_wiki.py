"""최근 2시간 내 분석 완료된 문서를 근거로 위키만 갱신하는 배치.

리포트 파이프라인과 완전히 독립된 스케줄로 돈다(로컬: Windows 작업
스케줄러/cron, 배포: EventBridge). reports/report_sections에는 아무것도
남기지 않는다.

사용법:
    python scripts/refresh_wiki.py
    python scripts/refresh_wiki.py --since-hours 3
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.pipeline_common.db import get_client
from src.wiki.generation import refresh_wiki_from_recent_analysis
from src.wiki.generation_models import WikiDraftGenerationResult


def get_workspace_id() -> str:
    rows = get_client().table("workspaces").select("id, name").limit(2).execute().data
    if len(rows) != 1:
        raise SystemExit(f"workspace_id를 자동으로 하나로 못 정했다 (workspaces 행 {len(rows)}개).")
    return str(rows[0]["id"])


def report_results(results: list[WikiDraftGenerationResult]) -> int:
    """실행 결과를 출력하고, 스케줄러가 확인할 종료 코드를 정한다.

    - results가 비어 있으면(새로 분석된 문서가 없어 처리할 이슈가 없었던 경우) 정상 상태이므로 0.
    - results가 있는데 전부 error_message가 있으면(완전 실패) 1 — 무인 배치라 로그/exit code로만
      실패를 알 수 있어야 한다.
    - 일부만 실패한 경우는 각 항목의 error를 출력하되, 배치 자체는 0으로 정상 종료한다.
    """
    print(f"[refresh_wiki] {len(results)}개 이슈 처리:")
    for r in results:
        print(f"  - {r.issue_key}: issue_page={r.issue_page_id} topic_action={r.topic_action}")
        if r.error_message:
            print(f"    error: {r.error_message}")

    if results and all(r.error_message is not None for r in results):
        return 1
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since-hours", type=int, default=2)
    args = parser.parse_args()

    workspace_id = get_workspace_id()
    results = refresh_wiki_from_recent_analysis(workspace_id, since_hours=args.since_hours)
    exit_code = report_results(results)
    if exit_code != 0:
        raise SystemExit(exit_code)

"""위키 중복 정리(dedup) 배치 — 이미 발행된 중복 위키 페이지를 LLM이 찾아 병합한다.

scripts/refresh_wiki_scheduled.py와 달리 사용자 설정 주기가 없다 — GitHub Actions
cron이 12시간 간격으로 도는 것 자체가 실행 주기다(급하지 않은 정리 작업이라 발행
배치의 30분 주기보다 훨씬 느슨하게 잡는다).

사용법:
    python scripts/dedup_wiki_scheduled.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.pipeline_common.db import get_client
from src.wiki.dedup import run_wiki_dedup_batch
from src.wiki.dedup_models import DedupResult


def log(msg: str) -> None:
    print(f"[dedup_wiki_scheduled] {msg}", flush=True)


def get_workspace_id() -> str:
    rows = get_client().table("workspaces").select("id, name").limit(2).execute().data
    if len(rows) != 1:
        raise SystemExit(f"workspace_id를 자동으로 하나로 못 정했다 (workspaces 행 {len(rows)}개).")
    return str(rows[0]["id"])


def report_results(results: list[DedupResult]) -> int:
    merged = [r for r in results if r.decision == "merged"]
    not_duplicate = [r for r in results if r.decision == "not_duplicate"]
    failed = [r for r in results if r.decision == "failed"]
    log(f"{len(results)}개 후보 처리: 병합 {len(merged)}건, 중복 아님 {len(not_duplicate)}건, 실패 {len(failed)}건")
    for r in merged:
        log(f"  - 병합: {r.page_a_id} + {r.page_b_id} -> 대표 {r.representative_page_id} (아카이빙: {r.archived_page_id})")
    for r in failed:
        log(f"  - 실패: {r.page_a_id} + {r.page_b_id}: {r.error_message}")
    if results and len(failed) == len(results):
        return 1
    return 0


if __name__ == "__main__":
    workspace_id = get_workspace_id()
    log("중복 위키 탐지·정리 시작")
    results = run_wiki_dedup_batch(workspace_id)
    exit_code = report_results(results)
    if exit_code != 0:
        raise SystemExit(exit_code)

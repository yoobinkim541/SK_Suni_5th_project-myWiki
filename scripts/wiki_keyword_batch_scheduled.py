"""위키 키워드 채우기 배치 — 키워드 없는 published 위키 페이지에 LLM이 122개 사전
안에서 키워드를 뽑아 채운다.

scripts/dedup_wiki_scheduled.py와 동일한 뼈대 — GitHub Actions cron이 매일 1회
도는 것 자체가 실행 주기다.

사용법:
    python scripts/wiki_keyword_batch_scheduled.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.pipeline_common.db import get_client
from src.wiki.keyword_batch import WikiKeywordPageResult, run_wiki_keyword_batch


def log(msg: str) -> None:
    print(f"[wiki_keyword_batch_scheduled] {msg}", flush=True)


def get_workspace_id() -> str:
    rows = get_client().table("workspaces").select("id, name").limit(2).execute().data
    if len(rows) != 1:
        raise SystemExit(f"workspace_id를 자동으로 하나로 못 정했다 (workspaces 행 {len(rows)}개).")
    return str(rows[0]["id"])


def report_results(results: list[WikiKeywordPageResult]) -> int:
    tagged = [r for r in results if r.status == "tagged"]
    no_match = [r for r in results if r.status == "no_match"]
    failed = [r for r in results if r.status == "failed"]
    log(f"{len(results)}개 페이지 처리: 태깅 {len(tagged)}건, 매칭 없음 {len(no_match)}건, 실패 {len(failed)}건")
    for r in failed:
        log(f"  - 실패: {r.slug}: {r.error_message}")
    if results and len(failed) == len(results):
        return 1
    return 0


if __name__ == "__main__":
    workspace_id = get_workspace_id()
    log("위키 키워드 채우기 시작")
    results = run_wiki_keyword_batch(workspace_id)
    exit_code = report_results(results)
    if exit_code != 0:
        raise SystemExit(exit_code)

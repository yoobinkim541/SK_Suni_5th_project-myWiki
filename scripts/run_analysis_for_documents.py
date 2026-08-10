"""특정 document_version_id 목록을 후보 선정 로직 없이 강제로 분석 파이프라인에 태운다.

run_analysis_pipeline()의 기본 후보 선정(select_analysis_candidates)은 "report_window"
(리포트 후보)와 "backlog"(일반 백로그) 우선순위로만 동작한다. 그래서 report_window에
안 걸리고 backlog 우선순위에서도 계속 밀리는 특정 문서 집합(예: 공시 문서가 뉴스 문서에
밀려 몇 회차째 분석이 시작도 안 되는 경우)은 스케줄 잡을 아무리 돌려도 처리되지 않는다.
이 스크립트는 그 우선순위를 완전히 건너뛰고, 지정한 문서만 분류->신뢰도->중요도->랭킹
4단계에 강제로 태운다. run_analysis_pipeline()이 이미 document_version_ids 파라미터로
이 경로를 지원하므로(scripts/run_analysis_pipeline.py:193-198), 여기서는 그 파라미터로
값을 넘기는 얇은 CLI 래퍼만 추가한다.

사용법:
    python scripts/run_analysis_for_documents.py <id1> <id2> ...
    python scripts/run_analysis_for_documents.py --file ids.txt   # 한 줄에 id 하나씩
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from scripts.run_analysis_pipeline import MAX_ANALYSIS_CANDIDATES, get_workspace_id, run_analysis_pipeline


def log(msg: str) -> None:
    print(f"[run_analysis_for_documents] {msg}", flush=True)


def collect_document_version_ids(*, positional: list[str], file_path: str | None) -> list[str]:
    """positional 인자와 --file(있으면)을 합쳐 중복 없는 id 목록을 순서 보존해서 만든다."""
    ids: list[str] = list(positional)
    if file_path:
        lines = Path(file_path).read_text(encoding="utf-8").splitlines()
        ids.extend(line.strip() for line in lines if line.strip())
    return list(dict.fromkeys(ids))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="지정한 document_version_id만 강제로 분석 파이프라인 실행")
    parser.add_argument("ids", nargs="*", help="document_version_id 목록")
    parser.add_argument("--file", default=None, help="한 줄에 id 하나씩 적힌 파일 경로")
    parser.add_argument("--workspace-id", default=None)
    args = parser.parse_args(argv)

    document_version_ids = collect_document_version_ids(positional=args.ids, file_path=args.file)
    if not document_version_ids:
        log("대상 id가 없습니다 (positional 인자 또는 --file로 지정하세요)")
        return 1
    if len(document_version_ids) > MAX_ANALYSIS_CANDIDATES:
        log(f"대상이 {len(document_version_ids)}건인데 한 번에 최대 {MAX_ANALYSIS_CANDIDATES}건만 처리 가능합니다 — 나눠서 실행하세요")
        return 1

    workspace_id = args.workspace_id or get_workspace_id()
    log(f"대상 {len(document_version_ids)}건 강제 분석 시작 (workspace={workspace_id})")
    result = run_analysis_pipeline(workspace_id, limit=len(document_version_ids), document_version_ids=document_version_ids)
    if result is None:
        log("일부 또는 전체 문서가 실패했거나 처리할 후보가 없었습니다 — 위 단계별 로그를 확인하세요")
        return 1
    log(f"완료: {len(result)}건 처리")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""수집 -> 정제를 순서대로 도는 배치 진입점.

흐름
    1. sources에서 enabled=true인 출처를 모두 가져온다 (--source-id면 그 소스만)
    2. 각 출처마다 collect()를 호출한다
    3. 정제 대기 문서(status='active'이면서 document_versions 행이 없는 문서)를 찾아
       각각 preprocess()를 호출한다

collect()·preprocess()는 예외를 던지지 않고 실패를 pipeline_jobs에 남기는 계약이라
(src/collectors/interface.py, src/preprocessing/interface.py 참조), 이 배치도 그 계약을
그대로 따른다 — 소스/문서 1건이 실패해도 나머지는 계속 처리한다.

사용법:
    python scripts/run_pipeline.py
    python scripts/run_pipeline.py --limit 3
    python scripts/run_pipeline.py --source-id <uuid>
    python scripts/run_pipeline.py --collect-only
    python scripts/run_pipeline.py --preprocess-only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.collectors.interface import collect
from src.pipeline_common import jobs, repository
from src.pipeline_common.db import get_client
from src.pipeline_common.models import CollectRequest
from src.preprocessing.interface import preprocess


def get_workspace_id() -> UUID:
    res = get_client().table("workspaces").select("id").eq("slug", "mywiki").single().execute()
    return UUID(res.data["id"])


def _merge_counts(total: dict[str, int], part: dict[str, int]) -> None:
    for key, value in part.items():
        total[key] = total.get(key, 0) + value


def run_collect(workspace_id: UUID, *, limit: int | None, source_id: UUID | None) -> dict:
    if source_id is not None:
        source = repository.get_source(source_id, workspace_id)
        if source is None:
            raise SystemExit(f"소스를 찾을 수 없다 (workspace 불일치 포함): {source_id}")
        sources = [source]
    else:
        sources = repository.list_enabled_sources(workspace_id)

    summary = {
        "sources": len(sources),
        "collected": 0,
        "new_documents": 0,
        "skip_reasons": {},
        "failure_reasons": {},
    }

    for source in sources:
        sid = UUID(str(source["id"]))
        request = CollectRequest(workspace_id=workspace_id, source_id=sid, limit=limit)
        collected = collect(request)
        new_count = sum(1 for doc in collected if doc.is_new_document)
        summary["collected"] += len(collected)
        summary["new_documents"] += new_count
        print(f"[collect] {source['name']}: {len(collected)}건 수집 (신규 {new_count}건)")

        # collect()는 성공 건만 반환하므로, 소스 단위 job의 result에서
        # skip/failure 사유를 읽어와 배치 요약에 반영한다 (계약을 바꾸지 않는다).
        job = repository.find_job_by_idempotency_key(jobs.source_collect_key(sid))
        result = (job or {}).get("result") or {}
        _merge_counts(summary["skip_reasons"], result.get("skip_reasons") or {})
        _merge_counts(summary["failure_reasons"], result.get("failure_reasons") or {})
        for notice in result.get("notices") or []:
            print(f"    notice: {notice}")
        if job is not None and job.get("status") == "failed":
            print(f"    소스 job 실패: {job.get('error_message')}")

    return summary


def run_preprocess(workspace_id: UUID) -> dict:
    active_documents = repository.list_active_documents(workspace_id)
    active_ids = [UUID(str(doc["id"])) for doc in active_documents]
    versioned_ids = repository.find_document_ids_with_versions(active_ids)
    pending = [doc_id for doc_id in active_ids if str(doc_id) not in versioned_ids]

    summary = {"pending": len(pending), "succeeded": 0, "failed": 0, "failure_reasons": {}}

    for document_id in pending:
        processed = preprocess(document_id)
        if processed is not None:
            summary["succeeded"] += 1
            continue
        summary["failed"] += 1
        job = repository.find_job_by_idempotency_key(jobs.parse_document_key(document_id))
        reason = (job or {}).get("error_message") or "알 수 없음"
        summary["failure_reasons"][reason] = summary["failure_reasons"].get(reason, 0) + 1
        print(f"[preprocess] 실패: {document_id} ({reason})")

    return summary


def print_summary(collect_summary: dict | None, preprocess_summary: dict | None) -> None:
    print("\n=== 요약 ===")
    if collect_summary is not None:
        print(f"수집 대상 소스: {collect_summary['sources']}개")
        print(
            f"수집 건수: {collect_summary['collected']}건 "
            f"(신규 문서 {collect_summary['new_documents']}건)"
        )
        if collect_summary["skip_reasons"]:
            print(f"건너뛴 사유: {collect_summary['skip_reasons']}")
        if collect_summary["failure_reasons"]:
            print(f"수집 실패 사유: {collect_summary['failure_reasons']}")
    if preprocess_summary is not None:
        print(f"정제 대기 문서: {preprocess_summary['pending']}건")
        print(f"정제 성공: {preprocess_summary['succeeded']}건")
        print(f"정제 실패: {preprocess_summary['failed']}건")
        if preprocess_summary["failure_reasons"]:
            print(f"정제 실패 사유: {preprocess_summary['failure_reasons']}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--limit", type=int, default=None, help="출처당 최대 수집 건수")
    parser.add_argument("--source-id", default=None, help="이 소스만 수집한다")
    parser.add_argument("--collect-only", action="store_true", help="수집만 하고 정제는 건너뛴다")
    parser.add_argument(
        "--preprocess-only", action="store_true", help="정제만 하고 수집은 건너뛴다"
    )
    args = parser.parse_args()

    if args.collect_only and args.preprocess_only:
        parser.error("--collect-only와 --preprocess-only는 함께 쓸 수 없다")

    workspace_id = get_workspace_id()

    collect_summary = None
    preprocess_summary = None

    if not args.preprocess_only:
        source_id = UUID(args.source_id) if args.source_id else None
        collect_summary = run_collect(workspace_id, limit=args.limit, source_id=source_id)

    if not args.collect_only:
        preprocess_summary = run_preprocess(workspace_id)

    print_summary(collect_summary, preprocess_summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())

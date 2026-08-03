"""수집 -> 정제를 순서대로 도는 배치 진입점.

흐름
    1. sources에서 enabled=true인 출처를 모두 가져온다 (--source-id면 그 소스만)
    2. 각 출처마다 collect()를 호출한다
    3. 정제 대기 문서를 찾아 각각 preprocess()를 호출한다.
       대기 조건은 find_pending_documents() 참조 (신규 + 재수집분)

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
from datetime import datetime
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.collectors.interface import collect
from src.pipeline_common import jobs, repository
from src.pipeline_common.db import get_client
from src.pipeline_common.models import CollectRequest
from src.pipeline_common.timeutil import parse_datetime
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


def _job_finished_at(job: dict | None) -> datetime | None:
    """job이 끝난 시각. completed_at이 비면 created_at으로 대신한다."""
    if not job:
        return None
    return parse_datetime(str(job.get("completed_at") or job.get("created_at") or ""))


def _last_processed_at(version: dict, parse_job: dict | None) -> datetime | None:
    """이 문서를 마지막으로 정제한 시각.

    버전 생성 시각만 보면 안 된다. 내용이 그대로면 preprocess()가 기존 버전을
    재사용해 새 행을 만들지 않으므로 (명세 §3-3) 버전 시각이 갱신되지 않고,
    그 문서는 재수집될 때마다 매번 재정제 대상으로 다시 잡힌다.
    실제로 정제를 돌린 시각은 parse_document job에 남으므로 둘 중 나중을 쓴다.
    """
    candidates = [
        parse_datetime(str(version.get("created_at") or "")),
        _job_finished_at(parse_job),
    ]
    known = [moment for moment in candidates if moment is not None]
    return max(known) if known else None


def find_pending_documents(workspace_id: UUID) -> tuple[list[UUID], list[UUID]]:
    """정제 대기 문서를 (신규, 재정제) 로 나눠 돌려준다.

    대기 조건 — status='active'인 문서 중
        (1) document_versions 행이 없다                        -> 신규
        (2) 마지막 완료된 collect job이 마지막 정제보다 나중이다 -> 재정제

    (2)가 없으면 이미 정제된 문서의 본문이 나중에 바뀌어도 자동 실행에서 재정제가
    안 된다. collect()는 그 사이에도 raw를 새로 올리므로 document_versions가
    참조하지 않는 파일만 쌓이고, content_hash·version_no 구조가 자동 경로에서는
    동작하지 않는다.

    조회는 문서 목록 / 최신 버전 / 최신 완료 collect job / 최신 완료 parse job
    각각 1회씩이고 대조는 파이썬에서 한다
    (N+1 금지, repository 계층의 2단계 조회 방식과 같다).

    내용이 그대로면 preprocess()가 동일 content_hash를 보고 새 행도 업로드도
    만들지 않으므로 (명세 §3-3), (2)로 몇 번 더 불러도 정합은 깨지지 않는다.
    이 조건의 목적은 불필요한 호출을 줄이는 것이다.
    """
    documents = repository.list_active_documents(workspace_id)
    document_ids = [UUID(str(doc["id"])) for doc in documents]
    latest_versions = repository.latest_versions_by_document(document_ids)
    collect_jobs = repository.latest_completed_collect_jobs_by_document(workspace_id, document_ids)
    parse_jobs = repository.latest_completed_parse_jobs_by_document(workspace_id, document_ids)

    new_targets: list[UUID] = []
    recollected: list[UUID] = []
    for document_id in document_ids:
        key = str(document_id)
        version = latest_versions.get(key)
        if version is None:
            new_targets.append(document_id)
            continue
        collected_at = _job_finished_at(collect_jobs.get(key))
        processed_at = _last_processed_at(version, parse_jobs.get(key))
        if collected_at and processed_at and collected_at > processed_at:
            recollected.append(document_id)
    return new_targets, recollected


def run_preprocess(workspace_id: UUID) -> dict:
    new_targets, recollected = find_pending_documents(workspace_id)
    pending = new_targets + recollected

    summary = {
        "pending": len(pending),
        "new": len(new_targets),
        "recollected": len(recollected),
        "succeeded": 0,
        "new_versions": 0,
        "unchanged": 0,
        "failed": 0,
        "failure_reasons": {},
    }

    for document_id in pending:
        processed = preprocess(document_id)
        if processed is not None:
            summary["succeeded"] += 1
            # 재정제했는데 내용이 같으면 기존 버전을 그대로 쓴다 (새 행·업로드 없음).
            if processed.is_new_version:
                summary["new_versions"] += 1
            else:
                summary["unchanged"] += 1
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
        print(
            f"정제 대기 문서: {preprocess_summary['pending']}건 "
            f"(신규 {preprocess_summary['new']}건 / 재정제 대상 {preprocess_summary['recollected']}건)"
        )
        print(
            f"정제 성공: {preprocess_summary['succeeded']}건 "
            f"(새 버전 {preprocess_summary['new_versions']}건 / "
            f"내용 동일 {preprocess_summary['unchanged']}건)"
        )
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

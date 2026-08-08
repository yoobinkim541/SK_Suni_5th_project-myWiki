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

파서를 바꾼 뒤 기존 문서에 반영할 때 (--rehash, run_rehash() 참조):
    python scripts/run_pipeline.py --rehash --dry-run
    python scripts/run_pipeline.py --rehash --limit 200
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.collectors.interface import collect
from src.pipeline_common import jobs, repository, storage
from src.pipeline_common.db import get_client
from src.pipeline_common.models import CollectRequest
from src.pipeline_common.timeutil import parse_datetime
from src.preprocessing import parsers
from src.preprocessing.interface import preprocess

# 본문 문장으로 볼 최소 길이. 관련기사 헤드라인은 이보다 짧고 종결어미로 끝나지도 않는다.
_BODY_SENTENCE_MIN_LEN = 40

# 본문 문장 보존율 하한. 이보다 낮은 문서는 본문을 건드렸을 수 있으므로 개별 확인한다.
#
# 감소율(shrink_ratio)을 기준으로 쓰지 않는 이유: 그건 본문 보존의 지표가 아니다.
# _MAIN_SELECTORS가 안 맞아 <body>로 폴백하는 사이트는 페이지의 절반 이상이
# 관련기사 레일이라 정상 제거가 50~90%로 나온다(dailian.co.kr 실측 52%).
# 2026-08-07 dry-run에서 감소율 0.3 기준으로는 982건 중 379건이 이상치로 잡혀
# 눈으로 볼 수 있는 규모가 아니었고, 그중 대부분이 정상이었다.
# 문장 보존율은 "얼마나 줄었나"가 아니라 "본문이 남았나"를 직접 잰다.
_BODY_RETENTION_MIN = 0.99

_HANGUL_RE = re.compile(r"[가-힣]")

# 한국어 기사 문단의 종결형. **마침표를 반드시 포함한다.**
#
# 마침표 없는 '다'를 넣으면 헤드라인체가 전부 걸린다 — 한국어 기사 제목은 마침표를
# 안 찍는다("…정부가 지원한다", "…SK텔레콤 담았다"). 2026-08-07 dry-run에서 이것 때문에
# 관련기사 헤드라인이 '본문 문장'으로 잡혀 이상치 112건이 나왔고, 열어보니 대부분
# 정상적으로 제거된 상용구였다.
_SENTENCE_ENDINGS = ("다.", "요.", "음.")

# Markdown 표기를 걷어내고 문장만 남기기 위한 것들.
# 이미지는 alt 처리(boilerplate.replace_images_with_alt)로 줄 모양이 바뀌므로,
# 걷어내지 않으면 정상 변경이 '사라진 문장'으로 잡힌다.
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_PREFIX_RE = re.compile(r"^[\s>*+\-#]+")
_MD_EMPHASIS_RE = re.compile(r"[*_`]+")


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


DEFAULT_PREPROCESS_LIMIT = 300
"""
한 회차에 정제할 문서 수 상한.

무제한 루프였다. 대기가 적을 땐 문제가 안 됐는데, list_active_documents의 1,000행
잘림을 고치자(#176) 그동안 안 보이던 문서 307건이 한꺼번에 대기로 들어왔다.
그때 상한이 없다는 게 드러났다.

값의 근거: 2026-08-07 실측으로 문서당 1.12초다(raw 다운로드 + 정제 + 업로드 + INSERT).
300건이면 약 5.6분이라, 스케줄러 55분 예산을 수집·분석과 나눠 쓰기에 무리가 없다.
대기가 5,000건까지 불어나도 한 회차가 93분을 쓰는 일은 생기지 않는다.

넘친 대기는 다음 회차가 이어서 처리한다 — find_pending_documents가 매번 다시
계산하므로 놓치는 문서는 없다.

⚠ 이 값은 스케줄러 timeout(P1, 이환희 담당)과 같은 예산을 나눠 쓴다. 조정이
필요하면 분석 단계 limit과 함께 봐야 한다.
"""


def run_preprocess(workspace_id: UUID, *, limit: int | None = DEFAULT_PREPROCESS_LIMIT) -> dict:
    new_targets, recollected = find_pending_documents(workspace_id)
    pending = new_targets + recollected
    total_pending = len(pending)
    if limit is not None:
        pending = pending[:limit]

    summary = {
        # 대기열 전체 크기. new + recollected와 합이 맞는다.
        "pending": total_pending,
        # 이번 회차에 실제로 처리하는 몫과, 상한에 걸려 미룬 몫.
        "processing": len(pending),
        "deferred": total_pending - len(pending),
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


# ------------------------------------------------------------
# 재해시 마이그레이션 (--rehash)
# ------------------------------------------------------------

# content_type을 collect job에서 못 읽을 때 raw 파일 확장자로 되짚는다.
# storage.EXT_BY_CONTENT_TYPE의 역방향이다.
_CONTENT_TYPE_BY_EXT = {ext: ct for ct, ext in storage.EXT_BY_CONTENT_TYPE.items()}


def _body_sentences(markdown: str) -> set[str]:
    """
    Markdown에서 '본문 문장'으로 볼 줄을 뽑는다.

    길이 40자 이상 + 한글 포함 + 한국어 종결어미로 끝나는 줄. 관련기사 헤드라인,
    메뉴, 버튼, 시세 위젯은 이 셋을 동시에 만족하지 않는다. 완벽한 분류는 아니지만
    "상용구를 지웠는가 본문을 지웠는가"를 가르는 데는 충분하다.
    """
    sentences = set()
    for raw_line in markdown.splitlines():
        line = _MD_IMAGE_RE.sub("", raw_line)
        line = _MD_PREFIX_RE.sub("", line)
        line = _MD_EMPHASIS_RE.sub("", line).strip()
        if len(line) < _BODY_SENTENCE_MIN_LEN:
            continue
        if not _HANGUL_RE.search(line):
            continue
        if line.endswith(_SENTENCE_ENDINGS):
            sentences.add(line)
    return sentences


def _content_type_for(raw_object_key: str, collect_result: dict) -> str:
    from_job = collect_result.get("content_type")
    if from_job:
        return str(from_job)
    ext = raw_object_key.rsplit(".", 1)[-1].lower() if "." in raw_object_key else ""
    return _CONTENT_TYPE_BY_EXT.get(ext, "text/html")


def _rehash_one(
    document_id: UUID,
    version: dict,
    collect_result: dict,
    *,
    dry_run: bool,
) -> dict:
    """문서 1건을 재해시한다. 반환값이 그대로 리포트 한 줄이 된다."""
    version_id = UUID(str(version["id"]))
    old_hash = version["content_hash"]
    record: dict = {
        "document_id": str(document_id),
        "document_version_id": str(version_id),
        "version_no": version.get("version_no"),
        "old_content_hash": old_hash,
        "old_parser_version": version.get("parser_version"),
        "markdown_object_key": version.get("markdown_object_key"),
        "raw_object_key": None,
        "raw_downloaded": False,
        "action": "skip",
        "skip_reason": None,
    }

    # raw 키는 행을 먼저 본다. preprocess()는 collect job에서만 읽어서 job이 없으면
    # 실패하는데, 행에 남은 키가 멀쩡한 경우가 있다.
    raw_key = version.get("raw_object_key") or collect_result.get("raw_object_key")
    if not raw_key:
        record["skip_reason"] = "raw_object_key 없음"
        return record
    record["raw_object_key"] = raw_key

    try:
        body = storage.download(raw_key)
    except Exception as exc:  # noqa: BLE001 - Storage 예외 종류가 버전마다 다르다
        record["skip_reason"] = f"raw 다운로드 실패: {exc}"
        return record
    record["raw_downloaded"] = True

    # 게이트 2(본문 보존량)는 구 파서 결과와 비교해야 한다. 구 파서 결과는 저장된
    # Markdown 그 자체다 — 구 파서 코드는 이 시점에 이미 없다.
    old_markdown = None
    try:
        old_markdown = storage.download(version["markdown_object_key"]).decode(
            "utf-8", errors="replace"
        )
        record["old_len"] = len(old_markdown)
    except Exception:  # noqa: BLE001 - 집계에서만 빠진다
        record["old_len"] = None

    try:
        parsed = parsers.parse(body, _content_type_for(raw_key, collect_result))
    except Exception as exc:  # noqa: BLE001 - 행을 건드리지 않고 사유만 남긴다
        record["skip_reason"] = f"정제 실패: {exc}"
        return record

    record["new_content_hash"] = parsed.content_hash
    record["new_parser_version"] = parsed.parser_version
    record["new_len"] = len(parsed.markdown)

    # 본문 문장이 얼마나 남았는가. 이게 게이트 2의 실제 판정 근거다.
    if old_markdown is not None:
        old_sentences = _body_sentences(old_markdown)
        if old_sentences:
            kept = old_sentences & _body_sentences(parsed.markdown)
            record["body_sentences"] = len(old_sentences)
            record["body_retention"] = round(len(kept) / len(old_sentences), 3)
            record["lost_sentences"] = [s[:100] for s in list(old_sentences - kept)[:3]]

    if parsed.content_hash == old_hash:
        # 상용구가 없던 문서. 커서만 전진시킨다.
        record["action"] = "parser_version_only"
        if not dry_run:
            repository.update_document_version_content(
                version_id,
                content_hash=parsed.content_hash,
                parser_version=parsed.parser_version,
                language=parsed.language,
            )
        return record

    record["action"] = "rehash"
    if dry_run:
        return record

    # 업로드를 먼저, UPDATE를 나중에 한다. UPDATE가 실패하면 행이 구 해시·구
    # parser_version을 유지하므로 커서가 전진하지 않고, 재정제는 결정적이라
    # 다음 패스가 같은 해시를 다시 계산해 재시도한다.
    try:
        storage.upload(
            version["markdown_object_key"], parsed.markdown.encode("utf-8"), "text/markdown"
        )
        repository.update_document_version_content(
            version_id,
            content_hash=parsed.content_hash,
            parser_version=parsed.parser_version,
            language=parsed.language,
        )
    except Exception as exc:  # noqa: BLE001
        # uq_dv_document_hash 충돌(형제 버전과 해시가 겹침) 포함. 행은 그대로 둔다.
        record["action"] = "skip"
        record["skip_reason"] = f"갱신 실패: {exc}"
    return record


def run_rehash(
    workspace_id: UUID,
    *,
    limit: int | None,
    dry_run: bool,
    force: bool,
    report_path: Path,
) -> dict:
    """
    파서를 바꾼 뒤 기존 document_versions를 제자리에서 다시 해시한다.

    새 행을 만들지 않는다 — 분석 단계가 "분석 행이 없는 document_versions"를 잡아가서,
    993개 행을 새로 만들면 그대로 LLM 4단계 대기열에 얹히기 때문이다.

    parser_version이 커서다. 이미 최신 파서로 갱신된 행은 건너뛰므로 중간에 끊겨도
    다시 돌리면 이어서 처리한다. --force면 커서를 무시한다(롤백 경로).
    """
    target_version = parsers.PARSER_VERSIONS["html"]
    documents = repository.list_active_documents(workspace_id)
    document_ids = [UUID(str(doc["id"])) for doc in documents]
    latest_versions = repository.latest_versions_by_document(document_ids)
    collect_jobs = repository.latest_completed_collect_jobs_by_document(
        workspace_id, document_ids
    )

    summary = {
        "documents": len(document_ids),
        "targets": 0,
        "rehashed": 0,
        "parser_version_only": 0,
        "skipped": 0,
        "raw_missing": 0,
        "skip_reasons": {},
        "dry_run": dry_run,
        "report_path": str(report_path),
    }

    records: list[dict] = []
    for document_id in document_ids:
        version = latest_versions.get(str(document_id))
        if version is None:
            continue
        if not force and version.get("parser_version") == target_version:
            continue
        if limit is not None and summary["targets"] >= limit:
            break
        summary["targets"] += 1

        collect_result = (collect_jobs.get(str(document_id)) or {}).get("result") or {}
        record = _rehash_one(document_id, version, collect_result, dry_run=dry_run)
        records.append(record)

        if record["action"] == "rehash":
            summary["rehashed"] += 1
        elif record["action"] == "parser_version_only":
            summary["parser_version_only"] += 1
        else:
            summary["skipped"] += 1
            reason = record["skip_reason"] or "알 수 없음"
            summary["skip_reasons"][reason] = summary["skip_reasons"].get(reason, 0) + 1
        if not record["raw_downloaded"]:
            summary["raw_missing"] += 1

    report_path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )
    summary["gates"] = _rehash_gates(records, summary)
    return summary


def _rehash_gates(records: list[dict], summary: dict) -> dict:
    """
    게이트 2(본문 보존량)·4(롤백 경로) 판정.

    게이트 1(인용문 보존)·3(접힘)은 인용 테이블과 다중 버전 전수 조회가 필요해
    이 배치가 아니라 별도 하네스가 맡는다.
    """
    shrinks = sorted(
        1 - (r["new_len"] / r["old_len"])
        for r in records
        if r.get("old_len") and r.get("new_len")
    )
    # 이상치는 감소율이 아니라 '본문 문장을 잃은 문서'다.
    outliers = [
        {
            "document_id": r["document_id"],
            "body_retention": r["body_retention"],
            "body_sentences": r["body_sentences"],
            "shrink_ratio": round(1 - r["new_len"] / r["old_len"], 3)
            if r.get("old_len") and r.get("new_len")
            else None,
            "lost_sentences": r.get("lost_sentences", []),
        }
        for r in records
        if r.get("body_retention") is not None
        and r["body_retention"] < _BODY_RETENTION_MIN
    ]
    retentions = sorted(
        r["body_retention"] for r in records if r.get("body_retention") is not None
    )

    def pct(p: float) -> float | None:
        if not shrinks:
            return None
        return round(shrinks[min(int(len(shrinks) * p), len(shrinks) - 1)], 3)

    # 게이트 4: 대상 중 raw를 못 받은 건이 있으면 FAIL. 못 받은 건은 행을 건드리지
    # 않았으므로 데이터는 안전하지만, "언제든 되돌릴 수 있다"는 근거가 성립하지 않는다.
    gate4 = summary["raw_missing"] == 0

    return {
        "gate2_body_preserved": {
            "verdict": "REVIEW" if outliers else "PASS",
            "measured": len(retentions),
            "body_retention_min": round(retentions[0], 3) if retentions else None,
            "body_retention_p01": round(retentions[len(retentions) // 100], 3)
            if len(retentions) >= 100
            else None,
            "shrink_p50": pct(0.5),
            "shrink_p90": pct(0.9),
            "shrink_max": round(shrinks[-1], 3) if shrinks else None,
            "outliers": outliers,
            "note": "이상치는 '본문 문장을 잃은 문서'다. 개별 확인 후에만 PASS로 닫는다",
        },
        "gate4_rollback": {
            "verdict": "PASS" if gate4 else "FAIL",
            "raw_missing": summary["raw_missing"],
            "targets": summary["targets"],
        },
    }


def print_rehash_summary(summary: dict) -> None:
    print("\n=== 재해시 요약 ===")
    mode = "DRY-RUN (쓰지 않음)" if summary["dry_run"] else "실행"
    print(f"모드: {mode}")
    print(f"대상: {summary['targets']}건 / 전체 문서 {summary['documents']}건")
    print(
        f"재해시 {summary['rehashed']}건 / "
        f"parser_version만 갱신 {summary['parser_version_only']}건 / "
        f"건너뜀 {summary['skipped']}건"
    )
    if summary["skip_reasons"]:
        print(f"건너뛴 사유: {summary['skip_reasons']}")
    print(f"리포트: {summary['report_path']}")

    gates = summary["gates"]
    g2 = gates["gate2_body_preserved"]
    g4 = gates["gate4_rollback"]
    print("\n--- 게이트 ---")
    print(
        f"게이트 2 (본문 보존량): {g2['verdict']} — "
        f"본문 문장 보존율 최소 {g2['body_retention_min']} / 하위 1% {g2['body_retention_p01']} "
        f"({g2['measured']}건 측정) · 참고: 길이 감소율 p50 {g2['shrink_p50']} / "
        f"p90 {g2['shrink_p90']} / max {g2['shrink_max']}"
    )
    if g2["outliers"]:
        print(f"  본문 문장을 잃은 문서 {len(g2['outliers'])}건 — 개별 확인 필요:")
        for item in g2["outliers"][:20]:
            print(
                f"    {item['document_id']}  보존율 {item['body_retention']} "
                f"({item['body_sentences']}문장 중)"
            )
            for sentence in item["lost_sentences"][:1]:
                print(f"      사라진 문장: {sentence[:80]}")
    print(f"게이트 4 (롤백 경로): {g4['verdict']} — raw 누락 {g4['raw_missing']}건")
    print("게이트 1(인용문 보존)·3(접힘)은 별도 하네스에서 판정한다.")

    passed = sum(1 for g in (g2, g4) if g["verdict"] == "PASS")
    verdict = "PASS" if passed == 2 else "FAIL"
    print(f"\nGATE: {verdict} ({passed}/2 · 이 배치가 판정하는 몫)")


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
        if preprocess_summary.get("deferred"):
            print(
                f"이번 회차 처리: {preprocess_summary['processing']}건 "
                f"(상한으로 {preprocess_summary['deferred']}건은 다음 회차로 미룸)"
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
    parser.add_argument(
        "--preprocess-limit",
        type=int,
        default=None,
        help="한 회차에 정제할 문서 수 상한 (기본 %(default)s → DEFAULT_PREPROCESS_LIMIT). 0이면 무제한",
    )
    parser.add_argument(
        "--rehash",
        action="store_true",
        help="파서 교체분을 기존 버전 행에 제자리 반영한다 (수집·정제를 하지 않는다)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="--rehash 계산만 하고 쓰지 않는다"
    )
    parser.add_argument("--report", default=None, help="--rehash JSONL 리포트 경로")
    parser.add_argument(
        "--force",
        action="store_true",
        help="--rehash에서 parser_version 커서를 무시하고 전건 재처리한다 (롤백 경로)",
    )
    args = parser.parse_args()

    if args.collect_only and args.preprocess_only:
        parser.error("--collect-only와 --preprocess-only는 함께 쓸 수 없다")
    if args.rehash and (args.collect_only or args.preprocess_only):
        parser.error("--rehash는 --collect-only/--preprocess-only와 함께 쓸 수 없다")
    if (args.dry_run or args.force or args.report) and not args.rehash:
        parser.error("--dry-run/--force/--report는 --rehash에서만 쓴다")

    workspace_id = get_workspace_id()

    if args.rehash:
        default_report = f"rehash_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        rehash_summary = run_rehash(
            workspace_id,
            limit=args.limit,
            dry_run=args.dry_run,
            force=args.force,
            report_path=Path(args.report or default_report),
        )
        print_rehash_summary(rehash_summary)
        return 0

    collect_summary = None
    preprocess_summary = None

    if not args.preprocess_only:
        source_id = UUID(args.source_id) if args.source_id else None
        collect_summary = run_collect(workspace_id, limit=args.limit, source_id=source_id)

    if not args.collect_only:
        # 0은 '무제한'이다. 대기를 통째로 비우고 싶을 때만 쓴다.
        preprocess_limit = DEFAULT_PREPROCESS_LIMIT
        if args.preprocess_limit is not None:
            preprocess_limit = None if args.preprocess_limit == 0 else args.preprocess_limit
        preprocess_summary = run_preprocess(workspace_id, limit=preprocess_limit)

    print_summary(collect_summary, preprocess_summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())

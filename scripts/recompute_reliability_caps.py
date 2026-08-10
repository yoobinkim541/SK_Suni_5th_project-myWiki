"""
저장된 reliability_score를 **LLM 호출 없이** 고쳐진 cap 로직으로 다시 계산한다.

    python scripts/recompute_reliability_caps.py --dry-run          # 게이트만
    python scripts/recompute_reliability_caps.py --days 7           # 실행 (승인 후)
    python scripts/recompute_reliability_caps.py --all              # 전체 확대
    python scripts/recompute_reliability_caps.py --rollback rpt.jsonl

왜 재계산으로 끝나는가
    cap은 LLM이 아니라 코드 단계다 — reliability_scoring.apply_machine_score_caps가
    min(llm_score, cap)을 적용한다. 그리고 LLM 원점수는 지워지지 않고 남아 있다:
    reliability_detail.criteria.<기준>.score가 raw이고, 같은 이름의 컬럼이 cap 적용
    후 값이다. 따라서 detail의 원점수에 지금 로직을 다시 걸면 같은 결과가 나온다.
    결정적이라 몇 번 돌려도 같은 값이고, 재평가를 돌리면 밀릴 분석 백로그도 안 건드린다.

무엇이 바뀌었나 (전부 상한 **완화**다 — 그래서 점수는 내려갈 수 없다)
    #257  단일 출처            independent_evidence  8 -> 12
    #257  disclosure를 공식 출처로  source_authority     16 -> 20
    #259  정정 오탐(부정·불확실)   current_validity      5 -> 20

안전 장치
    1. 재현 게이트. 저장된 값을 **옛 로직으로 먼저 재현**해 본다. 재현되지 않으면
       신호 재구성이 틀렸다는 뜻이므로 그 행은 건드리지 않는다.
    2. 단조성 게이트. 세 변경이 모두 완화라 새 점수가 옛 점수보다 낮으면 버그다.
    3. JSONL에 문서별 이전 값을 전건 남긴다 -> --rollback이 그대로 되돌린다.
    (#168 재해시 마이그레이션과 같은 구조다. scripts/run_pipeline.py run_rehash 참조)

건드리지 않는 것
    src/analysis/ 코드           이환희 담당. 여기서는 호출만 한다
    reliability_detail          원점수 원본. 훼손하면 재계산·원복 근거가 사라진다
    reliability_evaluated_at    #259의 _reliability_sort_key 1순위 키다. 바꾸면
                                "문서별 최신 행" 선택이 뒤집힌다
    reliability_prompt_version  evaluate_and_save_reliability가 이 값으로 재평가
                                여부를 판단한다. 바꾸면 야간 배치가 전건을 LLM으로
                                다시 돌린다 — 이 작업의 목적과 정반대다
    스키마                       기존 컬럼만 UPDATE한다
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analysis.reliability import _detect_official_correction, _is_official_source
from src.analysis.reliability_models import (
    CriterionCaps,
    MachineSignals,
    ReliabilityLevel,
    ReliabilityLLMResult,
    ReliabilityScoreBreakdown,
)
from src.analysis.reliability_scoring import apply_machine_score_caps, build_final_result
from src.categories.documents import chunked, in_published_window, window_start

CRITERIA = (
    "traceability",
    "source_authority",
    "current_validity",
    "independent_evidence",
    "factual_consistency",
)
SCORE_COLUMNS = tuple(f"{name}_score" for name in CRITERIA)

# #259가 develop에 들어간 시각. 이보다 뒤에 평가된 행은 이미 새 로직 산출물이다.
DEFAULT_EVALUATED_BEFORE = "2026-08-10T06:53:05+00:00"

PAGE_SIZE = 1000
FETCH_LIMIT = 100000

_ANALYSIS_COLUMNS = (
    "id, document_version_id, primary_category, reliability_status, reliability_score, "
    "reliability_level, reliability_summary_reason, reliability_detail, "
    "reliability_evaluated_at, created_at, "
    + ", ".join(SCORE_COLUMNS)
)


# ---------------------------------------------------------------------------
# 옛 로직 스냅샷 — 검증 전용
#
# 저장된 값이 이 로직으로 재현되는지 확인하는 데만 쓴다. 새 점수는 살아 있는
# src/analysis/reliability_scoring을 그대로 불러 만든다(아래 recompute_row).
# 여기 있는 것은 #257 이전 커밋(9e79c5a^)의 build_criterion_caps·_is_official_source·
# _detect_official_correction과 같다. 재현 대조를 하려면 그 시점 코드가 필요한데,
# 그 코드는 이미 없어졌으므로 동결본으로 들고 있는다.
# ---------------------------------------------------------------------------

_LEGACY_OFFICIAL_SOURCE_TOKENS = (
    "official",
    "government",
    "regulator",
    "filing",
    "press",
    "research",
    "conference",
)
_LEGACY_CORRECTION_KEYWORDS = ("정정", "철회", "반박", "취소")


def legacy_is_official_source(source_type: str | None) -> bool:
    if not source_type:
        return False
    normalized = source_type.lower()
    return any(token in normalized for token in _LEGACY_OFFICIAL_SOURCE_TOKENS)


def legacy_detect_official_correction(llm_result: ReliabilityLLMResult) -> bool:
    """절 단위 판정도 부정·불확실 제외도 없던 시절. 단순 부분문자열 매칭이다."""
    text = " ".join(
        llm_result.current_validity.warnings
        + llm_result.conflicting_claims
        + llm_result.missing_information
        + [llm_result.current_validity.reason]
    )
    return any(keyword in text for keyword in _LEGACY_CORRECTION_KEYWORDS)


def legacy_criterion_caps(signals: MachineSignals) -> CriterionCaps:
    caps = CriterionCaps()
    if not signals.has_any_url or not signals.has_any_markdown:
        caps.traceability_max = min(caps.traceability_max, 5)
    if not signals.has_official_source:
        caps.source_authority_max = min(caps.source_authority_max, 16)
    if signals.single_source_only:
        caps.independent_evidence_max = min(caps.independent_evidence_max, 8)
    if signals.duplicated_republish_detected:
        caps.independent_evidence_max = min(caps.independent_evidence_max, 10)
    if signals.conflicting_claims_present:
        caps.factual_consistency_max = min(caps.factual_consistency_max, 10)
    if signals.official_correction_detected:
        caps.current_validity_max = min(caps.current_validity_max, 5)
    if signals.missing_markdown_documents:
        caps.final_level_cap = ReliabilityLevel.MEDIUM
    return caps


def breakdown_from_caps(
    llm_result: ReliabilityLLMResult, caps: CriterionCaps
) -> ReliabilityScoreBreakdown:
    """apply_machine_score_caps의 min() 블록만 떼어낸 것.

    살아 있는 쪽은 신호에서 cap을 직접 만들어 쓰기 때문에 '임의의 cap을 적용해 달라'는
    호출을 받지 못한다. 옛 cap을 적용해 봐야 하는 재현 게이트에만 필요하다.
    """
    scores = {
        f"{name}_score": min(getattr(llm_result, name).score, getattr(caps, f"{name}_max"))
        for name in CRITERIA
    }
    return ReliabilityScoreBreakdown(total_score=sum(scores.values()), **scores)


# ---------------------------------------------------------------------------
# 저장된 행 -> 원점수·신호 복원
# ---------------------------------------------------------------------------


class SkipRow(Exception):
    """이 행은 건드리지 않는다. 메시지가 그대로 리포트의 skip_reason이 된다."""


def llm_result_from_detail(detail: dict[str, Any]) -> ReliabilityLLMResult:
    """reliability_detail -> LLM 원점수.

    detail.criteria.<기준>.score는 cap 적용 **전** 값이다. repository._build_reliability_detail이
    result.criteria를 저장하는데, build_final_result가 거기 넣는 건 capped breakdown이
    아니라 raw llm_result이기 때문이다. 이 스크립트 전체가 그 사실 위에 서 있다.
    """
    criteria = (detail or {}).get("criteria") or {}
    missing = [name for name in CRITERIA if not criteria.get(name)]
    if missing:
        raise SkipRow(f"detail_incomplete:{','.join(missing)}")
    try:
        return ReliabilityLLMResult.model_validate(
            {
                **{name: criteria[name] for name in CRITERIA},
                "conflicting_claims": list(detail.get("conflicting_claims") or []),
                "missing_information": list(detail.get("missing_information") or []),
            }
        )
    except Exception as exc:  # noqa: BLE001 - pydantic 오류 종류를 가리지 않는다
        raise SkipRow(f"detail_invalid:{type(exc).__name__}") from exc


def build_signals(
    *,
    llm_result: ReliabilityLLMResult,
    document_version_id: str,
    canonical_url: str | None,
    source_type: str | None,
    has_any_markdown: bool,
    legacy: bool,
) -> MachineSignals:
    """단건 평가 1행에 대한 MachineSignals 복원.

    reliability_detail에 저장된 source_signals는 못 쓴다 — official_source_included가
    하드코딩 False이고 url/markdown 신호는 아예 없다. 그래서 메타데이터에서 다시 만든다
    (문서·소스 행 조회뿐이고 스토리지 다운로드나 LLM 호출은 없다).

    단건이라 두 신호는 항상 상수다:
      single_source_only            문서가 하나라 항상 True
      duplicated_republish_detected _detect_duplicate_republish가 문서 1건이면 False
    """
    has_any_url = bool((canonical_url or "").strip())
    official = (
        legacy_is_official_source(source_type)
        if legacy
        else _is_official_source(source_type)
    )
    correction = (
        legacy_detect_official_correction(llm_result)
        if legacy
        else _detect_official_correction(llm_result)
    )
    return MachineSignals(
        has_any_url=has_any_url,
        has_any_markdown=has_any_markdown,
        has_complete_metadata=True,  # cap 계산에 쓰이지 않는다
        document_count=1,
        unique_source_count=1,
        unique_canonical_url_count=1 if has_any_url else 0,
        has_official_source=official,
        single_source_only=True,
        duplicated_republish_detected=False,
        conflicting_claims_present=bool(llm_result.conflicting_claims),
        official_correction_detected=correction,
        missing_markdown_documents=[] if has_any_markdown else [document_version_id],
    )


def evaluate_with(
    llm_result: ReliabilityLLMResult,
    *,
    document_version_id: str,
    issue_title: str,
    canonical_url: str | None,
    source_type: str | None,
    evaluated_ids: list[str],
    has_any_markdown: bool,
    legacy: bool,
):
    """원점수 + 신호 -> 평가 결과. legacy=False면 전부 살아 있는 로직을 부른다.

    새 점수는 여기서 apply_machine_score_caps가 만든다 — 이 스크립트는 cap을 직접
    계산하지 않는다. legacy=True 경로만 동결본(legacy_criterion_caps)을 쓰고, 그건
    재현 대조에만 쓰인다.
    """
    signals = build_signals(
        llm_result=llm_result,
        document_version_id=document_version_id,
        canonical_url=canonical_url,
        source_type=source_type,
        has_any_markdown=has_any_markdown,
        legacy=legacy,
    )
    if legacy:
        caps = legacy_criterion_caps(signals)
        breakdown = breakdown_from_caps(llm_result, caps)
    else:
        breakdown, caps = apply_machine_score_caps(llm_result=llm_result, signals=signals)
    return build_final_result(
        issue_id=document_version_id,
        issue_title=issue_title,
        llm_result=llm_result,
        breakdown=breakdown,
        caps=caps,
        evaluated_document_version_ids=evaluated_ids,
    )


def _stored_scores(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "reliability_score": row.get("reliability_score"),
        "reliability_level": row.get("reliability_level"),
        **{column: row.get(column) for column in SCORE_COLUMNS},
    }


def _result_scores(result) -> dict[str, Any]:
    return {
        "reliability_score": result.reliability_score,
        "reliability_level": result.reliability_level.value,
        **{column: getattr(result, column) for column in SCORE_COLUMNS},
    }


def recompute_row(
    row: dict[str, Any],
    *,
    document: dict[str, Any] | None,
    source_type: str | None,
    markdown_object_key: str | None,
) -> dict[str, Any]:
    """행 1건을 재계산한다. 반환값이 그대로 리포트 한 줄이 된다."""
    version_id = str(row.get("document_version_id"))
    record: dict[str, Any] = {
        "analysis_result_id": str(row.get("id")),
        "document_version_id": version_id,
        "document_id": str(document["id"]) if document else None,
        "primary_category": row.get("primary_category"),
        "published_at": (document or {}).get("published_at"),
        # 아래 category_impact가 문서 단위로 접을 때 쓰는 정렬 키.
        # categories/service.py _reliability_sort_key와 같은 순서다.
        "reliability_evaluated_at": row.get("reliability_evaluated_at"),
        "row_created_at": row.get("created_at"),
        "action": "skip",
        "skip_reason": None,
        "old": _stored_scores(row),
    }

    detail = row.get("reliability_detail") or {}
    evaluated_ids = list(detail.get("evaluated_document_version_ids") or [version_id])

    try:
        if len(evaluated_ids) != 1:
            # 여러 문서를 묶어 평가한 행은 single_source_only/duplicated_republish
            # 가정이 깨진다. 현재 파이프라인은 단건만 만들지만 방어해 둔다.
            raise SkipRow(f"multi_document:{len(evaluated_ids)}")
        llm_result = llm_result_from_detail(detail)

        # has_any_markdown만 메타데이터로 확정되지 않는다(본문을 받아 봐야 안다).
        # markdown_object_key가 없으면 본문도 없는 게 확실하고, 있으면 둘 다 가능하다
        # (평가 시점에 내려받기가 실패했을 수 있다). 가능한 값을 다 넣어 보고 저장된
        # 값을 재현하는 쪽을 채택한다. 둘 다 재현하면 낮게 나오는 쪽(markdown 없음)을
        # 고른다 — 점수를 올리는 마이그레이션에서 안전한 방향이다.
        candidates = (False, True) if markdown_object_key else (False,)
        context = {
            "document_version_id": version_id,
            "issue_title": (document or {}).get("title") or version_id,
            "canonical_url": (document or {}).get("canonical_url"),
            "source_type": source_type,
            "evaluated_ids": evaluated_ids,
        }

        # 옛 로직으로 재현되면 아직 안 고쳐진 행이고, 새 로직으로 재현되면 이미
        # 고쳐진 행이다(2회차 실행). 둘 다 아니면 신호 재구성이 틀린 것이므로
        # 손대지 않는다 — 이 게이트가 이 배치의 안전장치다.
        by_mode: dict[str, list[bool]] = {"legacy": [], "current": []}
        for candidate in candidates:
            for mode in ("legacy", "current"):
                result = evaluate_with(
                    llm_result, **context, has_any_markdown=candidate,
                    legacy=(mode == "legacy"),
                )
                if _result_scores(result) == _stored_scores(row):
                    by_mode[mode].append(candidate)

        # False가 먼저라 각 목록의 첫 값이 보수적인 쪽이다.
        mode, reproduced = (
            ("legacy", by_mode["legacy"]) if by_mode["legacy"] else ("current", by_mode["current"])
        )
        if not reproduced:
            raise SkipRow("reproduction_mismatch")
        has_any_markdown = reproduced[0]
        record["reproduced_as"] = mode
        record["markdown_signal"] = (
            "ambiguous_assumed_missing" if len(reproduced) == 2 else str(has_any_markdown)
        )

        result = evaluate_with(
            llm_result, **context, has_any_markdown=has_any_markdown, legacy=False
        )
    except SkipRow as exc:
        record["skip_reason"] = str(exc)
        return record

    record["new"] = _result_scores(result)
    record["new"]["reliability_summary_reason"] = result.summary_reason
    record["raw"] = {name: getattr(llm_result, name).score for name in CRITERIA}
    if record["new"] == {
        **record["old"],
        "reliability_summary_reason": row.get("reliability_summary_reason"),
    }:
        # 2회차 실행이거나 이 행에는 완화가 걸리지 않은 경우. 재현은 됐으므로 정상이다.
        record["action"] = "already_current"
    else:
        record["action"] = "update"
    record["delta"] = (record["new"]["reliability_score"] or 0) - (
        record["old"]["reliability_score"] or 0
    )
    return record


# ---------------------------------------------------------------------------
# 조회
# ---------------------------------------------------------------------------


def get_workspace_id(db) -> str:
    rows = db.table("workspaces").select("id, name").limit(2).execute().data
    if len(rows) != 1:
        raise SystemExit(f"워크스페이스를 자동으로 고를 수 없다. workspace_count={len(rows)}")
    return str(rows[0]["id"])


def fetch_target_rows(db, workspace_id: str, *, evaluated_before: str) -> list[dict]:
    """보정 대상 후보. 페이지로 나눠 전건 받는다(PostgREST 1,000행 상한)."""
    rows: list[dict] = []
    offset = 0
    while offset < FETCH_LIMIT:
        page = (
            db.table("document_analysis_results")
            .select(_ANALYSIS_COLUMNS)
            .eq("workspace_id", workspace_id)
            .eq("reliability_status", "completed")
            .lt("reliability_evaluated_at", evaluated_before)
            .order("id")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
            .data
        ) or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def fetch_context(db, workspace_id: str, version_ids: list[str]) -> tuple[dict, dict, dict]:
    """version_id -> (documents 행, source_type, markdown_object_key).

    document_versions에는 workspace_id 컬럼이 없다. documents 조회에 workspace_id를
    직접 걸어 격리한다 — 여기가 격리가 성립하는 유일한 지점이다.
    """
    versions: list[dict] = []
    for chunk in chunked(sorted(set(version_ids))):
        versions.extend(
            db.table("document_versions")
            .select("id, document_id, markdown_object_key")
            .in_("id", chunk)
            .execute()
            .data
            or []
        )

    document_ids = [str(v["document_id"]) for v in versions if v.get("document_id")]
    documents: list[dict] = []
    for chunk in chunked(sorted(set(document_ids))):
        documents.extend(
            db.table("documents")
            .select("id, title, canonical_url, published_at, created_at, source_id")
            .eq("workspace_id", workspace_id)
            .in_("id", chunk)
            .execute()
            .data
            or []
        )
    by_document = {str(d["id"]): d for d in documents}

    source_rows = (
        db.table("sources")
        .select("id, source_type")
        .eq("workspace_id", workspace_id)
        .execute()
        .data
        or []
    )
    source_types = {str(s["id"]): s.get("source_type") for s in source_rows}

    documents_by_version: dict[str, dict] = {}
    source_type_by_version: dict[str, str | None] = {}
    markdown_keys: dict[str, str | None] = {}
    for version in versions:
        version_id = str(version["id"])
        document = by_document.get(str(version.get("document_id")))
        if document is None:
            continue
        documents_by_version[version_id] = document
        source_type_by_version[version_id] = source_types.get(str(document.get("source_id")))
        markdown_keys[version_id] = version.get("markdown_object_key")
    return documents_by_version, source_type_by_version, markdown_keys


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------


def apply_update(db, workspace_id: str, record: dict[str, Any]) -> None:
    """점수 컬럼만 쓴다. 무엇을 안 쓰는지는 모듈 독스트링 참조."""
    new = record["new"]
    payload = {
        "reliability_score": new["reliability_score"],
        "reliability_level": new["reliability_level"],
        "reliability_summary_reason": new["reliability_summary_reason"],
        **{column: new[column] for column in SCORE_COLUMNS},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    (
        db.table("document_analysis_results")
        .update(payload)
        .eq("id", record["analysis_result_id"])
        .eq("workspace_id", workspace_id)
        .execute()
    )


def run(
    db,
    workspace_id: str,
    *,
    days: int | None,
    limit: int | None,
    dry_run: bool,
    evaluated_before: str,
    report_path: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    candidates = fetch_target_rows(db, workspace_id, evaluated_before=evaluated_before)
    version_ids = [
        str(r["document_version_id"]) for r in candidates if r.get("document_version_id")
    ]
    documents, source_types, markdown_keys = fetch_context(db, workspace_id, version_ids)

    # 창 판정은 카테고리 현황과 **같은 함수**를 쓴다. 화면에 보이는 것과 보정 대상이
    # 갈리면 "고쳤는데 화면이 그대로"가 된다.
    start = window_start(now, days=days) if days is not None else None
    targets = []
    for row in candidates:
        document = documents.get(str(row.get("document_version_id")))
        if document is None:
            continue
        if start is not None and not in_published_window(document, start):
            continue
        targets.append(row)
    if limit is not None:
        targets = targets[:limit]

    summary: dict[str, Any] = {
        "workspace_id": workspace_id,
        "dry_run": dry_run,
        "days": days,
        "evaluated_before": evaluated_before,
        "candidates": len(candidates),
        "targets": len(targets),
        "updated": 0,
        "already_current": 0,
        "skipped": 0,
        "skip_reasons": {},
        "report_path": str(report_path),
    }

    records: list[dict[str, Any]] = []
    for row in targets:
        version_id = str(row.get("document_version_id"))
        record = recompute_row(
            row,
            document=documents.get(version_id),
            source_type=source_types.get(version_id),
            markdown_object_key=markdown_keys.get(version_id),
        )
        records.append(record)

        if record["action"] == "update":
            if not dry_run:
                try:
                    apply_update(db, workspace_id, record)
                except Exception as exc:  # noqa: BLE001
                    record["action"] = "skip"
                    record["skip_reason"] = f"update_failed:{exc}"
            if record["action"] == "update":
                summary["updated"] += 1
        elif record["action"] == "already_current":
            summary["already_current"] += 1

        if record["action"] == "skip":
            summary["skipped"] += 1
            reason = (record["skip_reason"] or "unknown").split(":")[0]
            summary["skip_reasons"][reason] = summary["skip_reasons"].get(reason, 0) + 1

    report_path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )
    summary["gates"] = build_gates(records, summary)
    summary["categories"] = category_impact(records)
    return summary


def build_gates(records: list[dict], summary: dict) -> dict:
    """dry-run이 숫자 나열이 아니라 PASS/FAIL을 내게 하는 부분."""
    mismatches = [
        r["analysis_result_id"]
        for r in records
        if (r.get("skip_reason") or "").startswith("reproduction_mismatch")
    ]
    regressions = [
        {
            "analysis_result_id": r["analysis_result_id"],
            "old": r["old"]["reliability_score"],
            "new": r["new"]["reliability_score"],
        }
        for r in records
        if r.get("new") and r["delta"] < 0
    ]
    out_of_range = [
        r["analysis_result_id"]
        for r in records
        if r.get("new") and not _scores_in_range(r["new"])
    ]
    changed = [r for r in records if r["action"] == "update"]
    covered = all("old" in r for r in records)

    return {
        # 1. 재구성이 옛 값을 그대로 재현하는가. 아니면 그 행은 손대지 않았다.
        "gate1_reproduction": {
            "verdict": "PASS" if not mismatches else "FAIL",
            "mismatched": len(mismatches),
            "examples": mismatches[:5],
            "note": "재현 실패는 신호 재구성이 틀렸다는 뜻이다. 해당 행은 UPDATE하지 않았다",
        },
        # 2. 세 변경이 모두 상한 완화라 점수는 내려갈 수 없다.
        "gate2_monotonic": {
            "verdict": "PASS" if not regressions else "FAIL",
            "regressions": len(regressions),
            "examples": regressions[:5],
            "delta_max": max((r["delta"] for r in changed), default=0),
            "delta_mean": round(sum(r["delta"] for r in changed) / len(changed), 2)
            if changed
            else 0,
        },
        # 3. 모델 제약을 넘지 않는가.
        "gate3_range": {
            "verdict": "PASS" if not out_of_range else "FAIL",
            "out_of_range": len(out_of_range),
        },
        # 4. 되돌릴 근거가 전건 남았는가.
        "gate4_rollback": {
            "verdict": "PASS" if covered and summary["report_path"] else "FAIL",
            "recorded": len(records),
            "report_path": summary["report_path"],
        },
    }


def _scores_in_range(new: dict) -> bool:
    if not 0 <= (new["reliability_score"] or 0) <= 100:
        return False
    if any(not 0 <= (new[column] or 0) <= 20 for column in SCORE_COLUMNS):
        return False
    bucket = {"낮음": (0, 39), "보통": (40, 69), "높음": (70, 100)}.get(new["reliability_level"])
    if bucket is None:
        return False
    return bucket[0] <= new["reliability_score"] <= bucket[1]


def category_impact(records: list[dict]) -> dict:
    """게이트 5 — 카테고리별 평균이 어떻게 움직이는가. 승인 요청에 그대로 붙인다.

    화면과 같은 방식으로 센다: 분석 행이 아니라 **문서 단위**로 접고, 한 문서에서는
    가장 최근에 평가된 행 하나만 쓴다(categories/service.py
    _latest_reliability_scores_by_document와 같은 규칙). 행 단위로 평균 내면 재수집으로
    버전이 늘어난 문서가 여러 번 세어져 표가 화면과 어긋나고, 그러면 이 표를 붙여
    받은 승인이 실제 화면 변화와 다른 것을 근거로 한 것이 된다.
    """
    latest: dict[str, dict] = {}
    for record in records:
        if not record.get("new"):
            continue
        key = record.get("document_id") or record["document_version_id"]
        current = latest.get(key)
        if current is None or _impact_sort_key(record) > _impact_sort_key(current):
            latest[key] = record

    buckets: dict[str, list[dict]] = {}
    for record in latest.values():
        buckets.setdefault(record.get("primary_category") or "(미분류)", []).append(record)

    def label(avg: float) -> str:
        return "낮음" if avg < 40 else ("보통" if avg < 70 else "높음")

    impact: dict[str, dict] = {}
    for category, rows in sorted(buckets.items()):
        before = sum(r["old"]["reliability_score"] or 0 for r in rows) / len(rows)
        after = sum(r["new"]["reliability_score"] or 0 for r in rows) / len(rows)
        impact[category] = {
            "documents": len(rows),
            "avg_before": round(before, 1),
            "avg_after": round(after, 1),
            "label_before": label(before),
            "label_after": label(after),
        }
    return impact


def _impact_sort_key(record: dict) -> tuple[str, str]:
    return (
        str(record.get("reliability_evaluated_at") or ""),
        str(record.get("row_created_at") or ""),
    )


def rollback(db, workspace_id: str, report_path: Path, *, dry_run: bool) -> dict:
    """리포트에 남은 이전 값을 그대로 되돌린다."""
    restored = 0
    for line in report_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("action") != "update":
            continue
        if not dry_run:
            payload = {
                "reliability_score": record["old"]["reliability_score"],
                "reliability_level": record["old"]["reliability_level"],
                **{column: record["old"][column] for column in SCORE_COLUMNS},
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            (
                db.table("document_analysis_results")
                .update(payload)
                .eq("id", record["analysis_result_id"])
                .eq("workspace_id", workspace_id)
                .execute()
            )
        restored += 1
    return {"restored": restored, "dry_run": dry_run, "report_path": str(report_path)}


def print_summary(summary: dict) -> None:
    print("\n=== 신뢰도 상한 재계산 ===")
    print(f"모드: {'DRY-RUN (쓰지 않음)' if summary['dry_run'] else '실행'}")
    scope = f"발행일 최근 {summary['days']}일" if summary["days"] is not None else "전체"
    print(f"범위: {scope} / {summary['evaluated_before']} 이전 평가분")
    print(f"후보 {summary['candidates']}건 -> 대상 {summary['targets']}건")
    print(
        f"갱신 {summary['updated']}건 / 이미 최신 {summary['already_current']}건 / "
        f"건너뜀 {summary['skipped']}건"
    )
    if summary["skip_reasons"]:
        print(f"건너뛴 사유: {summary['skip_reasons']}")
    print(f"리포트: {summary['report_path']}")

    if summary["categories"]:
        print("\n카테고리별 평균 (게이트 5)")
        print(f"  {'카테고리':<12} {'건수':>5} {'이전':>7} {'이후':>7}  배지")
        for category, row in summary["categories"].items():
            badge = (
                f"{row['label_before']} -> {row['label_after']}"
                if row["label_before"] != row["label_after"]
                else row["label_before"]
            )
            print(
                f"  {category:<12} {row['documents']:>5} {row['avg_before']:>7} "
                f"{row['avg_after']:>7}  {badge}"
            )

    print("\n게이트")
    gates = summary["gates"]
    for key in ("gate1_reproduction", "gate2_monotonic", "gate3_range", "gate4_rollback"):
        gate = gates[key]
        print(f"  {key:<20} {gate['verdict']}")
        for field, value in gate.items():
            if field in {"verdict", "note"} or not value:
                continue
            print(f"      {field}: {value}")
        if gate.get("note"):
            print(f"      note: {gate['note']}")

    passed = sum(1 for g in gates.values() if g["verdict"] == "PASS")
    verdict = "PASS" if passed == len(gates) else "FAIL"
    print(f"\nGATE: {verdict} ({passed}/{len(gates)})")
    if summary["dry_run"]:
        print("실행 전 승인 필요: document_analysis_results는 src/analysis/ 파트 테이블이다")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="저장된 reliability_score를 LLM 호출 없이 현재 cap 로직으로 재계산한다."
    )
    parser.add_argument("--workspace-id", default=None)
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="발행일 기준 최근 N일만 대상으로 한다 (카테고리 현황과 같은 창)",
    )
    parser.add_argument(
        "--all", action="store_true", help="발행일 창을 걸지 않고 전체를 대상으로 한다"
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="계산만 하고 쓰지 않는다")
    parser.add_argument("--evaluated-before", default=DEFAULT_EVALUATED_BEFORE)
    parser.add_argument("--report", default=None, help="JSONL 리포트 경로")
    parser.add_argument("--rollback", default=None, help="리포트의 이전 값으로 되돌린다")
    args = parser.parse_args(argv)

    if args.days is not None and args.days <= 0:
        parser.error("--days는 0보다 커야 한다")
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit은 0보다 커야 한다")

    from dotenv import load_dotenv

    load_dotenv()
    from src.pipeline_common.db import get_client

    db = get_client()
    workspace_id = args.workspace_id or get_workspace_id(db)

    if args.rollback:
        result = rollback(db, workspace_id, Path(args.rollback), dry_run=args.dry_run)
        print(f"원복 {result['restored']}건 (dry_run={result['dry_run']})")
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary = run(
        db,
        workspace_id,
        days=None if args.all else args.days,
        limit=args.limit,
        dry_run=args.dry_run,
        evaluated_before=args.evaluated_before,
        report_path=Path(args.report or f"recompute_reliability_caps_{stamp}.jsonl"),
    )
    print_summary(summary)
    return 0 if all(g["verdict"] == "PASS" for g in summary["gates"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())

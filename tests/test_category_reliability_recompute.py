"""
신뢰도 상한 재계산 배치 테스트 (scripts/recompute_reliability_caps.py).

카테고리 현황이 '낮음'으로 굳어 있던 원인의 절반은 DB에 남은 옛 로직 산출물이다.
이 배치가 그걸 LLM 호출 없이 되돌려 놓는다.

tests/test_category_service.py와 같은 방식으로 파일 안에 로컬 Fake를 둔다 —
여기 필요한 .lt()와 .update()를 tests/pipeline/fake_supabase.py가 지원하지 않는다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts import recompute_reliability_caps as batch

WORKSPACE_ID = "ws-1"
NOW = datetime(2026, 8, 5, 3, 0, tzinfo=timezone.utc)
CUTOFF = "2026-08-10T06:53:05+00:00"


# ------------------------------------------------------------
# Fake Supabase
# ------------------------------------------------------------


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, rows, updates):
        self.rows = rows
        self.updates = updates
        self.filters = []
        self._limit = None
        self._range = None
        self._payload = None

    def select(self, _fields):
        return self

    def update(self, payload):
        self._payload = payload
        return self

    def eq(self, field, value):
        self.filters.append(("eq", field, value))
        return self

    def lt(self, field, value):
        self.filters.append(("lt", field, value))
        return self

    def in_(self, field, values):
        self.filters.append(("in", field, [str(v) for v in values]))
        return self

    def order(self, _field, desc=False):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def _matching(self):
        rows = self.rows
        for op, field, value in self.filters:
            if op == "eq":
                rows = [r for r in rows if str(r.get(field)) == str(value)]
            elif op == "lt":
                rows = [r for r in rows if r.get(field) and r[field] < value]
            elif op == "in":
                rows = [r for r in rows if str(r.get(field)) in value]
        return rows

    def execute(self):
        rows = self._matching()
        if self._payload is not None:
            for row in rows:
                row.update(self._payload)
                self.updates.append((str(row.get("id")), dict(self._payload)))
            return FakeResult([dict(r) for r in rows])
        if self._range is not None:
            start, end = self._range
            rows = rows[start : end + 1]
        if self._limit is not None:
            rows = rows[: self._limit]
        return FakeResult([dict(r) for r in rows])


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables
        self.updates: list[tuple[str, dict]] = []

    def table(self, name):
        return FakeTable(self.tables.setdefault(name, []), self.updates)


# ------------------------------------------------------------
# 픽스처
#
# 저장된 행은 "옛 로직으로 만들어진 것"이어야 한다. 그래서 점수를 손으로 적지 않고
# 옛 로직을 그대로 돌려서 만든다 — 그러지 않으면 재현 게이트만 통과시키려고 숫자를
# 맞추는 꼴이 되고, 게이트가 무엇을 지키는지 알 수 없어진다.
# ------------------------------------------------------------


def _criterion(score, reason="근거 있음", warnings=None):
    return {
        "score": score,
        "reason": reason,
        "evidence_document_ids": ["v1"],
        "warnings": warnings or [],
    }


def _detail(
    *,
    traceability=15,
    source_authority=18,
    current_validity=18,
    independent_evidence=15,
    factual_consistency=16,
    current_validity_reason="현재 유효하다",
    current_validity_warnings=None,
    conflicting_claims=None,
    missing_information=None,
    evaluated_ids=("v1",),
):
    return {
        "criteria": {
            "traceability": _criterion(traceability),
            "source_authority": _criterion(source_authority),
            "current_validity": _criterion(
                current_validity,
                reason=current_validity_reason,
                warnings=current_validity_warnings,
            ),
            "independent_evidence": _criterion(independent_evidence),
            "factual_consistency": _criterion(factual_consistency),
        },
        "conflicting_claims": list(conflicting_claims or []),
        "missing_information": list(missing_information or []),
        "evaluated_document_version_ids": list(evaluated_ids),
    }


def _legacy_stored(detail, *, source_type=None, canonical_url="https://example.com/1",
                   has_markdown=True):
    """옛 로직을 실제로 돌려서 '저장돼 있었을 값'을 만든다."""
    llm = batch.llm_result_from_detail(detail)
    signals = batch.build_signals(
        llm_result=llm,
        document_version_id="v1",
        canonical_url=canonical_url,
        source_type=source_type,
        has_any_markdown=has_markdown,
        legacy=True,
    )
    caps = batch.legacy_criterion_caps(signals)
    result = batch.build_final_result(
        issue_id="v1",
        issue_title="기사",
        llm_result=llm,
        breakdown=batch.breakdown_from_caps(llm, caps),
        caps=caps,
        evaluated_document_version_ids=list(detail["evaluated_document_version_ids"]),
    )
    return {
        "reliability_score": result.reliability_score,
        "reliability_level": result.reliability_level.value,
        "reliability_summary_reason": result.summary_reason,
        **{c: getattr(result, c) for c in batch.SCORE_COLUMNS},
    }


def _row(detail, *, version_id="v1", category="제품·기술", source_type=None,
         canonical_url="https://example.com/1", has_markdown=True, row_id="a1"):
    stored = _legacy_stored(
        detail, source_type=source_type, canonical_url=canonical_url,
        has_markdown=has_markdown,
    )
    return {
        "id": row_id,
        "workspace_id": WORKSPACE_ID,
        "document_version_id": version_id,
        "primary_category": category,
        "reliability_status": "completed",
        "reliability_detail": detail,
        "reliability_evaluated_at": "2026-08-09T00:00:00+00:00",
        "created_at": "2026-08-04T00:00:00+00:00",
        **stored,
    }


def _db(rows, *, source_type=None, published_at="2026-08-04T00:00:00+00:00",
        markdown_key="processed/v1.md"):
    version_ids = sorted({str(r["document_version_id"]) for r in rows})
    return FakeSupabase({
        "document_analysis_results": rows,
        "document_versions": [
            {"id": v, "document_id": f"doc-{v}", "markdown_object_key": markdown_key}
            for v in version_ids
        ],
        "documents": [
            {
                "id": f"doc-{v}",
                "workspace_id": WORKSPACE_ID,
                "title": f"기사 {v}",
                "canonical_url": "https://example.com/1",
                "published_at": published_at,
                "created_at": "2026-08-04T00:00:00+00:00",
                "source_id": "src-1",
            }
            for v in version_ids
        ],
        "sources": [
            {"id": "src-1", "workspace_id": WORKSPACE_ID, "source_type": source_type}
        ],
    })


def _run(db, tmp_path, **kwargs):
    kwargs.setdefault("days", 7)
    kwargs.setdefault("limit", None)
    kwargs.setdefault("dry_run", False)
    kwargs.setdefault("evaluated_before", CUTOFF)
    kwargs.setdefault("report_path", Path(tmp_path) / "report.jsonl")
    kwargs.setdefault("now", NOW)
    return batch.run(db, WORKSPACE_ID, **kwargs)


# ------------------------------------------------------------
# 원점수 복원 — 이 스크립트 전체가 서 있는 전제
# ------------------------------------------------------------


def test_detail의_criteria_점수는_cap_적용_전_원점수다():
    """저장된 컬럼(5)과 detail의 원점수(18)가 다르다는 것이 재계산이 가능한 이유다."""
    detail = _detail(current_validity=18, current_validity_reason="정정 보도가 있었다")
    row = _row(detail)

    assert row["current_validity_score"] == 5           # 컬럼은 cap 적용 후
    assert detail["criteria"]["current_validity"]["score"] == 18  # detail은 원점수

    llm = batch.llm_result_from_detail(detail)
    assert llm.current_validity.score == 18


def test_detail이_비면_건드리지_않는다():
    row = _row(_detail())
    row["reliability_detail"] = {"criteria": {"traceability": _criterion(10)}}

    record = batch.recompute_row(
        row, document={"id": "d", "canonical_url": "u", "title": "t"},
        source_type=None, markdown_object_key="k",
    )

    assert record["action"] == "skip"
    assert record["skip_reason"].startswith("detail_incomplete")
    assert "new" not in record


def test_여러_문서를_묶어_평가한_행은_건드리지_않는다():
    """단건 가정(single_source_only=True 등)이 깨지는 행이다."""
    detail = _detail(evaluated_ids=("v1", "v2"))
    row = _row(detail)

    record = batch.recompute_row(
        row, document={"id": "d", "canonical_url": "u", "title": "t"},
        source_type=None, markdown_object_key="k",
    )

    assert record["action"] == "skip"
    assert record["skip_reason"].startswith("multi_document")


# ------------------------------------------------------------
# 변경 3건이 각각 반영되는가
# ------------------------------------------------------------


def test_259_정정_오탐이_풀려_current_validity가_복원된다():
    """'정정 정황은 확인되지 않았다' 같은 문장이 옛 로직에서는 정정으로 잡혔다."""
    detail = _detail(
        current_validity=18,
        current_validity_reason="공식 정정이나 철회 정황은 확인되지 않았다",
    )
    row = _row(detail)
    assert row["current_validity_score"] == 5  # 옛 로직: 오탐으로 상한 5

    summary = _run(_db([row]), Path("/tmp"), report_path=Path("/tmp/r1.jsonl"))
    record = json.loads(Path("/tmp/r1.jsonl").read_text(encoding="utf-8").splitlines()[0])

    assert record["action"] == "update"
    assert record["new"]["current_validity_score"] == 18
    # +13은 정정 오탐(5->18), +4는 같은 행에 같이 걸린 #257 단일 출처 완화(8->12)다.
    assert record["delta"] == 17
    assert record["new"]["independent_evidence_score"] == 12
    assert summary["updated"] == 1


def test_257_단일_출처_상한이_8에서_12로_완화된다():
    detail = _detail(independent_evidence=15)
    row = _row(detail)
    assert row["independent_evidence_score"] == 8

    record = batch.recompute_row(
        row,
        document={"id": "d", "canonical_url": "https://example.com/1", "title": "t"},
        source_type=None,
        markdown_object_key="k",
    )

    assert record["new"]["independent_evidence_score"] == 12


def test_257_공시는_공식_출처라_source_authority_상한이_풀린다():
    detail = _detail(source_authority=18)
    row = _row(detail, source_type="disclosure")
    assert row["source_authority_score"] == 16

    record = batch.recompute_row(
        row,
        document={"id": "d", "canonical_url": "https://example.com/1", "title": "t"},
        source_type="disclosure",
        markdown_object_key="k",
    )

    assert record["new"]["source_authority_score"] == 18


def test_진짜_정정_기사는_그대로_5로_남는다():
    """완화가 과잉 적용되면 안 된다 — 부정어 없는 정정 서술은 여전히 정정이다."""
    detail = _detail(
        current_validity=18,
        current_validity_reason="해당 보도는 공식 정정되었다",
    )
    row = _row(detail)

    record = batch.recompute_row(
        row,
        document={"id": "d", "canonical_url": "https://example.com/1", "title": "t"},
        source_type=None,
        markdown_object_key="k",
    )

    assert record["new"]["current_validity_score"] == 5


# ------------------------------------------------------------
# 게이트
# ------------------------------------------------------------


def test_재현되지_않는_행은_UPDATE하지_않는다():
    """저장된 값이 어떤 옛 신호 조합으로도 안 나오면 재구성이 틀린 것이다."""
    row = _row(_detail())
    row["reliability_score"] = 42          # 손으로 비틀어 재현 불가로 만든다
    row["traceability_score"] = 1
    db = _db([row])

    summary = _run(db, Path("/tmp"), report_path=Path("/tmp/r2.jsonl"))

    assert summary["updated"] == 0
    assert summary["skip_reasons"] == {"reproduction_mismatch": 1}
    assert summary["gates"]["gate1_reproduction"]["verdict"] == "FAIL"
    assert db.updates == []


def test_점수가_내려가면_단조성_게이트가_FAIL이다():
    """세 변경이 모두 상한 완화라 감소는 논리적으로 불가능하다. 나오면 버그 신호다."""
    records = [
        {"analysis_result_id": "a1", "action": "update", "old": {"reliability_score": 70},
         "new": {"reliability_score": 60, "reliability_level": "보통",
                 **{c: 12 for c in batch.SCORE_COLUMNS}}, "delta": -10},
    ]

    gates = batch.build_gates(records, {"report_path": "r.jsonl"})

    assert gates["gate2_monotonic"]["verdict"] == "FAIL"
    assert gates["gate2_monotonic"]["regressions"] == 1


def test_정상_실행은_모든_게이트가_PASS다():
    detail = _detail(current_validity=18, current_validity_reason="정정 정황은 없다")
    db = _db([_row(detail)])

    summary = _run(db, Path("/tmp"), report_path=Path("/tmp/r3.jsonl"))

    assert all(g["verdict"] == "PASS" for g in summary["gates"].values())
    assert summary["gates"]["gate2_monotonic"]["delta_max"] > 0


# ------------------------------------------------------------
# 실행 안전성
# ------------------------------------------------------------


def test_두_번_돌려도_같은_값이고_두_번째는_already_current다():
    """원점수를 detail에서 읽으므로 멱등이다. 커서 없이도 재실행이 안전한 근거."""
    detail = _detail(current_validity=18, current_validity_reason="정정 정황은 없다")
    db = _db([_row(detail)])

    first = _run(db, Path("/tmp"), report_path=Path("/tmp/r4.jsonl"))
    after_first = dict(db.tables["document_analysis_results"][0])

    second = _run(db, Path("/tmp"), report_path=Path("/tmp/r5.jsonl"))

    assert first["updated"] == 1
    assert second["updated"] == 0
    assert second["already_current"] == 1
    assert second["gates"]["gate1_reproduction"]["verdict"] == "PASS"
    assert db.tables["document_analysis_results"][0]["reliability_score"] == after_first[
        "reliability_score"
    ]


def test_UPDATE는_점수_컬럼만_건드린다():
    """evaluated_at·prompt_version·detail을 쓰면 안 되는 이유는 모듈 독스트링 참조."""
    detail = _detail(current_validity=18, current_validity_reason="정정 정황은 없다")
    db = _db([_row(detail)])

    _run(db, Path("/tmp"), report_path=Path("/tmp/r6.jsonl"))

    assert len(db.updates) == 1
    _, payload = db.updates[0]
    assert set(payload) == {
        "reliability_score",
        "reliability_level",
        "reliability_summary_reason",
        *batch.SCORE_COLUMNS,
        "updated_at",
    }


def test_dry_run은_쓰지_않고_게이트만_낸다():
    detail = _detail(current_validity=18, current_validity_reason="정정 정황은 없다")
    db = _db([_row(detail)])

    summary = _run(db, Path("/tmp"), dry_run=True, report_path=Path("/tmp/r7.jsonl"))

    assert summary["updated"] == 1  # '바뀔 건수'는 보고하되
    assert db.updates == []         # 실제로 쓰지는 않는다
    assert db.tables["document_analysis_results"][0]["current_validity_score"] == 5


def test_리포트로_원복된다():
    detail = _detail(current_validity=18, current_validity_reason="정정 정황은 없다")
    db = _db([_row(detail)])
    report = Path("/tmp/r8.jsonl")

    _run(db, Path("/tmp"), report_path=report)
    changed = db.tables["document_analysis_results"][0]["reliability_score"]

    batch.rollback(db, WORKSPACE_ID, report, dry_run=False)

    restored = db.tables["document_analysis_results"][0]
    assert restored["reliability_score"] != changed
    assert restored["current_validity_score"] == 5  # 옛 값


# ------------------------------------------------------------
# 대상 범위 — 카테고리 현황과 같은 창을 본다
# ------------------------------------------------------------


def test_발행일이_창_밖이면_대상에서_빠진다():
    detail = _detail(current_validity=18, current_validity_reason="정정 정황은 없다")
    db = _db([_row(detail)], published_at="2026-07-01T00:00:00+00:00")

    summary = _run(db, Path("/tmp"), report_path=Path("/tmp/r9.jsonl"))

    assert summary["candidates"] == 1
    assert summary["targets"] == 0


def test_all이면_발행일_창을_걸지_않는다():
    detail = _detail(current_validity=18, current_validity_reason="정정 정황은 없다")
    db = _db([_row(detail)], published_at="2026-07-01T00:00:00+00:00")

    summary = _run(db, Path("/tmp"), days=None, report_path=Path("/tmp/r10.jsonl"))

    assert summary["targets"] == 1
    assert summary["updated"] == 1


def test_cutoff_이후_평가분은_후보에도_안_들어온다():
    """#259 머지 뒤에 평가된 행은 이미 새 로직 산출물이다."""
    detail = _detail(current_validity=18, current_validity_reason="정정 정황은 없다")
    row = _row(detail)
    row["reliability_evaluated_at"] = "2026-08-10T12:00:00+00:00"
    db = _db([row])

    summary = _run(db, Path("/tmp"), report_path=Path("/tmp/r11.jsonl"))

    assert summary["candidates"] == 0


def test_1000행을_넘어도_전건을_본다():
    """PostgREST 1,000행 상한. 이 저장소가 세 번 당한 자리다."""
    detail = _detail(current_validity=18, current_validity_reason="정정 정황은 없다")
    rows = [
        _row(detail, version_id=f"v{i:04d}", row_id=f"a{i:04d}") for i in range(1200)
    ]
    db = _db(rows)

    summary = _run(db, Path("/tmp"), report_path=Path("/tmp/r12.jsonl"))

    assert summary["candidates"] == 1200
    assert summary["updated"] == 1200


# ------------------------------------------------------------
# 게이트 5 — 승인 요청에 붙일 화면 변화표
# ------------------------------------------------------------


def test_카테고리별_평균_변화를_배지까지_보고한다():
    detail = _detail(current_validity=18, current_validity_reason="정정 정황은 없다")
    rows = [
        _row(detail, row_id="a1", version_id="v1"),
        _row(detail, row_id="a2", version_id="v2", category="정책·규제"),
    ]

    summary = _run(_db(rows), Path("/tmp"), report_path=Path("/tmp/r13.jsonl"))

    impact = summary["categories"]
    assert set(impact) == {"제품·기술", "정책·규제"}
    for row in impact.values():
        assert row["avg_after"] > row["avg_before"]
        assert row["label_before"] == "보통" and row["label_after"] == "높음"


def test_카테고리_평균은_문서_단위로_접어서_낸다():
    """행 단위로 평균 내면 재수집으로 버전이 늘어난 문서가 여러 번 세어진다.

    화면(_latest_reliability_scores_by_document)과 같은 규칙이어야 이 표를 붙여
    받은 승인이 실제 화면 변화를 근거로 한 것이 된다.
    """
    detail = _detail(current_validity=18, current_validity_reason="정정 정황은 없다")
    older = _row(detail, row_id="a1", version_id="v1")
    newer = _row(detail, row_id="a2", version_id="v2")
    newer["reliability_evaluated_at"] = "2026-08-09T12:00:00+00:00"

    db = _db([older, newer])
    # 두 분석 행이 같은 문서를 가리키게 한다 (재수집으로 버전이 둘)
    for version in db.tables["document_versions"]:
        version["document_id"] = "doc-same"
    db.tables["documents"] = [db.tables["documents"][0]]
    db.tables["documents"][0]["id"] = "doc-same"

    summary = _run(db, Path("/tmp"), report_path=Path("/tmp/r14.jsonl"))

    assert summary["updated"] == 2               # 두 행 모두 보정하되
    assert summary["categories"]["제품·기술"]["documents"] == 1  # 표에는 문서 1건

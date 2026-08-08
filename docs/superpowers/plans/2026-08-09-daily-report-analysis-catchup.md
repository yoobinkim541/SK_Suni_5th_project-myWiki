# 일일 리포트 분석 catchup 개선 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `daily-report-analysis-catchup.yml`이 매일 06:00 KST에 시작해서, nightly-analysis의 결과까지 포함한 오늘자 report-ready 후보 수를 확인하고, 07:15 KST 마감까지 최소 6건을 확보하도록 백로그를 이어서 분석하며, 최종적으로 `daily_report_analysis_batches`를 "오늘 selected_for_report=True 전체"로 채운다.

**Architecture:** `scripts/run_daily_report_analysis_catchup.py`의 `run_daily_report_analysis_catchup()`을 단발성 실행에서 "확인→(부족하면) 처리→재확인" 루프로 바꾼다. 후보 수 확인은 `src/analysis/repository.py`의 기존 `get_ranked_results_for_report()`를 재사용하고(새 쿼리 없음), 처리는 기존 `scripts/run_analysis_pipeline.py`의 함수들을 그대로 재사용한다. `daily-report-analysis-catchup.yml`의 cron 시각과 timeout만 같이 조정한다. `nightly-analysis.yml`/`run_nightly_analysis.py`는 변경하지 않는다.

**Tech Stack:** Python 3.12, pytest + monkeypatch(실제 Supabase/OpenRouter 호출 없이 함수 단위로 스텁), GitHub Actions.

## Global Constraints

- 새 함수/로직에 근거 없는 추측 로직을 넣지 않는다 — 기존 `select_analysis_candidates`/`run_analysis_pipeline`/`get_adaptive_analysis_limit`을 그대로 재사용한다(스펙 "비목표": `run_analysis_pipeline.py`의 스코어링 로직은 건드리지 않음).
- `ranking_batch_date`는 UTC 캘린더 날짜(`report_date - 1일`)로 조회한다(스펙 "날짜 변환 주의").
- `daily-report-analysis-catchup.yml`은 `scheduled-daily-report.yml`과 `concurrency: group: daily-report-schedule`를 공유하므로(`cancel-in-progress: false`), 07:30 KST 전에 반드시 끝나야 한다.
- 커밋 메시지는 `Feat:`/`Fix:`/`Test:` 접두사, 브랜치명은 `fix/<주제>`(collaboration_rule.md).
- push 전 `gh pr list --state open`으로 병렬 세션 중복 확인. 머지는 `gh pr merge --squash`만 사용.

---

### Task 1: `run_daily_report_analysis_catchup.py` — 최소 후보 수 확보 루프 + 배치 재구성

**Files:**
- Modify: `scripts/run_daily_report_analysis_catchup.py` (전체 재작성)
- Test: `tests/test_run_daily_report_analysis_catchup.py` (신규 — 기존 테스트 없음)

**Interfaces:**
- Consumes: `scripts.run_analysis_pipeline.get_adaptive_analysis_limit(workspace_id: str) -> int`, `scripts.run_analysis_pipeline.get_workspace_id() -> str`, `scripts.run_analysis_pipeline.run_analysis_pipeline(workspace_id: str, *, limit: int, document_version_ids: list[str] | None = None) -> list[str] | None`, `scripts.run_analysis_pipeline.select_analysis_candidates(workspace_id: str, *, limit: int) -> list[str]`, `src.analysis.daily_report_batch.save_analysis_batch(*, workspace_id: str, report_date: date, document_version_ids: Sequence[str], started_at: datetime) -> None`, `src.analysis.daily_report_batch.mark_analysis_batch_completed(*, workspace_id: str, report_date: date, completed_at: datetime) -> None`, `src.analysis.repository.get_ranked_results_for_report(*, workspace_id: str, ranking_batch_date: date, limit: int = 20, supabase=None) -> list[AnalysisResultForReport]`(`AnalysisResultForReport.document_version_id: str` 필드 보유)
- Produces: `run_daily_report_analysis_catchup(*, now: datetime | None = None, deadline: datetime | None = None, min_candidates: int = DEFAULT_MIN_CANDIDATES) -> list[str]`, `_ranking_batch_date_for(report_date: date) -> date`, `get_selected_results(workspace_id: str, report_date: date) -> list` — 이후 태스크는 없음(이 태스크가 마지막 코드 변경).

- [ ] **Step 1: 브랜치 준비**

```bash
git fetch origin
git checkout -b fix/daily-report-catchup-min-candidates origin/develop
```

- [ ] **Step 2: 실패하는 테스트부터 작성**

`tests/test_run_daily_report_analysis_catchup.py` 새로 작성:

```python
from datetime import date, datetime, timezone

import pytest

from scripts.run_daily_report_analysis_catchup import (
    _ranking_batch_date_for,
    run_daily_report_analysis_catchup,
)

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"


def _result(doc_id):
    return type("Result", (), {"document_version_id": doc_id})()


@pytest.fixture
def base_mocks(monkeypatch):
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_workspace_id", lambda: WORKSPACE_ID
    )
    saved_batches = []
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.save_analysis_batch",
        lambda **kwargs: saved_batches.append(kwargs),
    )
    completed = []
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.mark_analysis_batch_completed",
        lambda **kwargs: completed.append(kwargs),
    )
    return {"saved_batches": saved_batches, "completed": completed}


def test_ranking_batch_date_is_one_day_before_report_date():
    assert _ranking_batch_date_for(date(2026, 8, 9)) == date(2026, 8, 8)


def test_skips_pipeline_when_already_enough_candidates(base_mocks, monkeypatch):
    """nightly-analysis만으로 이미 6건 이상 선정돼 있으면 LLM 호출 없이 바로 종료해야 한다
    (구조적 버그 수정 확인 — 여기 후보들은 이 스크립트가 처리한 게 아니라 이미 선정돼 있던 것들)."""
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_selected_results",
        lambda workspace_id, report_date: [_result(f"doc-{i}") for i in range(6)],
    )
    pipeline_calls = []
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.run_analysis_pipeline",
        lambda *a, **k: pipeline_calls.append((a, k)),
    )

    result = run_daily_report_analysis_catchup(
        now=datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc),  # 06:00 KST
        min_candidates=6,
    )

    assert len(result) == 6
    assert pipeline_calls == []
    assert base_mocks["saved_batches"][0]["document_version_ids"] == []  # 시작 시 "running" 마커
    assert base_mocks["saved_batches"][-1]["document_version_ids"] == [f"doc-{i}" for i in range(6)]
    assert base_mocks["completed"][-1]["workspace_id"] == WORKSPACE_ID
    assert base_mocks["completed"][-1]["report_date"] == date(2026, 8, 9)


def test_loops_until_min_candidates_reached(base_mocks, monkeypatch):
    """부족하면 매 라운드 다시 확인하면서 백로그를 이어 처리한다. 최종 결과(6건) 중 2건("a","b")은
    이 실행이 직접 처리하지 않은 것 — nightly-analysis 등 다른 소스에서 이미 선정된 걸 그대로
    포함시키는지(구조적 버그 수정) 확인한다."""
    results_by_round = [
        [_result("a"), _result("b")],
        [_result("a"), _result("b"), _result("c"), _result("d")],
        [_result(f"x{i}") for i in range(6)],
    ]
    call_count = {"n": 0}

    def fake_get_selected(workspace_id, report_date):
        idx = min(call_count["n"], len(results_by_round) - 1)
        call_count["n"] += 1
        return results_by_round[idx]

    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_selected_results", fake_get_selected
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_adaptive_analysis_limit", lambda workspace_id: 20
    )
    candidate_rounds = [["doc-1", "doc-2"], ["doc-3", "doc-4"]]
    select_calls = {"n": 0}

    def fake_select(workspace_id, limit):
        i = select_calls["n"]
        select_calls["n"] += 1
        return candidate_rounds[i] if i < len(candidate_rounds) else []

    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.select_analysis_candidates", fake_select
    )
    pipeline_calls = []
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.run_analysis_pipeline",
        lambda workspace_id, *, limit, document_version_ids: pipeline_calls.append(document_version_ids),
    )

    result = run_daily_report_analysis_catchup(
        now=datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc),
        min_candidates=6,
    )

    assert pipeline_calls == [["doc-1", "doc-2"], ["doc-3", "doc-4"]]
    assert len(result) == 6


def test_stops_when_no_more_candidates(base_mocks, monkeypatch):
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_selected_results",
        lambda workspace_id, report_date: [_result("a")],
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_adaptive_analysis_limit", lambda workspace_id: 20
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.select_analysis_candidates",
        lambda workspace_id, limit: [],
    )
    pipeline_calls = []
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.run_analysis_pipeline",
        lambda *a, **k: pipeline_calls.append(1),
    )

    result = run_daily_report_analysis_catchup(
        now=datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc),
        min_candidates=6,
    )

    assert pipeline_calls == []
    assert len(result) == 1


def test_stops_when_candidates_do_not_change(base_mocks, monkeypatch):
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_selected_results",
        lambda workspace_id, report_date: [_result("a")],
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_adaptive_analysis_limit", lambda workspace_id: 20
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.select_analysis_candidates",
        lambda workspace_id, limit: ["doc-1", "doc-2"],  # 매번 똑같은 후보 — 진행 없음
    )
    pipeline_calls = []
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.run_analysis_pipeline",
        lambda *a, **k: pipeline_calls.append(1),
    )

    run_daily_report_analysis_catchup(
        now=datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc),
        min_candidates=6,
    )

    assert pipeline_calls == [1]  # 첫 라운드만 실행, 두 번째 라운드에서 반복 감지되어 멈춤


def test_stops_at_explicit_deadline(base_mocks, monkeypatch):
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_selected_results",
        lambda workspace_id, report_date: [_result("a")],
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.select_analysis_candidates",
        lambda *a, **k: pytest.fail("마감이 지났으면 호출되면 안 됨"),
    )

    now = datetime(2026, 8, 9, 21, 30, tzinfo=timezone.utc)
    deadline = datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc)  # 이미 지난 마감
    result = run_daily_report_analysis_catchup(now=now, deadline=deadline, min_candidates=6)

    assert len(result) == 1


def test_default_deadline_is_kst_0715_of_report_date(base_mocks, monkeypatch):
    """deadline을 명시하지 않으면 report_date(KST) 07:15가 기본 마감이어야 한다."""
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_selected_results",
        lambda workspace_id, report_date: [_result("a")],
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.select_analysis_candidates",
        lambda *a, **k: pytest.fail("마감이 지났으면 호출되면 안 됨"),
    )

    # UTC 2026-08-09 22:20 = KST 2026-08-10 07:20 — 그날 기본 마감(07:15 KST)을 5분 넘김
    now = datetime(2026, 8, 9, 22, 20, tzinfo=timezone.utc)
    result = run_daily_report_analysis_catchup(now=now, min_candidates=6)

    assert len(result) == 1


def test_falls_back_gracefully_when_ranking_load_fails(base_mocks, monkeypatch):
    """get_ranked_results_for_report가 RankingLoadFailedError를 던지면(DB 조회 실패),
    무한 재시도하지 않고 그 시점까지 알고 있던 상태로 종료해야 한다."""
    from src.analysis.exceptions import RankingLoadFailedError

    call_count = {"n": 0}

    def fake_get_selected(workspace_id, report_date):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return [_result("a"), _result("b")]  # 첫 확인은 성공(2건, 부족)
        raise RankingLoadFailedError("RANKED_REPORT_RESULTS_LOAD_FAILED")  # 이후 실패

    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_selected_results", fake_get_selected
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.get_adaptive_analysis_limit", lambda workspace_id: 20
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.select_analysis_candidates",
        lambda workspace_id, limit: ["doc-1"],
    )
    monkeypatch.setattr(
        "scripts.run_daily_report_analysis_catchup.run_analysis_pipeline", lambda *a, **k: None
    )

    result = run_daily_report_analysis_catchup(
        now=datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc),
        min_candidates=6,
    )

    # 두 번째 조회(라운드 처리 후 재확인)에서 실패 -> 첫 조회 때 알고 있던 2건으로 종료
    assert len(result) == 2
```

- [ ] **Step 3: 테스트가 실패하는지 확인**

Run: `pytest tests/test_run_daily_report_analysis_catchup.py -v`
Expected: `_ranking_batch_date_for` import 자체가 없어서 전부 수집(collection) 단계에서 `ImportError`로 실패.

- [ ] **Step 4: `scripts/run_daily_report_analysis_catchup.py` 전체 재작성**

```python
"""Run the adaptive analysis batch that feeds the 07:30 KST daily report.

목표: 07:30 KST 리포트 생성 전까지 최소 min_candidates(기본 6)건의
report-ready(selected_for_report=True) 문서를 확보한다. 이미 충분하면(주로
nightly-analysis.yml이 00:00 KST부터 밤새 처리해 둔 결과만으로) LLM 호출 없이
바로 끝나고, 부족하면 07:15 KST 내부 마감까지 백로그를 이어서 처리한다.

구조적 문제와 그 수정: 예전 버전은 "이번 실행이 직접 고른 후보"만
daily_report_analysis_batches에 기록했다. generate_daily_report_scheduled.py는
그 기록에 있는 document_version_ids로만 리포트 후보를 제한하는데
(candidate_provider.get_report_candidates), 이미 랭킹까지 끝난 문서는
select_analysis_candidates의 "재개 대상" 조회에 더 이상 안 걸리므로
nightly-analysis.yml이 처리한 결과가 리포트에서 아예 누락됐다. 이제는 매
실행 끝에 daily_report_analysis_batches를 "그 시점에 실제로
selected_for_report=True인 문서 전체"로 다시 채운다 — 이 실행이 직접
처리했는지 여부와 무관하게.

날짜 변환: rank_analysis_results가 기록하는 ranking_batch_date는 UTC 캘린더
날짜다(src/analysis/ranking.py: batch_date = reference_time_utc.date()).
이 배치가 도는 KST 00:00~07:15 구간은 전부 그 전날 UTC 날짜에 속하므로,
report_date(KST)에서 하루를 빼서 조회해야 한다.

사용법:
    python scripts/run_daily_report_analysis_catchup.py
    python scripts/run_daily_report_analysis_catchup.py --min-candidates 10
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from scripts.run_analysis_pipeline import (
    get_adaptive_analysis_limit,
    get_workspace_id,
    run_analysis_pipeline,
    select_analysis_candidates,
)
from src.analysis.daily_report_batch import mark_analysis_batch_completed, save_analysis_batch
from src.analysis.exceptions import RankingLoadFailedError
from src.analysis.repository import get_ranked_results_for_report

SEOUL_TZ = timezone(timedelta(hours=9))
DEFAULT_MIN_CANDIDATES = 6
# get_ranked_results_for_report 기본 limit(20)보다 넉넉히 잡아서, 이미 선정된 게 많아도
# 배치 기록에서 누락되는 일이 없게 한다(MAX_ANALYSIS_CANDIDATES=50보다 큼).
REPORT_SELECTION_LIMIT = 200


def log(message: str) -> None:
    print(f"[run_daily_report_analysis_catchup] {message}", flush=True)


def _ranking_batch_date_for(report_date: date) -> date:
    """rank_analysis_results가 기록하는 UTC 날짜로 변환한다(모듈 docstring 참고)."""
    return report_date - timedelta(days=1)


def _default_deadline(report_date: date) -> datetime:
    """KST 07:15 — scheduled-daily-report.yml(07:30 KST)이 시작하기 전에
    concurrency group(daily-report-schedule)을 반드시 비워야 한다."""
    deadline_kst = datetime.combine(report_date, time(hour=7, minute=15), tzinfo=SEOUL_TZ)
    return deadline_kst.astimezone(timezone.utc)


def get_selected_results(workspace_id: str, report_date: date) -> list:
    """오늘(report_date, KST) 리포트에 이미 선정된(selected_for_report=True) 분석 결과 전체."""
    ranking_batch_date = _ranking_batch_date_for(report_date)
    return get_ranked_results_for_report(
        workspace_id=workspace_id,
        ranking_batch_date=ranking_batch_date,
        limit=REPORT_SELECTION_LIMIT,
    )


def _try_get_selected_results(workspace_id: str, report_date: date) -> list | None:
    """조회 자체가 실패하면(RankingLoadFailedError) None을 반환한다 — 호출부가 무한
    재시도하지 않고 그 시점까지 알고 있던 상태로 우아하게 멈출 수 있게 한다."""
    try:
        return get_selected_results(workspace_id, report_date)
    except RankingLoadFailedError:
        log("selected_for_report 조회 실패 — 그 시점까지의 상태로 종료")
        return None


def run_daily_report_analysis_catchup(
    *,
    now: datetime | None = None,
    deadline: datetime | None = None,
    min_candidates: int = DEFAULT_MIN_CANDIDATES,
) -> list[str]:
    current_time = now or datetime.now(timezone.utc)
    workspace_id = get_workspace_id()
    report_date = current_time.astimezone(SEOUL_TZ).date()
    effective_deadline = deadline or _default_deadline(report_date)

    # "시작함" 마커 — 아직 몇 건이 될지 모르니 빈 목록으로 남긴다.
    save_analysis_batch(
        workspace_id=workspace_id,
        report_date=report_date,
        document_version_ids=[],
        started_at=current_time,
    )

    previous_candidate_ids: list[str] | None = None
    last_known_selected: list = []
    while datetime.now(timezone.utc) < effective_deadline:
        selected = _try_get_selected_results(workspace_id, report_date)
        if selected is None:
            break
        last_known_selected = selected
        if len(selected) >= min_candidates:
            log(f"이미 {len(selected)}건 선정됨(목표 {min_candidates}) — 종료")
            break

        limit = get_adaptive_analysis_limit(workspace_id)
        candidate_ids = select_analysis_candidates(workspace_id, limit=limit)
        if not candidate_ids:
            log("처리할 후보 없음 — 종료")
            break
        if candidate_ids == previous_candidate_ids:
            log("직전과 동일한 후보 집합 — 진행 없음, 종료")
            break

        log(f"선정 {len(selected)}건(목표 {min_candidates}) — 후보 {len(candidate_ids)}건 추가 분석")
        run_analysis_pipeline(workspace_id, limit=limit, document_version_ids=candidate_ids)
        previous_candidate_ids = candidate_ids
    else:
        log("마감 도달 — 종료")

    final_selected = _try_get_selected_results(workspace_id, report_date)
    if final_selected is None:
        final_selected = last_known_selected
    final_ids = [result.document_version_id for result in final_selected]
    save_analysis_batch(
        workspace_id=workspace_id,
        report_date=report_date,
        document_version_ids=final_ids,
        started_at=current_time,
    )
    mark_analysis_batch_completed(
        workspace_id=workspace_id,
        report_date=report_date,
        completed_at=datetime.now(timezone.utc),
    )
    log(f"완료 — 최종 {len(final_ids)}건")
    return final_ids


def main() -> int:
    parser = argparse.ArgumentParser(description="일일 리포트용 분석 catchup — 최소 후보 수 확보")
    parser.add_argument("--min-candidates", type=int, default=DEFAULT_MIN_CANDIDATES)
    args = parser.parse_args()

    run_daily_report_analysis_catchup(min_candidates=args.min_candidates)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest tests/test_run_daily_report_analysis_catchup.py -v`
Expected: 8개 테스트 전부 PASS.

- [ ] **Step 6: 전체 스위트 회귀 확인**

Run: `pytest -q`
Expected: 기존 테스트 전부 그대로 PASS(이 스크립트를 import하는 다른 모듈이 없음 — `grep -rn "run_daily_report_analysis_catchup" src/ scripts/ tests/`로 사전 확인됨, 워크플로우 YAML에서만 호출).

- [ ] **Step 7: 커밋**

```bash
git add scripts/run_daily_report_analysis_catchup.py tests/test_run_daily_report_analysis_catchup.py
git commit -m "$(cat <<'EOF'
Feat: 일일 리포트 분석 catchup이 최소 후보 수를 확보할 때까지 이어서 처리

daily_report_analysis_batches가 이 스크립트 자신이 처리한 문서로만
채워져서, nightly-analysis.yml이 밤새 랭킹까지 끝낸 문서가 리포트
후보에서 누락되던 구조적 문제를 수정한다 — 이제 매 실행 끝에
"실제로 selected_for_report=True인 오늘자 전체"로 다시 채운다.
또한 확보된 후보가 6건 미만이면 07:15 KST 마감까지 백로그를
이어서 처리한다(이미 충분하면 LLM 호출 없이 바로 종료).
EOF
)"
```

---

### Task 2: `daily-report-analysis-catchup.yml` — 시작 시각·타임아웃 조정

**Files:**
- Modify: `.github/workflows/daily-report-analysis-catchup.yml`

**Interfaces:**
- Consumes: Task 1의 `scripts/run_daily_report_analysis_catchup.py`(호출 방식 변경 없음 — 여전히 인자 없이 실행, 기본 `--min-candidates 6` 적용됨)

- [ ] **Step 1: 워크플로우 파일 전체 교체**

```yaml
name: Daily Report Analysis Catch-up

# 21:00 UTC는 KST 06:00 — nightly-analysis.yml(00:00 KST 시작, 최대 355분)이
# 아무리 늦어도 05:55 KST까지는 끝나므로 그 직후에 시작한다.
#
# scripts/run_daily_report_analysis_catchup.py가 07:15 KST를 내부 마감으로
# 잡고, 최소 후보 수(기본 6건, selected_for_report=True)를 못 채웠으면 그때까지
# 백로그를 이어서 처리한다. nightly-analysis.yml만으로 이미 충분하면 이
# 워크플로우는 LLM 호출 없이 바로 끝난다.
#
# scheduled-daily-report.yml과 concurrency group을 공유하므로(cancel-in-progress:
# false), 07:30 KST 리포트 생성 전에 반드시 끝나야 한다 — timeout-minutes는
# 내부 마감(06:00~07:15, 75분) + 안전마진 10분.
on:
  schedule:
    - cron: "0 21 * * *"
  workflow_dispatch: {}

concurrency:
  group: daily-report-schedule
  cancel-in-progress: false

jobs:
  catch-up:
    runs-on: ubuntu-latest
    timeout-minutes: 85
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Analyze backlog for the daily report
        run: python scripts/run_daily_report_analysis_catchup.py
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SECRET_KEY }}
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
```

- [ ] **Step 2: YAML 문법 확인**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/daily-report-analysis-catchup.yml', encoding='utf-8'))"`
Expected: 에러 없이 종료.

- [ ] **Step 3: 커밋**

```bash
git add .github/workflows/daily-report-analysis-catchup.yml
git commit -m "$(cat <<'EOF'
Feat: 일일 리포트 catchup 시작을 07:00에서 06:00 KST로 앞당김

nightly-analysis.yml 종료 직후부터 시작해 최소 후보 수 확보 루프에
쓸 시간을 늘린다. timeout-minutes도 내부 마감(07:15 KST)에 맞춰 조정.
EOF
)"
```

---

### Task 3: PR 생성 → 머지 → workflow_dispatch로 수동 확인

**Files:** 없음(git/gh 작업)

- [ ] **Step 1: 중복 확인 후 푸시**

```bash
gh pr list --state open
git push -u origin fix/daily-report-catchup-min-candidates
```

- [ ] **Step 2: PR 생성**

```bash
gh pr create --base develop --title "Fix: 일일 리포트 분석 catchup — 최소 후보 수 확보 + 배치 재구성 버그 수정" --body "$(cat <<'EOF'
## 작업내용
- run_daily_report_analysis_catchup.py가 report-ready 후보(selected_for_report=True)가 6건 미만이면 07:15 KST 마감까지 백로그를 이어서 처리
- daily_report_analysis_batches.document_version_ids를 "이 실행이 처리한 것"이 아니라 "그 시점의 selected_for_report 전체"로 재구성 — nightly-analysis.yml 결과가 리포트에서 누락되던 구조적 문제 수정
- daily-report-analysis-catchup.yml 시작을 07:00→06:00 KST, timeout 45→85분

## 변경이유
2026-08-08 리포트 섹션 부족 문제 조사 중 발견. 설계: docs/superpowers/specs/2026-08-09-daily-report-analysis-catchup-design.md

## 테스트결과
pytest tests/test_run_daily_report_analysis_catchup.py -v 8건 전체 통과, pytest -q 전체 스위트 회귀 없음

## 참고사항
nightly-analysis.yml/run_nightly_analysis.py는 변경 없음(범위 밖). 머지 후 workflow_dispatch로 한 번 수동 실행해서 실제 동작 확인 권장.

## 관련Issue
없음
EOF
)"
```

- [ ] **Step 3: 머지**

```bash
gh pr merge --squash
```

- [ ] **Step 4: workflow_dispatch로 수동 확인**

```bash
gh workflow run daily-report-analysis-catchup.yml
```

몇 분 후:

```bash
gh run list --workflow=daily-report-analysis-catchup.yml --limit 1
```

Expected: `success`. 로그에서 `[run_daily_report_analysis_catchup]` 라인들로 몇 건이 이미 선정돼 있었는지, 추가로 몇 라운드를 돌았는지 확인.

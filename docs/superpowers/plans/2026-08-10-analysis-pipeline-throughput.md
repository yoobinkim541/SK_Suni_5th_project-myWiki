# 분석 파이프라인 처리량 근본 개선 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 분류·신뢰도·중요도 3단계의 완전 순차 LLM 호출을 제한된 동시성(5)으로 바꾸고, `scheduled-data-refresh.yml`의 분석 단계에 다른 스케줄 잡과 동일한 자체 시간예산 데드라인 루프를 적용해서, 공시 분석 백로그가 구조적으로 계속 쌓이는 문제를 근본적으로 해결한다.

**Architecture:** `src/analysis/concurrency.py`에 `ThreadPoolExecutor` 기반 공용 헬퍼 하나를 만들고, 이미 모든 예외를 내부에서 삼켜 실패 상태 결과 객체를 반환하는(절대 위로 던지지 않는) 분류·신뢰도·중요도 3개 배치 함수의 리스트 컴프리헨션을 그 헬퍼로 교체한다. `scripts/refresh_data_scheduled.py`는 `run_analysis_pipeline()`을 한 번만 호출하던 것을, 이미 있는 `get_analysis_backlog_count()`로 매 회차 백로그를 확인하며 자체 시간예산(55분 job timeout 대비 50분) 안에서 반복 호출하도록 바꾼다.

**Tech Stack:** Python 3, `concurrent.futures.ThreadPoolExecutor`, pytest.

## Global Constraints

- 동시 실행 개수(스레드풀 크기)는 **5**(보수적 시작값, 사용자 확정) — OpenRouter 레이트리밋이 코드에 문서화돼 있지 않아 낮게 시작.
- 별도 비용 상한 로직은 넣지 않는다(사용자 확인 — 동시 5건은 총 호출 수·비용을 늘리지 않고 시간적으로만 압축).
- `SELF_BUDGET_MINUTES = 50`(`scheduled-data-refresh.yml`의 job timeout 55분 대비 5분 여유, 사용자 확정).
- 공시 17건(현재는 14건으로 확인됨) 백로그 우선 처리는 이 계획의 범위 밖 — 별도 원샷으로 처리(이미 처리 중, 이 계획과 독립).
- 산업 이슈 대상 공시 유형(DART `pblntf_ty`) 필터 기준 결정도 범위 밖.
- 분류·신뢰도·중요도 단건 함수(`classify_document_version`/`evaluate_and_save_reliability`/`evaluate_and_save_importance`)는 이미 모든 예외를 내부에서 잡아 실패 상태의 `Stored*Result`를 반환하고 절대 위로 던지지 않는다(각 함수 마지막의 `except Exception as exc: ... return _runtime_failure_result(...)` 블록으로 보장 — `src/analysis/interface.py:219-221`, `src/analysis/reliability.py:147-149`, `src/analysis/importance.py:244-246`). 새로 만드는 동시성 헬퍼는 이 계약에 의존하며 별도 예외 처리를 추가하지 않는다.
- 참고 스펙: `docs/superpowers/specs/2026-08-10-analysis-pipeline-throughput-design.md`

---

### Task 1: 공용 동시성 헬퍼

**Files:**
- Create: `src/analysis/concurrency.py`
- Test: `tests/test_analysis_concurrency.py`

**Interfaces:**
- Produces: `run_concurrently(items: list[T], fn: Callable[[T], R], *, max_workers: int = MAX_WORKERS) -> list[R]`, `MAX_WORKERS = 5` — Task 2가 이 함수와 상수를 그대로 import해서 쓴다.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_analysis_concurrency.py`:
```python
from __future__ import annotations

import threading
import time

from src.analysis.concurrency import MAX_WORKERS, run_concurrently


def test_run_concurrently_returns_empty_list_for_empty_input():
    assert run_concurrently([], lambda x: x) == []


def test_run_concurrently_preserves_input_order_even_when_later_items_finish_first():
    def fn(item: int) -> int:
        # 짝수는 일부러 오래 걸리게 해서, 먼저 끝나는 홀수 항목이 있어도
        # 반환 순서가 입력 순서를 그대로 따르는지 확인한다.
        if item % 2 == 0:
            time.sleep(0.05)
        return item

    result = run_concurrently([0, 1, 2, 3, 4], fn)
    assert result == [0, 1, 2, 3, 4]


def test_run_concurrently_runs_items_in_parallel_not_sequentially():
    barrier = threading.Barrier(MAX_WORKERS, timeout=2)

    def fn(item: int) -> int:
        barrier.wait()  # 전부 동시에 여기 도달해야 통과 — 순차 실행이면 타임아웃으로 실패
        return item

    result = run_concurrently(list(range(MAX_WORKERS)), fn)
    assert sorted(result) == list(range(MAX_WORKERS))


def test_run_concurrently_respects_max_workers_override():
    assert run_concurrently([1, 2, 3], lambda x: x * 2, max_workers=2) == [2, 4, 6]
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `pytest tests/test_analysis_concurrency.py -v`
Expected: FAIL(`ModuleNotFoundError: No module named 'src.analysis.concurrency'`).

- [ ] **Step 3: 구현**

`src/analysis/concurrency.py`:
```python
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, TypeVar

T = TypeVar("T")
R = TypeVar("R")

MAX_WORKERS = 5


def run_concurrently(items: list[T], fn: Callable[[T], R], *, max_workers: int = MAX_WORKERS) -> list[R]:
    """items를 fn에 최대 max_workers개씩 동시 실행하고, 입력과 같은 순서로 결과를 반환한다.

    fn은 예외를 던지지 않고 항상 결과 객체를 반환해야 한다 — 분류/신뢰도/중요도
    단건 함수는 이미 모든 예외를 내부에서 잡아 실패 상태의 결과를 반환하는 계약이
    있으므로, 이 헬퍼는 그 계약에 의존하며 별도 예외 처리를 하지 않는다.
    """
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(fn, items))
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `pytest tests/test_analysis_concurrency.py -v`
Expected: 4개 전부 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/analysis/concurrency.py tests/test_analysis_concurrency.py
git commit -m "Feat: 분석 파이프라인용 공용 동시성 헬퍼 추가"
```

---

### Task 2: 3개 배치 함수에 동시성 배선

**Files:**
- Modify: `src/analysis/interface.py:225-238` (`classify_document_versions`)
- Modify: `src/analysis/reliability.py:152-160` (`evaluate_and_save_reliabilities`)
- Modify: `src/analysis/importance.py:249-256` (`evaluate_and_save_importances`)
- Test: `tests/test_analysis_classifier.py`, `tests/test_analysis_reliability.py`, `tests/test_analysis_importance.py`

**Interfaces:**
- Consumes: Task 1의 `run_concurrently()`/`MAX_WORKERS`(`src/analysis/concurrency.py`).
- Produces: 세 함수의 시그니처·반환 타입(`list[StoredClassificationResult]`/`list[StoredReliabilityResult]`/`list[StoredImportanceResult]`)은 변경 없음 — 순서 보장 계약도 그대로 유지되므로 이 세 함수를 호출하는 기존 코드(`scripts/run_analysis_pipeline.py`, `scripts/run_nightly_analysis.py`)는 수정 불필요.

이 저장소에는 현재 세 배치 함수(`classify_document_versions`/`evaluate_and_save_reliabilities`/`evaluate_and_save_importances`) 자체를 직접 호출하는 테스트가 없다(grep으로 확인 완료 — `scripts/run_analysis_pipeline.py`/`run_nightly_analysis.py`의 테스트들은 이 함수들을 monkeypatch로 대체해서 호출 자체를 검증하지 않는다). 그래서 순서 회귀를 걱정할 기존 테스트는 없고, 이 태스크에서 새로 테스트를 추가한다.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_analysis_classifier.py` 파일 끝에 추가(파일 상단에 `from src.analysis.interface import classify_document_versions`가 이미 있는지 확인하고 없으면 추가):
```python
def test_classify_document_versions_preserves_order_and_runs_concurrently(monkeypatch):
    import time

    call_order: list[str] = []

    def fake_classify(*, workspace_id, document_version_id, force=False):
        if document_version_id == "doc-slow":
            time.sleep(0.05)
        call_order.append(document_version_id)
        return document_version_id  # 실제 StoredClassificationResult 대신 id를 그대로 반환해 순서만 확인

    monkeypatch.setattr("src.analysis.interface.classify_document_version", fake_classify)

    results = classify_document_versions(
        workspace_id="ws-1",
        document_version_ids=["doc-slow", "doc-fast-1", "doc-fast-2"],
    )

    assert results == ["doc-slow", "doc-fast-1", "doc-fast-2"]
    assert set(call_order) == {"doc-slow", "doc-fast-1", "doc-fast-2"}
```

`tests/test_analysis_reliability.py` 파일 끝에 추가:
```python
def test_evaluate_and_save_reliabilities_preserves_order(monkeypatch):
    def fake_evaluate(*, workspace_id, document_version_id, force=False):
        return document_version_id

    monkeypatch.setattr("src.analysis.reliability.evaluate_and_save_reliability", fake_evaluate)

    results = evaluate_and_save_reliabilities(
        workspace_id="ws-1",
        document_version_ids=["doc-1", "doc-2", "doc-3"],
    )

    assert results == ["doc-1", "doc-2", "doc-3"]
```
(`evaluate_and_save_reliabilities`가 파일 상단에 이미 import돼 있는지 확인하고 없으면 추가.)

`tests/test_analysis_importance.py` 파일 끝에 추가:
```python
def test_evaluate_and_save_importances_preserves_order(monkeypatch):
    def fake_evaluate(*, workspace_id, document_version_id, force=False):
        return document_version_id

    monkeypatch.setattr("src.analysis.importance.evaluate_and_save_importance", fake_evaluate)

    results = evaluate_and_save_importances(
        workspace_id="ws-1",
        document_version_ids=["doc-1", "doc-2", "doc-3"],
    )

    assert results == ["doc-1", "doc-2", "doc-3"]
```
(`evaluate_and_save_importances`가 파일 상단에 이미 import돼 있는지 확인하고 없으면 추가.)

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `pytest tests/test_analysis_classifier.py::test_classify_document_versions_preserves_order_and_runs_concurrently tests/test_analysis_reliability.py::test_evaluate_and_save_reliabilities_preserves_order tests/test_analysis_importance.py::test_evaluate_and_save_importances_preserves_order -v`
Expected: 세 테스트 모두 지금은 PASS할 수도 있다(리스트 컴프리헨션도 순서를 보존하므로) — 이 단계에서 확인할 건 "지금 코드로도 순서는 맞다"는 것. 다음 스텝에서 구현을 동시성으로 바꾼 뒤 다시 돌려서 여전히 통과하는지 확인하는 게 진짜 회귀 테스트다. 혹시 fake 함수 몽키패치 경로가 틀려서 `AttributeError`가 나면 그건 실패로 취급하고 경로를 바로잡는다.

- [ ] **Step 3: 구현 — `classify_document_versions`**

`src/analysis/interface.py` 상단 import에 추가:
```python
from .concurrency import run_concurrently
```
225-238행을 아래로 교체:
```python
def classify_document_versions(
    *,
    workspace_id: str,
    document_version_ids: list[str],
    force: bool = False,
) -> list[StoredClassificationResult]:
    return run_concurrently(
        document_version_ids,
        lambda document_version_id: classify_document_version(
            workspace_id=workspace_id,
            document_version_id=document_version_id,
            force=force,
        ),
    )
```

- [ ] **Step 4: 구현 — `evaluate_and_save_reliabilities`**

`src/analysis/reliability.py` 상단 import에 추가:
```python
from .concurrency import run_concurrently
```
152-160행을 아래로 교체:
```python
def evaluate_and_save_reliabilities(*, workspace_id: str, document_version_ids: list[str], force: bool = False) -> list[StoredReliabilityResult]:
    return run_concurrently(
        document_version_ids,
        lambda document_version_id: evaluate_and_save_reliability(
            workspace_id=workspace_id,
            document_version_id=document_version_id,
            force=force,
        ),
    )
```

- [ ] **Step 5: 구현 — `evaluate_and_save_importances`**

`src/analysis/importance.py` 상단 import에 추가:
```python
from .concurrency import run_concurrently
```
249-256행을 아래로 교체:
```python
def evaluate_and_save_importances(*, workspace_id: str, document_version_ids: list[str], force: bool = False) -> list[StoredImportanceResult]:
    return run_concurrently(
        document_version_ids,
        lambda document_version_id: evaluate_and_save_importance(
            workspace_id=workspace_id,
            document_version_id=document_version_id,
            force=force,
        ),
    )
```

- [ ] **Step 6: 테스트 실행 — 통과 확인**

Run: `pytest tests/test_analysis_classifier.py tests/test_analysis_reliability.py tests/test_analysis_importance.py -v`
Expected: 전체 PASS(기존 테스트 포함, 회귀 없음).

- [ ] **Step 7: Commit**

```bash
git add src/analysis/interface.py src/analysis/reliability.py src/analysis/importance.py tests/test_analysis_classifier.py tests/test_analysis_reliability.py tests/test_analysis_importance.py
git commit -m "Feat: 분류/신뢰도/중요도 배치 처리에 제한된 동시성 적용"
```

---

### Task 3: `scheduled-data-refresh` 데드라인 루프

**Files:**
- Modify: `scripts/refresh_data_scheduled.py`
- Test: `tests/test_refresh_data_scheduled.py`

**Interfaces:**
- Consumes: `scripts/run_analysis_pipeline.py`의 기존 `get_analysis_backlog_count(workspace_id) -> int`, `get_adaptive_analysis_limit(workspace_id) -> int`, `run_analysis_pipeline(workspace_id, limit) -> list[str] | None`(전부 기존 함수, 변경 없음).
- Produces: `run_scheduled_refresh()`의 시그니처가 `run_scheduled_refresh(*, now: datetime | None = None, clock: Callable[[], datetime] | None = None) -> bool`로 바뀐다(`clock` 파라미터 추가, 기본값은 실제 벽시계라 기존 호출부는 그대로 동작). `if __name__ == "__main__":` 블록(88-89행)은 `run_scheduled_refresh()`를 인자 없이 호출하므로 수정 불필요.

`run_analysis_pipeline()`의 반환값(`None`)은 "더 처리할 후보가 없음"과 "일부 후보가 어느 단계에서든 실패함"(`scripts/run_analysis_pipeline.py:233-240`) 둘 다에서 나오므로 루프 종료 신호로 쓸 수 없다 — 대신 이미 있는 `get_analysis_backlog_count(workspace_id)`(분류/신뢰도/중요도/랭킹 각 단계 대기 문서 수를 합쳐 세는 함수)를 매 회차 시작 전에 직접 호출해서 0인지로 판단한다.

**시계 주입 필요 — `now` 파라미터를 데드라인 기준으로 재사용하면 안 된다.** `run_scheduled_refresh(*, now: datetime | None = None)`의 `now`는 게이트 판정(`is_refresh_due`/`is_within_nightly_analysis_window`, 둘 다 시각의 "요일 내 시간대"나 "상대 경과 시간"만 본다)을 결정적으로 테스트하기 위한 것이라, 기존 테스트들은 전부 `2026-08-06` 같은 고정된 과거 날짜를 넘긴다. 이 고정 날짜를 데드라인 계산(`current_time + timedelta(minutes=SELF_BUDGET_MINUTES)`)에 그대로 쓰면, 데드라인 루프의 실시간 체크(`실제 현재 시각 < deadline`)가 항상 "이미 지난 데드라인"으로 판정돼버려 분석이 단 한 번도 안 돌게 된다(실제 벽시계 시각이 테스트 작성 시점보다 며칠이라도 지나면 바로 이 문제가 터진다).

그래서 `run_scheduled_refresh()`에 `clock: Callable[[], datetime] | None = None` 파라미터를 새로 추가한다(`generate_wiki_drafts_for_sections()`가 이미 쓰는 것과 같은 패턴, `src/wiki/generation.py`). `now`는 게이트 판정에만 계속 쓰고, 데드라인 계산·루프의 실시간 체크는 전부 이 `clock`(기본값 `lambda: datetime.now(timezone.utc)`)으로만 한다 — 서로 다른 두 "시각" 개념을 완전히 분리해서, 게이트 테스트용 고정 날짜가 데드라인 로직에 영향을 주지 않게 한다.

- [ ] **Step 1: 기존 테스트 중 이번 변경으로 깨지는 것 확인**

`tests/test_refresh_data_scheduled.py:138-174`의 `test_run_scheduled_refresh_leaves_daily_report_for_08_kst_schedule`가 분석 단계를 정확히 한 번만 호출하는 것으로 가정하고 있다(`steps == [..., ("analysis", (WORKSPACE_ID, 20)), ...]`, 단일 항목). 이 테스트는 `clock`을 주입하지 않는다(기본값인 실제 벽시계를 그대로 쓴다 — 빠르게 끝나는 테스트라 데드라인에 걸릴 일이 없다). 대신 `get_analysis_backlog_count`를 첫 호출엔 5, 두 번째 호출엔 0을 반환하는 순차 mock으로 바꿔서 "분석 1회 실행 후 백로그 소진으로 루프 종료"를 검증하도록 아래로 교체한다:
```python
def test_run_scheduled_refresh_leaves_daily_report_for_08_kst_schedule(monkeypatch):
    steps: list[tuple[str, object]] = []
    now = datetime(2026, 8, 6, 0, 30, tzinfo=timezone.utc)

    monkeypatch.setattr("scripts.refresh_data_scheduled.get_workspace_id", lambda: WORKSPACE_ID)
    monkeypatch.setattr(
        "scripts.refresh_data_scheduled.get_workspace_settings",
        lambda workspace_id: SimpleNamespace(last_data_refresh_at=None, data_refresh_cycle_minutes=120),
    )
    monkeypatch.setattr(
        "scripts.refresh_data_scheduled.run_collect",
        lambda workspace_id, limit, source_id: steps.append(("collect", str(workspace_id))) or {"collected": 1},
    )
    monkeypatch.setattr(
        "scripts.refresh_data_scheduled.run_preprocess",
        lambda workspace_id: steps.append(("preprocess", str(workspace_id))) or {"processed": 1},
    )
    monkeypatch.setattr(
        "scripts.refresh_data_scheduled.get_adaptive_analysis_limit",
        lambda workspace_id: 20,
    )
    backlog_counts = iter([5, 0])  # 1회차 시작 전엔 백로그 있음, 1회 처리 후엔 소진
    monkeypatch.setattr(
        "scripts.refresh_data_scheduled.get_analysis_backlog_count",
        lambda workspace_id: next(backlog_counts),
    )
    monkeypatch.setattr(
        "scripts.refresh_data_scheduled.run_analysis_pipeline",
        lambda workspace_id, limit: steps.append(("analysis", (str(workspace_id), limit))) or ["doc-1"],
    )
    monkeypatch.setattr(
        "scripts.refresh_data_scheduled.mark_data_refreshed",
        lambda workspace_id, at: steps.append(("mark", at.isoformat())),
    )

    assert run_scheduled_refresh(now=now) is True
    assert steps == [
        ("collect", WORKSPACE_ID),
        ("preprocess", WORKSPACE_ID),
        ("analysis", (WORKSPACE_ID, 20)),
        ("mark", now.isoformat()),
    ]
```

같은 파일에 새 테스트 2개를 추가한다(`test_run_scheduled_refresh_skips_analysis_during_catchup_window` 함수 다음, `test_run_analysis_pipeline_returns_none_when_a_stage_fails` 앞):
```python
def test_run_scheduled_refresh_loops_analysis_until_backlog_drained(monkeypatch):
    """백로그가 여러 회차에 걸쳐 있으면, 소진될 때까지 run_analysis_pipeline을 반복 호출한다."""
    steps: list[tuple[str, object]] = []
    now = datetime(2026, 8, 6, 0, 30, tzinfo=timezone.utc)

    monkeypatch.setattr("scripts.refresh_data_scheduled.get_workspace_id", lambda: WORKSPACE_ID)
    monkeypatch.setattr(
        "scripts.refresh_data_scheduled.get_workspace_settings",
        lambda workspace_id: SimpleNamespace(last_data_refresh_at=None, data_refresh_cycle_minutes=120),
    )
    monkeypatch.setattr("scripts.refresh_data_scheduled.run_collect", lambda workspace_id, limit, source_id: {"collected": 1})
    monkeypatch.setattr("scripts.refresh_data_scheduled.run_preprocess", lambda workspace_id: {"processed": 1})
    monkeypatch.setattr("scripts.refresh_data_scheduled.get_adaptive_analysis_limit", lambda workspace_id: 20)
    # 3회차 시작 전 백로그: 40 -> 20 -> 0(소진, 루프 종료)
    backlog_counts = iter([40, 20, 0])
    monkeypatch.setattr(
        "scripts.refresh_data_scheduled.get_analysis_backlog_count",
        lambda workspace_id: next(backlog_counts),
    )
    monkeypatch.setattr(
        "scripts.refresh_data_scheduled.run_analysis_pipeline",
        lambda workspace_id, limit: steps.append("analysis") or ["doc-1"],
    )
    monkeypatch.setattr("scripts.refresh_data_scheduled.mark_data_refreshed", lambda workspace_id, at: None)

    assert run_scheduled_refresh(now=now) is True
    assert steps == ["analysis", "analysis"]  # 백로그가 40->20일 때 2번 호출, 0이 되자 3번째는 안 함


def test_run_scheduled_refresh_stops_at_deadline_even_with_backlog_remaining(monkeypatch):
    """clock을 주입해서, 데드라인 계산 직후 첫 루프 조건 체크 시점에 이미 데드라인을
    넘긴 상태를 강제로 재현한다 — 실제 벽시계나 now 파라미터에 기대지 않는 결정적 테스트.
    백로그가 남아있어도(999건) run_analysis_pipeline을 한 번도 호출하지 않고 멈춰야 한다."""
    steps: list[tuple[str, object]] = []
    now = datetime(2026, 8, 6, 0, 30, tzinfo=timezone.utc)
    # 1번째 호출: deadline 계산에 쓰임(2026-01-01 00:00 + 50분 = 00:50).
    # 2번째 호출: while 조건의 실시간 체크(2026-01-01 01:00) — 이미 00:50을 넘겼다.
    clock_calls = iter([
        datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
    ])
    fake_clock = lambda: next(clock_calls)

    monkeypatch.setattr("scripts.refresh_data_scheduled.get_workspace_id", lambda: WORKSPACE_ID)
    monkeypatch.setattr(
        "scripts.refresh_data_scheduled.get_workspace_settings",
        lambda workspace_id: SimpleNamespace(last_data_refresh_at=None, data_refresh_cycle_minutes=120),
    )
    monkeypatch.setattr("scripts.refresh_data_scheduled.run_collect", lambda workspace_id, limit, source_id: {"collected": 1})
    monkeypatch.setattr("scripts.refresh_data_scheduled.run_preprocess", lambda workspace_id: {"processed": 1})
    monkeypatch.setattr("scripts.refresh_data_scheduled.get_adaptive_analysis_limit", lambda workspace_id: 20)
    monkeypatch.setattr("scripts.refresh_data_scheduled.get_analysis_backlog_count", lambda workspace_id: 999)  # 백로그가 남아있어도
    monkeypatch.setattr(
        "scripts.refresh_data_scheduled.run_analysis_pipeline",
        lambda workspace_id, limit: steps.append("analysis") or ["doc-1"],
    )
    monkeypatch.setattr("scripts.refresh_data_scheduled.mark_data_refreshed", lambda workspace_id, at: None)

    assert run_scheduled_refresh(now=now, clock=fake_clock) is True
    assert steps == []  # 데드라인이 이미 지났으므로 analysis가 한 번도 호출되지 않는다
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `pytest tests/test_refresh_data_scheduled.py -v`
Expected: 방금 고친 기존 테스트와 새로 추가한 2개 테스트가 FAIL(`AttributeError: <module> does not have the attribute 'get_analysis_backlog_count'` 또는 `steps` 불일치) — 아직 구현을 안 바꿨으므로.

- [ ] **Step 3: 구현**

`scripts/refresh_data_scheduled.py`의 import부(3-6행)에 `Callable` 추가:
```python
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Callable
from uuid import UUID
```

14행(`from scripts.run_analysis_pipeline import get_adaptive_analysis_limit, run_analysis_pipeline`)을 아래로 교체:
```python
from scripts.run_analysis_pipeline import get_adaptive_analysis_limit, get_analysis_backlog_count, run_analysis_pipeline
```

`GRACE_MINUTES = 15`(20행) 다음에 추가:
```python
SELF_BUDGET_MINUTES = 50
"""job timeout(scheduled-data-refresh.yml, 55분) 대비 5분 여유를 둔 자체 시간 예산.
refresh_wiki_scheduled.py/run_nightly_analysis.py와 같은 self-budget 패턴 — collect()가
이미 20-24분을 쓰므로(워크플로 주석 참고), 분석 단계가 나머지 시간을 데드라인까지
반복 소비하다가 하드 타임아웃으로 배치 중간에 잘리는 대신 스스로 멈춘다.

now 파라미터(게이트 판정용, 고정된 과거 날짜로 테스트하는 경우가 많음)와는 별개로,
데드라인 계산·체크는 항상 run_scheduled_refresh()의 clock 파라미터(기본값: 실제 벽시계)만
쓴다 — 두 "시각" 개념이 섞이면 게이트 테스트용 고정 날짜가 데드라인을 항상 "이미 지남"으로
오판하게 만든다."""
```

`run_scheduled_refresh()`(55-85행)의 함수 시그니처 한 줄(55행)만 아래로 교체:
```python
def run_scheduled_refresh(*, now: datetime | None = None, clock: Callable[[], datetime] | None = None) -> bool:
```

56-57행(`workspace_id = get_workspace_id()` / `settings = get_workspace_settings(workspace_id)`)은 그대로 두고, 그 바로 다음 줄(기존의 빈 줄 58행 앞)에 한 줄만 추가한다:
```python
    get_current_time = clock or (lambda: datetime.now(timezone.utc))
```

59행의 `current_time = now or datetime.now(timezone.utc)`을 포함해 함수의 나머지 본문(60-74행, 82-85행)은 아래에서 지정하는 부분(75-81행) 외엔 그대로 둔다.

75-81행(`if is_within_nightly_analysis_window(...): ... else: ... run_analysis_pipeline(...)`)을 아래로 교체:
```python
    if is_within_nightly_analysis_window(current_time):
        log("analysis skipped during nightly analysis window (00:00-07:15 KST)")
    else:
        deadline = get_current_time() + timedelta(minutes=SELF_BUDGET_MINUTES)
        while get_analysis_backlog_count(workspace_id) > 0 and get_current_time() < deadline:
            analysis_limit = get_adaptive_analysis_limit(workspace_id)
            log(f"analysis pipeline started (limit={analysis_limit})")
            run_analysis_pipeline(workspace_id, limit=analysis_limit)
```

(`run_analysis_pipeline(...)`의 반환값을 더 이상 `is None` 체크에 쓰지 않는다 — 위에서 설명한 대로 그 반환값은 루프 종료 신호로 신뢰할 수 없다. 대신 각 회차 시작 전 `get_analysis_backlog_count()`로 직접 확인한다. 데드라인 계산·체크는 `now`가 아니라 `get_current_time()`으로만 한다 — `current_time`은 게이트 판정에만 쓴다.)

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `pytest tests/test_refresh_data_scheduled.py -v`
Expected: 전체 PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/refresh_data_scheduled.py tests/test_refresh_data_scheduled.py
git commit -m "Feat: scheduled-data-refresh 분석 단계에 자체 시간예산 데드라인 루프 적용"
```

---

## Self-Review 결과

- **스펙 커버리지**: 목표 1(동시성)·목표 2(데드라인 루프) 둘 다 Task 1-3에 대응됨. 범위 밖 항목(17건 백로그, 공시 유형 필터)은 계획에 넣지 않음 — 확인 완료.
- **플레이스홀더 스캔**: "TBD"/"적절히 처리" 류 표현 없음.
- **타입 일관성**: `run_concurrently(items: list[T], fn: Callable[[T], R], *, max_workers: int = MAX_WORKERS) -> list[R]`가 Task 1에서 정의되고 Task 2의 세 배치 함수 모두 동일 시그니처로 호출 — 일치 확인. `run_scheduled_refresh()`는 Task 3에서 `clock: Callable[[], datetime] | None = None` 파라미터가 추가되지만 하위 호환(기본값이 실제 벽시계)이라 `if __name__ == "__main__":` 호출부는 무수정 — 일치 확인.

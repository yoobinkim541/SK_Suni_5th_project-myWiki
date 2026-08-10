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

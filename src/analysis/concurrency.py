from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, TypeVar

T = TypeVar("T")
R = TypeVar("R")

MAX_WORKERS = 12  # PR #270 도입 초기값(5)에서 상향 — OpenRouter 429/레이트리밋 신호 없이
# 8/11 야간분석 배치가 순조롭게 처리된 것을 보고 운영하며 올리기로 한 원래 계획대로 조정.
# 여전히 429 백오프는 없으므로(design doc 참고) 만약 레이트리밋이 걸리면 이 값을 낮춘다.


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

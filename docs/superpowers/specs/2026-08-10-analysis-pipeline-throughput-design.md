# 분석 파이프라인 처리량 근본 개선 설계 (동시성 + 데드라인 루프)

## 배경

대시보드 "최근 산업 이슈" 섹션 실연동을 위해, 공시 문서가 분류 → 신뢰도 → 중요도/요약 → 랭킹 4단계를 거쳐 `core_summary`까지 도달해야 화면에 쓸 수 있다. 현재 공시 17건 기준 중요도/요약까지 완료된 건 3건뿐이고, 나머지는 각 단계에 미완료 상태로 쌓여 있다(분석 미시작 12/분류만 5/신뢰도만 3). 이건 일회성 지연이 아니라 구조적으로 계속 쌓이는 백로그다.

**얕은 원인**: `scheduled-data-refresh.yml`(30분 주기로 깨어남, job timeout 55분)의 실행 스크립트 `refresh_data_scheduled.py`가 `run_analysis_pipeline(workspace_id, limit=analysis_limit)`을 데드라인 없이 **딱 한 번만** 호출한다. 이 코드베이스의 다른 스케줄 잡 3개 — `run_nightly_analysis.py`(`DEFAULT_BUDGET_MINUTES=335`), `run_daily_report_analysis_catchup.py`(07:15 KST 데드라인), `refresh_wiki_scheduled.py`(`SELF_BUDGET_MINUTES=80`) — 는 전부 이미 "자체 시간예산 안에서 데드라인까지 반복 처리" 패턴을 쓰는데 이 잡만 없다. 실제로 55분 타임아웃에 배치 중간(분류는 끝, 신뢰도 도중)에 강제 종료된 사례가 워크플로 주석에 실측으로 남아 있다(2026-08-07, run 31135258583).

**근본 원인**: `src/analysis/interface.py`(classify)·`src/analysis/reliability.py`·`src/analysis/importance.py`의 배치 처리 함수 3개 전부 `for document_version_id in document_version_ids: ...` 형태의 완전 순차 처리다 — 문서 1건당 LLM 호출 1건씩, `asyncio`/`ThreadPoolExecutor`/배치 API 호출이 `src/analysis/`·`scripts/` 어디에도 없다(grep으로 확인). 문서 하나가 분류→신뢰도→중요도 3단계에서 LLM 호출을 3번 순차로 거친다. 반면 수집/정제 단계는 문서당 1.12초로 매우 빠르다(실측, `scripts/run_pipeline.py` 주석 — 300건에 5.6분). 그래서 수집은 하루에 수십~수백 건이 쌓이는데, 분석(3단계 순차 LLM)이 하루에 처리 가능한 양은 훨씬 적다 — 55분이든 355분이든 "문서 수 × 3번의 순차 LLM 왕복"이라는 하드캡에 묶여 있고, 355분짜리 야간 배치조차 최근 3회 중 2회가 시간을 다 쓰고 강제 종료됐다(GitHub Actions 플랫폼 하드캡이 360분이라 이 워크플로는 이미 그 한계에 붙어 있어 더 늘릴 수 없음).

코드베이스 어디에도 "의도적으로 동시성을 피했다"는 근거(레이트리밋/비용/경합 우려 코멘트 등)가 없다 — 순차 처리는 설계 의도라기보다 원래 그렇게 만들어진 것으로 보인다. 랭킹 단계는 LLM을 쓰지 않는 순수 계산이라 병목이 아니다.

## 목표

1. 분류·신뢰도·중요도 3단계의 문서별 LLM 호출을 제한된 동시성으로 병렬화해서, 같은 시간 예산 안에 처리 가능한 문서 수를 늘린다.
2. `scheduled-data-refresh.yml`의 분석 단계에 이미 다른 3개 잡이 쓰고 있는 것과 동일한 "자체 시간예산 + 데드라인까지 반복 처리" 패턴을 적용해서, 배치 중간에 하드 타임아웃으로 잘리는 대신 예산 안에서 최대한 처리하고 깔끔히 멈춘다.

**범위 밖**: 현재 쌓여있는 공시 17건의 우선 처리는 이 설계의 대상이 아니다 — 기존 파이프라인 함수를 그대로 재사용하는 별도의 짧은 원샷 스크립트로 이 설계와 무관하게 바로 처리한다. 산업 이슈에 포함/제외할 공시 유형(DART `pblntf_ty`) 필터 기준 결정도 이번 범위 밖(별도 의사결정 필요, 이 스펙은 순수 처리량 문제만 다룸).

## 아키텍처

### 1. 공용 동시성 헬퍼 (신규)

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

    fn은 예외를 던지지 않고 항상 결과 객체를 반환해야 한다(분류/신뢰도/중요도 단건 함수는
    이미 모든 예외를 내부에서 잡아 실패 상태의 Stored*Result를 반환하는 계약이 있음 —
    이 헬퍼는 그 계약에 의존하며 별도 예외 처리를 하지 않는다).
    """
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(fn, items))
```

`max_workers=5`(보수적 시작값 — OpenRouter 실제 레이트리밋이 코드에 문서화돼 있지 않아, 순차 대비 5배 처리량으로 시작해서 운영하면서 올리기로 결정). 429 응답에 대한 별도 백오프는 이번 범위에 넣지 않는다 — `create_json_completion()`이 이미 갖고 있는 `DEFAULT_MAX_RETRIES=1` + 폴백 모델 재시도가 그대로 적용되고, 5개 동시 요청은 레이트리밋을 유발할 위험이 낮다고 판단(운영하면서 실제로 걸리면 그때 백오프를 추가).

### 2. 3개 배치 함수 배선

- `src/analysis/interface.py`의 `classify_document_versions()`(현재 225-238행 리스트 컴프리헨션)를 `run_concurrently(document_version_ids, lambda doc_id: classify_document_version(workspace_id=workspace_id, document_version_id=doc_id, force=force))`로 교체.
- `src/analysis/reliability.py`의 `evaluate_and_save_reliabilities()`(현재 151-159행)를 같은 방식으로 `evaluate_and_save_reliability()` 호출에 적용.
- `src/analysis/importance.py`의 `evaluate_and_save_importances()`(현재 249-257행)를 같은 방식으로 `evaluate_and_save_importance()` 호출에 적용.

세 함수 다 반환 타입(`list[StoredClassificationResult]`/`list[StoredReliabilityResult]`/`list[StoredImportanceResult]`)과 순서 보장 계약이 그대로 유지된다 — `ThreadPoolExecutor.map()`은 입력 순서대로 결과를 반환하므로 호출부 어디도 추가로 고칠 필요가 없다.

이 세 함수는 `scheduled-data-refresh`/`nightly-analysis`/`daily-report-analysis-catchup` 세 스케줄 잡이 전부 공유해서 쓰므로, 여기 한 군데를 고치면 세 잡 전부 동시에 처리량이 늘어난다.

### 3. `scheduled-data-refresh` 데드라인 루프

`scripts/refresh_data_scheduled.py`에 `refresh_wiki_scheduled.py`와 동일한 패턴을 적용한다:

```python
SELF_BUDGET_MINUTES = 50  # job timeout 55분 대비 5분 여유
```

job 시작 시각을 기준으로 데드라인을 계산한다(`start_time + timedelta(minutes=SELF_BUDGET_MINUTES)`).

`run_analysis_pipeline()`(`scripts/run_analysis_pipeline.py:193-242`)의 반환값은 루프 종료 신호로 쓸 수 없다는 점에 주의 — 이 함수는 (a) 처리할 후보가 아예 없을 때(`candidate_ids`가 빈 리스트)와 (b) 후보를 처리했지만 그중 일부가 어느 단계에서든 실패했을 때(`_has_failed_results(...)`) 둘 다 `None`을 반환한다(193-242행). 즉 "이번 회차에 `None`이 나왔다"는 "더 처리할 게 없다"는 뜻이 아닐 수 있다 — 일부만 실패했어도 백로그는 여전히 남아있을 수 있다.

그래서 루프 종료 조건은 `run_analysis_pipeline()`의 반환값이 아니라, 이미 존재하는 `get_analysis_backlog_count(workspace_id)`(`scripts/run_analysis_pipeline.py`, 분류/신뢰도/중요도/랭킹 각 단계에서 처리 대기 중인 문서 수를 합쳐 `MAX_ANALYSIS_CANDIDATES` 상한으로 세는 함수)를 매 회차 시작 전에 직접 확인해서 판단한다:

```python
while get_analysis_backlog_count(workspace_id) > 0 and datetime.now(timezone.utc) < deadline:
    analysis_limit = get_adaptive_analysis_limit(workspace_id)
    log(f"analysis pipeline started (limit={analysis_limit})")
    run_analysis_pipeline(workspace_id, limit=analysis_limit)
```

기존 코드(77-81행)의 "analysis skipped/started" 로그 구조는 그대로 유지하고, 이 반복문이 그 자리를 대체한다. `run_nightly_analysis.py`의 `run_prioritized_stages_until_exhausted()`가 이미 쓰는 "데드라인까지 반복, 소진되면 조기 종료" 골격과 동일한 방식이다.

collect() 단계는 건드리지 않는다(이미 빠르고 문제가 없음) — 데드라인은 collect() 이후 분석 단계에만 적용된다.

### 4. 비용

동시 5건 호출은 총 호출 수·총 비용을 늘리지 않는다 — 같은 호출을 시간적으로 압축해서 5배 빠르게 끝낼 뿐이다. 별도 비용 상한 로직은 넣지 않는다(사용자 확인 완료).

## 에러 처리

- 세 단건 함수(`classify_document_version`/`evaluate_and_save_reliability`/`evaluate_and_save_importance`) 전부 이미 모든 예외(API 키 누락, 문서 없음, 워크스페이스 불일치, 마크다운 없음, OpenRouter 타임아웃/API 에러, JSON 파싱 실패, 점수 유효성, 분류 로드/저장 실패, `ValueError`, 그리고 최종 `except Exception` catch-all)를 내부에서 잡아 실패 상태의 `Stored*Result`를 반환한다 — 위로 던지지 않는다. `run_concurrently()`는 이 계약에 의존하므로 별도 예외 처리를 추가하지 않는다.
- `ThreadPoolExecutor.map()`은 제너레이터를 반환하는데, 만약(계약 위반으로) 내부 함수가 실제로 예외를 던지면 `list()`로 소비하는 시점에 그 예외가 그대로 전파된다 — 이건 기존 계약이 깨졌을 때만 발생하는 시나리오라 별도 처리를 추가하지 않고 기존 로직과 동일하게 호출부까지 전파되게 둔다(현재도 리스트 컴프리헨션이 예외를 던지면 그대로 전파되므로 동작 변화 없음).
- `run_analysis_pipeline()`은 4단계 스테이지 호출을 감싼 `try`에 `except Exception: raise`(`scripts/run_analysis_pipeline.py:231-232`)가 있어 예외를 그대로 위로 전파한다 — 지금도 단일 호출에서 이렇게 동작하므로, 데드라인 루프로 바꿔도 동일하게 예외가 `refresh_data_scheduled.py` 호출부까지 전파되게 두고 새로 잡지 않는다(동작 변화 없음).

## 테스트

- `run_concurrently()`: 빈 리스트를 주면 빈 리스트를 반환하는지, 입력 순서와 결과 순서가 일치하는지(느리게 끝나는 항목이 앞에 있어도 순서 보존), `max_workers`를 넘는 항목 수도 정상 처리되는지.
- `classify_document_versions()`/`evaluate_and_save_reliabilities()`/`evaluate_and_save_importances()`: 기존 시퀀스 기반 테스트가 동시성 도입 후에도 그대로 통과하는지(순서·개수·반환 타입 회귀 확인) — mock으로 개별 호출 순서를 검증하던 기존 테스트가 있다면 동시 실행에서도 여전히 유효한 방식으로 검증되는지 확인.
- `refresh_data_scheduled.py`의 데드라인 루프: 데드라인 전에 후보가 소진되면 루프가 조기 종료되는지, 데드라인에 도달하면 남은 후보가 있어도 루프가 멈추는지(회차 수를 세는 mock으로 확인) — `refresh_wiki_scheduled.py`/`run_nightly_analysis.py`의 기존 데드라인 루프 테스트 패턴을 그대로 따른다.

## 영향받는 파일

| 파일 | 변경 |
|---|---|
| `src/analysis/concurrency.py`(신규) | `run_concurrently()` + `MAX_WORKERS=5` |
| `src/analysis/interface.py` | `classify_document_versions()`가 `run_concurrently()` 사용하도록 배선 |
| `src/analysis/reliability.py` | `evaluate_and_save_reliabilities()`가 `run_concurrently()` 사용하도록 배선 |
| `src/analysis/importance.py` | `evaluate_and_save_importances()`가 `run_concurrently()` 사용하도록 배선 |
| `scripts/refresh_data_scheduled.py` | `SELF_BUDGET_MINUTES=50` 데드라인 루프 추가 |
| 각 모듈의 테스트 파일 | 위 테스트 항목 반영 |

프론트엔드·DB 스키마 변경 없음.

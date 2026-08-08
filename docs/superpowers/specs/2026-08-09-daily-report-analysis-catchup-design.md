# 일일 리포트 분석 catchup 개선 설계

## 배경

이환희님이 2026-08-08 리포트가 섹션 4개만 나온 문제를 조사한 결과, 리포트 생성 시점에 ranking-ready 후보가 4개뿐이었던 게 원인이었다(이후 같은 배치에서 10개까지 쌓인 것도 확인). PR #185(야간 배치 예산 335분 축소 + 단계별 마감 체크, 리포트 cron 08:00→07:30)로 강제종료·마감 초과 문제는 개선됐지만, "리포트 생성 시점에 최소 몇 개는 확보돼 있어야 한다"는 요구는 남아 있다.

이 스펙을 위해 코드를 조사하는 과정에서, 애초 논의(나이트리 배치를 22:00+04:00 KST 이중 크론으로 돌리자는 제안)보다 더 근본적인 문제를 발견했다 — 아래 "발견한 구조적 문제" 참고.

## 현재 파이프라인

1. **`nightly-analysis.yml`** — KST 00:00 시작, `run_nightly_analysis.py`, 내부 예산 335분(잡 타임아웃 355분). 오늘 발행 문서 우선 → 백로그 순으로 분류→신뢰도→중요도→랭킹 4단계를 시간이 허락하는 만큼 처리한다. `daily_report_analysis_batches`에는 기록을 남기지 않는다.
2. **`daily-report-analysis-catchup.yml`** — KST 07:00 시작(UTC 22:00), `run_daily_report_analysis_catchup.py` → `scripts/run_analysis_pipeline.py`. 건수 기반(최대 50건, 백로그 크기에 따라 적응)으로 후보를 골라 같은 4단계를 한 번 실행하고, 그 실행이 고른 문서 ID를 `daily_report_analysis_batches`(workspace_id+report_date 유니크)에 upsert한다.
3. **`scheduled-daily-report.yml`** — KST 07:30, `generate_daily_report_scheduled.py`. `daily_report_analysis_batches`에서 오늘자 완료된 행을 찾아 그 `document_version_ids`로 **정확히 제한**해서 리포트 후보를 뽑는다(`candidate_provider.py`: "Supplying document IDs pins a report to one exact analysis batch").

## 발견한 구조적 문제

2번(catchup)이 `daily_report_analysis_batches.document_version_ids`를 **"이번 실행이 직접 고른 후보"로만** 채운다. 이미 랭킹까지 끝난 문서는 `select_analysis_candidates`의 "재개 대상"(ready_for_ranking/importance/reliability) 조회에 더 이상 안 걸리므로, **1번(nightly-analysis)이 밤새 완전히 처리해 둔 문서는 catchup의 선택 대상에도, 따라서 배치 기록에도 들어가지 않는다.** 그 결과 3번(리포트 생성)은 nightly-analysis의 결과를 아예 보지 못한다 — "분석이 늦어서 후보가 빠지는" 것이 아니라 "이미 분석해놓고도 리포트가 그 결과를 못 찾는" 구조적 문제다.

## 목표

1. nightly-analysis 결과가 리포트 후보 풀에 항상 반영되게 한다.
2. 리포트 생성 시점(07:30 KST)까지 최소 6개의 ranking-ready(`selected_for_report=True`) 후보를 확보하도록, 부족하면 catchup이 추가로 분석을 이어간다.
3. `scheduled-daily-report.yml`과의 concurrency 경합으로 리포트 생성이 밀리지 않게 한다.

## 비목표

- `nightly-analysis.yml`/`run_nightly_analysis.py` 자체 변경 (원래 제안했던 22:00/04:00 KST 이중 크론은 이 설계로 불필요해짐)
- `run_analysis_pipeline.py`의 후보 스코어링 중 깨진 것으로 보이는 한글 키워드 매칭(`"sk????"` 등, 인코딩 손상 추정) 수정 — 범위 밖, 별도 팔로업으로 남김
- 리포트 셀렉션 임계값(중요도/신뢰도 40점 등) 자체 조정 — 이번 문제와 무관

## 설계

### `daily_report_analysis_batches` 재구성
`run_daily_report_analysis_catchup.py`가 (루프 종료 후) `document_version_ids`를 "이번 실행이 처리한 것"이 아니라 **`get_ranked_results_for_report(workspace_id, ranking_batch_date)`로 조회한 "오늘자 selected_for_report=True 전체"**로 채워서 `save_analysis_batch`를 호출한다. `nightly-analysis`가 별도 기록을 안 남겨도, 실제 분석 테이블(`document_analysis_results`)에는 이미 반영돼 있으므로 이 조회로 자연히 포함된다.

**날짜 변환 주의**: `rank_analysis_results`가 기록하는 `ranking_batch_date`는 UTC 캘린더 날짜다(`batch_date = reference_time_utc.date()`). KST 00:00~07:15는 전부 그 전날 UTC 날짜에 속하므로, `report_date`(KST)가 아니라 `report_date - 1일`로 조회해야 한다. 이 스펙이 다루는 시간대(KST 00:00~07:15)에서는 이 관계가 항상 성립한다.

### 최소 후보 확보 루프
```
while now < deadline(07:15 KST):
    selected = get_ranked_results_for_report(workspace_id, ranking_batch_date)
    if len(selected) >= MIN_CANDIDATES(6): break   # nightly-analysis만으로 충분하면 LLM 호출 없이 즉시 종료
    candidate_ids = select_analysis_candidates(workspace_id, limit=adaptive_limit)
    if not candidate_ids: break                     # 더 처리할 백로그 없음
    if candidate_ids == previous_candidate_ids: break  # 진행 없음(같은 후보 반복) — 무의미한 재시도 방지
    run_analysis_pipeline(workspace_id, limit=adaptive_limit, document_version_ids=candidate_ids)
    previous_candidate_ids = candidate_ids
```
루프 시작 전 `save_analysis_batch(document_version_ids=[], status="running")`로 시작을 기록하고, 루프 종료 후 최종 `selected` 전체로 다시 `save_analysis_batch` + `mark_analysis_batch_completed`를 호출한다.

### 워크플로우 변경 (`daily-report-analysis-catchup.yml`)
- cron: `0 22 * * *`(07:00 KST) → **`0 21 * * *`(06:00 KST)** — nightly-analysis가 최대로 늦어도 KST 05:55에는 끝나므로, 그 직후부터 시작해 마감(07:15)까지 최대한 여유를 준다.
- `timeout-minutes`: 45 → **85** — 내부 마감(07:15, 시작 대비 75분) + 안전마진 10분. `scheduled-daily-report.yml`과 `concurrency: group: daily-report-schedule`를 공유하므로(`cancel-in-progress: false`), catchup이 07:30 전에 확실히 끝나야 리포트 생성이 밀리지 않는다.

## 에러 처리

- `run_analysis_pipeline` 내부에서 문서 1건 실패는 기존처럼 각 stage 함수 안에서 실패로 기록되고 예외를 던지지 않는다(변경 없음) — 배치 전체가 멈추지 않는다.
- `get_ranked_results_for_report` 조회 자체가 실패하면(`RankingLoadFailedError`) 루프를 중단하고 그 시점까지의 `selected`(빈 리스트일 수 있음)로 배치를 기록한다 — 조용히 죽기보다는 있는 걸로라도 리포트가 시도되게 한다.

## 테스트

`run_daily_report_analysis_catchup.py`에 테스트가 전혀 없어(확인함) 이번에 새로 작성한다:
- 이미 6개 이상 선정돼 있으면 `run_analysis_pipeline`을 한 번도 안 부르고 즉시 배치를 기록하는지
- 부족하면 여러 라운드를 돌면서 매번 개수를 다시 확인하는지
- 후보가 소진되면(빈 리스트) 마감 전이라도 멈추는지
- 마감 시각에 도달하면 멈추는지
- 직전과 동일한 후보 집합이면(진행 없음) 멈추는지
- 최종 `document_version_ids`가 "이번 실행이 고른 것"이 아니라 "조회 시점의 selected_for_report 전체"인지(nightly-analysis가 기록한 것처럼 꾸민 fixture 포함)
- `ranking_batch_date` 계산이 `report_date - 1일`인지

## 스펙 자체 검토

- **플레이스홀더**: 없음 — 모든 섹션에 구체적 함수명/필드명/시각을 명시했다.
- **일관성**: "범위 밖"에 nightly-analysis 미변경을 명시했고, 설계 전체가 그 전제로 일관되게 작성됐다.
- **범위**: 단일 파일(`scripts/run_daily_report_analysis_catchup.py`) + 워크플로우 1개 변경으로 국한돼 있어 계획 하나로 다루기 적절하다.
- **모호성**: `MIN_CANDIDATES` 기본값(6)과 마감(07:15)을 CLI 인자로 노출할지 여부는 계획 단계에서 확정한다 — 기존 `run_nightly_analysis.py`의 `--budget-minutes` 패턴을 따라 `--min-candidates`/`--deadline-minutes` 형태로 노출하는 쪽으로 계획에서 구체화한다.

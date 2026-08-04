# 수집·분석 주기를 사용자 설정으로 — 설계 문서

날짜: 2026-08-04
작성: 김유빈 (Wiki·지식베이스 담당) + Claude Code

## 배경

Wiki 업데이트 주기는 설정 화면에서 사용자가 고른 값(`workspace_settings.wiki_update_cycle_minutes`)을
`wiki-refresh-gate.yml`이 실제로 따르는데, 그 앞단인 수집(`scheduled-collection.yml`)과
분석(`scheduled-analysis.yml`, 2026-08-04 오전 추가)은 둘 다 고정 2시간 cron이라 사용자
설정과 무관했다. 설정 화면에는 "일일 수집 시각"이라는 죽은 UI(고정 텍스트 "08:00", 백엔드
미연결)까지 남아있어 혼란을 더했다.

## 결정한 접근

- 수집·분석은 강하게 결합돼 있으므로(분석은 수집 결과가 있어야 의미가 있음) 설정값 하나
  (`data_refresh_cycle_minutes`)로 묶는다.
- 죽어있던 "일일 수집 시각"(하루 1번, 특정 시각) UI는 걷어내고, Wiki 업데이트 주기와 같은
  "주기 길이"(30분~24시간 드롭다운) 모델로 통일한다.
- `scheduled-collection.yml` + `scheduled-analysis.yml`을 `scheduled-data-refresh.yml` 하나로
  합친다 — 같은 게이트가 수집→분석 순서를 한 실행 안에서 보장하게 해서, 분석이 그 직전
  수집 결과를 놓치는 레이스를 원천 차단한다.
- 설정 저장 시 우측 하단 토스트로 성공 피드백을 준다 — 새 설정뿐 아니라 기존 Wiki 업데이트
  주기·대화 보관 기간 저장에도 동일하게 적용해서 3개 설정의 피드백을 통일한다.

## 변경 사항

### DB
`workspace_settings`에 컬럼 추가:
- `data_refresh_cycle_minutes int NOT NULL DEFAULT 120` (CHECK: 30/60/120/180/360/720/1440 —
  wiki_update_cycle_minutes 선택지에 120분(2시간)을 추가. 기본값 120은 지금 실제 수집 주기와
  정확히 일치)
- `last_data_refresh_at timestamptz`

### 백엔드
- `src/settings/models.py`: `WorkspaceSettings`에 두 필드 추가
- `src/settings/service.py`: `DATA_REFRESH_CYCLE_MINUTES_CHOICES` 상수, get/update 로직에 필드 추가
- `src/api/schemas.py`/`settings_router.py`: 필드 추가(wiki_update_cycle_minutes와 동일 패턴)
- `scripts/run_pipeline.py`: `run_collect`/`run_preprocess`는 이미 재사용 가능한 함수라 그대로 둠
- `scripts/run_analysis_pipeline.py`: 배치 본문을 `run_analysis_pipeline(workspace_id, limit)` 함수로
  추출(현재는 `main()` 안에 다 있어서 재사용이 안 됨) — CLI 진입점은 이 함수를 부르도록 변경
- `scripts/refresh_data_scheduled.py` 신규 — `refresh_wiki_scheduled.py`와 동일한 게이트 패턴:
  주기 미도달 시 스킵, 도달 시 `run_collect`+`run_preprocess`(수집) → `run_analysis_pipeline`(분석)
  순서로 실행 → `last_data_refresh_at`을 게이트 통과 시각으로 갱신
- `.github/workflows/scheduled-data-refresh.yml` 신규(30분 cron) — 기존 두 워크플로우 파일 삭제

### 프론트엔드
- `SettingsPage.jsx`: "일일 수집 시각" 죽은 행 제거 → "데이터 갱신 주기" 드롭다운(Wiki 업데이트
  주기와 동일 옵션) 추가
- `services/settingsApi.js`: `updateDataRefreshCycle` 추가
- 우측 하단 토스트 신규 스타일 추가, Wiki 업데이트 주기·데이터 갱신 주기·대화 보관 기간
  3개 저장 성공 시 전부 표시. 실패 시엔 기존과 동일하게 `console.error`만(토스트 없음)

## 검증 계획

1. 로컬 유닛 테스트(설정 서비스·게이트 로직)
2. 마이그레이션을 실제 Supabase 프로젝트에 적용
3. VM에서 `refresh_data_scheduled.py` 직접 실행 — 주기 미도달 시 스킵, 강제로 지난 시각을 넣어
   주기 도달시켰을 때 수집→분석이 순서대로 도는지 확인
4. 프론트 빌드 + 브라우저로 드롭다운 변경 → 우측 하단 토스트 표시 확인

## 스코프 밖

- 카테고리별 상한, 랭킹 로직 등 기존 파이프라인 내부 판단 기준은 이번 대상이 아니다.
- "일일 리포트 생성 시간" 등 다른 설정 항목은 건드리지 않는다.

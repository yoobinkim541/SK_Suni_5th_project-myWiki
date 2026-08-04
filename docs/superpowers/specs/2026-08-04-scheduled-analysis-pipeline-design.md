# 분석(분류/신뢰도/중요도/랭킹) 배치 자동화 — 설계 문서

날짜: 2026-08-04
작성: 김유빈 (Wiki·지식베이스 담당) + Claude Code

## 배경

wiki page_type 확장(같은 날짜, 별도 설계 문서 참고) 검증 중, 파이프라인을 실제로 돌려보다가
더 근본적인 문제를 발견했다.

`document_analysis_results`(분류·신뢰도·중요도·랭킹)에 새 행이 최근 20시간 넘게 하나도
안 생기고 있었는데, 그동안 `scheduled-collection.yml`은 2시간마다 계속 문서를 수집하고
있었다 — 미분석 문서가 15건 이상 쌓여 있었다.

원인: 분류(`scripts/classify_document.py`)/신뢰도(`evaluate_reliability.py`)/중요도
(`evaluate_importance.py`)/랭킹(`rank_analysis_results.py`) 4단계가 전부 **문서 1건씩만
받는 수동 스크립트**로만 존재했고, 이걸 도는 GitHub Actions 워크플로우가 아예 없었다.
`scheduled-collection.yml`(수집·정제)과 `wiki-refresh-gate.yml`(위키 생성)은 있는데, 그
사이의 "분석" 단계만 빠져 있었다.

즉 지금 있는 위키/리포트 후보는 전부 이 공백이 생기기 전에 누군가 수동으로 돌려놓은
분석 결과의 재활용이었고, 그 백로그가 소진되면 위키 축적이 다시 멈추는 구조였다.

## 결정한 접근

`scripts/run_pipeline.py`(수집·정제 배치)와 같은 패턴으로, 4단계를 순서대로 도는 배치
진입점(`scripts/run_analysis_pipeline.py`)과 이를 도는 워크플로우(`scheduled-analysis.yml`)를
추가한다.

각 단계는 "이 단계를 아직 안 거친 문서"만 골라서 처리한다:
- 신뢰도/중요도/랭킹은 이미 `get_documents_ready_for_reliability`/`get_documents_ready_for_importance`
  같은 조회 함수가 `src/analysis/repository.py`에 있었다(다만 어디서도 안 불리고 있었음).
- 분류는 그런 함수가 없었다 — `document_analysis_results` 행 자체가 없는 상태라
  `documents`/`document_versions`에서 직접 찾아야 해서 `get_documents_ready_for_classification`을
  새로 추가했다.
- 랭킹도 "이미 중요도까지 끝났는데 랭킹만 안 된 것"을 찾는 함수가 없어서
  `get_documents_ready_for_ranking`을 새로 추가했다.

## 변경 사항

1. `src/analysis/repository.py`: `get_documents_ready_for_classification`,
   `get_documents_ready_for_ranking` 신규 추가
2. `scripts/run_analysis_pipeline.py` 신규 — 분류→신뢰도→중요도→랭킹 순서로 실행,
   각 단계 결과를 요약 로그로 출력. `run_pipeline.py`와 마찬가지로 문서 1건 실패가
   나머지를 막지 않는다.
3. `.github/workflows/scheduled-analysis.yml` 신규 — 2시간마다(수집 30분 뒤) 실행
4. 유닛 테스트: `tests/test_analysis_repository_ready_for.py`

## 검증 계획

- 로컬 유닛 테스트
- VM에서 실제 미분석 문서로 `run_analysis_pipeline.py` 실행 — 분류→신뢰도→중요도→랭킹이
  실제로 이어지는지, 그 결과가 `wiki-refresh-gate`/리포트 후보 선정에 실제로 잡히는지 확인

## 스코프 밖

- 랭킹 단계의 `report_selection_position`/카테고리별 상한 등 기존 선정 로직 자체는 이번
  변경 대상이 아니다(PR #36에서 이미 다룸) — 이번은 순수하게 "그 로직까지 데이터가
  도달하게" 만드는 배치 자동화다.

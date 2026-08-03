# 위키 주기 갱신(2시간) 설계

> 기준일: 2026-08-03
> 담당: 김유빈 (Wiki·지식베이스)
> 대상 파일: `src/report/candidate_provider.py`(추가 함수만), `src/wiki/generation.py`, `scripts/refresh_wiki.py`

---

## 1. 목적

리포트 파이프라인(`generate_daily_report()`, 보통 일 1회)과 별개로, **2시간마다** 최근 분석 완료된 문서를 근거로 위키 이슈/주제 페이지를 갱신한다. 리포트 산출물(`reports`/`report_sections`)은 만들지 않고 위키만 최신화한다.

## 2. 핵심 원칙

- 기존 리포트 파이프라인의 candidate 선별→그룹핑→wiki_context 보강→섹션 작성 단계를 **그대로 재사용**한다. 새 로직을 만들지 않는다.
- `report/interface.py`를 포함해 report 모듈의 기존 파일은 **하나도 수정하지 않는다** — 새 함수 1개만 `candidate_provider.py`에 추가하고, 오케스트레이션은 전부 `wiki/generation.py`(이 파트 소유 파일)에 둔다.
- 리포트 파이프라인과 완전히 독립된 별도 스케줄(외부 스케줄러가 2시간마다 스크립트 호출)로 돈다 — `archive_stale_wiki_pages`와 같은 패턴.

## 3. 대상 문서 선정

기존 `get_report_candidates(workspace_id, report_date)`는 "그 날 발행된 문서 전체"를 반환해서 2시간마다 재호출하면 같은 문서가 계속 재처리된다. 대신 신규 함수:

```python
def get_recently_analyzed_candidates(
    *,
    workspace_id: str,
    since: datetime,
    supabase: Client | None = None,
) -> list[ReportCandidate]:
```

`src/report/candidate_provider.py`에 추가한다. `document_analysis_results`를 `workspace_id` + 4개 상태(`status`/`reliability_status`/`importance_status`/`ranking_status`='completed') + `importance_evaluated_at >= since`로 먼저 좁힌 뒤, 관련 `document_versions`/`documents`/`sources`를 조회해 `ReportCandidate`로 변환한다. 기존 `to_report_candidate()`/`build_report_candidates()`/`_row_is_report_candidate_ready()`를 그대로 재사용해 변환 로직 중복을 없앤다.

## 4. 오케스트레이션

`src/wiki/generation.py`에 추가:

```python
def refresh_wiki_from_recent_analysis(
    workspace_id: str,
    *,
    since_hours: int = 2,
    requested_by: str | None = None,
) -> list[WikiDraftGenerationResult]:
```

흐름 (전부 기존 함수 재사용, 리포트 저장 3종만 생략):

```
get_recently_analyzed_candidates(since=now - since_hours)
  -> select_report_candidates(...)        # ReportGenerationConfig() 기본값 사용
  -> group_report_candidates(...)
  -> enrich_issue_groups(...)
  -> compose_report_sections(...)
  -> generate_wiki_drafts_for_sections(...)   # 이미 존재, 그대로 호출
```

`save_report_sections` / `create_and_save_markdown_artifact` / `mark_report_completed` / `create_report_version`은 호출하지 않는다 — `reports`/`report_sections`에는 아무 흔적도 안 남는다.

후보가 0건이면(최근 `since_hours` 내 신규 분석 없음) 각 단계가 빈 리스트를 반환하며 자연스럽게 조기 종료한다.

## 5. 에러 처리

- 이슈 단위 실패 격리는 `generate_wiki_drafts_for_sections` 내부에 이미 있으므로 그대로 적용된다.
- candidate 조회~섹션 작성(select/group/enrich/compose) 단계 자체가 실패하면 예외를 그대로 전파해 스크립트가 non-zero exit — 리포트 파이프라인과 달리 이 흐름을 감싸는 "리포트 실패 처리" 개념이 없으므로, 외부 스케줄러가 다음 2시간 주기에 재시도하는 것으로 충분하다(단발성 배치이므로 재시도 비용이 낮음).

## 6. 스크립트

`scripts/refresh_wiki.py` — `scripts/archive_stale_wiki_pages.py`와 동일한 구조(workspace_id 자동 조회, argparse로 `--since-hours` 조정 가능, `load_dotenv()`). 로컬은 Windows 작업 스케줄러/cron으로 2시간마다 호출, 배포 시엔 EventBridge(CLAUDE.md 아키텍처와 일치)로 동일하게 연결.

## 7. 테스트

- `tests/test_report_candidate_provider.py`: `get_recently_analyzed_candidates`가 `since` 이전 분석 완료 건을 제외하는지, 4개 상태 중 하나라도 미완료면 제외하는지.
- `tests/test_wiki_generation.py`: `refresh_wiki_from_recent_analysis`가 candidate 5단계 함수를 순서대로 호출하는지(monkeypatch), 빈 candidate 목록일 때 조기 종료하는지, report 저장 3종 함수를 호출하지 않는지.

## 8. 이번 설계에 포함하지 않는 것

- `since_hours`를 넘어선 "마지막 실행 이후"의 정밀한 델타 추적(예: 별도 체크포인트 테이블) — 스케줄러가 정확히 2시간마다 도는 것을 전제로 `since_hours=2` 고정값이면 충분하다고 보고, 스케줄이 밀리는 경우의 정밀 보정은 범위 밖.
- 이 흐름 전용 실패 알림/모니터링 — 필요해지면 별도 설계.

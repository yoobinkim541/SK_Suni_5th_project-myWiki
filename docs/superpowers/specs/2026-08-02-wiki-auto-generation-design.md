# Wiki 자동 생성 설계

> 기준일: 2026-08-02
> 담당: 김유빈 (Wiki·지식베이스)
> 대상 파일: `src/wiki/generation.py`, `src/wiki/generation_prompts.py`, `src/wiki/generation_models.py`, `src/wiki/service.py`(review_wiki_version 시그니처만), `src/report/interface.py`(호출 한 줄 추가)

---

## 1. 목적

분석 파이프라인(`document_analysis_results`)과 리포트 파이프라인(`report_sections`)의 결과를 근거로, 사람 개입 없이 Wiki 문서(`wiki_pages`/`wiki_page_versions`/`wiki_page_sources`)를 생성·갱신·발행하고, 오래된 문서는 자동으로 아카이빙한다.

저장 계층(`create_wiki_version`, `upsert_wiki_page`, `record_wiki_validation`, `review_wiki_version`, `publish_wiki_version`)은 이미 구현되어 있다. 이 설계는 그 앞단 — "분석/리포트 결과를 어떤 Wiki 페이지에 어떤 내용으로 반영할지" — 를 다룬다.

## 2. 핵심 원칙

- **근거 없으면 쓰지 않는다.** LLM이 생성하는 모든 주장(claim)은 반드시 `document_version_id`를 명시해야 하고, 그 목록이 비어 있으면 해당 이슈의 주제 페이지 갱신 자체를 건너뛴다(이슈 페이지는 만들되, 주제 페이지는 갱신하지 않음).
- **기존 문단을 삭제하지 않는다.** 주제 페이지 갱신은 새 버전을 추가하는 것이며, "변경 이력" 섹션에 이번 갱신 사유를 남긴다. 기존 서술을 지우고 다시 쓰는 게 아니라 통합·보강한다.
- **검증을 통과하면 항상 자동 승인·발행한다** (2026-08-04 개정: 신뢰도 게이트 폐지 — 아래 §5 참고). `confidence_score`는 계속 기록하되 표시·분석용일 뿐, 더 이상 발행 여부를 가르지 않는다.

## 3. 트리거와 흐름 (2가지, 서로 독립)

### 3.1 생성/갱신 — `generate_daily_report()`에 연결

```
report/interface.py generate_daily_report()
  ...
  stage = "compose_sections"
  section_drafts = compose_report_sections(...)
  ...
  stage = "generate_wiki_drafts"          # <- 신규 1줄 추가
  wiki_results = generate_wiki_drafts_for_sections(
      section_drafts, workspace_id=request.workspace_id,
  )
  ...
```

- 리포트 생성이 스케줄(예: 일 1회 배치)에 맞춰 도는 한, Wiki 갱신도 같은 주기로 자동 반영된다. 별도 스케줄을 새로 만들 필요가 없다.
- `generate_wiki_drafts_for_sections()`는 **리포트 생성 자체를 실패시키지 않는다.** 이슈 단위로 try/except하고, 실패는 로그+결과 리스트에만 남긴다.

### 3.2 아카이빙 — 독립된 주기 실행

```python
def archive_stale_wiki_pages(
    workspace_id: str,
    *,
    staleness_days: int = 90,
    supabase: Client | None = None,
) -> list[str]:
    """published 상태이고 최신 버전 created_at이 staleness_days 이전인 페이지를
    archived로 전환한다. 반환값: 아카이빙된 page_id 목록."""
```

- 리포트/위키 생성 흐름과 완전히 분리된 별도 진입점. `scripts/archive_stale_wiki_pages.py`로 노출하고, 배포 시 별도 스케줄(예: 매일 1회)로 등록한다.
- 판단 기준은 "그 페이지의 **가장 최근 버전** `wiki_page_versions.created_at`"이며, 대상은 `status='published'`인 페이지만(이미 draft/archived인 건 건드리지 않음).

## 4. 페이지 단위와 계층 구조

### 4.1 이슈 페이지 (`page_type='issue'`)

- `ReportSectionDraft` 1건 = 이슈 페이지 1건.
- `slug = section.issue_key` — 결정적이므로 재실행해도 같은 페이지에 새 버전만 쌓이고 중복 생성되지 않는다.
- 본문은 LLM을 다시 부르지 않고, 이미 리포트 단계에서 만들어진 `current_summary` / `key_facts` / `implications` / `watch_points`를 고정 마크다운 템플릿으로 조립한다.
- `wiki_page_sources`는 `section.news_citations`(`document_version_id`, `evidence_text`, `citation_order`)를 그대로 매핑.

### 4.2 주제 페이지 (`page_type in {industry, company, technology, term}`)

- 후보는 두 소스에서 모은다:
  1. `section.wiki_references` — composer가 이미 유사도로 골라놓은 관련 기존 페이지(제목+본문 포함, 최대 3개)
  2. **기존 최상위 주제 페이지 전체 목록**(`parent_page_id IS NULL`인 industry/company/technology/term 페이지, 제목만) — 새 주제를 어디 밑에 둘지 판단하는 용도
- LLM 프롬프트에 위 두 후보 + 이슈의 요약/근거를 넣고, 구조화 출력으로 다음을 받는다:
  - `action`: `"update_existing"` | `"create_new"` | `"skip"`(근거 부족)
  - `update_existing`이면 `target_wiki_page_id`
  - `create_new`이면 `slug` / `title` / `page_type` / `parent_page_id`(기존 최상위 목록 중 선택, 없으면 `null`=새 최상위)
  - `markdown` — 새 버전 전체 본문(현재 상황 → 수급 구조 → 종합 판단 → 변경 이력 → 관련 문서 → 출처)
  - `change_summary` — 변경 이력에 들어갈 한 줄
  - `claims`: `[{document_version_id, claim_text, citation_order}]`
  - `confidence_score`: 0~1, 이 갱신이 근거로 얼마나 잘 뒷받침되는지 LLM 자기평가
- `claims`가 비어 있으면 주제 페이지 갱신을 하지 않는다(이슈 페이지만 생성).
- 계층은 `wiki_pages.parent_page_id`(자기참조) 트리를 그대로 쓴다. 강제 2단계가 아니라 LLM이 상황에 맞게 깊이를 정한다(예: 반도체산업 → SK하이닉스 → HBM4). 이슈 페이지의 `parent_page_id`는 이번에 연결된 주제 페이지로 설정한다.

## 5. 자동 승인/발행

> **2026-08-04 개정**: 애초 설계는 주제 페이지에 신뢰도 게이트(`confidence_score >= 0.6`)를 두고, 미달 시 사람이 `review_wiki_version()`을 수동 호출해 게시하도록 남겨뒀다. 그런데 그 수동 검토 경로(UI·엔드포인트·스크립트 어디에도)가 실제로는 한 번도 만들어지지 않아서, 게이트 미달 생성물이 영구히 `pending`에 쌓이기만 하고 아무도 게시할 수 없는 상태가 됐다. myWiki는 "사람이 쓰는 위키"가 아니라 **LLM이 전량 생성하는 위키**이므로, 검토자를 나중에 두기보다 게이트 자체를 없애고 이슈 페이지와 동일하게 검증 통과 시 항상 자동 발행하는 쪽으로 정책을 바꿨다. 아래는 개정된 정책이다.

**이슈 페이지**와 **주제 페이지** 모두, 새 버전을 만들면 검증을 거쳐 항상 자동 승인·발행한다(confidence 게이트 없음):

```
create_wiki_version(draft)                                   # generated_by='llm'
record_wiki_validation(version_id, 'passed', confidence_score)  # confidence_score는 기록만, 게이트 아님
review_wiki_version(version_id, reviewer_id=None, decision='approved')
publish_wiki_version(page_id, version_id)
```

- `review_wiki_version()`은 현재 `reviewer_id: str` 필수라 배치에서 못 쓴다. 시그니처를 `reviewer_id: str | None = None`으로만 넓힌다(하위 호환, 기존 호출부 영향 없음). `reviewed_by=NULL` + `generated_by='llm'` 조합 자체가 "자동 승인"이라는 표시가 된다 — `pipeline_jobs.requested_by=NULL`(배치)과 같은 기존 컨벤션.
- `AUTO_PUBLISH_CONFIDENCE_THRESHOLD` 상수와 게이트 분기는 폐지 시점에 함께 제거했다(더 이상 쓰이지 않음).

## 6. 모듈 구조

```
src/wiki/
├── generation.py           # 오케스트레이션: generate_wiki_drafts_for_sections, archive_stale_wiki_pages
├── generation_prompts.py   # 주제 페이지 갱신 LLM 프롬프트 (시스템 프롬프트에 "근거 없는 문장 금지" 명시)
├── generation_models.py    # WikiDraftGenerationResult, WikiTopicLLMResult 등
└── (기존 interface.py / service.py / query.py 변경 없음, review_wiki_version 시그니처만 확장)

scripts/
└── archive_stale_wiki_pages.py   # archive_stale_wiki_pages() CLI 진입점
```

- LLM 호출은 `src/analysis/classifier.py`의 `create_json_completion` / `parse_json_response` 패턴을 재사용한다(OpenRouter, JSON 강제 출력).

## 7. 에러 처리

- 이슈 단위 실패(LLM 오류, JSON 파싱 실패, `claims` 비어있음)는 해당 이슈의 위키 갱신만 건너뛰고 나머지 이슈·리포트 생성 자체에는 영향 없음.
- `archive_stale_wiki_pages()`는 조회 전용 판단 + 단순 UPDATE라 실패 시 전체 예외를 던져도 무방(배치 자체를 재시도하면 됨).

## 8. 테스트 계획

`tests/test_wiki_generation.py` 신규:
- 이슈 페이지 최초 생성 / 재실행 시 같은 페이지에 버전만 추가
- 기존 주제 페이지 매칭 → 갱신(변경 이력 포함) 확인
- 신규 주제 생성 + 부모 배치(기존 최상위 목록에서 선택 / 최상위로 신규 생성 둘 다)
- `claims` 비어있으면 주제 페이지 갱신 스킵, 이슈 페이지는 정상 생성
- `confidence_score`와 무관하게 검증 통과 시 항상 자동 발행 (2026-08-04 개정)
- 이슈 1건 LLM 실패해도 나머지 이슈는 정상 처리
- `archive_stale_wiki_pages`: 90일 경과 published만 archived로, draft/archived/최근 갱신 페이지는 그대로

LLM/Storage는 기존 analysis/report 테스트 패턴대로 fake client + monkeypatch로 대체(실제 네트워크 호출 없음).

## 9. 이번 설계에 포함하지 않는 것

- 사람이 수동으로 위키를 "편집"하는 새 UI/API — 기존 `create_wiki_version()` 직접 호출로 이미 가능하므로 범위 밖.
- 아카이빙된 페이지의 복구(un-archive) 흐름 — 필요해지면 별도 설계.
- QMD 인덱스 재색인(`request_wiki_index`) 자동 호출 — 이번 범위 밖, 필요 시 다음 단계에서 연결.

# 이슈 페이지 LLM 재작성 설계

## 배경

리포트 파이프라인이 자동 생성하는 위키 문서는 두 종류다 — 토픽 페이지와 이슈 페이지. 토픽 페이지는 `_generate_topic_page`(`src/wiki/generation.py`)가 LLM(`WIKI_TOPIC_SYSTEM_PROMPT`)으로 기존 문서와 통합하며 자유 마크다운을 새로 쓴다. 반면 이슈 페이지는 `_generate_issue_page` → `_build_issue_page_markdown`이 **LLM 호출 없이** 리포트 섹션 필드(`current_summary`, `key_facts`, `implications`, `watch_points`)를 마크다운 템플릿에 그대로 꽂아 넣기만 한다 — 문장이 아니라 리포트용 불릿 필드가 그대로 위키 문서 본문이 된다.

이번 스펙은 이슈 페이지도 토픽 페이지 수준으로 읽기 좋은 문서가 되도록 LLM 재작성 단계를 추가하는 것만 다룬다.

**범위 밖**: chat_wiki.py(챗봇 저장 위키)를 정식 생성 파이프라인 규율에 편입시키는 것 — 실시간 응답 경로와 배치 파이프라인 구조가 안 맞아 별도 스펙으로 다룬다. 임베딩 기반 검색/추천/중복정리 개선, 에이전트 검색 성능 개선, 모델 설정 통일·관측성 개선도 별도 스펙 대상이다. 토픽 페이지 생성 로직 자체의 변경도 범위 밖(이미 LLM이 관여하고 있어 이번 개선 대상이 아님).

## 목표

1. 이슈 페이지의 "현재 상황 / 핵심 사실 / 시사점 / 주시할 지점" 네 섹션이 리포트 필드를 그대로 이어붙인 문장이 아니라, LLM이 자연스럽게 다듬은 문장으로 채워진다.
2. LLM이 리포트 필드에 없는 사실·수치·인용을 새로 지어내지 않는다.
3. "## 출처" 섹션과 인용 근거(`sources`)는 이 변경과 무관하게 지금과 100% 동일하게 코드가 그대로 생성한다 — citation 안전성(예: document_version_id 노출 사고 재발)에 새 위험을 만들지 않는다.
4. LLM 호출이 실패(타임아웃/잘못된 JSON/예외)해도 이슈 페이지 생성 자체는 지금처럼 항상 성공한다 — 원본 리포트 필드 그대로 폴백.
5. 기존 위키 생성 아키텍처(OpenRouter 모델 설정, JSON 스키마 검증 패턴)를 그대로 재사용해 새 설정/모델 분기점을 만들지 않는다.

## 비목표

- 이슈 페이지에 토픽 페이지처럼 `update_existing`/`create_new`/`skip` 판단을 추가하는 것 — 이슈 페이지는 이미 `find_matching_issue_page`(비-LLM 매칭)로 기존/신규 여부가 결정되므로 이 판단은 필요 없다.
- 이슈 페이지에 신뢰도 게이트를 새로 추가하는 것 — 토픽 페이지도 2026-08-04 개정으로 검증 통과 시 신뢰도와 무관하게 항상 게시하는 정책이라(`generation.py` 주석, `record_wiki_validation`/`review_wiki_version`/`publish_wiki_version` 무조건 호출), 이슈 페이지만 별도 게이트를 두면 정책이 어긋난다.
- "## 출처" 섹션 형식이나 인용 연결 로직 변경 — 그대로 유지.
- 프롬프트 품질 튜닝/실험 — 최초 버전은 토픽 프롬프트의 "절대 규칙" 스타일을 그대로 따르는 단순 버전으로 시작.

## 아키텍처

`generation.py`에 함수 하나, `generation_prompts.py`에 프롬프트 하나를 추가한다. 새 모듈은 만들지 않는다(chat_wiki.py처럼 완전히 다른 입력 형태가 아니라 기존 `ReportSectionDraft` 필드를 그대로 다루므로 `generation.py`에 자연스럽게 붙는다).

```
generation_prompts.py
└── ISSUE_PAGE_REWRITE_SYSTEM_PROMPT / build_issue_page_rewrite_user_prompt(section, evidence_texts)

generation_models.py
└── IssuePageRewriteResult(BaseModel): current_summary: str, key_facts: list[str],
                                        implications: list[str], watch_points: list[str]

generation.py
└── _rewrite_issue_page_content(section, evidence_texts, *, llm_client=None)
      -> ReportSectionDraft  # section.model_copy(update={current_summary, key_facts, implications, watch_points})
```

`_generate_issue_page`가 진입 시(페이지 매칭/생성 분기보다 먼저) `_rewrite_issue_page_content`를 호출하고, 그 결과로 만든 필드를 이후 `_build_issue_page_markdown`에 넘긴다. `_build_issue_page_markdown`의 시그니처와 "## 출처" 조립 로직은 변경하지 않는다 — 재작성된 필드도 지금과 같은 템플릿 조립 함수를 그대로 통과한다.

`llm_client` 기본값은 `_generate_topic_page`와 동일하게 `classifier.get_openrouter_settings()` + `create_json_completion()`을 감싼 함수 — 새 모델 설정을 만들지 않고 기존 v4-flash 기본/v4-pro 폴백을 그대로 물려받는다. 테스트에서 fake client를 주입할 수 있도록 파라미터화한다(`WikiTopicLLMClient`와 같은 타입 형태 재사용).

## 프롬프트 설계

`ISSUE_PAGE_REWRITE_SYSTEM_PROMPT`는 토픽 프롬프트의 "절대 규칙" 패턴을 따르되 훨씬 좁은 역할만 맡는다:

- 입력으로 받은 현재상황/핵심사실/시사점/주시할지점과 [근거 문서] 텍스트에 없는 새로운 사실·수치·기업명·날짜를 절대 추가하지 말 것
- 네 섹션 모두 채워서 반환할 것(리포트가 이미 채워둔 필드이므로 "skip" 개념 없음 — 빈 값이 오면 호출부가 실패로 간주하고 폴백)
- `key_facts`/`implications`/`watch_points`는 원본과 같은 리스트 형태로, 각 항목은 한 문장 이내
- 출처·인용은 다루지 않는다(별도로 코드가 조립하므로 프롬프트에 언급조차 하지 않음 — 토픽 프롬프트처럼 "document_version_id를 본문에 쓰지 마라"를 명시할 필요 자체가 없음)
- 마크다운 코드블록 없이 지정된 JSON 구조로만 응답

JSON 출력 형식:
```json
{
  "current_summary": "...",
  "key_facts": ["...", "..."],
  "implications": ["...", "..."],
  "watch_points": ["...", "..."]
}
```

## 데이터 흐름

1. (변경 없음) `generate_wiki_drafts_for_sections` → `_generate_topic_page` → `_generate_issue_page(section, ..., parent_page_id=topic_page_id, evidence_texts, citation_attribution, ...)`
2. **(신규)** `_generate_issue_page` 진입 시 `_rewrite_issue_page_content(section, evidence_texts)` 호출
3. 성공 + 스키마 검증 통과 → 재작성된 4개 필드로 `_build_issue_page_markdown` 호출
4. 실패(예외/빈 값/검증 실패) → 원본 `section.current_summary`/`section.key_facts`/`section.implications`/`section.watch_points` 그대로 `_build_issue_page_markdown` 호출(현재 동작과 100% 동일)
5. (변경 없음) `_build_issue_page_sources` → `WikiDraftInput` → `create_wiki_version` → `record_wiki_validation` → `review_wiki_version` → `publish_wiki_version`

## 에러 처리

`_rewrite_issue_page_content` 내부에서 LLM 호출/검증이 실패하면(`OpenRouterApiError`, `OpenRouterTimeoutError`, `InvalidJsonResponseError`, `ValidationError`, 빈/공백 응답, 그 외 예상 밖 예외 포함 — `except Exception`으로 폭넓게 흡수) 예외를 상위로 던지지 않고 원본 필드 그대로 반환한다. 이 함수는 항상 성공해야 하는 "best-effort 다듬기" 단계이므로 예외 타입을 좁게 제한하지 않는다(로그는 `logger.exception`으로 남겨 관측성을 유지). `generate_wiki_drafts_for_sections`가 이미 토픽/이슈 단계를 각각 try/except로 감싸 단계별 실패를 격리하고 있으므로(`generation.py` 기존 구조), 이슈 페이지 쪽 실패 격리는 한 겹 더 깊어질 뿐 기존 구조를 바꾸지 않는다. LLM 호출 성공 여부와 무관하게 이슈 페이지 생성은 지금처럼 항상 성공한다.

## 테스트

- `tests/test_wiki_generation.py`(기존 파일에 추가): `_rewrite_issue_page_content` 단위 테스트
  - 정상 케이스: fake LLM client가 유효한 JSON을 반환 → 4개 필드가 재작성된 값으로 교체되는지
  - 스키마 검증 실패 케이스: LLM이 필수 필드 누락/빈 배열을 반환 → 원본 필드로 폴백하는지
  - 예외 케이스: LLM 호출 자체가 예외를 던짐(타임아웃 등) → 원본 필드로 폴백하는지
- `_build_issue_page_markdown` 관련 기존 테스트: LLM 재작성 여부와 무관하게 "## 출처" 섹션과 `sources` 구성이 동일한지 확인하는 회귀 테스트 추가(citation 안전성 확인)
- `_generate_issue_page`/`generate_wiki_drafts_for_sections` 통합 테스트: fake client 주입 시 실제로 재작성된 마크다운이 게시되는지, client가 예외를 던지는 경우에도 이슈 페이지가 정상 게시되는지

## 영향받는 파일

| 파일 | 변경 |
|---|---|
| `src/wiki/generation_prompts.py` | `ISSUE_PAGE_REWRITE_SYSTEM_PROMPT`, `build_issue_page_rewrite_user_prompt` 추가 |
| `src/wiki/generation_models.py` | `IssuePageRewriteResult` 추가 |
| `src/wiki/generation.py` | `_rewrite_issue_page_content` 신규, `_generate_issue_page`에서 호출하도록 변경 |
| `tests/test_wiki_generation.py` | 갱신 |

프론트엔드 변경 없음(문서 구조·헤더가 동일하게 유지되므로 `WikiPage.jsx`/`WikiCard.jsx` 등은 그대로 동작).

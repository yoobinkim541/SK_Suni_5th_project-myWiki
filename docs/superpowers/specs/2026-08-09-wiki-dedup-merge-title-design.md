# 위키 중복 병합 시 제목 갱신 설계

## 배경

`src/wiki/dedup.py`의 `_judge_and_merge()`는 두 위키 페이지를 LLM으로 판단해 하나로 병합한다 — 대표 페이지에 통합된 새 본문(`markdown`)을 쓰고 다른 페이지는 아카이빙한다. 그런데 병합 LLM의 출력 스키마(`WikiDedupLLMResult`)에는 제목 필드가 없어서, 저장할 때 `representative_info.title`(병합 **전** 대표 페이지의 원래 제목)을 그대로 쓴다. 본문은 두 문서를 합친 새 내용인데 페이지 제목(사이드바에 보이는 값)은 병합 전 원래 제목에 그대로 고정되는 문제가 생긴다.

이 패턴은 바로 앞서 고친 챗봇 저장 버그(PR #225, `save_message_to_wiki`가 `upsert_wiki_page`의 `ignore_duplicates=True` 때문에 기존 페이지 title을 못 바꾸던 문제)와 근본 원인이 같지만 **호출부가 다르다** — `update_wiki_page_title()` 인프라는 이미 있으므로 병합 경로에도 마저 연결한다.

라이브 DB 조사에서 실제로 이 문제로 어긋난 사례를 확인했다: 챗봇 저장 페이지 두 건("CXMT 기업을 전체적으로 분석해줘", "SK하이닉스와 중국 CXMT 경쟁 관련 최근 동향 정리해줘")이 dedup 배치로 병합돼 본문은 "CXMT 기업 종합 분석"이라는 새 제목으로 시작하는데 페이지 제목은 병합 전 원래 질문 그대로였다(PR #225에서 데이터는 이미 직접 정정함 — 이번 스펙은 코드만 고쳐 재발을 막는다).

**범위 밖**: 토픽 페이지의 `update_existing` 경로(`generation.py`)는 이번 대상이 아니다 — 토픽 페이지는 여러 이슈에 걸쳐 재사용되는 "주제"라 제목이 회차마다 안 바뀌는 게 설계 의도(`WIKI_TOPIC_SYSTEM_PROMPT`에 이미 이 정책이 명시돼 있음)이고, 실제로 새 정보가 추가돼도 같은 폭넓은 주제를 가리키므로 제목을 바꿀 이유가 없다. dedup 병합은 반대로 두 문서를 하나의 새 내용으로 합성하는 것이므로 제목도 새로 지어야 한다는 점에서 다르다.

## 목표

1. dedup 병합이 성사되면, 대표 페이지의 `wiki_pages.title`이 병합된 새 본문을 반영한 제목으로 갱신된다.
2. LLM이 병합을 결정했는데 제목을 못 만들면(빈 값 등) 병합 자체를 취소한다 — 본문은 새로 바뀌었는데 제목이 없는/부실한 상태로 발행되는 일이 없어야 한다(기존 `markdown` 빈값 검증과 동일한 안전장치).
3. 기존 병합 로직(대표 선정, claims 검증, 아카이빙, 재부모지정)은 그대로 둔다 — 제목 처리만 추가한다.

## 아키텍처

`WikiDedupLLMResult`(`dedup_models.py`)에 `title: str | None = None` 필드를 추가한다(`markdown`/`change_summary`와 같은 패턴 — 병합이 아니면 없어도 되므로 옵셔널, 병합일 때만 `_judge_and_merge`가 명시적으로 빈 값을 검증). `WIKI_DEDUP_SYSTEM_PROMPT`(`dedup_prompts.py`)의 절대 규칙에 "병합 시 통합된 내용을 대표하는 새 제목을 지으라"는 지침과 JSON 출력 형식에 `"title"` 필드를 추가한다.

`_judge_and_merge()`는 기존에 `if not valid_claims or not (result.markdown or "").strip(): return not_duplicate`로 markdown 빈값을 걸러내는 지점에 title 빈값 검사도 같이 추가하고, 병합 성공 뒤 `create_wiki_version()` 호출 다음 줄에 `update_wiki_page_title(representative_info.page_id, result.title, supabase=supabase)`를 추가한다.

## 데이터 흐름

1. (변경 없음) `run_wiki_dedup_batch` → `_judge_and_merge(pair, content_a, content_b, ...)`
2. (변경 없음) LLM 호출 → `WikiDedupLLMResult` 파싱
3. **(신규)** `result.decision == "merge"`인데 `not (result.title or "").strip()`이면 `not_duplicate`로 폴백(markdown 빈값 검사와 나란히)
4. (변경 없음) `create_wiki_version(draft)` → `record_wiki_validation` → `review_wiki_version` → `publish_wiki_version(representative_info.page_id, version_id)`
5. **(신규)** `update_wiki_page_title(representative_info.page_id, result.title, supabase=supabase)`
6. (변경 없음) `archive_wiki_page(other_info.page_id)` → `reparent_children(...)`

## 에러 처리

`update_wiki_page_title` 호출 자체가 실패하면(DB 오류 등) 그 예외는 `run_wiki_dedup_batch`의 페어별 try/except가 이미 잡아 `DedupResult(decision="failed", ...)`로 격리한다(기존 구조 그대로 — 이 병합 건만 실패 처리되고 다른 페어 처리는 막지 않는다). 새 실패 모드를 추가로 만들지 않는다.

## 테스트

- `tests/test_wiki_dedup_models.py`(있으면): `WikiDedupLLMResult`에 `title` 필드가 옵셔널로 잘 들어가는지
- `tests/test_wiki_dedup.py`:
  - 기존 `test_merge_creates_version_archives_other_and_reparents_children`의 fake LLM 응답에 `"title": "통합 제목"` 추가하고, `update_wiki_page_title` 호출을 캡처해 `(대표 page_id, "통합 제목")`로 호출됐는지 검증하도록 갱신
  - 신규: 병합인데 title이 빈 문자열/없음 → `not_duplicate`로 폴백하고 `create_wiki_version`/`update_wiki_page_title` 둘 다 호출 안 되는지
  - 나머지 기존 테스트(`test_not_duplicate_decision_does_nothing`, `test_merge_skipped_when_representative_page_id_is_invalid`, `test_merge_skipped_when_no_valid_grounded_claims`, `test_uses_injected_llm_client_instead_of_create_json_completion`)는 fake LLM 응답이 전부 `"decision": "not_duplicate"`이거나 검증 실패로 `not_duplicate`에 조기 반환되는 케이스라 `update_wiki_page_title` 호출 코드 자체에 도달하지 않는다 — stub 추가 불필요, 그대로 둔다.

## 영향받는 파일

| 파일 | 변경 |
|---|---|
| `src/wiki/dedup_models.py` | `WikiDedupLLMResult.title` 필드 추가 |
| `src/wiki/dedup_prompts.py` | 시스템 프롬프트에 제목 지시 + JSON 스키마에 `title` 추가 |
| `src/wiki/dedup.py` | `_judge_and_merge`에 title 빈값 검증 + `update_wiki_page_title` 호출 추가 |
| `tests/test_wiki_dedup.py` | 기존 merge 성공 테스트 갱신 + title 빈값 폴백 테스트 신규 |

프론트엔드 변경 없음. 새 모델/설정 분기점 없음(기존 `get_openrouter_settings`/`create_json_completion` 그대로 재사용).

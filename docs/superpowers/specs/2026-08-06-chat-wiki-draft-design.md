# 대화 기반 위키 저장(save-to-wiki) 본문 템플릿 설계

## 배경

에이전트 챗봇 화면(`AgentPage.jsx`)의 "위키에 저장" 버튼은 이미 백엔드 `POST /chat/sessions/{id}/messages/{id}/save-to-wiki`까지 실제로 연결되어 정상 동작한다. 문제는 그 결과물의 품질이다 — 현재 `save_message_to_wiki`(`src/api/main.py`)는:

- 제목: 사용자 질문 앞 80자를 단순 자르기(`user_message["content"][:80]`) — 문장 중간에서 잘려도 그대로 씀
- 본문: 챗봇 답변 원문(`message["content"]`)을 그대로 마크다운으로 저장

반면 리포트 파이프라인이 자동 생성하는 이슈/토픽 위키 페이지(`src/wiki/generation.py`)는 `# 제목 / ## 현재 상황 / ## 핵심 사실 / ## 시사점 / ## 주시할 지점 / ## 출처` 구조를 갖춘 정식 문서다. 대화에서 저장된 페이지만 이 구조에서 벗어나 있어 같은 위키 안에서 형식이 섞인다.

이번 스펙은 대화 기반 저장 결과물이 기존 위키 페이지와 같은 수준의 "제목 + 구조화된 본문"을 갖추도록 생성 로직만 다룬다.

**범위 밖**: 프론트엔드 "위키에 저장" 버튼/흐름(이미 완성되어 변경 불필요), 이슈/토픽 자동 생성 파이프라인 자체, dedup 배치와의 통합(저장된 대화 위키 페이지가 이슈·토픽 페이지와 제목이 겹칠 경우의 중복 처리는 기존 dedup 배치의 매일 cron이 그대로 커버하므로 별도 작업 없음).

## 목표

1. 대화에서 저장되는 위키 페이지가 질문/답변 요약/핵심 근거/출처로 구조화된 제목+본문을 갖는다.
2. LLM 호출이 실패해도(타임아웃, 잘못된 JSON 등) 저장 자체는 실패하지 않고 같은 템플릿 구조로 안전하게 대체된다.
3. 기존 위키 생성 아키텍처(OpenRouter 모델 설정, JSON 스키마 검증 패턴)를 그대로 재사용해 새로운 설정/모델 분기점을 만들지 않는다.

## 비목표

- 답변 요약 품질을 위해 별도 프롬프트 실험/튜닝 — 최초 버전은 기존 토픽 페이지 프롬프트 스타일을 따르는 단순 버전으로 시작.
- 저장된 대화 위키 페이지를 이슈/토픽 페이지 계층(`parent_page_id`)에 편입시키는 것 — 현재도 `page_type="issue"`로 저장되며 이 스펙에서 변경하지 않음.
- citations가 없거나 `is_llm_fallback`인 경우의 처리 — 기존 400 검증 로직 그대로 유지.

## 아키텍처

새 모듈 `src/wiki/chat_wiki.py` 하나로 구성한다. `src/wiki/generation.py`의 토픽 페이지 LLM 생성 패턴(`_generate_topic_page`)과 같은 뼈대를 쓰되, 리포트 섹션 그룹핑이 필요 없는 단건 Q&A라 별도 모듈로 분리한다.

```
src/wiki/chat_wiki.py
├── CHAT_WIKI_SYSTEM_PROMPT / _build_chat_wiki_user_prompt(question, answer, citations)
├── ChatWikiLLMResult(BaseModel): title, answer_summary, key_evidence: list[str]
├── ChatWikiDraft(dataclass/NamedTuple): title: str, markdown: str
├── ChatWikiLLMClient = Callable[[str, str, str | None], str]  # (system, user, model) -> raw JSON
└── compose_chat_wiki_draft(question, answer, citations, *, llm_client=None) -> ChatWikiDraft
```

`llm_client` 기본값은 `analysis/classifier.py`의 `create_json_completion` + `get_openrouter_settings()`를 그대로 감싼 함수 — 새 모델 설정을 만들지 않고 기존 v4-flash 기본/v4-pro 폴백을 그대로 물려받는다. (`generation.py`가 `WikiTopicLLMClient` 주입을 테스트에서 쓰는 것과 동일하게, `compose_chat_wiki_draft`도 테스트에서 fake client를 주입할 수 있게 파라미터화한다.)

## 마크다운 템플릿

```
# {title}

## 질문
{question}

## 답변 요약
{answer_summary}

## 핵심 근거
- {key_evidence[0]}
- {key_evidence[1]}
...

## 출처
- {citation.quoted_text} (document_version_id={citation.document_version_id})
```

- `title`, `answer_summary`, `key_evidence`는 LLM 응답(`ChatWikiLLMResult`)에서 옴.
- `## 출처` 섹션은 LLM을 거치지 않고 코드에서 `citations` 리스트로 직접 조립한다 — `generation.py`의 `_build_issue_page_markdown`이 출처 섹션을 만드는 방식과 동일한 패턴(`{evidence} (document_version_id=...)`).
- `question`은 사용자 질문 원문 그대로(요약 대상 아님 — 무슨 질문에 대한 답인지 원문이 남아야 함).

## 데이터 흐름

1. (변경 없음) 사용자가 `AgentPage.jsx`에서 "위키에 저장" 클릭 → `POST /chat/sessions/{id}/messages/{id}/save-to-wiki`
2. (변경 없음) `save_message_to_wiki`가 `is_llm_fallback` → citations 존재 여부 순서로 검증
3. **(신규)** `compose_chat_wiki_draft(question=user_message["content"] if user_message else "채팅에서 저장된 답변", answer=message["content"], citations=citations)` 호출 → `ChatWikiDraft(title, markdown)` 반환 — 선행 사용자 메시지가 없는 예외적인 경우(현재 코드의 기존 폴백 문자열과 동일)도 `compose_chat_wiki_draft`가 정상적인 입력으로 처리한다.
4. (변경) 기존 `title = user_message["content"][:80]` / `markdown=message["content"]` 대신 3번 결과 사용
5. (변경 없음) `upsert_wiki_page` → `WikiDraftInput` → `create_wiki_version` → `record_wiki_validation` → `review_wiki_version` → `publish_wiki_version`

## 에러 처리

`compose_chat_wiki_draft` 내부에서 LLM 호출/검증이 실패하면(`OpenRouterApiError`, `OpenRouterTimeoutError`, `ValidationError`, JSON 파싱 실패 등) 예외를 상위로 던지지 않고 코드 폴백으로 같은 `ChatWikiDraft` 형태를 만든다:

- `title` = 질문 앞 80자(기존 동작과 동일한 최후 수단)
- `answer_summary` = 답변 원문 그대로
- `key_evidence` = `citations`의 `quoted_text`를 그대로 리스트로 사용(LLM 요약 없이)

즉 LLM 호출 성공 여부와 무관하게 저장 자체는 항상 같은 템플릿 구조로 성공한다 — "위키에 저장" 버튼을 누른 사용자가 LLM 일시 장애 때문에 저장 실패를 겪는 일은 없다. 이 폴백은 기존 `is_llm_fallback`(챗봇 답변 자체가 위키 근거 없이 생성됐다는 플래그)과는 별개 개념이라 이름과 로그 메시지에서 혼동되지 않게 한다.

## 테스트

- `tests/test_wiki_chat_draft.py`(신규): `compose_chat_wiki_draft` 단위 테스트
  - 정상 케이스: fake LLM client가 유효한 JSON을 반환 → 5개 섹션이 모두 채워진 마크다운 검증
  - `ValidationError` 케이스: LLM이 스키마에 안 맞는 JSON을 반환 → 코드 폴백 결과 검증
  - 예외 케이스: LLM 호출 자체가 예외를 던짐(타임아웃 등) → 코드 폴백 결과 검증
- `tests/test_chat_sessions.py`(기존): `save-to-wiki` 관련 테스트가 있다면 새 마크다운 구조(질문/답변 요약/핵심 근거/출처 헤더)를 검증하도록 갱신

## 영향받는 파일

| 파일 | 변경 |
|---|---|
| `src/wiki/chat_wiki.py` | 신규 |
| `tests/test_wiki_chat_draft.py` | 신규 |
| `src/api/main.py` | `save_message_to_wiki`에서 `compose_chat_wiki_draft` 호출로 교체 |
| `tests/test_chat_sessions.py` | 기존 save-to-wiki 테스트 있으면 갱신 |

프론트엔드 변경 없음.

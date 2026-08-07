# 웹 검색 그라운딩 단계 설계

**작성일:** 2026-08-08
**선행 기능:** `docs/superpowers/specs/2026-08-07-document-grounded-fallback-design.md` (위키→원문 2단계 그라운딩, 브랜치 `worktree-document-grounded-fallback`에서 구현·병합 대기 중)

## 배경

에이전트는 현재 3단계로 답한다: ① 위키 그라운딩 → ② 원문(뉴스+DART) 그라운딩 → ③ 그마저 실패하면 출처 없이 LLM 일반 지식으로 답변(`is_llm_fallback=True`, `citations` 항상 빈 배열, 위키 저장 차단).

③ 단계는 실제로는 "근거를 못 찾았다"가 아니라 "**축적된 데이터베이스 안에서는** 근거를 못 찾았다"일 뿐이다 — 질문이 아직 파이프라인이 수집하지 않은 최신 사안이면, 인터넷에는 답이 있어도 에이전트는 무조건 출처 없는 답변으로 떨어진다. 이번 기능은 ③ 앞에 **웹 검색 그라운딩** 단계를 끼워 넣어, 위키·원문 모두 근거가 없을 때 실시간 웹 검색으로 마지막 시도를 하게 한다. 검색으로도 근거를 못 찾을 때만 기존 ③(출처 없는 일반 지식 답변)으로 떨어진다.

## 답변 단계 구조

| 단계 | 동작 | 근거 검증 |
|---|---|---|
| 1. 위키 그라운딩 (기존) | 위키 페이지에서 근거 탐색 | `_is_grounded` |
| 2. 원문 그라운딩 (기존) | 수집된 뉴스+DART 원문에서 근거 탐색 | `_is_grounded` |
| 3. 웹 검색 그라운딩 (신규) | 네이버 검색 API로 실시간 검색, 검색 결과 스니펫에서 근거 탐색 | `_is_grounded` (동일 메커니즘으로 확장) |
| 4. LLM 일반 지식 폴백 (기존 3단계 재번호) | 위 세 단계 모두 실패 시 출처 없이 답변 | 없음 — `is_llm_fallback=True`, 위키 저장 차단(기존 동작 그대로) |

`WikiAgent.answer()`의 `_safe_run()` 체인에 `_web_search_answer`가 `_document_answer`와 `_llm_fallback_answer` 사이에 추가된다. 앞 단계와 마찬가지로 이 단계 자체가 예외를 던져도(네이버 API 장애 등) `_safe_run`이 잡아 다음 단계로 넘어간다 — 크래시 없이 항상 답변을 낸다는 기존 불변식 유지.

## 웹 검색 도구

**신규 모듈:** `src/pipeline_common/web_search.py`

```python
def search_web(query: str, limit: int = 5) -> list[WebSearchHit]: ...

@dataclass
class WebSearchHit:
    title: str
    url: str
    snippet: str
    published_at: str | None
```

`src/collectors/fetchers.py::fetch_naver_news`와 같은 네이버 검색 API(`NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET`, `httpx.get`, 헤더/파라미터 구조)를 재사용하되, 파이프라인 수집용 무거운 처리(원문 페이지 GET, `_fetch_article`, 소스별 config, 요청 간 sleep, dedup)는 전부 뺀다 — 채팅 응답 시간 안에 끝나야 하므로 **검색 결과의 title/originallink/description/pubDate만** 받아 바로 반환한다. 원문 전체를 긁지 않고 검색 스니펫만으로 그라운딩한다(정확성보다 응답 속도·안정성 우선 — 스니펫에 없는 내용은 애초에 인용 근거로 쓸 수 없으므로 할루시네이션 억제 효과도 있음).

`fetchers.py`의 `strip_html`은 재사용하지 않는다 — `pipeline_common`(agent 런타임이 참조)이 `collectors`(수집 파이프라인)를 참조하는 건 레이어 역행이다(`document_search.py`가 이미 같은 이유로 `wiki/repository.py`를 참조하지 않는 것과 동일한 원칙). 네이버 검색 응답의 `<b>` 하이라이트 태그만 벗기면 되는 간단한 로직이라 `web_search.py` 안에 몇 줄로 자체 구현한다.

**`WikiTools` 위임 메서드** (`src/agent/wiki_tools.py`, 기존 `search_documents`/`read_document`와 같은 패턴):
```python
def search_web(self, query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> list[web_search.WebSearchHit]:
    return web_search.search_web(query, limit)
```
(workspace_id를 받지 않는다 — 웹 검색은 워크스페이스 스코프 데이터가 아니라 실시간 외부 검색이므로.)

## 에이전트 도구 세트

`src/agent/core.py`에 `WEB_SEARCH_TOOLS` 추가:
```python
WEB_SEARCH_TOOLS = [
    {"type": "function", "function": {"name": "search_web", ...}},  # query -> WebSearchHit 목록(title/url/snippet/published_at)
    _SUBMIT_ANSWER_TOOL,
    _SUBMIT_NO_ANSWER_TOOL,
]
```
`DOCUMENT_TOOLS`(search+read 2단계)와 달리 **검색 도구 하나뿐**이다 — `search_web`이 이미 스니펫(그라운딩에 쓸 내용 전부)을 반환하므로 `read_document` 같은 별도 조회 단계가 필요 없다.

새 시스템 프롬프트 `WEB_SEARCH_ANSWER_SYSTEM_PROMPT`(`DOCUMENT_ANSWER_SYSTEM_PROMPT`와 같은 규칙 — 문장마다 [N] 각주, 검색 결과에 실제로 있는 내용만, 없으면 `submit_no_answer`)를 추가하고, `_web_search_answer()`가 `_document_answer()`와 같은 모양으로 `_run_grounded_answer(..., system_prompt=WEB_SEARCH_ANSWER_SYSTEM_PROMPT, tools=WEB_SEARCH_TOOLS, tool_handlers={"search_web": handle_search_web})`를 호출한다.

## 인용 식별자 확장 — 핵심 아키텍처 변경

**문제:** 기존 `_is_grounded`/`seen_document_version_ids`/`Citation`은 전부 `document_version_id`(DB 행 PK)를 유일한 인용 식별자로 가정한다. `submit_answer` 도구 스키마도 `citations[].document_version_id`를 필수로 요구한다. 웹 검색 결과는 DB 행이 아니라 URL이 식별자다 — document_version_id가 없다.

**결정:** 위키/원문 단계와 그라운딩 검증 메커니즘을 그대로 공유하기 위해(Task 4에서 통합한 `_run_grounded_answer`를 다시 쪼개지 않기 위해), 기존 스키마를 확장한다:

- `submit_answer` 도구 스키마: `citations[].document_version_id`를 선택 필드로 바꾸고 `citations[].source_url`을 추가. 설명에 "document_version_id 또는 source_url 중 정확히 하나"를 명시.
- `Citation` 데이터클래스에 `source_url: Optional[str] = None` 추가.
- "seen" 추적 집합이 document_version_id뿐 아니라 URL도 담도록 일반화(`handle_search_web`이 검색으로 얻은 URL들을 이 집합에 추가). `_is_grounded`는 각 citation의 `document_version_id or source_url`이 이 집합에 있는지로 검증(기존 로직과 같은 자리, 식별자만 이원화).
- 위키/원문 단계는 지금처럼 `document_version_id`만 채워서 제출하고 `source_url`은 항상 `None` — 동작 변화 없음. 웹 검색 단계만 `source_url`을 채우고 `document_version_id=None`.

대안(웹 전용 `submit_web_answer` 도구를 따로 만들어 기존 스키마를 안 건드리는 안)도 검토했으나, `_run_grounded_answer`의 `elif name == "submit_answer"` 분기(약 40줄, JSON 파싱 실패 복구·grounding 검증·오답 강등 로직 포함)를 통째로 복제하게 되어 Task 4가 막 없앤 중복을 되살린다 — 기각.

## 인용 저장 스키마 확장

`message_citations` 테이블(현재: `document_version_id`가 NOT NULL FK, 그 외 컬럼은 `_enrich_message_citations`가 매 조회마다 `document_versions`→`documents`→`sources` 조인으로 채움 — 테이블 자체엔 제목/URL 컬럼이 없음):

- `document_version_id`를 nullable로 변경.
- `source_url text`, `source_title text`, `published_at text` 컬럼 추가(nullable) — 웹 검색 인용은 조인할 DB 행이 없으므로, 검색 결과에서 얻은 값을 저장 시점에 이 컬럼들에 직접 써넣는다.
- 별도 `citation_type` 구분 컬럼은 추가하지 않는다(YAGNI) — `document_version_id IS NULL`이 이미 "웹 검색 인용"과 "DB 문서 기반 인용"을 완전히 구분하는 판별식이라 중복 컬럼이 불필요하다. 기존 행은 전부 `document_version_id`가 있으므로 백필도 필요 없다.

`save_agent_message`(`src/api/db.py`)의 `message_citations` insert에 `source_url`/`source_title`/`published_at`을 `Citation`에서 그대로 옮겨 쓰는 필드 3개를 추가한다.

`_enrich_message_citations`는 `document_version_id`가 `None`인 행을 조인 대상에서 제외하고, 그 행들은 저장 시점에 이미 채워둔 자기 자신의 `source_url`/`source_title`/`published_at`을 그대로 통과시킨다(조인으로 덮어쓰지 않음).

`CitationOut`(`src/api/schemas.py`): `document_version_id: Optional[str]`로 변경(기존엔 필수). `document_title`/`source_url`/`published_at` 필드는 이미 있으므로 그대로 재사용 — 새 필드 없이 웹 검색 인용도 같은 필드에 채워서 내려준다. 프론트는 `document_version_id`가 `null`인지로 "웹 검색 근거" 배지를 띄울지 판단할 수 있다.

## 위키 저장 흐름 — 변경 없음

`is_llm_fallback`은 새 4단계(진짜 출처 없음)일 때만 `True`다. 1~3단계는 전부 `False`이므로 `save_message_to_wiki`의 기존 차단 로직(`if message.get("is_llm_fallback"): raise ...`)이 그대로 유효하다 — 웹 검색 그라운딩 답변도 지금과 똑같이 수동 "위키에 저장" 버튼으로 저장 가능해진다. 백엔드에 새로 만들 저장-차단/허용 로직은 없다. "저장할지 물어보기" UX는 프론트가 `document_version_id === null && citations.length > 0`(웹 검색 근거)을 보고 프롬프트를 띄울지 말지 정하면 된다 — 이 저장소 밖(별도 프론트 레포)의 몫이라 이 스펙 범위 밖이다.

## 에러 처리

- 네이버 API 인증정보 없음/호출 실패/타임아웃: `search_web`이 던진 예외는 잡지 않는다 — `_run_grounded_answer`의 도구 디스패치 루프는 지금도 `tool_handlers[name](...)` 호출을 try/except로 감싸지 않으므로(기존 `handle_search_documents` 등도 마찬가지), 예외는 그대로 `_web_search_answer` 밖으로 나가 `answer()`의 `_safe_run`이 잡는다 — 웹 검색 단계 전체가 "근거 없음"으로 강등되고 4단계(LLM 폴백)로 자연스럽게 넘어간다. 새로 만드는 예외 처리가 아니라 기존 단계들과 동일한 기존 동작을 그대로 물려받는 것이다.
- 검색 결과 0건: `search_web`이 빈 리스트를 반환 — 모델이 `submit_no_answer`를 호출하는 정상 경로(빈 seen 집합이라 애초에 grounding 불가능).
- `_is_grounded`가 URL 식별자 검증에 실패(모델이 검색 결과에 없는 URL을 지어냄): 기존과 동일하게 근거 없음으로 강등.

## 테스트

- `tests/test_pipeline_common_web_search.py`(신규): `httpx.get`을 mock해서 검색 API 호출 파라미터, 응답 파싱(title/url/snippet/published_at), HTML 태그 스트립, 인증정보 없음 시 예외를 검증. `test_pipeline_common_document_search.py`의 FakeSupabase 패턴과 달리 여기는 실제 외부 HTTP 호출이라 `httpx.get`을 monkeypatch하는 방식(`fetchers.py` 관련 기존 테스트가 있다면 그 패턴 참고).
- `tests/test_agent_wiki_tools.py`: `search_web` 위임 테스트 추가(기존 패턴과 동일).
- `tests/test_agent_core.py`: `_web_search_answer`가 `WEB_SEARCH_TOOLS`를 모델에 넘기는지(Finding 3과 같은 패턴으로 이번엔 처음부터 테스트 포함), `source_url` 기반 citation이 grounding 검증을 통과/실패하는 경우, `_web_search_answer`가 예외를 던져도 크래시 없이 다음 단계로 넘어가는지, 4단계까지 전부 실패했을 때 최종적으로 `is_llm_fallback=True`가 되는지.
- `tests/test_chat_sessions.py`(또는 `src/api/db.py` 테스트): `document_version_id=None` citation이 `message_citations`에 저장/조회되는 왕복 테스트, `_enrich_message_citations`가 이 행을 조인 없이 그대로 통과시키는지.
- 마이그레이션 파일(`supabase/migrations/`)은 계획 단계에서 정확한 SQL(컬럼 추가·nullable 변경)로 작성.

## 범위 밖

- 프론트엔드 UI(배지 렌더링, 저장 프롬프트 모달) — 별도 레포, 이 스펙은 프론트가 쓸 API 계약까지만.
- 웹 검색 결과를 `documents`/`document_versions`에 영구 저장(파이프라인 편입)하는 것 — 브레인스토밍 중 검토했으나 채팅 응답 경로에 수집 파이프라인 복잡도(워크스페이스/소스 등록, 중복 검사, storage 쓰기)를 얹는 게 과함(YAGNI)으로 기각. 저장하고 싶으면 사용자가 "위키에 저장"을 눌러 기존 흐름으로 처리한다.
- 네이버 검색 API 외 다른 웹 검색 백엔드 — 필요해지면 별도 스펙.

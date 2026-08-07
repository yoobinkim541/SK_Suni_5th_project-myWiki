# 위키 근거 없을 때 원문 문서(뉴스+DART) 근거로 답변하는 중간 단계 설계

## 배경

`WikiAgent.answer()`는 현재 2단계다.

1. `_wiki_answer()` — 발행된 위키 페이지에서만 근거를 찾아 `[N]` 각주로 답변
2. `_llm_fallback_answer()` — 1이 실패하면 위키 근거 없이 모델의 일반 지식으로만 답변(`is_llm_fallback=True`, citations 항상 빈 배열)

문제는 위키에 실제로 발행된 문서가 수집된 원문 전체의 극히 일부라는 것이다(예: 네이버 뉴스 문서 489건 중 위키 인용으로 채택된 건 7건, ~3%). 나머지는 `documents`/`document_versions`에 원문이 그대로 있는데도 위키로 정제되지 않았다는 이유만으로 2단계에서 근거 없이 버려진다. 사용자가 받는 답변은 실제로 우리 DB에 원문(뉴스 기사, DART 공시)이 있는 주제인데도 "위키 근거 아님" 딱지가 붙은 무근거 답변이 된다.

이 스펙은 이 두 단계 사이에 "위키엔 없지만 수집된 원문에는 있는" 경우를 커버하는 중간 단계를 추가한다.

**범위 밖**: 실시간 웹 검색(외부 API 연동), 위키 생성 파이프라인 자체 개선(원문이 위키로 더 잘 정제되게 만드는 것 — 이건 별개 문제), 프론트엔드 변경(citation 링크 렌더링은 `document_version_id`만으로 이미 동작함, 아래 "왜 프론트 변경이 없는지" 참고).

## 목표

1. 위키에 근거가 없어도, 수집된 원문(뉴스+DART, 발행 여부 무관) 중 관련 있는 게 있으면 그걸 근거로 `[N]` 각주 답변을 만든다 — 원문 기사/공시 링크가 출처로 뜬다.
2. 원문에도 근거가 없으면(우리 DB에 아예 수집된 적 없는 주제) 기존처럼 출처 없는 일반 지식 답변으로 넘어간다 — 이 마지막 단계는 그대로 유지.
3. 기존 위키 그라운딩 흐름(`_wiki_answer`)의 크래시 내성(JSON 파싱 실패 복구, `choices=None` 폴백, 예외 시 다음 단계로 안전 이동)을 새 단계도 그대로 갖는다 — 별도로 재구현하다 놓치지 않는다.

## 비목표

- 위키 생성 파이프라인이 이 원문들을 실제로 위키로 승격시키게 만드는 것(별개 개선 과제).
- `search_documents`가 위키 페이지까지 같이 검색하게 만드는 것 — 위키는 여전히 1단계(`_wiki_answer`)에서만 찾는다. 두 소스를 한 라운드에 섞으면 도구 5개(`list_wiki_topics`/`search_wiki_pages`/`read_wiki_page`/`search_documents`/`read_document`)를 한 라운드 예산 안에서 모델이 헷갈릴 위험이 있어, 단계를 분리해 프롬프트를 각각 명확히 유지한다.

## 왜 프론트 변경이 없는지

`src/api/db.py::_enrich_message_citations()`가 `message_citations.document_version_id -> document_versions.document_id -> documents(title/canonical_url/published_at/source_id) -> sources.name` 순으로 조인해 `CitationOut.source_url`을 채운다 — **위키 테이블을 전혀 거치지 않는다.** 즉 이번에 추가하는 citation이 위키 페이지가 아니라 원문 문서를 직접 가리켜도, 기존 저장/조회 경로가 그대로 링크를 만들어준다.

## 아키텍처

### 1) `src/pipeline_common/document_search.py` (신규)

`src/wiki/repository.py::search_wiki_contexts` / `src/wiki/query.py::_enrich_sources`와 같은 패턴을 원문 문서에 적용한다. 위키 전용 모듈(`src/wiki/`)에 두지 않는 이유: `documents`/`document_versions`는 위키가 아니라 파이프라인 공용 테이블이고, `pipeline_common`이 이미 그 접근을 담당하는 자리다.

```python
DEFAULT_SCAN_LIMIT = 50  # published_at desc로 최근 N건만 스캔 (검색 지연·storage 다운로드 비용 제한)

@dataclass
class DocumentSearchHit:
    document_version_id: str
    title: str
    score: float

@dataclass
class DocumentDetail:
    document_version_id: str
    title: str
    markdown: str
    canonical_url: str | None
    source_name: str | None
    published_at: str | None

def search_documents(workspace_id: str, query: str, limit: int = 5, *, supabase=None) -> list[DocumentSearchHit]: ...
def get_document_detail(workspace_id: str, document_version_id: str, *, supabase=None) -> DocumentDetail | None: ...
```

`search_documents` 구현:
1. `documents`에서 `workspace_id` + `status='active'` 필터, `published_at desc` 정렬, `DEFAULT_SCAN_LIMIT`건만 조회.
2. 문서별 **최신** `document_version`(가장 높은 `version_no`)만 후보로 삼는다 — 재수집으로 버전이 여러 개 쌓인 문서라도 최신 내용 하나만 스코어링 대상.
3. 각 후보의 `markdown_object_key`를 `processed` 버킷에서 내려받아 `search_wiki_contexts`와 동일한 title 60% + 본문 30% + coverage 10% 토큰 오버랩 스코어링(`_score_page`와 같은 로직, 이 모듈에 맞게 복사 — `wiki/repository.py`를 import하지 않는다. 위키 모듈이 파이프라인 공용 모듈을 참조하는 건 몰라도 반대 방향은 레이어 위반).
4. 점수 0인 건 제외, 점수 내림차순 상위 `limit`건 반환.

**`.in_()` 청크 주의**: 이번 세션에서 청크 없는 `.in_()`이 세 번 크래시를 냈다(`categories/service.py`, `analysis/repository.py`, `report/candidate_provider.py`). `DEFAULT_SCAN_LIMIT=50`이 이미 안전 임계치(150)보다 한참 작아 단일 `.in_()` 호출로 충분하지만, 재발 방지 차원에서 이 사실과 임계치 근거를 모듈 docstring에 명시한다.

### 2) `src/agent/wiki_tools.py` (수정)

`WikiTools`에 얇은 위임 메서드 2개 추가 — 기존 `list_wiki_topics`/`read_wiki_page`가 `wiki_query`에 위임하는 것과 같은 패턴:

```python
def search_documents(self, query: str, limit: int = 5) -> list[DocumentSearchHit]:
    return document_search.search_documents(self.workspace_id, query, limit=limit)

def read_document(self, document_version_id: str) -> Optional[DocumentDetail]:
    return document_search.get_document_detail(self.workspace_id, document_version_id)
```

모듈 docstring을 "Wiki 조회 도구"에서 "Wiki·원문 문서 조회 도구"로 갱신 — 더 이상 위키 전용이 아님을 명시.

### 3) `src/agent/core.py` (수정 — 공유 루프로 리팩터링)

`_wiki_answer()`의 라운드 루프(도구 호출 → 파싱 → 디스패치 → grounding 검증)를 `_document_answer()`와 그대로 복제하면, 이번에 막 고친 크래시 내성(JSON 파싱 실패 복구, `choices=None` 처리)을 두 곳에 각각 유지해야 해서 한쪽만 고치고 잊어버리는 사고가 나기 쉽다. 대신 공통 로직을 하나로 뽑는다:

```python
def _run_grounded_answer(
    self,
    question: str,
    history: list[dict] | None,
    *,
    system_prompt: str,
    tools: list[dict],
    discovery_handlers: dict[str, Callable[[dict], object]],  # tool name -> (args) -> tool 결과(JSON 직렬화 가능)
    read_handler: tuple[str, Callable[[dict], object | None]],  # (tool name, (args) -> 읽은 항목 or None)
) -> AgentResult:
    """라운드 루프, JSON 파싱 복구, choices 검증, submit_answer/submit_no_answer 처리,
    grounding 검증까지 — _wiki_answer/_document_answer가 공유하는 본체."""
```

- `_wiki_answer()`는 `discovery_handlers={"list_wiki_topics": ..., "search_wiki_pages": ...}`, `read_handler=("read_wiki_page", ...)`로 이 함수를 호출하도록 리팩터링.
- `_document_answer()`는 `discovery_handlers={"search_documents": ...}`, `read_handler=("read_document", ...)`로 같은 함수를 호출.
- `submit_answer`/`submit_no_answer` 처리, `_is_grounded()` 검증, `seen_document_version_ids` 추적, `MAX_TOOL_ROUNDS` 초과 처리는 전부 공유 본체 안에 한 벌만 존재.

**리팩터링 안전장치**: `_wiki_answer()`의 외부 동작(입출력)은 그대로 유지해야 한다 — `tests/test_agent_core.py`의 기존 24개 테스트가 전부 그 동작을 이미 고정해뒀으므로, 리팩터링 후에도 수정 없이 전부 통과해야 한다. 이게 곧 "리팩터링이 안전했다"는 증거다.

새 프롬프트/도구:

```python
DOCUMENT_ANSWER_SYSTEM_PROMPT = """
너는 myWiki의 답변 Agent다. 위키에 정리된 문서는 없지만, 수집된 원문(뉴스 기사·DART 공시)
중에 관련 있는 게 있는지 찾는 단계다. 규칙:
1. 반드시 read_document로 실제 읽은 원문 내용만 근거로 답변해라. 사전 지식으로 빈틈을 채우지 마라.
2. search_documents로 질문 키워드와 관련된 원문을 먼저 찾고, read_document로 내용을 확인해라.
3. 근거를 찾았으면 submit_answer([N] 각주 + citations)를, 못 찾았으면 submit_no_answer를 호출해라.
   (citations 형식/검증 규칙은 위키 답변과 동일 — document_version_id는 read_document로 실제
   읽은 것 중에서만, [N]은 citations 배열 순서와 정확히 대응)
4. 톤은 직접적이고 전문적으로.
"""

_SUBMIT_ANSWER_TOOL = next(t for t in TOOLS if t["function"]["name"] == "submit_answer")
_SUBMIT_NO_ANSWER_TOOL = next(t for t in TOOLS if t["function"]["name"] == "submit_no_answer")

DOCUMENT_TOOLS = [
    {"type": "function", "function": {"name": "search_documents", ...}},
    {"type": "function", "function": {"name": "read_document", ...}},
    _SUBMIT_ANSWER_TOOL,   # 기존 submit_answer 스키마 그대로 재사용(이름으로 찾아 참조 — 인덱스 의존 금지)
    _SUBMIT_NO_ANSWER_TOOL,
]
```

`answer()`는 3단계로 확장:

```python
def answer(self, question, history=None) -> AgentResult:
    result = self._safe(self._wiki_answer, question, history)
    if result.has_answer:
        return result
    result = self._safe(self._document_answer, question, history)
    if result.has_answer:
        return result
    fallback = self._llm_fallback_answer(question, history)
    return fallback if fallback is not None else result
```

(`_safe`는 지금 `answer()`에 있는 try/except 래핑을 재사용할 수 있게 작은 헬퍼로 뽑는다 — 위키 단계든 문서 단계든 예외가 나면 다음 단계로 넘어가야 하므로.)

## Citation 표시 차이

위키 답변의 `Citation.wiki_slug`는 원문 문서 답변에서는 항상 `None`이다(위키 페이지가 아니므로). 프론트가 `wiki_slug` 유무로 "위키 페이지 보기" 링크를 조건부 렌더링하고 있다면 자연히 숨겨지고, `source_url`(원문 링크)은 그대로 뜬다 — 별도 프론트 분기 불필요(citation 자체에 "이건 원문 직접 인용"이라는 새 플래그를 추가하지 않는다. `wiki_slug is None`이 이미 그 신호다).

## 테스트

- `tests/test_pipeline_common_document_search.py` (신규): `search_documents`/`get_document_detail` 단위 테스트. `tests/test_wiki_search.py`와 같은 FakeSupabase/FakeTable 패턴 재사용
  - 제목에만 매칭 / 본문에만 매칭 / 둘 다 매칭 스코어 비교
  - 문서당 최신 버전만 후보가 되는지(구버전 제외)
  - `status != 'active'` 문서 제외
  - 무관 문서 점수 0 제외
- `tests/test_agent_wiki_tools.py` (확장): `WikiTools.search_documents`/`read_document`가 `document_search` 모듈에 올바르게 위임하는지
- `tests/test_agent_core.py` (확장):
  - 기존 24개 테스트 전부 무변경으로 통과(리팩터링 안전성 증거)
  - 신규: 위키 실패 -> `_document_answer`가 원문으로 grounding 성공 -> `is_llm_fallback=False`, `citations[0].wiki_slug is None`, `source_url` 존재
  - 신규: 위키도 원문도 실패 -> 기존처럼 `_llm_fallback_answer`(`is_llm_fallback=True`)로 넘어감
  - 신규: `_document_answer` 중 크래시(JSON 파싱 실패 등) -> 다음 단계로 안전 이동(위키 테스트에서 검증한 것과 동일한 케이스를 문서 단계에도)

## 영향받는 파일

| 파일 | 변경 |
|---|---|
| `src/pipeline_common/document_search.py` | 신규 |
| `src/agent/wiki_tools.py` | `search_documents`/`read_document` 위임 메서드 추가 |
| `src/agent/core.py` | `_run_grounded_answer` 공유 루프로 리팩터링, `_document_answer` 추가, `answer()` 3단계로 확장 |
| `tests/test_pipeline_common_document_search.py` | 신규 |
| `tests/test_agent_wiki_tools.py` | 확장 |
| `tests/test_agent_core.py` | 확장(+기존 24건 무변경 통과 확인) |

프론트엔드 변경 없음.

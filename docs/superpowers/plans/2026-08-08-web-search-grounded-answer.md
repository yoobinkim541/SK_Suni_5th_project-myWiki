# 웹 검색 그라운딩 단계 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 위키·원문 그라운딩이 모두 실패했을 때, 사용자가 명시적으로 요청하면 네이버 검색 API로 실시간 웹 검색 그라운딩을 한 번 더 시도하고(3단계), 그것도 실패해야 기존의 출처 없는 LLM 일반 지식 폴백(4단계)으로 자동 전환한다.

**Architecture:** `WikiAgent.answer()`에 `allow_web_search: bool = False` 파라미터를 추가해 2턴 흐름(1턴=위키+원문만, 2턴=사용자가 "웹에서 찾아줘"를 요청했을 때만 웹 검색+LLM 폴백까지)을 코드로 강제한다. 웹 검색 그라운딩은 기존 `_run_grounded_answer` 공유 루프를 그대로 타되, 인용 식별자를 `document_version_id`(DB 행) 하나에서 `source_url`(실시간 검색 결과)까지 받도록 확장한다. 새 엔드포인트는 만들지 않는다 — 기존 `/regenerate`에 쿼리 파라미터 하나만 추가해 재사용한다.

**Tech Stack:** Python/FastAPI, Supabase(Postgres), httpx(네이버 검색 API 직접 호출), pytest.

**Spec:** `docs/superpowers/specs/2026-08-08-web-search-grounded-answer-design.md` — 이 문서에 배경·대안 검토·범위밖 항목이 정리돼 있다. 이 플랜은 그 스펙의 구현 세부사항이다.

## Global Constraints

- 네이버 검색 API 자격증명은 기존 `NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET` 환경변수를 그대로 쓴다(새 변수 없음).
- 원문 전체를 긁지 않는다 — 검색 API 응답의 title/description/originallink/pubDate 스니펫만으로 그라운딩한다.
- 새 엔드포인트를 만들지 않는다 — 기존 `POST .../messages/{message_id}/regenerate`에 쿼리 파라미터 `allow_web_search: bool = False`만 추가한다.
- `message_citations.document_version_id`를 nullable로 바꾸되, `document_version_id`와 `source_url` 중 정확히 하나는 항상 있어야 한다(CHECK 제약으로 DB에 강제).
- 이 저장소에 프론트엔드 코드는 없다 — 프론트 변경은 스펙 문서의 "프론트엔드" 섹션에 계약으로만 정리한다(구현 범위 밖).
- 마이그레이션 파일: `supabase/migrations/YYYYMMDDHHMMSS_description.sql`, 헤더 주석 없음. `ADD CONSTRAINT IF NOT EXISTS`는 유효하지 않은 Postgres 문법이므로 쓰지 않는다(`ADD COLUMN IF NOT EXISTS`는 유효, 그대로 사용).
- 각 태스크는 독립적으로 테스트 가능해야 하고, 태스크 완료마다 커밋한다(TDD: 실패하는 테스트 먼저 → 구현 → 통과 확인 → 커밋).

---

### Task 1: `src/pipeline_common/web_search.py` — 네이버 검색 API 래퍼

**Files:**
- Create: `src/pipeline_common/web_search.py`
- Test: `tests/test_pipeline_common_web_search.py`

**Interfaces:**
- Produces: `search_web(query: str, limit: int = 5) -> list[WebSearchHit]`, `WebSearchHit(title: str, url: str, snippet: str, published_at: str | None)`, `class WebSearchError(RuntimeError)`. Task 2가 이 함수와 클래스를 그대로 가져다 쓴다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
"""src/pipeline_common/web_search.py 단위 테스트 — 네이버 검색 API 호출은 httpx.get을 monkeypatch한다."""
from __future__ import annotations

import httpx
import pytest

from src.pipeline_common import web_search


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def test_search_web_returns_parsed_hits(monkeypatch):
    captured = {}

    def fake_get(url, *, params, headers, timeout):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        return FakeResponse(200, {
            "items": [
                {
                    "title": "SK\ud558\uc774\ub2c9\uc2a4 <b>ADR</b> \ub098\uc2a4\ub2e5 \uc0c1\uc7a5",
                    "originallink": "https://example.com/article-1",
                    "link": "https://news.naver.com/article-1",
                    "description": "SK\ud558\uc774\ub2c9\uc2a4\uac00 <b>ADR</b>\uc744 \uc0c1\uc7a5\ud588\ub2e4.",
                    "pubDate": "Fri, 07 Aug 2026 09:00:00 +0900",
                },
            ]
        })

    monkeypatch.setattr(web_search.httpx, "get", fake_get)
    monkeypatch.setenv("NAVER_CLIENT_ID", "test-id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "test-secret")

    hits = web_search.search_web("SK\ud558\uc774\ub2c9\uc2a4 ADR", limit=5)

    assert len(hits) == 1
    assert hits[0].title == "SK\ud558\uc774\ub2c9\uc2a4 ADR \ub098\uc2a4\ub2e5 \uc0c1\uc7a5"  # <b> \ud0dc\uadf8 \uc81c\uac70\ub428
    assert hits[0].url == "https://example.com/article-1"  # originallink \uc6b0\uc120
    assert hits[0].snippet == "SK\ud558\uc774\ub2c9\uc2a4\uac00 ADR\uc744 \uc0c1\uc7a5\ud588\ub2e4."
    assert hits[0].published_at == "2026-08-07T09:00:00+09:00"
    assert captured["params"]["query"] == "SK\ud558\uc774\ub2c9\uc2a4 ADR"
    assert captured["params"]["display"] == 5
    assert captured["headers"]["X-NCP-APIGW-API-KEY-ID"] == "test-id"


def test_search_web_falls_back_to_link_when_no_originallink(monkeypatch):
    def fake_get(url, *, params, headers, timeout):
        return FakeResponse(200, {
            "items": [{
                "title": "\uc81c\ubaa9", "originallink": "", "link": "https://news.naver.com/x",
                "description": "\uc124\uba85", "pubDate": "",
            }]
        })

    monkeypatch.setattr(web_search.httpx, "get", fake_get)
    monkeypatch.setenv("NAVER_CLIENT_ID", "test-id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "test-secret")

    hits = web_search.search_web("q")

    assert hits[0].url == "https://news.naver.com/x"
    assert hits[0].published_at is None


def test_search_web_clamps_limit_to_naver_display_range(monkeypatch):
    """\ub124\uc774\ubc84 \uac80\uc0c9 API\uc758 display\ub294 1~100 \ubc94\uc704\ub9cc \ud5c8\uc6a9\ud55c\ub2e4 \u2014 \ubc94\uc704 \ubc16 limit\uc744 \ud074\ub7a8\ud504\ud574\uc57c \ud55c\ub2e4."""
    captured = {}

    def fake_get(url, *, params, headers, timeout):
        captured["display"] = params["display"]
        return FakeResponse(200, {"items": []})

    monkeypatch.setattr(web_search.httpx, "get", fake_get)
    monkeypatch.setenv("NAVER_CLIENT_ID", "test-id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "test-secret")

    web_search.search_web("q", limit=0)
    assert captured["display"] == 1

    web_search.search_web("q", limit=999)
    assert captured["display"] == 100


def test_search_web_raises_when_credentials_missing(monkeypatch):
    monkeypatch.delenv("NAVER_CLIENT_ID", raising=False)
    monkeypatch.delenv("NAVER_CLIENT_SECRET", raising=False)

    with pytest.raises(web_search.WebSearchError):
        web_search.search_web("q")


def test_search_web_raises_on_error_status(monkeypatch):
    def fake_get(url, *, params, headers, timeout):
        return FakeResponse(401, {"errorMessage": "Invalid auth"})

    monkeypatch.setattr(web_search.httpx, "get", fake_get)
    monkeypatch.setenv("NAVER_CLIENT_ID", "test-id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "test-secret")

    with pytest.raises(web_search.WebSearchError):
        web_search.search_web("q")
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `pytest tests/test_pipeline_common_web_search.py -v`
Expected: FAIL — `src.pipeline_common.web_search` 모듈이 없음

- [ ] **Step 3: 구현**

```python
"""
네이버 검색 API(뉴스) 실시간 검색 — Agent가 위키·원문 모두 근거가 없을 때(_web_search_answer)
쓰는 3차 그라운딩 도구다.

src/collectors/fetchers.py::fetch_naver_news와 같은 API를 호출하지만, 파이프라인 수집용
무거운 처리(원문 페이지 GET, 소스별 config, 요청 간 sleep, 중복 검사)는 전부 뺀다 — 채팅
응답 시간 안에 끝나야 하므로 검색 결과의 title/originallink/description/pubDate만 그대로
반환한다. src/collectors(수집 파이프라인)를 참조하지 않는다 — pipeline_common(Agent 런타임이
참조)이 collectors를 참조하면 레이어 역행이다(document_search.py가 wiki/repository.py를
참조하지 않는 것과 같은 원칙). strip_html도 그래서 여기서 자체 구현한다.
"""
from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass

import httpx

from . import timeutil

_NAVER_SEARCH_URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"
_NAVER_DISPLAY_MIN = 1
_NAVER_DISPLAY_MAX = 100
_TIMEOUT_SEC = 10.0
_HTML_TAG = re.compile(r"<[^>]+>")


class WebSearchError(RuntimeError):
    """네이버 검색 API 호출 실패(자격증명 없음/HTTP 오류/네트워크 오류) 시."""


@dataclass
class WebSearchHit:
    title: str
    url: str
    snippet: str
    published_at: str | None


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    return html.unescape(_HTML_TAG.sub("", text)).strip()


def _clamp_display(limit: int) -> int:
    return max(_NAVER_DISPLAY_MIN, min(_NAVER_DISPLAY_MAX, int(limit)))


def search_web(query: str, limit: int = 5) -> list[WebSearchHit]:
    client_id = os.environ.get("NAVER_CLIENT_ID")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise WebSearchError("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수가 없다")

    try:
        response = httpx.get(
            _NAVER_SEARCH_URL,
            params={"query": query, "display": _clamp_display(limit), "sort": "date"},
            headers={
                "X-NCP-APIGW-API-KEY-ID": client_id,
                "X-NCP-APIGW-API-KEY": client_secret,
            },
            timeout=_TIMEOUT_SEC,
        )
    except Exception as exc:  # noqa: BLE001 - httpx 예외 계층이 넓다
        raise WebSearchError(f"네이버 검색 API 호출 실패: {exc}") from exc

    payload = response.json()
    # status_code를 확인 안 하면 인증 실패(401) 같은 오류 응답도 items가 빈 리스트라
    # "정상 호출인데 0건"으로 조용히 넘어간다 — fetchers.py의 같은 교훈을 그대로 적용.
    if response.status_code >= 400:
        reason = payload.get("errorMessage") or payload.get("error", {}).get("message", "")
        raise WebSearchError(f"네이버 검색 API 응답 오류 {response.status_code}: {reason}")

    hits: list[WebSearchHit] = []
    for entry in payload.get("items", [])[:limit]:
        url = (entry.get("originallink") or entry.get("link") or "").strip()
        if not url:
            continue
        published = timeutil.parse_datetime(entry.get("pubDate"))
        hits.append(
            WebSearchHit(
                title=_strip_html(entry.get("title")),
                url=url,
                snippet=_strip_html(entry.get("description")),
                published_at=published.isoformat() if published else None,
            )
        )
    return hits
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `pytest tests/test_pipeline_common_web_search.py -v`
Expected: PASS (5개 테스트 전부)

- [ ] **Step 5: 커밋**

```bash
git add src/pipeline_common/web_search.py tests/test_pipeline_common_web_search.py
git commit -m "Feat: 네이버 검색 API 실시간 웹 검색 래퍼 추가"
```

---

### Task 2: `WikiTools.search_web` 위임 메서드

**Files:**
- Modify: `src/agent/wiki_tools.py`
- Test: `tests/test_agent_wiki_tools.py`

**Interfaces:**
- Consumes: Task 1의 `web_search.search_web(query, limit) -> list[WebSearchHit]`.
- Produces: `WikiTools.search_web(query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> list[web_search.WebSearchHit]`. Task 4가 이 메서드를 쓴다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_agent_wiki_tools.py`에 기존 `test_search_documents_delegates_to_document_search_module`과 같은 패턴으로 추가:

```python
def test_search_web_delegates_to_web_search_module(monkeypatch):
    tools = WikiTools(workspace_id="ws-1")
    called = {}

    def fake_search_web(query, limit):
        called["query"] = query
        called["limit"] = limit
        return ["fake-hit"]

    monkeypatch.setattr(wiki_tools_module.web_search, "search_web", fake_search_web)

    result = tools.search_web("SK하이닉스", limit=3)

    assert result == ["fake-hit"]
    assert called == {"query": "SK하이닉스", "limit": 3}
```

(`wiki_tools_module`은 이 테스트 파일이 기존에 `import src.agent.wiki_tools as wiki_tools_module` 같은 별칭으로 이미 import하고 있을 것이다 — 파일 상단의 기존 import 방식을 그대로 따라라. `document_search`를 monkeypatch하는 기존 테스트가 어떤 이름으로 모듈을 import하는지 그대로 참고해서 맞춰라.)

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `pytest tests/test_agent_wiki_tools.py::test_search_web_delegates_to_web_search_module -v`
Expected: FAIL — `WikiTools`에 `search_web` 없음

- [ ] **Step 3: 구현**

`src/agent/wiki_tools.py` 상단 import에 추가:
```python
from ..pipeline_common import document_search, web_search
```
(기존 `from ..pipeline_common import document_search` 줄을 이렇게 바꾼다.)

`WikiTools` 클래스에 `read_document` 메서드 바로 뒤에 추가:
```python
    def search_web(self, query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> list[web_search.WebSearchHit]:
        """실시간 웹(네이버 검색)에서 찾는다. 위키·원문 모두 근거가 없을 때(_web_search_answer)만
        쓰는 3차 검색 도구 — workspace 스코프 데이터가 아니라 workspace_id를 받지 않는다."""
        return web_search.search_web(query, limit)
```

모듈 docstring의 "위키에 근거가 없을 때는 search_documents() → read_document()로..." 문장 뒤에 한 줄 추가:
"그마저 없을 때는 search_web()으로 실시간 웹(네이버 검색)에서 찾는다."

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `pytest tests/test_agent_wiki_tools.py -v`
Expected: PASS (전체)

- [ ] **Step 5: 커밋**

```bash
git add src/agent/wiki_tools.py tests/test_agent_wiki_tools.py
git commit -m "Feat: WikiTools.search_web 위임 메서드 추가"
```

---

### Task 3: 인용 식별자 확장 — `Citation.source_url` + `_is_grounded` 일반화

**Files:**
- Modify: `src/agent/core.py`
- Test: `tests/test_agent_core.py`

**Interfaces:**
- Produces: `Citation(quote, document_version_id=None, wiki_slug=None, relevance_score=None, source_url=None)`(필드 순서 변경 — `quote`가 첫 필드), `_is_grounded(citations, seen_identifiers)`가 `document_version_id` 또는 `source_url` 중 있는 쪽으로 검증. `submit_answer` 도구 스키마의 `citations[].document_version_id`가 선택 필드로 바뀌고 `source_url`이 추가됨. 내부 변수명 `seen_document_version_ids` → `seen_identifiers`로 전면 변경(웹 검색 URL도 담으므로).
- Consumes: 없음(순수 리팩터링 + 스키마 확장).

이 태스크는 **위키·원문 두 기존 단계의 동작을 하나도 바꾸지 않는다** — Task 4가 웹 검색 단계를 실제로 추가하기 전에, 공유 그라운딩 메커니즘만 먼저 URL도 받을 수 있게 넓혀두는 순수 확장이다. 기존 24개+ 테스트(Task 1~6, 최종 fix wave까지의 전체 `test_agent_core.py`)는 전부 그대로 통과해야 한다 — `Citation(**c)`가 kwargs 기반이라 필드 순서를 바꿔도 기존 생성 코드(`src/agent/core.py:420`)와 테스트는 영향받지 않는다(저장소 전체에서 `Citation(` 생성이 이 한 곳과 `tests/test_agent_core.py:782`뿐이고 둘 다 kwargs 방식임을 grep으로 이미 확인했다 — 새로 추가하는 테스트도 kwargs로만 생성해라).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_agent_core.py`에 추가(기존 `_is_grounded` 관련 테스트나 `Citation` import 근처에 배치):

```python
def test_is_grounded_accepts_source_url_identifier():
    citation = Citation(quote="인용문", source_url="https://example.com/a")
    assert WikiAgent._is_grounded([citation], {"https://example.com/a"})


def test_is_grounded_rejects_url_not_in_seen_set():
    citation = Citation(quote="인용문", source_url="https://example.com/fake")
    assert not WikiAgent._is_grounded([citation], {"https://example.com/real"})


def test_is_grounded_rejects_citation_with_no_identifier():
    citation = Citation(quote="인용문")  # document_version_id도 source_url도 없음
    assert not WikiAgent._is_grounded([citation], {"https://example.com/a"})


def test_is_grounded_still_validates_document_version_id_identifier():
    """기존 동작 회귀 확인 — document_version_id 경로는 그대로 동작해야 한다."""
    citation = Citation(quote="인용문", document_version_id="doc-1")
    assert WikiAgent._is_grounded([citation], {"doc-1"})
    assert not WikiAgent._is_grounded([citation], {"doc-2"})
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `pytest tests/test_agent_core.py -k test_is_grounded -v`
Expected: `test_is_grounded_accepts_source_url_identifier`와 `test_is_grounded_rejects_citation_with_no_identifier`가 FAIL(현재 `Citation`은 `source_url` 필드가 없어 `TypeError`, `_is_grounded`는 `document_version_id`만 봄). 나머지 두 개는 이미 PASS(기존 동작).

- [ ] **Step 3: 구현**

`src/agent/core.py`의 `Citation` 데이터클래스(현재 위치 근처, `document_version_id: str` / `quote: str` / `wiki_slug: Optional[str] = None` / `relevance_score: Optional[float] = None`)를 전체 교체:

```python
@dataclass
class Citation:
    quote: str
    document_version_id: Optional[str] = None
    wiki_slug: Optional[str] = None
    relevance_score: Optional[float] = None
    source_url: Optional[str] = None
    source_title: Optional[str] = None
    source_published_at: Optional[str] = None
```

`source_title`/`source_published_at`은 모델이 채우는 값이 아니다(`submit_answer` 도구 스키마엔 이 두 필드가 없다 — 모델이 지어낸 제목/날짜를 그대로 믿으면 안 되므로). Task 4의 `_web_search_answer`가 `search_web` 결과에서 얻은 실제 값으로 이 두 필드를 채운다.

`_is_grounded`를 전체 교체:

```python
    @staticmethod
    def _is_grounded(citations: list[Citation], seen_identifiers: set[str]) -> bool:
        """citations가 비어있지 않고, 전부 실제로 조회한 문서/검색 결과를 인용하며
        (document_version_id 또는 source_url 중 있는 쪽으로 seen_identifiers를 검증),
        relevance_score가 있다면 message_citations의 CHECK 제약(0~1) 범위 안인지."""
        if not citations:
            return False
        for citation in citations:
            identifier = citation.document_version_id or citation.source_url
            if identifier is None or identifier not in seen_identifiers:
                return False
            if citation.relevance_score is not None and not (0.0 <= citation.relevance_score <= 1.0):
                return False
        return True
```

`_run_grounded_answer`와 `submit_answer` 처리 분기(약 367~456행) 안에서 `seen_document_version_ids`라는 이름이 쓰이는 모든 위치(로컬 변수 선언, `_is_grounded` 호출 인자, docstring 언급, 그리고 `_wiki_answer`/`_document_answer`의 `handle_read_wiki_page`/`handle_read_document` 클로저 시그니처 `def handle_...(args: dict, seen: set[str])`의 `seen` 사용부는 이름이 이미 `seen`이라 그대로 둬도 됨 — `tool_handlers` 타입 힌트 `Callable[[dict, set[str]], object]`도 그대로)를 `seen_identifiers`로 바꿔라:

- `seen_document_version_ids: set[str] = set()` → `seen_identifiers: set[str] = set()`
- `output = tool_handlers[name](args, seen_document_version_ids)` → `output = tool_handlers[name](args, seen_identifiers)`
- `is_grounded = self._is_grounded(citations, seen_document_version_ids)` → `is_grounded = self._is_grounded(citations, seen_identifiers)`
- docstring 안 "seen_document_version_ids를 in-place로 갱신해야 한다" 문장 → "seen(식별자 집합, document_version_id 또는 URL)을 in-place로 갱신해야 한다"

`TOOLS`의 `submit_answer` 함수 정의(`citations` 파라미터 스키마)를 교체:

```python
                    "citations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "document_version_id": {"type": "string"},
                                "wiki_slug": {"type": "string"},
                                "source_url": {"type": "string"},
                                "quote": {"type": "string"},
                                "relevance_score": {"type": "number"},
                            },
                            "required": ["quote"],
                        },
                    },
```
(기존 `"required": ["document_version_id", "quote"]`를 `"required": ["quote"]`로 바꾸고 `source_url` 속성 추가.)

같은 `submit_answer` 함수의 `answer` 필드 `description` 문자열 바로 위, `citations`에 대한 설명이 필요하면 도구 `description`(`"충분한 근거를 찾았을 때 최종 답변과 근거 목록을 제출한다."`)은 그대로 둬도 된다 — 식별자 규칙은 각 그라운딩 단계의 시스템 프롬프트(`SYSTEM_PROMPT`/`DOCUMENT_ANSWER_SYSTEM_PROMPT`는 `document_version_id`만, Task 4에서 추가할 `WEB_SEARCH_ANSWER_SYSTEM_PROMPT`는 `source_url`만 쓰라고 명시)로 충분히 통제된다.

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `pytest tests/test_agent_core.py -v`
Expected: PASS (기존 테스트 전부 + 신규 4개, 총 45개 — 필드 순서 변경/변수명 변경이 기존 동작을 하나도 안 바꿨는지 전체 스위트로 확인)

- [ ] **Step 5: 커밋**

```bash
git add src/agent/core.py tests/test_agent_core.py
git commit -m "Refactor: 인용 식별자를 document_version_id 외 source_url까지 받도록 확장"
```

---

### Task 4: `_web_search_answer` + `answer(allow_web_search=...)` 게이팅

**Files:**
- Modify: `src/agent/core.py`
- Test: `tests/test_agent_core.py`

**Interfaces:**
- Consumes: Task 2의 `WikiTools.search_web`, Task 3의 `Citation.source_url`/`_is_grounded`.
- Produces: `WikiAgent.answer(question, history=None, *, allow_web_search: bool = False) -> AgentResult`. Task 6(API 레이어)이 이 파라미터를 그대로 넘겨받는다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_agent_core.py`에 추가(기존 `test_answer_uses_document_answer_when_wiki_has_no_answer` 근처 — `FakeDocumentSearchHit`/`FakeDocumentDetail` fake가 이미 있는 것처럼 `FakeWebSearchHit`도 같은 파일 상단에 추가):

```python
@dataclass
class FakeWebSearchHit:
    title: str
    url: str
    snippet: str
    published_at: Optional[str]


def test_answer_does_not_try_web_search_by_default(agent, wiki_tools, monkeypatch):
    """allow_web_search=False(기본값)면 원문 그라운딩 실패 시 그 자리에서 멈춘다 —
    웹 검색도 LLM 폴백도 시도하지 않는다."""
    wiki_tools.search_wiki_pages.return_value = []
    wiki_tools.search_documents.return_value = []
    call_count = {"n": 0}

    def fake_call_model(messages, use_tools=True, tools=None):
        call_count["n"] += 1
        return tool_call_response(("call-1", "submit_no_answer", {"reason": "근거 없음"}))

    monkeypatch.setattr(agent, "_call_model", fake_call_model)

    result = agent.answer("질문")  # allow_web_search 기본값 False

    assert result.has_answer is False
    assert result.is_llm_fallback is False
    # 위키 1라운드 + 원문 1라운드 = 2회. 웹 검색/LLM 폴백이 시도됐다면 3회 이상이어야 한다.
    assert call_count["n"] == 2


def test_answer_tries_web_search_when_allowed(agent, wiki_tools, monkeypatch):
    wiki_tools.search_wiki_pages.return_value = []
    wiki_tools.search_documents.return_value = []
    wiki_tools.search_web.return_value = [
        FakeWebSearchHit(
            title="SK하이닉스 ADR 상장",
            url="https://example.com/a",
            snippet="SK하이닉스가 나스닥에 ADR을 상장했다.",
            published_at="2026-08-07T09:00:00+09:00",
        )
    ]
    citation = {"source_url": "https://example.com/a", "quote": "ADR을 상장했다"}
    responses = [
        tool_call_response(("call-1", "submit_no_answer", {"reason": "위키 근거 없음"})),
        tool_call_response(("call-2", "submit_no_answer", {"reason": "원문 근거 없음"})),
        tool_call_response(("call-3", "search_web", {"query": "SK하이닉스 ADR"})),
        tool_call_response(("call-4", "submit_answer", {
            "answer": "SK하이닉스가 나스닥에 ADR을 상장했다.[1]",
            "citations": [citation],
        })),
    ]
    monkeypatch.setattr(agent, "_call_model", MagicMock(side_effect=responses))

    result = agent.answer("SK하이닉스 ADR 상장이 뭐야?", allow_web_search=True)

    assert result.has_answer is True
    assert result.is_llm_fallback is False
    assert result.citations[0].source_url == "https://example.com/a"
    assert result.citations[0].document_version_id is None  # DB 행이 아니므로 항상 None
    assert result.citations[0].source_title == "SK하이닉스 ADR 상장"  # search_web 결과에서 채움
    assert result.citations[0].source_published_at == "2026-08-07T09:00:00+09:00"


def test_answer_falls_back_to_llm_when_web_search_also_fails(agent, wiki_tools, monkeypatch):
    wiki_tools.search_wiki_pages.return_value = []
    wiki_tools.search_documents.return_value = []
    wiki_tools.search_web.return_value = []
    responses = [
        tool_call_response(("call-1", "submit_no_answer", {"reason": "위키 근거 없음"})),
        tool_call_response(("call-2", "submit_no_answer", {"reason": "원문 근거 없음"})),
        tool_call_response(("call-3", "submit_no_answer", {"reason": "웹 검색 근거 없음"})),
        plain_text_response("일반 지식으로는 이렇습니다."),
    ]
    monkeypatch.setattr(agent, "_call_model", MagicMock(side_effect=responses))

    result = agent.answer("아주 최신 질문", allow_web_search=True)

    assert result.has_answer is True
    assert result.is_llm_fallback is True
    assert result.citations == []


def test_web_search_answer_passes_web_search_tools_not_document_tools(agent, wiki_tools, monkeypatch):
    wiki_tools.search_web.return_value = []
    captured_tools = []

    def fake_call_model(messages, use_tools=True, tools=None):
        captured_tools.append(tools)
        return tool_call_response(("call-1", "submit_no_answer", {"reason": "근거 없음"}))

    monkeypatch.setattr(agent, "_call_model", fake_call_model)

    agent._web_search_answer("질문")

    assert captured_tools[0] is core.WEB_SEARCH_TOOLS
    assert captured_tools[0] is not core.DOCUMENT_TOOLS
    assert captured_tools[0] is not core.TOOLS
```

(`core`는 이 테스트 파일이 이미 `from src.agent import core` 같은 형태로 import하고 있을 것이다 — 기존 `test_document_answer_passes_document_tools_not_wiki_tools_to_model` 테스트가 쓰는 import 별칭을 그대로 따라라. `agent`/`wiki_tools` fixture, `tool_call_response`/`plain_text_response` 헬퍼, `MagicMock`은 이미 파일에 있는 기존 헬퍼를 재사용해라 — 새로 만들지 마라.)

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `pytest tests/test_agent_core.py -k "web_search" -v`
Expected: FAIL — `answer()`가 `allow_web_search` 파라미터를 모름, `_web_search_answer`/`WEB_SEARCH_TOOLS` 없음, `wiki_tools.search_web`이 Mock에 자동 생성되긴 하지만 실제 위임 경로가 없음

- [ ] **Step 3: 구현**

`src/agent/core.py`에 `DOCUMENT_TOOLS` 정의 바로 뒤, `Citation` 데이터클래스 앞에 추가:

```python
# 위키에도, 수집된 원문에도 근거가 없어서 사용자가 명시적으로 "웹에서 찾아줘"를
# 요청했을 때만(WikiAgent.answer(allow_web_search=True)) 쓰는 3차 그라운딩 단계.
WEB_SEARCH_ANSWER_SYSTEM_PROMPT = """\
너는 myWiki의 답변 Agent다. 위키에도, 수집된 원문(뉴스+DART)에도 근거가 없어서
실시간 웹 검색으로 마지막으로 근거를 찾는 단계다. 규칙:
1. search_web으로 찾은 검색 결과(제목·요약·링크)에 실제로 있는 내용만 근거로
   답변해라. 사전 지식이나 추측으로 빈틈을 채우지 마라. 검색 결과 요약이 짧아
   구체적 내용이 부족하면, 그 부족한 부분은 답변에 넣지 마라.
2. 답을 뒷받침할 근거를 찾았으면 submit_answer를 호출해라. 문장마다 어떤 근거
   (citations)를 썼는지 반드시 포함하고, citations의 source_url은 search_web
   결과에서 실제로 본 url 중에서만 골라라(지어내지 마라). document_version_id는
   비워둬라 — DB 문서가 아니다. 답변 본문에 쓰는 근거 번호 [N]은 반드시 citations
   배열의 N번째(1부터 시작) 항목과 정확히 대응해야 한다 — citations에 없는 번호는
   절대 쓰지 마라.
3. 근거를 찾지 못했거나 근거가 불충분하면 submit_answer 대신 반드시
   submit_no_answer를 호출해라.
4. 톤은 직접적이고 전문적으로, 가벼운 대화체는 쓰지 마라.
"""

WEB_SEARCH_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": (
                "질문 키워드로 실시간 웹(네이버 검색)을 찾는다. 위키·수집된 원문 어디에도 "
                "근거가 없을 때만 쓰는 최후 수단 — 검색 결과의 제목·요약·링크·게시일을 반환한다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "질문에서 뽑은 검색 키워드"},
                },
                "required": ["query"],
            },
        },
    },
    _SUBMIT_ANSWER_TOOL,
    _SUBMIT_NO_ANSWER_TOOL,
]
```

`WikiAgent.answer()`를 전체 교체:

```python
    def answer(
        self, question: str, history: Optional[list[dict]] = None, *, allow_web_search: bool = False
    ) -> AgentResult:
        """4단계로 근거를 찾는다: 위키(_wiki_answer) -> 수집된 원문(_document_answer) ->
        (allow_web_search일 때만) 실시간 웹 검색(_web_search_answer) -> 위키 근거 없이
        일반 지식(_llm_fallback_answer). 앞 세 그라운딩 단계는 예외가 나도(OpenRouter
        응답 이상 등) 그대로 새 나가지 않고 다음 단계로 넘어간다 — 500으로 죽는 대신
        최소한 다음 단계 결과(또는 일반 지식 폴백)라도 낸다.

        allow_web_search=False(기본값)면 원문 그라운딩 실패 시 그 자리에서 근거 없음을
        반환한다 — 웹 검색도 일반 지식 폴백도 시도하지 않는다(2턴 흐름의 1턴). 사용자가
        명시적으로 "웹에서 찾아줘"를 요청했을 때만(allow_web_search=True, 2턴) 웹 검색을
        시도하고, 그것도 실패하면 자동으로 일반 지식 폴백까지 이어간다 — 한 번 요청한
        뒤라 추가 확인 없이 진행한다."""
        result = self._safe_run(
            self._wiki_answer, question, history, no_answer_reason="위키 근거 조회 중 오류 발생"
        )
        if result.has_answer:
            return result
        result = self._safe_run(
            self._document_answer, question, history, no_answer_reason="원문 문서 조회 중 오류 발생"
        )
        if result.has_answer or not allow_web_search:
            return result
        result = self._safe_run(
            self._web_search_answer, question, history, no_answer_reason="웹 검색 중 오류 발생"
        )
        if result.has_answer:
            return result
        fallback = self._llm_fallback_answer(question, history)
        return fallback if fallback is not None else result
```

`_document_answer` 메서드 바로 뒤에 `_web_search_answer` 추가:

```python
    def _web_search_answer(self, question: str, history: Optional[list[dict]] = None) -> AgentResult:
        # search_web 결과의 (title, published_at)을 url로 찾아올 수 있게 기억해둔다 —
        # 모델은 citations에 source_url만 채우고 title/published_at은 안 채우므로
        # (submit_answer 스키마에 그 두 필드가 없다), 저장할 값은 여기서 직접 채운다.
        hit_by_url: dict[str, tuple[str, Optional[str]]] = {}

        def handle_search_web(args: dict, seen: set[str]) -> object:
            hits = self.wiki_tools.search_web(args["query"])
            # 원문 단계와 다르게 read 단계가 따로 없다 — search_web 결과 자체가 그라운딩에
            # 쓸 내용(title/snippet) 전부라, 검색 시점에 바로 seen에 URL을 채운다.
            seen.update(h.url for h in hits)
            hit_by_url.update({h.url: (h.title, h.published_at) for h in hits})
            return [h.__dict__ for h in hits]

        result = self._run_grounded_answer(
            question,
            history,
            system_prompt=WEB_SEARCH_ANSWER_SYSTEM_PROMPT,
            tools=WEB_SEARCH_TOOLS,
            tool_handlers={"search_web": handle_search_web},
        )
        # submit_answer 스키마를 다른 단계와 공유하므로 document_version_id/wiki_slug
        # 필드 자체를 막지 못한다 — 모델이 실수로 채워 보내도 여기서 강제로 지운다
        # (_document_answer의 wiki_slug=None 강제와 같은 방어 패턴). source_title/
        # source_published_at은 hit_by_url에서 실제 검색 결과 값으로 채운다.
        if result.has_answer and result.citations:
            def _enrich(c: Citation) -> Citation:
                title, published_at = hit_by_url.get(c.source_url, (None, None))
                return replace(
                    c,
                    document_version_id=None,
                    wiki_slug=None,
                    source_title=title,
                    source_published_at=published_at,
                )

            result.citations = [_enrich(c) for c in result.citations]
        return result
```

**기존 LLM 폴백 테스트 7개를 수정해라 — 이 게이팅 도입으로 전부 깨진다.** `answer()`가 이제
`allow_web_search=True`일 때만 원문 실패 이후로 진행하므로, "폴백까지 자동으로 이어진다"고
가정한 기존 테스트는 `agent.answer(...)` 호출에 `allow_web_search=True`를 추가해야 한다.
이 중 순서 고정 리스트(`MagicMock(side_effect=[...])`)를 쓰는 테스트는 웹 검색 라운드용
`submit_no_answer` 응답을 리스트 중간에 하나 더 끼워 넣어야 한다(안 넣으면 리스트가
조기 소진돼 `_llm_fallback_answer`가 `StopIteration`을 삼켜 우연히 통과하는 것처럼 보일 수
있다 — 명시적으로 넣어서 실제로 웹 검색 단계를 거치는 걸 검증해라). `use_tools`/`call_count`
기반으로 반응하는 fake(고정 리스트가 아닌 것)는 라운드가 늘어도 그대로 동작하므로
`allow_web_search=True` 추가만 하면 된다.

1. `test_answer_falls_back_to_llm_when_wiki_answer_raises`(383행) — `fake_call_model`이
   `use_tools` 분기 방식(고정 리스트 아님)이라 그대로 둬도 된다. `agent.answer("질문")`
   (402행)을 `agent.answer("질문", allow_web_search=True)`로 바꿔라.

2. `test_answer_falls_back_to_llm_when_wiki_and_documents_both_have_no_answer`(549행) —
   `responses` 리스트에 항목을 하나 추가:
   ```python
       responses = [
           tool_call_response(("call-1", "submit_no_answer", {"reason": "위키에 관련 문서 없음"})),
           tool_call_response(("call-2", "submit_no_answer", {"reason": "원문에도 관련 문서 없음"})),
           tool_call_response(("call-3", "submit_no_answer", {"reason": "웹 검색에도 근거 없음"})),
           plain_text_response("SK하이닉스는 국내 반도체 기업이다."),
       ]
   ```
   `agent.answer("아무 질문")`(557행)을 `agent.answer("아무 질문", allow_web_search=True)`로.

3. `test_answer_falls_back_to_llm_when_document_answer_raises`(564행) — `fake_call_model`이
   `call_count`/`use_tools` 기반 분기(고정 리스트 아님)라 그대로 둬도 된다.
   `agent.answer("질문")`(579행)을 `agent.answer("질문", allow_web_search=True)`로.

4. `test_answer_falls_back_to_llm_when_no_wiki_answer`(591행) — `responses` 리스트에
   항목 추가:
   ```python
       responses = [
           tool_call_response(("call-1", "submit_no_answer", {"reason": "위키에 관련 문서 없음"})),
           tool_call_response(("call-2", "submit_no_answer", {"reason": "원문에도 관련 문서 없음"})),
           tool_call_response(("call-3", "submit_no_answer", {"reason": "웹 검색에도 근거 없음"})),
           plain_text_response("HBM은 여러 D램을 수직으로 쌓아 대역폭을 늘린 고대역폭 메모리다."),
       ]
   ```
   `agent.answer("HBM이 뭐야?")`(600행)을 `agent.answer("HBM이 뭐야?", allow_web_search=True)`로.

5. `test_llm_fallback_answer_calls_model_without_tools`(631행) — `responses` 리스트에
   항목 추가:
   ```python
       responses = [
           tool_call_response(("call-1", "submit_no_answer", {"reason": "위키에 관련 문서 없음"})),
           tool_call_response(("call-2", "submit_no_answer", {"reason": "원문에도 관련 문서 없음"})),
           plain_text_response("일반 지식 답변"),
       ]
   ```
   (기존엔 2개뿐이었다 — 원문 단계용 `submit_no_answer`를 추가해서 위키/원문/웹검색 세
   단계가 각각 정직하게 실행되게 한다.) `agent.answer("아무 질문")`(641행)을
   `agent.answer("아무 질문", allow_web_search=True)`로.

6. `test_answer_keeps_no_answer_when_llm_fallback_raises`(647행) — `fake_call_model`이
   `use_tools` 분기 방식(고정 리스트 아님)이라 그대로 둬도 된다.
   `agent.answer("아무 질문")`(662행)을 `agent.answer("아무 질문", allow_web_search=True)`로.

7. `test_answer_keeps_no_answer_when_llm_fallback_returns_empty_text`(669행) —
   `responses` 리스트에 항목 추가:
   ```python
       responses = [
           tool_call_response(("call-1", "submit_no_answer", {"reason": "근거 없음"})),
           tool_call_response(("call-2", "submit_no_answer", {"reason": "원문에도 관련 문서 없음"})),
           tool_call_response(("call-3", "submit_no_answer", {"reason": "웹 검색에도 근거 없음"})),
           plain_text_response("   "),
       ]
   ```
   `agent.answer("아무 질문")`(680행)을 `agent.answer("아무 질문", allow_web_search=True)`로.
   (주석 "최종 결과는 마지막으로 실행된 단계(원문 단계)의 사유로 남는다"도 "마지막으로
   실행된 단계(웹 검색 단계)의 사유로 남는다"로 고치고, 최종 `no_answer_reason`이
   `"웹 검색에도 근거 없음"`이 되는지 assert를 하나 추가해라.)

`test_answer_does_not_fall_back_when_wiki_answer_found`(609행)은 위키 단계에서 바로
근거를 찾아 끝나므로(원문/웹검색/폴백 어느 것도 실행 안 됨) 수정할 필요 없다.

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `pytest tests/test_agent_core.py -v`
Expected: PASS (전체 — 위 7개 수정 반영, 기존 테스트가 `agent.answer(...)`를 위치 인자로만 호출한다면 `allow_web_search`가 키워드 전용(`*` 뒤)이라 그 외 테스트는 영향 없어야 한다)

- [ ] **Step 5: 커밋**

```bash
git add src/agent/core.py tests/test_agent_core.py
git commit -m "Feat: 웹 검색 그라운딩 단계(allow_web_search 옵트인) 추가"
```

---

### Task 5: DB 스키마 확장 — `message_citations` + `CitationOut`

**Files:**
- Create: `supabase/migrations/20260808010000_message_citations_web_search.sql`
- Modify: `src/api/db.py`, `src/api/schemas.py`, `docs/architecture/myWiki_v2_supabase.sql`
- Test: `tests/test_chat_sessions.py`(또는 이 저장소의 기존 `db.py` 관련 API 테스트 파일 — `save_agent_message`/`update_agent_message`/`list_message_citations`를 이미 테스트하는 파일을 찾아 그 옆에 추가해라)

**Interfaces:**
- Consumes: Task 3의 `Citation.source_url`.
- Produces: `message_citations.document_version_id`가 nullable, `source_url`/`source_title`/`published_at` 컬럼 추가. `CitationOut.document_version_id: Optional[str]`. Task 6이 여기 의존하지 않는다(API 레이어는 `agent.answer()` 호출만 관여) — 하지만 Task 7의 전체 검증이 이 저장 왕복에 의존한다.

- [ ] **Step 1: 마이그레이션 작성**

`supabase/migrations/20260808010000_message_citations_web_search.sql`:
```sql
ALTER TABLE public.message_citations ALTER COLUMN document_version_id DROP NOT NULL;

ALTER TABLE public.message_citations ADD COLUMN IF NOT EXISTS source_url TEXT;
ALTER TABLE public.message_citations ADD COLUMN IF NOT EXISTS source_title TEXT;
ALTER TABLE public.message_citations ADD COLUMN IF NOT EXISTS published_at TEXT;

ALTER TABLE public.message_citations
ADD CONSTRAINT ck_mc_has_identifier CHECK (document_version_id IS NOT NULL OR source_url IS NOT NULL);
```

Supabase SQL Editor로 수동 적용해라(이 저장소의 기존 마이그레이션 관례 — `is_llm_fallback` 컬럼 추가 때와 동일하게 "수동 적용 완료"를 커밋 메시지에 남겨라). 로컬 테스트는 전부 FakeSupabase 기반이라 이 적용과 무관하게 통과한다.

- [ ] **Step 2: 실패하는 테스트 작성**

기존 `save_agent_message`/`list_message_citations` 테스트가 있는 파일(예: `tests/test_chat_sessions.py` — 실제 파일은 `grep -rn "save_agent_message" tests/`로 확인해라)에 추가:

```python
def test_save_agent_message_persists_web_search_citation_without_document_version_id():
    """document_version_id가 없는(웹 검색) citation도 저장돼야 한다."""
    result = AgentResult(
        has_answer=True,
        answer="SK하이닉스가 ADR을 상장했다.[1]",
        citations=[Citation(
            quote="ADR을 상장했다",
            source_url="https://example.com/a",
        )],
        model_name="test-model",
    )
    # (기존 save_agent_message 테스트가 세션/메시지를 어떻게 준비하는지 그대로 따라
    # session_id를 마련하고 db.save_agent_message(session_id, result)를 호출해라)

    saved = db.save_agent_message(session_id, result)
    citations = db.list_message_citations(saved["id"])

    assert len(citations) == 1
    assert citations[0]["document_version_id"] is None
    assert citations[0]["source_url"] == "https://example.com/a"
    assert citations[0]["document_title"] is None  # source_title을 안 채웠으므로


def test_enrich_message_citations_skips_join_for_web_search_rows():
    """document_version_id가 None인 행은 documents/document_versions 조인 없이,
    저장 시점에 채운 source_title을 document_title로 그대로 통과시킨다."""
    rows = [{
        "document_version_id": None,
        "source_url": "https://example.com/a",
        "source_title": "SK하이닉스 ADR 상장",
        "published_at": "2026-08-07T09:00:00+09:00",
        "quoted_text": "ADR을 상장했다",
        "relevance_score": None,
        "citation_order": 1,
    }]

    enriched = db._enrich_message_citations(rows)

    assert enriched[0]["document_title"] == "SK하이닉스 ADR 상장"
    assert enriched[0]["source_url"] == "https://example.com/a"
    assert enriched[0]["source_name"] is None
    assert enriched[0]["reliability_score"] is None
```

실제 세션/메시지 준비 보일러플레이트는 같은 파일의 기존 `save_agent_message` 테스트를 그대로 참고해서 맞춰라 — FakeSupabase 패턴인지 실제 테스트 DB 픽스처인지 그 파일의 기존 관례를 따른다.

- [ ] **Step 3: 테스트 실행해서 실패 확인**

Run: `pytest tests/test_chat_sessions.py -k "web_search" -v`(정확한 파일명은 Step 2에서 확인한 것으로)
Expected: FAIL — `source_url`/`source_title`/`published_at`을 안 넣어서 저장 안 됨, `_enrich_message_citations`가 `document_version_id=None`인 행도 조인하려다 에러나거나 `document_title=None`으로 덮어씀

- [ ] **Step 4: 구현**

`src/api/db.py`의 `save_agent_message`(약 353~365행) citation row 생성 부분 교체 — `Citation`의 `source_title`/`source_published_at`(Task 3·4에서 이미 추가됨)을 그대로 옮겨 쓴다:

```python
    if result.has_answer and result.citations:
        rows = [
            {
                "message_id": message["id"],
                "document_version_id": c.document_version_id,
                "source_url": c.source_url,
                "source_title": c.source_title,
                "published_at": c.source_published_at,
                "quoted_text": c.quote,
                "relevance_score": c.relevance_score,
                "citation_order": i,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            for i, c in enumerate(result.citations, start=1)
        ]
        db.table("message_citations").insert(rows).execute()
```

`update_agent_message`(약 393~406행)의 동일한 row 생성 블록도 똑같이 교체해라(지금은 `document_version_id`/`quoted_text`/`relevance_score`/`citation_order`만 있음 — 위와 같이 `source_url`/`source_title`/`published_at` 3개 필드 추가).

`_enrich_message_citations`(약 411~470행)를 교체 — 함수 시작부에서 `document_version_id`가 `None`인 행을 걸러내고 조인 대상에서 뺀다:

```python
def _enrich_message_citations(rows: list[dict]) -> list[dict]:
    """message_citations 원본 행에 문서 제목·매체명·게시일·개별 신뢰도를 붙인다.

    document_version_id가 있는 행(위키/원문 근거)만 documents/document_versions를
    조인해서 채운다. document_version_id가 없는 행(웹 검색 근거)은 저장 시점에 이미
    자기 행에 source_url/source_title/published_at을 직접 채워뒀으므로(조인할 DB
    행 자체가 없음) 그대로 통과시키고 document_title 필드명만 맞춰준다.
    """
    if not rows:
        return rows

    joinable_rows = []
    for row in rows:
        if row["document_version_id"] is None:
            row["document_title"] = row.pop("source_title", None)
            row["source_name"] = None
            row["reliability_score"] = None
        else:
            joinable_rows.append(row)

    if not joinable_rows:
        return rows

    document_version_ids = list({r["document_version_id"] for r in joinable_rows})
    db = get_supabase()

    versions_res = (
        db.table("document_versions")
        .select("id, document_id")
        .in_("id", document_version_ids)
        .execute()
    )
    document_id_by_version = {row["id"]: row["document_id"] for row in versions_res.data}

    document_ids = list({doc_id for doc_id in document_id_by_version.values() if doc_id})
    documents_by_id: dict[str, dict] = {}
    if document_ids:
        documents_res = (
            db.table("documents")
            .select("id, title, canonical_url, published_at, source_id")
            .in_("id", document_ids)
            .execute()
        )
        documents_by_id = {row["id"]: row for row in documents_res.data}

    source_ids = list({row["source_id"] for row in documents_by_id.values() if row.get("source_id")})
    source_name_by_id: dict[str, str] = {}
    if source_ids:
        sources_res = db.table("sources").select("id, name").in_("id", source_ids).execute()
        source_name_by_id = {row["id"]: row["name"] for row in sources_res.data}

    analysis_res = (
        db.table("document_analysis_results")
        .select("document_version_id, reliability_score")
        .in_("document_version_id", document_version_ids)
        .execute()
    )
    reliability_by_version = {
        row["document_version_id"]: row["reliability_score"]
        for row in analysis_res.data
        if row.get("reliability_score") is not None
    }

    for row in joinable_rows:
        document_id = document_id_by_version.get(row["document_version_id"])
        document = documents_by_id.get(document_id) if document_id else None
        row["document_title"] = document.get("title") if document else None
        row["source_url"] = document.get("canonical_url") if document else None
        row["published_at"] = document.get("published_at") if document else None
        row["source_name"] = source_name_by_id.get(document.get("source_id")) if document else None
        row["reliability_score"] = reliability_by_version.get(row["document_version_id"])
    return rows
```

`src/api/schemas.py`의 `CitationOut.document_version_id: str`을 `document_version_id: Optional[str] = None`으로 바꿔라.

`docs/architecture/myWiki_v2_supabase.sql`(참고용 통합 스키마 문서)도 같이 갱신해라 — 이 프로젝트는 마이그레이션과 이 파일을 계속 동기화해온 관례가 있다:
- `CREATE TABLE message_citations`의 `document_version_id UUID NOT NULL`을 `document_version_id UUID`로(NOT NULL 제거), `qmd_uri`/`source_start_line`/`source_end_line` 다음 줄에 `source_url TEXT,`/`source_title TEXT,`/`published_at TEXT,` 추가.
- `ck_mc_relevance` CHECK 제약 바로 아래 줄에 `ALTER TABLE message_citations ADD CONSTRAINT ck_mc_has_identifier CHECK (document_version_id IS NOT NULL OR source_url IS NOT NULL);` 추가.

- [ ] **Step 5: 테스트 실행해서 통과 확인**

Run: `pytest tests/test_chat_sessions.py tests/test_agent_core.py -v`
Expected: PASS (전체 — Task 4에서 추가한 웹 검색 테스트에 `source_title` assert를 보강했다면 그것도 통과해야 한다)

- [ ] **Step 6: 커밋**

```bash
git add supabase/migrations/20260808010000_message_citations_web_search.sql src/api/db.py src/api/schemas.py src/agent/core.py tests/test_chat_sessions.py tests/test_agent_core.py docs/architecture/myWiki_v2_supabase.sql
git commit -m "Feat: message_citations가 웹 검색 인용(document_version_id 없는 source_url)을 저장하도록 확장 (마이그레이션 Supabase SQL Editor 수동 적용 완료)"
```

(SQL Editor에 실제로 적용한 뒤에만 이 커밋 메시지 문구를 써라 — 적용 안 했으면 "적용 필요"로 남기고 사용자에게 알려라.)

---

### Task 6: API 레이어 — `regenerate` 엔드포인트에 `allow_web_search` 쿼리 파라미터

**Files:**
- Modify: `src/api/main.py`
- Test: `tests/test_chat_sessions.py`(또는 `main.py`의 `regenerate_message`를 이미 테스트하는 파일)

**Interfaces:**
- Consumes: Task 4의 `WikiAgent.answer(allow_web_search=...)`.
- Produces: `POST /chat/sessions/{session_id}/messages/{message_id}/regenerate?allow_web_search=true`.

- [ ] **Step 1: 실패하는 테스트 작성**

기존 `regenerate_message`(재생성) 엔드포인트 테스트 옆에 추가(파일은 `grep -rn "regenerate" tests/`로 확인 — TestClient 기반이면 아래 형태, 아니면 그 파일의 기존 관례를 따라라):

```python
def test_regenerate_passes_allow_web_search_to_agent(client, monkeypatch, ...):
    """?allow_web_search=true가 agent.answer()에 allow_web_search=True로 전달돼야 한다."""
    captured = {}

    class FakeAgent:
        def __init__(self, *_a, **_kw): pass
        def answer(self, question, history=None, *, allow_web_search=False):
            captured["allow_web_search"] = allow_web_search
            return AgentResult(has_answer=False, no_answer_reason="테스트")

    monkeypatch.setattr(main_module, "WikiAgent", FakeAgent)

    # (기존 재생성 테스트가 세션/메시지를 준비하는 방식 그대로 session_id/message_id 마련)
    client.post(f"/chat/sessions/{session_id}/messages/{message_id}/regenerate?allow_web_search=true", ...)

    assert captured["allow_web_search"] is True


def test_regenerate_defaults_allow_web_search_to_false(client, monkeypatch, ...):
    captured = {}

    class FakeAgent:
        def __init__(self, *_a, **_kw): pass
        def answer(self, question, history=None, *, allow_web_search=False):
            captured["allow_web_search"] = allow_web_search
            return AgentResult(has_answer=False, no_answer_reason="테스트")

    monkeypatch.setattr(main_module, "WikiAgent", FakeAgent)

    client.post(f"/chat/sessions/{session_id}/messages/{message_id}/regenerate", ...)  # 쿼리 파라미터 없음

    assert captured["allow_web_search"] is False
```

세션/메시지 준비, 인증 mock, `client` fixture는 기존 `regenerate` 테스트(같은 파일에 이미 있을 것)를 그대로 복사해서 맞춰라 — 새 패턴을 만들지 마라.

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `pytest tests/test_chat_sessions.py -k "allow_web_search" -v`
Expected: FAIL — `regenerate_message`가 `allow_web_search` 쿼리 파라미터를 안 받음

- [ ] **Step 3: 구현**

`src/api/main.py`의 `regenerate_message` 함수 시그니처와 `agent.answer(...)` 호출부를 교체:

```python
@app.post("/chat/sessions/{session_id}/messages/{message_id}/regenerate", response_model=ChatMessageOut)
def regenerate_message(
    session_id: str,
    message_id: str,
    allow_web_search: bool = False,
    profile: dict = Depends(get_current_user),
):
    """다시 생성 — 같은 질문으로 Agent를 다시 호출해 답변 행을 그 자리에서 교체한다.
    (프론트가 새 Q&A를 아래에 덧붙이는 방식도 가능하지만, 그러면 새로고침 시 옛 답변이
    DB에 남아 있어 다시 나타난다 — 진짜 "다시 생성"이 되려면 in-place 교체가 필요하다.)

    allow_web_search=true는 1턴(위키+원문)에서 근거를 못 찾은 뒤, 사용자가 명시적으로
    "웹에서 찾아줘"를 요청했을 때 프론트가 이 엔드포인트를 다시 호출하며 붙이는
    쿼리 파라미터다 — 웹 검색 그라운딩(그리고 그것도 실패하면 일반 지식 폴백까지)을
    허용한다."""
    workspace_id = _require_workspace(profile)
    message = _get_owned_message(session_id, message_id, workspace_id, profile["id"])

    user_message = db.get_preceding_user_message(session_id, message["created_at"])
    if user_message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="짝이 되는 질문 메시지를 찾을 수 없음")

    history = [
        {"role": "user" if m["role"] == "user" else "assistant", "content": m["content"]}
        for m in db.list_chat_messages(session_id)
        if m["id"] not in (user_message["id"], message_id)
    ]

    wiki_tools = WikiTools(workspace_id=workspace_id)
    agent = WikiAgent(wiki_tools)
    result = agent.answer(user_message["content"], history=history, allow_web_search=allow_web_search)

    updated = db.update_agent_message(message_id, result)
    return _to_message_out(updated)
```

(FastAPI는 경로에 없는 `bool` 파라미터를 자동으로 쿼리 파라미터로 취급한다 — 새 Pydantic 요청 모델을 만들 필요 없다.)

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `pytest tests/test_chat_sessions.py -v`
Expected: PASS (전체)

- [ ] **Step 5: 커밋**

```bash
git add src/api/main.py tests/test_chat_sessions.py
git commit -m "Feat: regenerate 엔드포인트에 allow_web_search 쿼리 파라미터 추가"
```

---

### Task 7: 전체 회귀 + 실제 DB/API로 최종 검증

**Files:** 없음(검증 전용 태스크)

**Interfaces:** 없음

- [ ] **Step 1: 전체 테스트 스위트 실행**

Run: `pytest tests/ -q`
Expected: 이 플랜에서 추가/수정한 파일들의 테스트가 전부 통과하고, 그 외 실패가 있다면 `git stash`로 baseline과 비교해 이 브랜치 작업 전부터 있던 무관 실패인지 확인한다(이전 `document-grounded-fallback` 플랜의 Task 6에서 이미 확인된 12건 — `pipeline/test_pending_documents.py` 3건, `test_analysis_*_missing_api_key` 4건, `test_report_assembler.py`/`test_report_interface.py` 5건 — 과 정확히 같은 목록인지 대조한다).

- [ ] **Step 2: 실제 네이버 검색 API로 웹 검색 자체 검증**

```bash
python -c "
import sys
sys.path.insert(0, r'C:\myWIKI\SK_Suni_5th_project-myWiki')
from dotenv import load_dotenv
load_dotenv(r'C:\myWIKI\SK_Suni_5th_project-myWiki\.env')
from src.pipeline_common import web_search

hits = web_search.search_web('SK하이닉스 HBM4', limit=3)
for h in hits:
    print(h.title, '|', h.url, '|', h.published_at)
"
```
Expected: 실제 네이버 뉴스 검색 결과 3건이 크래시 없이 출력됨(자격증명은 워크트리 `.env`에 이미 있음).

- [ ] **Step 3: 실제 DB로 전체 4단계 경로 재현**

```bash
python -c "
import sys
sys.path.insert(0, r'C:\myWIKI\SK_Suni_5th_project-myWiki')
from dotenv import load_dotenv
load_dotenv(r'C:\myWIKI\SK_Suni_5th_project-myWiki\.env')
from src.agent.core import WikiAgent
from src.agent.wiki_tools import WikiTools

tools = WikiTools(workspace_id='<실제 workspace_id>')
agent = WikiAgent(tools)

# 1턴: 위키/원문에 없을 법한 질문으로 has_answer=False가 그 자리에서 오는지 확인
r1 = agent.answer('위키에도 원문에도 없을 법한 아주 최신 질문')
print('1턴:', r1.has_answer, r1.is_llm_fallback)

# 2턴: 같은 질문에 allow_web_search=True로 재시도 — 웹 검색이 실제로 도는지
r2 = agent.answer('위키에도 원문에도 없을 법한 아주 최신 질문', allow_web_search=True)
print('2턴:', r2.has_answer, r2.is_llm_fallback)
for c in r2.citations:
    print('citation:', c.document_version_id, c.source_url, c.source_title)
"
```
Expected: 1턴은 `has_answer=False`에서 멈춤(크래시 없음). 2턴은 웹 검색이 실제로 실행돼(네이버 API 호출 로그 또는 결과로 확인) `has_answer=True`(웹 검색 근거, `source_url` 채워짐, `document_version_id=None`)이거나, 검색으로도 못 찾으면 `is_llm_fallback=True`로 자연스럽게 떨어짐 — 어느 쪽이든 크래시 없음.

- [ ] **Step 4: `save_agent_message` 왕복까지 실제 DB로 확인**

Step 3의 `r2`가 `has_answer=True`이고 `citations`가 있는 경우, 실제 채팅 세션에 저장 → `list_message_citations`로 재조회까지 해서 `document_version_id=None`, `source_url`/`document_title` 채워짐을 확인한다(테스트 데이터는 확인 후 정리). `r2`가 근거를 못 찾아 `is_llm_fallback=True`로 떨어졌다면, 이 단계는 원하는 질문을 바꿔가며 웹 검색 그라운딩이 실제로 성공하는 케이스를 최소 1번은 재현해라 — 저장 경로가 한 번도 실제 DB로 검증 안 된 채 끝나면 안 된다.

- [ ] **Step 5: 최종 커밋 없음 — Task 1~6의 커밋이 이미 완료 상태**

문제를 발견하면 해당 Task로 돌아가 수정 후 그 Task의 커밋을 새로 만든다(이미 만든 커밋을 amend하지 않는다).

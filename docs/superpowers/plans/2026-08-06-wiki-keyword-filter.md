# 위키 페이지 연동 키워드 생성 + 키워드 검색/필터 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 모든 published 위키 페이지에 `src/categories/keywords.py`의 122개 사전 안에서 LLM이 뽑은 키워드가 채워지고, 그 키워드로 위키 페이지 목록을 검색/필터할 수 있는 백엔드를 만든다.

**Architecture:** 새 정규화 테이블 `wiki_page_keywords(page_id, keyword)`에 저장. 위키 페이지 생성 경로(이슈/토픽/챗봇 저장, 3곳)는 건드리지 않고, `wiki-dedup-batch`/`citation_id_cleanup.py`와 같은 구조의 독립 배치(`src/wiki/keyword_batch.py`)가 "키워드 없는 published 페이지"를 찾아 채운다 — 기존 페이지 백필과 신규 페이지 커버를 같은 메커니즘으로 처리. 검색은 기존 `GET /wiki/pages`(이미 `page_type`/`q` 필터가 있음)에 `keyword` 파라미터를 추가하고, 필터 칩 UI가 쓸 `GET /wiki/keywords`(키워드+건수)를 신규로 추가.

**Tech Stack:** Python, FastAPI, Pydantic v2, Supabase(postgrest), pytest, OpenRouter(기존 `analysis/classifier.py` 클라이언트 재사용) — 새 라이브러리 추가 없음.

## Global Constraints

- `keyword`는 항상 `src/categories/keywords.py`의 `CATEGORY_KEYWORDS`(6개 카테고리, 총 122개) 값 중 하나 — 자유 텍스트 절대 아님. 사전 밖 값은 LLM이 반환해도 버린다.
- 새 OpenRouter 모델/설정을 추가하지 않는다 — `analysis/classifier.py`의 `get_openrouter_settings()`(기본 `deepseek/deepseek-v4-flash`, 폴백 `deepseek/deepseek-v4-pro`)를 그대로 재사용.
- 페이지당 키워드는 최대 8개.
- 배치 실행 중 한 페이지의 LLM 호출/파싱이 실패해도 배치 전체가 멈추지 않는다 — 그 페이지만 건너뛰고 다음 페이지로 계속 진행(로그만 남김, 다음 배치 실행 때 자동 재시도).
- 위키 페이지 생성 로직(`src/wiki/generation.py`, `src/wiki/chat_wiki.py`)은 이번 작업에서 수정하지 않는다 — 키워드는 오직 별도 배치가 채운다.
- 프론트엔드는 변경하지 않는다.
- postgrest 조회는 이 코드베이스의 기존 관례(embedded join 대신 순차 조회, `_enrich_sources`/`_enrich_message_citations` 패턴)를 따른다.

---

### Task 1: `wiki_page_keywords` 테이블 마이그레이션

**Files:**
- Create: `supabase/migrations/20260806020000_create_wiki_page_keywords.sql`

**Interfaces:**
- Produces: `wiki_page_keywords` 테이블(컬럼: `id`, `page_id`, `keyword`, `created_at`) — 이후 모든 태스크가 이 테이블 이름과 컬럼명을 그대로 씀.

이 태스크는 SQL 파일 하나를 작성하는 것으로, TDD 사이클이 아니라 기존 마이그레이션 파일과의 스타일 일치 여부를 스스로 확인하는 것으로 검증한다. **주의: 이 마이그레이션을 실제 Supabase 프로젝트에 적용(apply)하는 것은 이 태스크의 범위가 아니다 — 파일만 작성한다. 적용은 컨트롤러(사람)가 검토 후 별도로 진행한다.**

- [ ] **Step 1: 마이그레이션 파일 작성**

```sql
CREATE TABLE IF NOT EXISTS public.wiki_page_keywords (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  page_id uuid NOT NULL REFERENCES public.wiki_pages(id) ON DELETE CASCADE,
  keyword varchar(50) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (page_id, keyword)
);

CREATE INDEX IF NOT EXISTS idx_wiki_page_keywords_keyword ON public.wiki_page_keywords(keyword);

ALTER TABLE public.wiki_page_keywords ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS wiki_page_keywords_select ON public.wiki_page_keywords;

CREATE POLICY wiki_page_keywords_select ON public.wiki_page_keywords
FOR SELECT
USING (EXISTS (
  SELECT 1 FROM public.wiki_pages p
  WHERE p.id = wiki_page_keywords.page_id AND is_workspace_member(p.workspace_id)
));
```

이 파일은 `supabase/migrations/20260804000000_create_push_subscriptions.sql`(RLS 정책 스타일)과 `docs/architecture/myWiki_v2_supabase.sql`의 `wiki_page_versions_select`/`wiki_page_sources_select`(자식 테이블 → 부모 JOIN으로 workspace_id 도달하는 정책 패턴)를 그대로 따른 것이다. `is_workspace_member()` 함수는 이미 스키마에 정의돼 있으므로 여기서 새로 만들지 않는다.

- [ ] **Step 2: 스타일 일치 자체 점검**

`supabase/migrations/20260804000000_create_push_subscriptions.sql`을 다시 읽고: 테이블명이 `public.` 프리픽스 포함, `IF NOT EXISTS`, RLS enable, `DROP POLICY IF EXISTS` 후 `CREATE POLICY` 순서가 동일한지 확인. `docs/architecture/myWiki_v2_supabase.sql`의 550번째 줄 근처 `wiki_page_sources_select` 정책과 새 정책의 JOIN 구조(부모 테이블 alias `p`, `is_workspace_member(p.workspace_id)`)가 같은 패턴인지 확인.

- [ ] **Step 3: 커밋**

```bash
git add supabase/migrations/20260806020000_create_wiki_page_keywords.sql
git commit -m "feat: wiki_page_keywords 테이블 마이그레이션 추가"
```

---

### Task 2: 키워드 추출 프롬프트

**Files:**
- Create: `src/wiki/keyword_prompts.py`
- Test: `tests/test_wiki_keyword_prompts.py`

**Interfaces:**
- Consumes: `src/categories/keywords.py`의 `CATEGORY_KEYWORDS: dict[str, tuple[str, ...]]`(이미 존재, 수정하지 않음).
- Produces: `WIKI_KEYWORD_SYSTEM_PROMPT: str`. `build_wiki_keyword_user_prompt(markdown: str) -> str`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_wiki_keyword_prompts.py
from __future__ import annotations

from src.categories.keywords import CATEGORY_KEYWORDS
from src.wiki import keyword_prompts


def test_system_prompt_includes_every_dictionary_keyword():
    for keywords in CATEGORY_KEYWORDS.values():
        for keyword in keywords:
            assert keyword in keyword_prompts.WIKI_KEYWORD_SYSTEM_PROMPT


def test_user_prompt_includes_markdown_body():
    prompt = keyword_prompts.build_wiki_keyword_user_prompt("# HBM4\n\nHBM4는 차세대 메모리다.")
    assert "HBM4는 차세대 메모리다." in prompt
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `python -m pytest tests/test_wiki_keyword_prompts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.wiki.keyword_prompts'`

- [ ] **Step 3: `src/wiki/keyword_prompts.py` 작성**

```python
from __future__ import annotations

from ..categories.keywords import CATEGORY_KEYWORDS


def _build_keyword_dictionary_block() -> str:
    lines = [f"[{category}] " + ", ".join(keywords) for category, keywords in CATEGORY_KEYWORDS.items()]
    return "\n".join(lines)


WIKI_KEYWORD_SYSTEM_PROMPT = f"""당신은 SK하이닉스 반도체 산업 위키를 관리하는 편집자입니다.

주어진 위키 문서 본문을 읽고, 아래 [키워드 사전]에 있는 단어 중 이 문서와 실제로
관련된 것만 골라 반환하십시오.

절대 규칙:
- [키워드 사전]에 없는 단어는 절대 반환하지 마십시오. 사전에 없는 개념이 본문에
  등장해도 지어내지 말고 생략하십시오.
- 본문에 실제로 언급되거나 명확히 관련된 키워드만 고르십시오. 무관한 키워드를
  억지로 채우지 마십시오.
- 최대 8개까지만 반환하십시오. 관련 키워드가 하나도 없으면 빈 배열을 반환하십시오.
- 마크다운 코드블록 없이 지정된 JSON 구조로만 응답하십시오.

[키워드 사전]
{_build_keyword_dictionary_block()}

JSON 출력 형식:
{{
  "keywords": ["키워드1", "키워드2"]
}}"""


def build_wiki_keyword_user_prompt(markdown: str) -> str:
    return f"[위키 본문]\n{markdown}"
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `python -m pytest tests/test_wiki_keyword_prompts.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/wiki/keyword_prompts.py tests/test_wiki_keyword_prompts.py
git commit -m "feat: 위키 키워드 추출 프롬프트 추가"
```

---

### Task 3: `extract_keywords_for_page` — LLM 호출 + 사전 필터링

**Files:**
- Create: `src/wiki/keyword_batch.py`
- Test: `tests/test_wiki_keyword_batch.py`

**Interfaces:**
- Consumes: Task 2의 `WIKI_KEYWORD_SYSTEM_PROMPT`, `build_wiki_keyword_user_prompt`. `analysis/classifier.py`의 `create_json_completion`, `get_openrouter_settings`, `parse_json_response`. `analysis/exceptions.py`의 `MissingApiKeyError`, `OpenRouterApiError`, `OpenRouterTimeoutError`, `InvalidJsonResponseError`.
- Produces: `WikiKeywordLLMResult(BaseModel)` — 필드 `keywords: list[str]`. `MAX_KEYWORDS_PER_PAGE = 8`. `extract_keywords_for_page(markdown: str, *, llm_client=None) -> list[str]` — 사전 밖 값 제거 + 8개로 자른 최종 키워드 리스트를 반환(LLM 실패 시 예외를 그대로 던짐 — 폴백 없음, Task 4의 배치 루프가 페이지 단위로 잡아서 건너뜀).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_wiki_keyword_batch.py
from __future__ import annotations

import json

from pydantic import ValidationError

from src.analysis.exceptions import OpenRouterTimeoutError
from src.wiki import keyword_batch


def test_extract_keywords_filters_out_of_dictionary_values(monkeypatch):
    monkeypatch.setattr(
        keyword_batch,
        "create_json_completion",
        lambda **kwargs: json.dumps({"keywords": ["HBM", "지어낸키워드", "삼성전자"]}),
    )

    keywords = keyword_batch.extract_keywords_for_page("HBM 관련 문서, 삼성전자 언급")

    assert keywords == ["HBM", "삼성전자"]


def test_extract_keywords_truncates_to_max_eight(monkeypatch):
    from src.categories.keywords import CATEGORY_KEYWORDS

    nine_real_keywords = list(CATEGORY_KEYWORDS["제품·기술"]) + list(CATEGORY_KEYWORDS["경쟁사"])
    nine_real_keywords = nine_real_keywords[:9]
    assert len(nine_real_keywords) == 9

    monkeypatch.setattr(
        keyword_batch, "create_json_completion",
        lambda **kwargs: json.dumps({"keywords": nine_real_keywords}),
    )

    keywords = keyword_batch.extract_keywords_for_page("본문")

    assert len(keywords) == keyword_batch.MAX_KEYWORDS_PER_PAGE
    assert keywords == nine_real_keywords[:8]


def test_extract_keywords_returns_empty_list_when_no_match(monkeypatch):
    monkeypatch.setattr(
        keyword_batch, "create_json_completion", lambda **kwargs: json.dumps({"keywords": []}),
    )

    assert keyword_batch.extract_keywords_for_page("아무 관련 없는 본문") == []


def test_extract_keywords_uses_injected_llm_client():
    calls = []

    def fake_client(system_prompt, user_prompt, model):
        calls.append((system_prompt, user_prompt, model))
        return json.dumps({"keywords": ["HBM"]})

    keywords = keyword_batch.extract_keywords_for_page("본문", llm_client=fake_client)

    assert keywords == ["HBM"]
    assert len(calls) == 1
    assert calls[0][0] == keyword_batch.WIKI_KEYWORD_SYSTEM_PROMPT


def test_extract_keywords_raises_on_llm_exception(monkeypatch):
    def raise_timeout(**kwargs):
        raise OpenRouterTimeoutError("timeout")

    monkeypatch.setattr(keyword_batch, "create_json_completion", raise_timeout)

    try:
        keyword_batch.extract_keywords_for_page("본문")
        assert False, "OpenRouterTimeoutError가 그대로 올라와야 한다"
    except OpenRouterTimeoutError:
        pass


def test_extract_keywords_raises_on_invalid_schema(monkeypatch):
    monkeypatch.setattr(
        keyword_batch, "create_json_completion", lambda **kwargs: json.dumps({"not_keywords": []}),
    )

    try:
        keyword_batch.extract_keywords_for_page("본문")
        assert False, "ValidationError가 그대로 올라와야 한다"
    except ValidationError:
        pass
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `python -m pytest tests/test_wiki_keyword_batch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.wiki.keyword_batch'`

- [ ] **Step 3: `src/wiki/keyword_batch.py` 작성 (모델 + extract_keywords_for_page만)**

```python
from __future__ import annotations

import logging

from pydantic import BaseModel

from ..analysis.classifier import create_json_completion, get_openrouter_settings, parse_json_response
from ..categories.keywords import CATEGORY_KEYWORDS
from .keyword_prompts import WIKI_KEYWORD_SYSTEM_PROMPT, build_wiki_keyword_user_prompt

logger = logging.getLogger(__name__)

MAX_KEYWORDS_PER_PAGE = 8

_ALLOWED_KEYWORDS = frozenset(
    keyword for keywords in CATEGORY_KEYWORDS.values() for keyword in keywords
)


class WikiKeywordLLMResult(BaseModel):
    keywords: list[str] = []


def extract_keywords_for_page(markdown: str, *, llm_client=None) -> list[str]:
    """위키 본문에서 122개 사전 안의 키워드만 추출한다.

    LLM 호출/파싱/스키마 검증이 실패하면 예외를 그대로 던진다(여기서 폴백하지 않음) —
    호출부(run_wiki_keyword_batch)가 페이지 단위로 잡아서 그 페이지만 건너뛰고
    배치를 계속 진행하는 게 이 함수의 책임 밖이기 때문이다.
    """
    settings = get_openrouter_settings()
    user_prompt = build_wiki_keyword_user_prompt(markdown)

    if llm_client is not None:
        response_text = llm_client(WIKI_KEYWORD_SYSTEM_PROMPT, user_prompt, settings.model)
    else:
        response_text = create_json_completion(
            system_prompt=WIKI_KEYWORD_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=settings.model,
        )
    payload = parse_json_response(response_text)
    result = WikiKeywordLLMResult.model_validate(payload)

    in_dictionary = [kw for kw in result.keywords if kw in _ALLOWED_KEYWORDS]
    return in_dictionary[:MAX_KEYWORDS_PER_PAGE]
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `python -m pytest tests/test_wiki_keyword_batch.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/wiki/keyword_batch.py tests/test_wiki_keyword_batch.py
git commit -m "feat: extract_keywords_for_page — LLM 키워드 추출 + 122개 사전 필터링"
```

---

### Task 4: 배치 실행 — `find_pages_missing_keywords` + `run_wiki_keyword_batch` + 스케줄 스크립트

**Files:**
- Modify: `src/wiki/keyword_batch.py`
- Create: `scripts/wiki_keyword_batch_scheduled.py`
- Create: `.github/workflows/wiki-keyword-batch.yml`
- Test: `tests/test_wiki_keyword_batch.py`

**Interfaces:**
- Consumes: Task 3의 `extract_keywords_for_page`. `src/wiki/query.py`의 `get_published_wiki_page(workspace_id, slug) -> WikiPageContent | None`(이미 존재, `.markdown`/`.title` 속성 있음). `src/analysis/repository.py`의 `get_supabase()`(이미 존재).
- Produces: `WikiKeywordPageResult(BaseModel)` — 필드 `page_id: str`, `slug: str`, `status: Literal["tagged", "no_match", "failed"]`, `keywords: list[str] = []`, `error_message: str | None = None`. `find_pages_missing_keywords(workspace_id, *, supabase=None) -> list[dict]` — 각 dict는 `{"id": str, "slug": str}`. `run_wiki_keyword_batch(workspace_id, *, supabase=None) -> list[WikiKeywordPageResult]`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_wiki_keyword_batch.py에 이어서 추가

from src.wiki.interface import WikiPageContent


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []
        self.in_filters = []

    def select(self, _fields):
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def in_(self, field, values):
        self.in_filters.append((field, set(values)))
        return self

    def execute(self):
        rows = self.rows
        for field, value in self.filters:
            rows = [r for r in rows if r.get(field) == value]
        for field, values in self.in_filters:
            rows = [r for r in rows if r.get(field) in values]
        return FakeResult([dict(r) for r in rows])


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return FakeTable(self.tables.get(name, []))


def _content(page_id, slug, markdown):
    return WikiPageContent(
        page_id=page_id, slug=slug, title=f"제목-{slug}", page_type="issue",
        published_at=None, version_id=f"v-{slug}", version_no=1, markdown=markdown,
        change_summary=None, confidence_score=None, validation_status="passed",
        review_status="approved", generated_by="llm", generator_model=None,
        created_at="2026-08-06T00:00:00Z", sources=(), versions=(),
    )


def test_find_pages_missing_keywords_excludes_pages_with_existing_keywords():
    db = FakeSupabase({
        "wiki_pages": [
            {"id": "page-1", "slug": "hbm4", "status": "published"},
            {"id": "page-2", "slug": "supply", "status": "published"},
        ],
        "wiki_page_keywords": [{"page_id": "page-1", "keyword": "HBM"}],
    })

    candidates = keyword_batch.find_pages_missing_keywords("ws-1", supabase=db)

    assert candidates == [{"id": "page-2", "slug": "supply"}]


def test_run_wiki_keyword_batch_tags_page_and_inserts_keywords(monkeypatch):
    db = FakeSupabase({
        "wiki_pages": [{"id": "page-1", "slug": "hbm4", "status": "published"}],
        "wiki_page_keywords": [],
    })
    monkeypatch.setattr(keyword_batch, "get_published_wiki_page", lambda ws, slug: _content("page-1", "hbm4", "HBM4 본문"))

    inserted = []
    monkeypatch.setattr(keyword_batch, "_insert_page_keywords", lambda page_id, keywords, *, supabase: inserted.append((page_id, keywords)))
    monkeypatch.setattr(keyword_batch, "extract_keywords_for_page", lambda markdown: ["HBM"])

    results = keyword_batch.run_wiki_keyword_batch("ws-1", supabase=db)

    assert len(results) == 1
    assert results[0].status == "tagged"
    assert results[0].keywords == ["HBM"]
    assert inserted == [("page-1", ["HBM"])]


def test_run_wiki_keyword_batch_marks_no_match_without_insert(monkeypatch):
    db = FakeSupabase({
        "wiki_pages": [{"id": "page-1", "slug": "hbm4", "status": "published"}],
        "wiki_page_keywords": [],
    })
    monkeypatch.setattr(keyword_batch, "get_published_wiki_page", lambda ws, slug: _content("page-1", "hbm4", "무관한 본문"))
    monkeypatch.setattr(keyword_batch, "extract_keywords_for_page", lambda markdown: [])

    inserted = []
    monkeypatch.setattr(keyword_batch, "_insert_page_keywords", lambda *a, **k: inserted.append(a))

    results = keyword_batch.run_wiki_keyword_batch("ws-1", supabase=db)

    assert results[0].status == "no_match"
    assert inserted == []


def test_run_wiki_keyword_batch_continues_after_one_page_fails(monkeypatch):
    db = FakeSupabase({
        "wiki_pages": [
            {"id": "page-1", "slug": "fails", "status": "published"},
            {"id": "page-2", "slug": "ok", "status": "published"},
        ],
        "wiki_page_keywords": [],
    })
    contents = {"fails": _content("page-1", "fails", "본문1"), "ok": _content("page-2", "ok", "본문2")}
    monkeypatch.setattr(keyword_batch, "get_published_wiki_page", lambda ws, slug: contents[slug])

    def fake_extract(markdown):
        if markdown == "본문1":
            raise OpenRouterTimeoutError("timeout")
        return ["HBM"]

    monkeypatch.setattr(keyword_batch, "extract_keywords_for_page", fake_extract)
    monkeypatch.setattr(keyword_batch, "_insert_page_keywords", lambda *a, **k: None)

    results = keyword_batch.run_wiki_keyword_batch("ws-1", supabase=db)

    assert len(results) == 2
    by_slug = {r.slug: r for r in results}
    assert by_slug["fails"].status == "failed"
    assert "timeout" in by_slug["fails"].error_message
    assert by_slug["ok"].status == "tagged"
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `python -m pytest tests/test_wiki_keyword_batch.py -v`
Expected: FAIL — `AttributeError: module 'src.wiki.keyword_batch' has no attribute 'find_pages_missing_keywords'`

- [ ] **Step 3: `src/wiki/keyword_batch.py`의 import 갱신 + 새 코드 추가**

파일 맨 위 import 블록을 아래로 교체(Task 3에서 쓴 `from pydantic import BaseModel`를 `BaseModel, ValidationError`로, 그리고 새 import 4줄을 추가):

```python
from __future__ import annotations

import logging
from typing import Literal, Optional

from pydantic import BaseModel, ValidationError
from supabase import Client

from ..analysis.classifier import create_json_completion, get_openrouter_settings, parse_json_response
from ..analysis.exceptions import (
    InvalidJsonResponseError,
    MissingApiKeyError,
    OpenRouterApiError,
    OpenRouterTimeoutError,
)
from ..analysis.repository import get_supabase
from ..categories.keywords import CATEGORY_KEYWORDS
from .keyword_prompts import WIKI_KEYWORD_SYSTEM_PROMPT, build_wiki_keyword_user_prompt
from .query import get_published_wiki_page
```

그 아래 `logger`, `MAX_KEYWORDS_PER_PAGE`, `_ALLOWED_KEYWORDS`, `WikiKeywordLLMResult`, `extract_keywords_for_page`(Task 3에서 만든 것)는 그대로 두고, 파일 맨 끝에 아래 코드를 추가한다:

```python
class WikiKeywordPageResult(BaseModel):
    page_id: str
    slug: str
    status: Literal["tagged", "no_match", "failed"]
    keywords: list[str] = []
    error_message: Optional[str] = None


def find_pages_missing_keywords(workspace_id: str, *, supabase: Client | None = None) -> list[dict]:
    """published 페이지 중 wiki_page_keywords에 행이 하나도 없는 페이지를 찾는다.

    embedded join 대신 순차 조회(이 코드베이스의 기존 관례) — 전체 published 페이지와
    이미 키워드가 있는 page_id 집합을 각각 조회해 파이썬에서 차집합을 구한다.
    """
    db = supabase or get_supabase()

    pages = (
        db.table("wiki_pages")
        .select("id, slug")
        .eq("workspace_id", workspace_id)
        .eq("status", "published")
        .execute()
        .data
    )
    if not pages:
        return []

    page_ids = [row["id"] for row in pages]
    tagged_res = (
        db.table("wiki_page_keywords")
        .select("page_id")
        .in_("page_id", page_ids)
        .execute()
    )
    tagged_page_ids = {row["page_id"] for row in tagged_res.data}

    return [{"id": row["id"], "slug": row["slug"]} for row in pages if row["id"] not in tagged_page_ids]


def _insert_page_keywords(page_id: str, keywords: list[str], *, supabase: Client) -> None:
    if not keywords:
        return
    supabase.table("wiki_page_keywords").insert(
        [{"page_id": page_id, "keyword": keyword} for keyword in keywords]
    ).execute()


def run_wiki_keyword_batch(workspace_id: str, *, supabase: Client | None = None) -> list[WikiKeywordPageResult]:
    """키워드 없는 published 페이지를 찾아 채운다.

    한 페이지의 LLM 호출/파싱이 실패해도 그 페이지만 'failed'로 기록하고 다음
    페이지로 계속 진행한다 — 다음 배치 실행 때 여전히 '키워드 없음' 상태라 자동
    재시도된다.
    """
    db = supabase or get_supabase()
    candidates = find_pages_missing_keywords(workspace_id, supabase=db)

    results: list[WikiKeywordPageResult] = []
    for candidate in candidates:
        content = get_published_wiki_page(workspace_id, candidate["slug"])
        if content is None:
            continue

        try:
            keywords = extract_keywords_for_page(content.markdown)
        except (
            MissingApiKeyError,
            OpenRouterApiError,
            OpenRouterTimeoutError,
            InvalidJsonResponseError,
            ValidationError,
        ) as exc:
            logger.warning(
                "wiki_keyword_extraction_failed",
                extra={"page_id": candidate["id"], "slug": candidate["slug"], "error": str(exc)},
            )
            results.append(
                WikiKeywordPageResult(
                    page_id=candidate["id"], slug=candidate["slug"],
                    status="failed", error_message=str(exc),
                )
            )
            continue

        if keywords:
            _insert_page_keywords(candidate["id"], keywords, supabase=db)
            results.append(
                WikiKeywordPageResult(page_id=candidate["id"], slug=candidate["slug"], status="tagged", keywords=keywords)
            )
        else:
            results.append(WikiKeywordPageResult(page_id=candidate["id"], slug=candidate["slug"], status="no_match"))

    return results
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `python -m pytest tests/test_wiki_keyword_batch.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: 스케줄 스크립트 작성**

```python
# scripts/wiki_keyword_batch_scheduled.py
"""위키 키워드 채우기 배치 — 키워드 없는 published 위키 페이지에 LLM이 122개 사전
안에서 키워드를 뽑아 채운다.

scripts/dedup_wiki_scheduled.py와 동일한 뼈대 — GitHub Actions cron이 매일 1회
도는 것 자체가 실행 주기다.

사용법:
    python scripts/wiki_keyword_batch_scheduled.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.pipeline_common.db import get_client
from src.wiki.keyword_batch import WikiKeywordPageResult, run_wiki_keyword_batch


def log(msg: str) -> None:
    print(f"[wiki_keyword_batch_scheduled] {msg}", flush=True)


def get_workspace_id() -> str:
    rows = get_client().table("workspaces").select("id, name").limit(2).execute().data
    if len(rows) != 1:
        raise SystemExit(f"workspace_id를 자동으로 하나로 못 정했다 (workspaces 행 {len(rows)}개).")
    return str(rows[0]["id"])


def report_results(results: list[WikiKeywordPageResult]) -> int:
    tagged = [r for r in results if r.status == "tagged"]
    no_match = [r for r in results if r.status == "no_match"]
    failed = [r for r in results if r.status == "failed"]
    log(f"{len(results)}개 페이지 처리: 태깅 {len(tagged)}건, 매칭 없음 {len(no_match)}건, 실패 {len(failed)}건")
    for r in failed:
        log(f"  - 실패: {r.slug}: {r.error_message}")
    if results and len(failed) == len(results):
        return 1
    return 0


if __name__ == "__main__":
    workspace_id = get_workspace_id()
    log("위키 키워드 채우기 시작")
    results = run_wiki_keyword_batch(workspace_id)
    exit_code = report_results(results)
    if exit_code != 0:
        raise SystemExit(exit_code)
```

- [ ] **Step 6: GitHub Actions 워크플로 작성**

```yaml
# .github/workflows/wiki-keyword-batch.yml
name: Wiki Keyword Batch

on:
  schedule:
    - cron: "30 18 * * *" # 매일 1회(한국시간 새벽 3시 30분) — wiki-dedup-batch와 겹치지 않게 30분 뒤
  workflow_dispatch: {}

jobs:
  keyword-batch:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run wiki keyword batch
        run: python scripts/wiki_keyword_batch_scheduled.py
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SECRET_KEY }}
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
```

`.github/workflows/wiki-dedup-batch.yml`을 그대로 참고해 만든 것 — env 시크릿 이름까지 동일하게 맞춘다.

- [ ] **Step 7: 커밋**

```bash
git add src/wiki/keyword_batch.py tests/test_wiki_keyword_batch.py scripts/wiki_keyword_batch_scheduled.py .github/workflows/wiki-keyword-batch.yml
git commit -m "feat: 위키 키워드 배치 — find_pages_missing_keywords/run_wiki_keyword_batch + 스케줄"
```

---

### Task 5: `list_published_wiki_pages`에 `keyword` 필터 추가

**Files:**
- Modify: `src/wiki/query.py` (함수 `list_published_wiki_pages`, 현재 39-58번째 줄 — 함수명으로 다시 찾을 것)
- Test: `tests/test_wiki_query_related_pages.py` 또는 신규 `tests/test_wiki_query.py`(해당 함수를 테스트하는 기존 파일이 있으면 거기에 추가, 없으면 신규 파일 생성)

**Interfaces:**
- Consumes: 없음(순수 조회 로직 확장).
- Produces: `list_published_wiki_pages(workspace_id, page_type=None, query=None, keyword=None, limit=50, offset=0) -> list[WikiPageSummary]` — `keyword` 파라미터가 새로 추가됨. 이후 Task 6이 이 파라미터를 그대로 라우터에 연결.

- [ ] **Step 1: 기존 테스트 파일 확인**

`tests/test_wiki_query_related_pages.py`를 열어 `list_published_wiki_pages`를 테스트하는 기존 테스트가 있는지 확인한다. 없으면 아래처럼 신규 파일 `tests/test_wiki_query.py`를 만든다(있으면 그 파일에 아래 테스트 함수들을 추가).

- [ ] **Step 2: 실패하는 테스트 작성**

```python
# tests/test_wiki_query.py (신규 — 이미 list_published_wiki_pages 테스트가 있는 기존 파일이 있다면 그쪽에 추가)
from __future__ import annotations

from src.wiki import query as wiki_query

WORKSPACE_ID = "ws-1"


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []
        self.in_filters = []
        self.ilike_filters = []
        self._limit = None
        self._offset = None

    def select(self, _fields):
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def in_(self, field, values):
        self.in_filters.append((field, set(values)))
        return self

    def ilike(self, field, pattern):
        self.ilike_filters.append((field, pattern))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def offset(self, n):
        self._offset = n
        return self

    def execute(self):
        rows = self.rows
        for field, value in self.filters:
            rows = [r for r in rows if r.get(field) == value]
        for field, values in self.in_filters:
            rows = [r for r in rows if r.get(field) in values]
        return FakeResult([dict(r) for r in rows])


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return FakeTable(self.tables.get(name, []))


def test_list_published_wiki_pages_filters_by_keyword(monkeypatch):
    db = FakeSupabase({
        "wiki_pages": [
            {"id": "page-1", "slug": "hbm4", "title": "HBM4", "page_type": "technology",
             "status": "published", "parent_page_id": None, "published_at": "2026-08-01T00:00:00Z"},
            {"id": "page-2", "slug": "supply", "title": "공급망", "page_type": "supply_chain",
             "status": "published", "parent_page_id": None, "published_at": "2026-08-01T00:00:00Z"},
        ],
        "wiki_page_keywords": [{"page_id": "page-1", "keyword": "HBM"}],
    })
    monkeypatch.setattr(wiki_query, "_get_client", lambda: db)

    results = wiki_query.list_published_wiki_pages(WORKSPACE_ID, keyword="HBM")

    assert [r.slug for r in results] == ["hbm4"]


def test_list_published_wiki_pages_keyword_no_match_returns_empty(monkeypatch):
    db = FakeSupabase({
        "wiki_pages": [
            {"id": "page-1", "slug": "hbm4", "title": "HBM4", "page_type": "technology",
             "status": "published", "parent_page_id": None, "published_at": "2026-08-01T00:00:00Z"},
        ],
        "wiki_page_keywords": [],
    })
    monkeypatch.setattr(wiki_query, "_get_client", lambda: db)

    results = wiki_query.list_published_wiki_pages(WORKSPACE_ID, keyword="수출통제")

    assert results == []
```

- [ ] **Step 3: 테스트 실행해서 실패 확인**

Run: `python -m pytest tests/test_wiki_query.py -v`
Expected: FAIL — `TypeError: list_published_wiki_pages() got an unexpected keyword argument 'keyword'`

- [ ] **Step 4: `src/wiki/query.py` 수정**

```python
def list_published_wiki_pages(
    workspace_id: str,
    page_type: Optional[PageType] = None,
    query: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[WikiPageSummary]:
    db = _get_client()
    q = (
        db.table("wiki_pages")
        .select("id, slug, title, page_type, status, parent_page_id, published_at")
        .eq("workspace_id", workspace_id)
        .eq("status", "published")
    )
    if page_type:
        q = q.eq("page_type", page_type)
    if query:
        q = q.ilike("title", f"%{query}%")
    if keyword:
        keyword_res = db.table("wiki_page_keywords").select("page_id").eq("keyword", keyword).execute()
        matching_page_ids = [row["page_id"] for row in keyword_res.data]
        if not matching_page_ids:
            return []
        q = q.in_("id", matching_page_ids)
    res = q.limit(limit).offset(offset).execute()
    return [WikiPageSummary(**row) for row in res.data]
```

기존 `def list_published_wiki_pages(...)` 시그니처와 함수 본문 전체를 위 코드로 교체한다.

- [ ] **Step 5: 테스트 실행해서 통과 확인**

Run: `python -m pytest tests/test_wiki_query.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: 기존 wiki 쿼리 테스트 전체 회귀 확인**

Run: `python -m pytest tests/test_wiki_query_related_pages.py tests/test_wiki_query.py -v`
Expected: 전부 PASS, 회귀 없음

- [ ] **Step 7: 커밋**

```bash
git add src/wiki/query.py tests/test_wiki_query.py
git commit -m "feat: list_published_wiki_pages에 keyword 필터 추가"
```

---

### Task 6: `GET /wiki/pages?keyword=` 연결 + `GET /wiki/keywords` 신규

**Files:**
- Modify: `src/api/wiki_router.py` (함수 `list_pages`, 현재 29-41번째 줄 — 함수명으로 다시 찾을 것)
- Modify: `src/api/schemas.py` (새 스키마 추가)
- Test: `tests/test_wiki_router.py`

**Interfaces:**
- Consumes: Task 5의 `wiki_query.list_published_wiki_pages(..., keyword=...)`.
- Produces: `GET /wiki/pages?keyword=X`(기존 엔드포인트 확장). `GET /wiki/keywords`(신규, 응답 `list[WikiKeywordCountOut]` — 필드 `keyword: str`, `count: int`).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_wiki_router.py에 이어서 추가 — 기존 import에 WikiKeywordCountOut 추가 필요 없음(응답 JSON만 확인)

def test_list_pages_with_keyword_filter(client, monkeypatch):
    captured = {}

    def fake_list_pages(workspace_id, **kw):
        captured.update(kw)
        return [
            WikiPageSummary(
                id=PAGE_ID, slug="hbm4", title="HBM4", page_type="technology",
                status="published", parent_page_id=None, published_at="2026-07-24T00:00:00Z",
            )
        ]

    monkeypatch.setattr(wiki_query, "list_published_wiki_pages", fake_list_pages)

    res = client.get("/wiki/pages?keyword=HBM")

    assert res.status_code == 200
    assert captured["keyword"] == "HBM"
    assert res.json()[0]["slug"] == "hbm4"


def test_list_keywords(client, monkeypatch):
    monkeypatch.setattr(
        wiki_query, "list_workspace_keyword_counts",
        lambda workspace_id: [{"keyword": "HBM", "count": 12}, {"keyword": "수출통제", "count": 5}],
    )

    res = client.get("/wiki/keywords")

    assert res.status_code == 200
    assert res.json() == [{"keyword": "HBM", "count": 12}, {"keyword": "수출통제", "count": 5}]
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `python -m pytest tests/test_wiki_router.py -v -k "keyword"`
Expected: FAIL — 첫 번째 테스트는 `keyword` 파라미터가 전달 안 돼서 `captured["keyword"]`가 `KeyError`, 두 번째는 `AttributeError: module 'src.wiki.query' has no attribute 'list_workspace_keyword_counts'`

- [ ] **Step 3: `src/wiki/query.py`에 집계 함수 추가**

```python
def list_workspace_keyword_counts(workspace_id: str) -> list[dict]:
    """워크스페이스 안에서 published 페이지에 걸린 키워드별 건수. 건수 내림차순."""
    db = _get_client()
    published_res = (
        db.table("wiki_pages")
        .select("id")
        .eq("workspace_id", workspace_id)
        .eq("status", "published")
        .execute()
    )
    published_ids = {row["id"] for row in published_res.data}
    if not published_ids:
        return []

    keywords_res = (
        db.table("wiki_page_keywords")
        .select("page_id, keyword")
        .in_("page_id", list(published_ids))
        .execute()
    )
    counts: dict[str, int] = {}
    for row in keywords_res.data:
        counts[row["keyword"]] = counts.get(row["keyword"], 0) + 1

    return [
        {"keyword": keyword, "count": count}
        for keyword, count in sorted(counts.items(), key=lambda pair: -pair[1])
    ]
```

- [ ] **Step 4: `src/api/schemas.py`에 응답 스키마 추가**

`class WikiPageSummaryOut(BaseModel):` 정의부 바로 위에 추가:

```python
class WikiKeywordCountOut(BaseModel):
    keyword: str
    count: int
```

- [ ] **Step 5: `src/api/wiki_router.py` 수정**

import 줄 수정:

```python
from .schemas import WikiKeywordCountOut, WikiPageContentOut, WikiPageSummaryOut, WikiVersionSummaryOut
```

`list_pages` 함수를 아래로 교체:

```python
@router.get("/pages", response_model=list[WikiPageSummaryOut])
def list_pages(
    page_type: Optional[PageType] = Query(default=None),
    q: Optional[str] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    profile: dict = Depends(get_current_user),
):
    """WikiPage 좌측 트리용 목록. page_type으로 그룹핑해서 렌더링한다."""
    workspace_id = _require_workspace(profile)
    return wiki_query.list_published_wiki_pages(
        workspace_id, page_type=page_type, query=q, keyword=keyword, limit=limit, offset=offset
    )
```

`get_versions` 함수 뒤에 새 엔드포인트 추가:

```python
@router.get("/keywords", response_model=list[WikiKeywordCountOut])
def list_keywords(profile: dict = Depends(get_current_user)):
    """위키 목록 화면의 키워드 필터 칩 바용 — 실제 사용 중인 키워드+건수."""
    workspace_id = _require_workspace(profile)
    return wiki_query.list_workspace_keyword_counts(workspace_id)
```

- [ ] **Step 6: 테스트 실행해서 통과 확인**

Run: `python -m pytest tests/test_wiki_router.py -v`
Expected: 전부 PASS(기존 테스트 포함 회귀 없음, 신규 2건 포함)

- [ ] **Step 7: 관련 전체 테스트 스위트 실행**

Run: `python -m pytest tests/test_wiki_router.py tests/test_wiki_query.py tests/test_wiki_query_related_pages.py tests/test_wiki_keyword_batch.py tests/test_wiki_keyword_prompts.py -v`
Expected: 전부 PASS

- [ ] **Step 8: 커밋**

```bash
git add src/wiki/query.py src/api/wiki_router.py src/api/schemas.py tests/test_wiki_router.py
git commit -m "feat: GET /wiki/pages keyword 필터 연결 + GET /wiki/keywords 신규 엔드포인트"
```

---

## 최종 확인

- [ ] `python -m pytest tests/ -k "keyword"` 전체 통과
- [ ] `git log --oneline -6` — 6개 커밋(Task 1~6) 확인
- [ ] `docs/superpowers/specs/2026-08-06-wiki-keyword-filter-design.md`의 목표 3가지(모든 페이지 키워드 채움, 122개 사전 제한, 검색/필터 API)가 전부 구현됐는지 스펙과 다시 대조
- [ ] **컨트롤러가 직접 처리(구현 계획 범위 밖)**: Task 1의 마이그레이션을 실제 Supabase 프로젝트에 적용, ERDCloud에 `wiki_page_keywords` 테이블 + `wiki_pages` 관계선 추가([[feedback-docs-sync]])

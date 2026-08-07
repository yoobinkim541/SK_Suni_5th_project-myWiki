# 위키 근거 없을 때 원문 문서 근거 답변 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `WikiAgent`가 위키에 근거가 없어도, 수집된 원문(뉴스+DART, 위키 발행 여부 무관)에서 근거를 찾아 `[N]` 각주 + 출처 링크로 답변하는 중간 그라운딩 단계를 추가한다.

**Architecture:** `_wiki_answer()`(위키 그라운딩)와 `_llm_fallback_answer()`(무근거 일반 지식) 사이에 `_document_answer()`(원문 그라운딩)를 추가한다. 두 그라운딩 단계(`_wiki_answer`/`_document_answer`)는 라운드 루프·JSON 파싱 복구·grounding 검증을 공유 헬퍼 `_run_grounded_answer()`로 통일해서 쓴다.

**Tech Stack:** Python, OpenAI SDK(OpenRouter 호환), Supabase(supabase-py), pytest.

## Global Constraints

- `_wiki_answer()`의 외부 동작(입출력)은 리팩터링 후에도 그대로 유지한다 — `tests/test_agent_core.py`의 기존 24개 테스트가 수정 없이 전부 통과해야 한다.
- 새 `.in_()` 쿼리는 청크 분할 임계치(150, `src/analysis/repository.py::_IN_CLAUSE_CHUNK_SIZE`)를 넘지 않는 범위로만 설계한다(스캔 상한 50건으로 이미 안전).
- 프론트엔드 변경 없음 — `src/api/db.py::_enrich_message_citations()`가 `document_version_id`만으로 이미 citation 링크를 만든다.
- 위키 검색(`search_wiki_pages`)과 원문 검색(`search_documents`)을 한 라운드에 섞지 않는다 — 단계를 분리해서 각 시스템 프롬프트를 명확히 유지한다.

---

## 참고 스펙

`docs/superpowers/specs/2026-08-07-document-grounded-fallback-design.md`

## 파일 구조

| 파일 | 역할 |
|---|---|
| `src/pipeline_common/document_search.py` (신규) | `documents`/`document_versions`에 대한 title+본문 관련도 검색·단건 조회. `wiki/repository.py::search_wiki_contexts`와 같은 스코어링을 원문에 적용 |
| `src/agent/wiki_tools.py` (수정) | `WikiTools.search_documents()`/`read_document()` 위임 메서드 추가 |
| `src/agent/core.py` (수정) | `_wiki_answer`를 공유 헬퍼 `_run_grounded_answer`로 리팩터링, `_document_answer` 추가, `answer()` 3단계로 확장 |
| `tests/test_pipeline_common_document_search.py` (신규) | `document_search.py` 단위 테스트 |
| `tests/test_agent_wiki_tools.py` (수정) | `search_documents`/`read_document` 위임 테스트 추가 |
| `tests/test_agent_core.py` (수정) | 3단계 흐름·크래시 내성 테스트 추가 |

---

### Task 1: `document_search.search_documents()` — 원문 문서 검색

**Files:**
- Create: `src/pipeline_common/document_search.py`
- Test: `tests/test_pipeline_common_document_search.py`

**Interfaces:**
- Consumes: `src/analysis/repository.py::get_supabase()`(기존), `src/pipeline_common/storage.py::split_key()`(기존)
- Produces: `DocumentSearchHit(document_version_id: str, title: str, score: float)` dataclass, `search_documents(workspace_id: str, query: str, limit: int = 5, *, supabase: Client | None = None) -> list[DocumentSearchHit]` — Task 3(`WikiTools.search_documents`)이 그대로 가져다 쓴다.

- [ ] **Step 1: 테스트 파일 뼈대와 FakeSupabase 작성**

`tests/test_wiki_search.py`의 `FakeResult`/`FakeStorageBucket`/`FakeStorage`/`FakeTable`/`FakeSupabase` 패턴을 그대로 재사용한다(`order`/`eq`/`in_`/`limit`/`select`/`execute` 지원, `storage.from_(bucket).download()` 지원). `maybe_single()`도 추가로 지원해야 한다(Task 2에서 씀) — `FakeTable.maybe_single()`은 `self`를 그대로 반환하고, `execute()`가 `single`이 걸린 상태면 `FakeResult(rows[0] if rows else None)`을 돌려주도록 플래그를 하나 둔다.

```python
"""src/pipeline_common/document_search.py 단위 테스트 — DB/Storage는 FakeSupabase로 대체한다."""
from __future__ import annotations

from src.pipeline_common import document_search

WORKSPACE_ID = "ws-1"


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeStorageBucket:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects

    def download(self, path: str) -> bytes:
        if path not in self.objects:
            raise FileNotFoundError(path)
        return self.objects[path]


class FakeStorage:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects

    def from_(self, _bucket: str) -> FakeStorageBucket:
        return FakeStorageBucket(self.objects)


class FakeTable:
    def __init__(self, rows: list[dict]):
        self.rows = [dict(r) for r in rows]
        self.eq_filters: list[tuple[str, object]] = []
        self.in_filters: list[tuple[str, set[object]]] = []
        self.ordering: list[tuple[str, bool]] = []
        self.row_limit: int | None = None
        self._want_single = False

    def select(self, _fields: str) -> "FakeTable":
        return self

    def eq(self, field: str, value: object) -> "FakeTable":
        self.eq_filters.append((field, value))
        return self

    def in_(self, field: str, values: list[object]) -> "FakeTable":
        self.in_filters.append((field, set(values)))
        return self

    def order(self, field: str, desc: bool = False) -> "FakeTable":
        self.ordering.append((field, desc))
        return self

    def limit(self, value: int) -> "FakeTable":
        self.row_limit = value
        return self

    def maybe_single(self) -> "FakeTable":
        self._want_single = True
        return self

    def execute(self) -> FakeResult:
        rows = self.rows
        for field, value in self.eq_filters:
            rows = [r for r in rows if r.get(field) == value]
        for field, values in self.in_filters:
            rows = [r for r in rows if r.get(field) in values]
        for field, desc in reversed(self.ordering):
            rows = sorted(rows, key=lambda r: r.get(field) or "", reverse=desc)
        if self.row_limit is not None:
            rows = rows[: self.row_limit]
        if self._want_single:
            return FakeResult(rows[0] if rows else None)
        return FakeResult(rows)


class FakeSupabase:
    def __init__(self, tables: dict[str, list[dict]], objects: dict[str, bytes] | None = None):
        self.tables = tables
        self.storage = FakeStorage(objects or {})

    def table(self, name: str) -> FakeTable:
        return FakeTable(self.tables.get(name, []))
```

- [ ] **Step 2: 실패하는 검색 테스트 작성**

같은 파일 하단에 이어서 추가:

```python
def _document_row(doc_id: str, title: str, published_at: str, status: str = "active") -> dict:
    return {
        "id": doc_id,
        "workspace_id": WORKSPACE_ID,
        "title": title,
        "canonical_url": f"https://example.com/{doc_id}",
        "published_at": published_at,
        "status": status,
        "source_id": "source-1",
    }


def _version_row(version_id: str, doc_id: str, version_no: int, key: str) -> dict:
    return {
        "id": version_id,
        "document_id": doc_id,
        "version_no": version_no,
        "markdown_object_key": key,
    }


def test_search_documents_matches_title_and_body():
    supabase = FakeSupabase(
        tables={
            "documents": [
                _document_row("doc-1", "SK하이닉스 ADR 나스닥 상장", "2026-08-01T00:00:00+00:00"),
                _document_row("doc-2", "관련 없는 기사", "2026-08-02T00:00:00+00:00"),
            ],
            "document_versions": [
                _version_row("ver-1", "doc-1", 1, "processed/ws-1/doc-1/1.md"),
                _version_row("ver-2", "doc-2", 1, "processed/ws-1/doc-2/1.md"),
            ],
        },
        objects={
            "ws-1/doc-1/1.md": b"SK\xed\x95\x98\xec\x9d\xb4\xeb\x8b\x89\xec\x8a\xa4\xea\xb0\x80 \xeb\x82\x98\xec\x8a\xa4\xeb\x8b\xa5\xec\x97\x90 ADR\xec\x9d\x84 \xec\x83\x81\xec\x9e\xa5\xed\x96\x88\xeb\x8b\xa4.",
            "ws-1/doc-2/1.md": "자동차 산업 동향".encode("utf-8"),
        },
    )

    results = document_search.search_documents(WORKSPACE_ID, "SK하이닉스 ADR 상장", limit=5, supabase=supabase)

    assert len(results) == 1
    assert results[0].document_version_id == "ver-1"
    assert results[0].title == "SK하이닉스 ADR 나스닥 상장"
    assert 0.0 < results[0].score <= 1.0


def test_search_documents_uses_latest_version_per_document():
    supabase = FakeSupabase(
        tables={
            "documents": [_document_row("doc-1", "HBM 수요 전망", "2026-08-01T00:00:00+00:00")],
            "document_versions": [
                _version_row("ver-1a", "doc-1", 1, "processed/ws-1/doc-1/1.md"),
                _version_row("ver-1b", "doc-1", 2, "processed/ws-1/doc-1/2.md"),
            ],
        },
        objects={
            "ws-1/doc-1/1.md": "옛 버전 HBM 내용".encode("utf-8"),
            "ws-1/doc-1/2.md": "HBM 수요".encode("utf-8"),
        },
    )

    results = document_search.search_documents(WORKSPACE_ID, "HBM 수요", limit=5, supabase=supabase)

    assert len(results) == 1
    assert results[0].document_version_id == "ver-1b"


def test_search_documents_excludes_inactive_status():
    supabase = FakeSupabase(
        tables={
            "documents": [_document_row("doc-1", "HBM 수요", "2026-08-01T00:00:00+00:00", status="deleted")],
            "document_versions": [_version_row("ver-1", "doc-1", 1, "processed/ws-1/doc-1/1.md")],
        },
        objects={"ws-1/doc-1/1.md": "HBM 수요".encode("utf-8")},
    )

    results = document_search.search_documents(WORKSPACE_ID, "HBM 수요", limit=5, supabase=supabase)

    assert results == []


def test_search_documents_excludes_zero_overlap():
    supabase = FakeSupabase(
        tables={
            "documents": [_document_row("doc-1", "관련 없는 제목", "2026-08-01T00:00:00+00:00")],
            "document_versions": [_version_row("ver-1", "doc-1", 1, "processed/ws-1/doc-1/1.md")],
        },
        objects={"ws-1/doc-1/1.md": "관련 없는 본문".encode("utf-8")},
    )

    results = document_search.search_documents(WORKSPACE_ID, "HBM 반도체", limit=5, supabase=supabase)

    assert results == []
```

주의: `FakeStorageBucket.download()`의 키는 `split_key()`가 버킷 접두사를 뗀 뒤의 path(`ws-1/doc-1/1.md`)다 — `objects` 딕셔너리 키를 그 형태로 맞춘다.

- [ ] **Step 2b: 실패 확인**

Run: `pytest tests/test_pipeline_common_document_search.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.pipeline_common.document_search'`

- [ ] **Step 3: `document_search.py` 구현**

```python
"""
원문 문서(documents/document_versions) 제목+본문 관련도 검색.

Agent가 위키에 근거가 없을 때(_document_answer) 수집된 원문(뉴스+DART, 위키 발행
여부 무관)에서 근거를 찾는 두 번째 그라운딩 단계가 쓴다.

src/wiki/repository.py::search_wiki_contexts()와 같은 스코어링(title 60% + 본문
30% + coverage 10% 토큰 오버랩)을 documents/document_versions에 적용한다. 위키
전용 모듈(src/wiki/)에 두지 않는 이유: documents/document_versions는 위키가
아니라 파이프라인 공용 테이블이고, pipeline_common이 이미 그 접근을 담당하는
자리다. wiki/repository.py를 import하지 않는다 — 위키 모듈이 pipeline_common을
참조하는 건 몰라도 반대 방향은 레이어 위반이라, 스코어링 로직은 이 모듈에
독립적으로 둔다(중복이지만 의도적 — 약 20줄).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from supabase import Client

from ..analysis.repository import get_supabase
from . import storage

DEFAULT_SCAN_LIMIT = 50
"""
스캔할 최근 문서 수 상한. search_wiki_contexts의 DEFAULT_MAX_PAGE_SCAN(30)과 같은
이유 — 후보마다 storage에서 markdown을 내려받아 스코어링하므로 무한정 스캔하면
느려진다. 50은 .in_() 청크 분할 임계치(150, src/analysis/repository.py의
_IN_CLAUSE_CHUNK_SIZE)보다 한참 작아 이 모듈의 .in_() 호출은 청크 분할이 필요 없다.
"""

_URL_PATTERN = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_NON_WORD_PATTERN = re.compile(r"[\W_]+", re.UNICODE)


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


def search_documents(
    workspace_id: str, query: str, limit: int = 5, *, supabase: Client | None = None
) -> list[DocumentSearchHit]:
    db = supabase or get_supabase()

    document_rows = (
        db.table("documents")
        .select("id, title")
        .eq("workspace_id", workspace_id)
        .eq("status", "active")
        .order("published_at", desc=True)
        .limit(DEFAULT_SCAN_LIMIT)
        .execute()
        .data
    )
    if not document_rows:
        return []
    titles_by_document_id = {row["id"]: row["title"] for row in document_rows}
    document_ids = list(titles_by_document_id.keys())

    version_rows = (
        db.table("document_versions")
        .select("id, document_id, version_no, markdown_object_key")
        .in_("document_id", document_ids)
        .execute()
        .data
    )
    latest_version_by_document: dict[str, dict] = {}
    for row in version_rows:
        current = latest_version_by_document.get(row["document_id"])
        if current is None or row["version_no"] > current["version_no"]:
            latest_version_by_document[row["document_id"]] = row

    query_token_set = _tokenize_search_text(query)
    if not query_token_set:
        return []

    hits: list[DocumentSearchHit] = []
    for document_id, version in latest_version_by_document.items():
        title = titles_by_document_id[document_id]
        bucket, path = storage.split_key(version["markdown_object_key"])
        markdown_bytes = db.storage.from_(bucket).download(path)
        content = markdown_bytes.decode("utf-8")

        score = _score_document(title=str(title), content=content, query_token_set=query_token_set)
        if score is None:
            continue
        hits.append(DocumentSearchHit(document_version_id=str(version["id"]), title=str(title), score=score))

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:limit]


def get_document_detail(
    workspace_id: str, document_version_id: str, *, supabase: Client | None = None
) -> DocumentDetail | None:
    raise NotImplementedError  # Task 2에서 구현


def _score_document(*, title: str, content: str, query_token_set: set[str]) -> float | None:
    title_tokens = _tokenize_search_text(title)
    body_tokens = _tokenize_search_text(content)

    title_overlap = len(title_tokens & query_token_set)
    body_overlap = len(body_tokens & query_token_set)
    total_overlap = len((title_tokens | body_tokens) & query_token_set)
    if total_overlap == 0:
        return None

    query_size = len(query_token_set)
    return min(
        1.0,
        (title_overlap / query_size * 0.6)
        + (body_overlap / query_size * 0.3)
        + (total_overlap / query_size * 0.1),
    )


def _normalize_search_text(value: str | None) -> str:
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", value).lower()
    normalized = _URL_PATTERN.sub(" ", normalized)
    normalized = _NON_WORD_PATTERN.sub(" ", normalized)
    normalized = " ".join(normalized.split())
    return normalized.strip()


def _tokenize_search_text(value: str | None) -> set[str]:
    normalized = _normalize_search_text(value)
    if not normalized:
        return set()
    tokens: set[str] = set()
    for token in normalized.split():
        if len(token) > 1 or any(character.isdigit() for character in token):
            tokens.add(token)
    return tokens
```

- [ ] **Step 4: 검색 테스트 통과 확인**

Run: `pytest tests/test_pipeline_common_document_search.py -v`
Expected: 4개 테스트(`test_search_documents_matches_title_and_body`, `test_search_documents_uses_latest_version_per_document`, `test_search_documents_excludes_inactive_status`, `test_search_documents_excludes_zero_overlap`) PASS

- [ ] **Step 5: 커밋**

```bash
git add src/pipeline_common/document_search.py tests/test_pipeline_common_document_search.py
git commit -m "feat: 원문 문서 title+본문 관련도 검색 추가 (search_documents)"
```

---

### Task 2: `document_search.get_document_detail()` — 원문 문서 단건 조회

**Files:**
- Modify: `src/pipeline_common/document_search.py` (Task 1에서 만든 `get_document_detail` stub 구현)
- Test: `tests/test_pipeline_common_document_search.py`

**Interfaces:**
- Consumes: Task 1의 `DocumentDetail`, `get_supabase`, `storage.split_key`
- Produces: `get_document_detail(workspace_id: str, document_version_id: str, *, supabase=None) -> DocumentDetail | None` — Task 3(`WikiTools.read_document`)이 그대로 가져다 쓴다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_pipeline_common_document_search.py`에 이어서 추가:

```python
def test_get_document_detail_returns_full_content_and_metadata():
    supabase = FakeSupabase(
        tables={
            "document_versions": [_version_row("ver-1", "doc-1", 1, "processed/ws-1/doc-1/1.md")],
            "documents": [_document_row("doc-1", "SK하이닉스 ADR 상장", "2026-07-10T00:00:00+00:00")],
            "sources": [{"id": "source-1", "name": "DART - SK하이닉스"}],
        },
        objects={"ws-1/doc-1/1.md": "SK하이닉스가 나스닥에 ADR을 상장했다.".encode("utf-8")},
    )

    detail = document_search.get_document_detail(WORKSPACE_ID, "ver-1", supabase=supabase)

    assert detail is not None
    assert detail.document_version_id == "ver-1"
    assert detail.title == "SK하이닉스 ADR 상장"
    assert detail.markdown == "SK하이닉스가 나스닥에 ADR을 상장했다."
    assert detail.canonical_url == "https://example.com/doc-1"
    assert detail.source_name == "DART - SK하이닉스"
    assert detail.published_at == "2026-07-10T00:00:00+00:00"


def test_get_document_detail_returns_none_when_version_not_found():
    supabase = FakeSupabase(tables={"document_versions": [], "documents": [], "sources": []})

    detail = document_search.get_document_detail(WORKSPACE_ID, "missing-ver", supabase=supabase)

    assert detail is None


def test_get_document_detail_returns_none_when_workspace_mismatch():
    """다른 workspace의 문서는 조회되면 안 된다 — workspace 격리."""
    supabase = FakeSupabase(
        tables={
            "document_versions": [_version_row("ver-1", "doc-1", 1, "processed/other-ws/doc-1/1.md")],
            "documents": [
                {**_document_row("doc-1", "다른 워크스페이스 문서", "2026-07-10T00:00:00+00:00"), "workspace_id": "other-ws"}
            ],
            "sources": [],
        },
        objects={},
    )

    detail = document_search.get_document_detail(WORKSPACE_ID, "ver-1", supabase=supabase)

    assert detail is None
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_pipeline_common_document_search.py -k get_document_detail -v`
Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: `get_document_detail` 구현**

`src/pipeline_common/document_search.py`의 `get_document_detail` stub을 교체:

```python
def get_document_detail(
    workspace_id: str, document_version_id: str, *, supabase: Client | None = None
) -> DocumentDetail | None:
    db = supabase or get_supabase()

    version_res = (
        db.table("document_versions")
        .select("id, document_id, markdown_object_key")
        .eq("id", document_version_id)
        .maybe_single()
        .execute()
    )
    version = version_res.data if version_res else None
    if not version:
        return None

    document_res = (
        db.table("documents")
        .select("id, title, canonical_url, published_at, source_id")
        .eq("id", version["document_id"])
        .eq("workspace_id", workspace_id)
        .maybe_single()
        .execute()
    )
    document = document_res.data if document_res else None
    if not document:
        return None

    source_name = None
    if document.get("source_id"):
        source_res = (
            db.table("sources")
            .select("name")
            .eq("id", document["source_id"])
            .maybe_single()
            .execute()
        )
        if source_res and source_res.data:
            source_name = source_res.data.get("name")

    bucket, path = storage.split_key(version["markdown_object_key"])
    markdown_bytes = db.storage.from_(bucket).download(path)

    return DocumentDetail(
        document_version_id=str(version["id"]),
        title=str(document["title"]),
        markdown=markdown_bytes.decode("utf-8"),
        canonical_url=document.get("canonical_url"),
        source_name=source_name,
        published_at=document.get("published_at"),
    )
```

- [ ] **Step 4: 전체 테스트 통과 확인**

Run: `pytest tests/test_pipeline_common_document_search.py -v`
Expected: 7개 테스트 전부 PASS

- [ ] **Step 5: 커밋**

```bash
git add src/pipeline_common/document_search.py tests/test_pipeline_common_document_search.py
git commit -m "feat: 원문 문서 단건 조회 추가 (get_document_detail)"
```

---

### Task 3: `WikiTools.search_documents()` / `read_document()` 위임 메서드

**Files:**
- Modify: `src/agent/wiki_tools.py`
- Test: `tests/test_agent_wiki_tools.py`

**Interfaces:**
- Consumes: Task 1/2의 `document_search.search_documents`/`get_document_detail`/`DocumentSearchHit`/`DocumentDetail`
- Produces: `WikiTools.search_documents(query, limit=5) -> list[DocumentSearchHit]`, `WikiTools.read_document(document_version_id) -> Optional[DocumentDetail]` — Task 5(`core.py`의 `_document_answer`)가 그대로 가져다 쓴다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_agent_wiki_tools.py` 맨 아래에 추가:

```python
def test_search_documents_delegates_to_document_search_module(monkeypatch):
    captured = {}

    def fake_search_documents(workspace_id, query, limit=5, *, supabase=None):
        captured["workspace_id"] = workspace_id
        captured["query"] = query
        captured["limit"] = limit
        return []

    monkeypatch.setattr(
        "src.agent.wiki_tools.document_search.search_documents", fake_search_documents
    )

    tools = WikiTools(workspace_id="ws-1")
    tools.search_documents("SK하이닉스 ADR", limit=3)

    assert captured == {"workspace_id": "ws-1", "query": "SK하이닉스 ADR", "limit": 3}


def test_read_document_delegates_to_document_search_module(monkeypatch):
    captured = {}

    def fake_get_document_detail(workspace_id, document_version_id, *, supabase=None):
        captured["workspace_id"] = workspace_id
        captured["document_version_id"] = document_version_id
        return None

    monkeypatch.setattr(
        "src.agent.wiki_tools.document_search.get_document_detail", fake_get_document_detail
    )

    tools = WikiTools(workspace_id="ws-1")
    result = tools.read_document("ver-1")

    assert result is None
    assert captured == {"workspace_id": "ws-1", "document_version_id": "ver-1"}
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_agent_wiki_tools.py -k "search_documents_delegates or read_document_delegates" -v`
Expected: FAIL — `AttributeError: <module 'src.agent.wiki_tools'> does not have the attribute 'document_search'`

- [ ] **Step 3: `WikiTools`에 위임 메서드 추가**

`src/agent/wiki_tools.py` 수정 — import 추가:

```python
from ..pipeline_common import document_search
```

파일 맨 위 docstring도 갱신(더 이상 위키 전용이 아님을 명시):

```python
"""
Wiki·원문 문서 조회 도구 — Agent 전용 어댑터 (Karpathy LLM Wiki 패턴).

Agent 가 list_wiki_topics() → read_wiki_page() 를 순차 호출해 필요한 문서만 읽는다.
위키에 근거가 없을 때는 search_documents() → read_document()로 수집된 원문(뉴스+DART,
위키 발행 여부 무관)에서 근거를 찾는다.
실제 DB/Storage 조회는 src/wiki/query.py, src/pipeline_common/document_search.py 에 위임한다.

변경 시 주의:
- WikiPageContent.sources 의 필드명은 core.py 가 __dict__ 로 직접 접근하므로
  src/wiki/interface.py 의 WikiSource 필드명과 맞춰야 한다.
"""
```

클래스 맨 아래(`search_wiki_pages` 메서드 뒤)에 메서드 추가:

```python
    def search_documents(
        self, query: str, limit: int = DEFAULT_SEARCH_LIMIT
    ) -> list[document_search.DocumentSearchHit]:
        """
        질문 키워드로 수집된 원문(뉴스+DART, 위키 발행 여부 무관)을 title+본문 관련도
        순으로 찾는다. 위키에 근거가 없을 때(_document_answer)만 쓰는 2차 검색 도구다 —
        위키 발행 여부와 무관하게 수집된 원문 전체를 대상으로 한다.
        """
        return document_search.search_documents(self.workspace_id, query, limit=limit)

    def read_document(self, document_version_id: str) -> Optional[document_search.DocumentDetail]:
        """원문 문서 1건의 전체 내용과 출처 메타데이터(매체명·게시일·원문 링크)를 반환한다."""
        return document_search.get_document_detail(self.workspace_id, document_version_id)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_agent_wiki_tools.py -v`
Expected: 기존 6개 + 신규 2개 = 8개 전부 PASS

- [ ] **Step 5: 커밋**

```bash
git add src/agent/wiki_tools.py tests/test_agent_wiki_tools.py
git commit -m "feat: WikiTools에 원문 문서 검색/조회 위임 메서드 추가"
```

---

### Task 4: `_wiki_answer`를 공유 헬퍼 `_run_grounded_answer`로 리팩터링

**Files:**
- Modify: `src/agent/core.py`
- Test: `tests/test_agent_core.py` (수정 없음 — 리팩터링 안전성은 기존 24개 테스트로 검증)

**Interfaces:**
- Consumes: 없음(내부 리팩터링)
- Produces: `WikiAgent._run_grounded_answer(question, history, *, system_prompt, tools, tool_handlers) -> AgentResult` — Task 5의 `_document_answer`가 그대로 가져다 쓴다. `tool_handlers`는 `dict[str, Callable[[dict, set[str]], object]]` — key는 tool 이름, value는 `(args, seen_document_version_ids) -> JSON 직렬화 가능한 결과`. `WikiAgent._call_model(messages, *, use_tools=True, tools=None)` — `tools=None`이면 `TOOLS`를 기본으로 쓴다.

이 태스크는 **동작을 바꾸지 않는 리팩터링**이다 — 새 테스트를 추가하지 않고, 기존 `tests/test_agent_core.py`의 24개 테스트가 한 글자도 안 고친 채로 전부 통과하는 것 자체가 성공 기준이다.

- [ ] **Step 1: 리팩터링 전 베이스라인 확인**

Run: `pytest tests/test_agent_core.py -v`
Expected: 24 passed (리팩터링 전 상태 기록 — 이후 비교 기준)

- [ ] **Step 2: `Callable` import 추가**

`src/agent/core.py` 상단 import 수정:

```python
from typing import Callable, Optional
```

- [ ] **Step 3: `_call_model`/`_complete`에 `tools` 파라미터 추가**

`src/agent/core.py`의 `_call_model`/`_complete`(현재 330~368행)를 교체:

```python
    def _call_model(self, messages: list[dict], *, use_tools: bool = True, tools: list[dict] | None = None):
        try:
            return self._complete(MODEL_NAME, messages, use_tools=use_tools, tools=tools)
        except Exception:
            if FALLBACK_MODEL_NAME == MODEL_NAME:
                raise
            logger.warning(
                "openrouter_primary_model_failed_using_fallback",
                extra={"primary_model": MODEL_NAME, "fallback_model": FALLBACK_MODEL_NAME},
            )
            return self._complete(FALLBACK_MODEL_NAME, messages, use_tools=use_tools, tools=tools)

    def _complete(
        self, model: str, messages: list[dict], *, use_tools: bool = True, tools: list[dict] | None = None
    ):
        # _llm_fallback_answer(위키 근거 없는 일반 지식 답변)는 tools 없이 호출한다 —
        # WikiTools/citations를 아예 안 주려는 것이므로 도구 자체를 노출하면 안 된다.
        if not use_tools:
            response = self.client.chat.completions.create(
                model=model, max_tokens=1500, messages=messages,
            )
        else:
            response = self.client.chat.completions.create(
                model=model,
                max_tokens=1500,
                tools=tools if tools is not None else TOOLS,
                # 매 라운드는 4개 도구 중 하나로 끝나야 한다는 게 아래 로직 전체의 전제다.
                # tool_choice="auto"(기본값)로 두면 모델이 도구 없이 텍스트로 답을 끝낼 수
                # 있는데, 특히 대화 히스토리가 있는 짧은 후속 질문("그러면~")에서 모델이
                # 직전 턴 답변 텍스트를 근거로 오인해 이번 턴 조회를 건너뛰는 경우가 있었다
                # ("모델이 근거 조회 없이 응답을 종료함"). "required"로 강제해 그 경로를 막는다.
                tool_choice="required",
                messages=messages,
            )
        # 실측 버그: OpenRouter가 HTTP 200에 choices=None(또는 빈 배열)인 응답을 줄 때가
        # 있다 — 예외를 안 던져서 그대로 두면 호출부의 response.choices[0]에서
        # TypeError로 크래시한다. 여기서 실패로 취급해야 _call_model의 기존 폴백 모델
        # 재시도 경로(원인이 primary 모델 자체가 아니어도)를 그대로 탄다.
        if not response.choices:
            raise OpenRouterEmptyResponseError(f"OpenRouter returned no choices (model={model})")
        return response
```

- [ ] **Step 4: `_wiki_answer`를 `_run_grounded_answer` 호출로 교체**

`src/agent/core.py`의 `_wiki_answer`(현재 224~315행)를 통째로 아래로 교체:

```python
    def _wiki_answer(self, question: str, history: Optional[list[dict]] = None) -> AgentResult:
        def handle_list_wiki_topics(args: dict, seen: set[str]) -> object:
            topics = self.wiki_tools.list_wiki_topics()
            return [t.__dict__ for t in topics]

        def handle_search_wiki_pages(args: dict, seen: set[str]) -> object:
            hits = self.wiki_tools.search_wiki_pages(args["query"])
            return [h.__dict__ for h in hits]

        def handle_read_wiki_page(args: dict, seen: set[str]) -> object:
            page = self.wiki_tools.read_wiki_page(args["slug"])
            if page is None:
                return {"error": "문서를 찾을 수 없음"}
            seen.update(s.document_version_id for s in page.sources)
            return {
                "title": page.title,
                "markdown": page.markdown,
                "sources": [s.__dict__ for s in page.sources],
            }

        return self._run_grounded_answer(
            question,
            history,
            system_prompt=SYSTEM_PROMPT,
            tools=TOOLS,
            tool_handlers={
                "list_wiki_topics": handle_list_wiki_topics,
                "search_wiki_pages": handle_search_wiki_pages,
                "read_wiki_page": handle_read_wiki_page,
            },
        )

    def _run_grounded_answer(
        self,
        question: str,
        history: Optional[list[dict]],
        *,
        system_prompt: str,
        tools: list[dict],
        tool_handlers: dict[str, Callable[[dict, set[str]], object]],
    ) -> AgentResult:
        """라운드 루프 본체 — _wiki_answer/_document_answer가 공유한다.

        tool_handlers는 {tool 이름: handler}. handler(args, seen_document_version_ids)는
        JSON 직렬화 가능한 tool 결과를 반환하고, "읽기" 성격의 도구라면
        seen_document_version_ids를 in-place로 갱신해야 한다(뒤이은 submit_answer의
        grounding 검증이 이 집합을 기준으로 판정한다). submit_answer/submit_no_answer는
        두 그라운딩 단계에서 동일하므로 여기서 직접 처리하고 tool_handlers에 넣지 않는다.
        """
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        messages.extend(history or [])
        messages.append({"role": "user", "content": question})
        seen_document_version_ids: set[str] = set()

        for _ in range(MAX_TOOL_ROUNDS):
            response = self._call_model(messages, tools=tools)
            choice = response.choices[0]
            message = choice.message

            if choice.finish_reason != "tool_calls" or not message.tool_calls:
                # 모델이 도구 없이 텍스트로만 끝냈다면, 규칙 위반이므로 근거 없음으로 처리
                return AgentResult(has_answer=False, no_answer_reason="모델이 근거 조회 없이 응답을 종료함")

            messages.append(message.model_dump(exclude_unset=True))
            terminal_result: Optional[AgentResult] = None

            for tool_call in message.tool_calls:
                name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments or "{}")
                except json.JSONDecodeError:
                    # 실측 버그: 모델이 tool call 인자로 잘린(비정상 종료된) JSON을 줄 때가
                    # 있다 — 그대로 두면 answer() 전체가 크래시한다. 이 호출만 실패로
                    # 알리고 다음 라운드에서 모델이 다시 시도하게 둔다.
                    messages.append(
                        self._tool_result(tool_call.id, {"error": "잘못된 인자(JSON 파싱 실패)"})
                    )
                    continue

                if name in tool_handlers:
                    output = tool_handlers[name](args, seen_document_version_ids)
                    messages.append(self._tool_result(tool_call.id, output))

                elif name == "submit_answer":
                    try:
                        citations = [Citation(**c) for c in args.get("citations", [])]
                        is_grounded = self._is_grounded(citations, seen_document_version_ids)
                    except (TypeError, ValueError):
                        # 모델이 citations 항목에 필수 필드(quote 등)를 빼먹거나
                        # relevance_score에 숫자가 아닌 값을 넣는 등 도구 스키마를 어겼을 때 —
                        # 그대로 두면 Citation(**c) 생성이나 _is_grounded의 점수 비교에서
                        # TypeError가 나서 요청 전체가 죽는다(실측: 폴백 모델 응답에서 발생).
                        # 지어낸/형식이 어긋난 근거이므로 근거 없음으로 강등한다.
                        citations = []
                        is_grounded = False
                    if is_grounded:
                        terminal_result = AgentResult(
                            has_answer=True,
                            answer=strip_orphaned_citation_markers(args["answer"], len(citations)),
                            citations=citations,
                        )
                    else:
                        # citations가 비었거나, 실제로 조회한 문서에 없는 document_version_id를
                        # 인용했거나(모델의 지어낸 근거), relevance_score가 CHECK 제약(0~1)
                        # 범위를 벗어남 — 이런 답변을 그대로 저장하면 message_citations
                        # FK/CHECK 위반으로 API가 500을 내거나, 근거 없는 답이 저장된다.
                        terminal_result = AgentResult(
                            has_answer=False,
                            no_answer_reason="인용 근거가 실제로 조회한 문서와 일치하지 않음",
                        )
                    messages.append(self._tool_result(tool_call.id, {"status": "recorded"}))

                elif name == "submit_no_answer":
                    terminal_result = AgentResult(
                        has_answer=False, no_answer_reason=args["reason"],
                    )
                    messages.append(self._tool_result(tool_call.id, {"status": "recorded"}))

            if terminal_result is not None:
                return terminal_result

        return AgentResult(has_answer=False, no_answer_reason="최대 조회 횟수 초과 — 근거 확정 실패")
```

- [ ] **Step 5: 리팩터링 후 회귀 확인 (기존 24개 무변경 통과)**

Run: `pytest tests/test_agent_core.py -v`
Expected: 24 passed — Step 1과 정확히 같은 개수, 테스트 코드는 한 글자도 안 고침. 하나라도 실패하면 리팩터링이 동작을 바꾼 것이므로, diff를 다시 보고 원래 `_wiki_answer` 로직과 한 줄씩 대조한다.

- [ ] **Step 6: 커밋**

```bash
git add src/agent/core.py
git commit -m "refactor: _wiki_answer 라운드 루프를 공유 헬퍼 _run_grounded_answer로 추출"
```

---

### Task 5: `_document_answer` 추가 + `answer()` 3단계로 확장

**Files:**
- Modify: `src/agent/core.py`
- Test: `tests/test_agent_core.py`

**Interfaces:**
- Consumes: Task 3의 `WikiTools.search_documents`/`read_document`, Task 4의 `_run_grounded_answer`
- Produces: `WikiAgent._document_answer(question, history=None) -> AgentResult`, `WikiAgent.answer()`가 3단계(`_wiki_answer` → `_document_answer` → `_llm_fallback_answer`)로 동작

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_agent_core.py`의 fake DTO 섹션(현재 `FakeSearchHit` 근처, 100번째 줄 부근)에 추가:

```python
@dataclass
class FakeDocumentSearchHit:
    document_version_id: str
    title: str
    score: float


@dataclass
class FakeDocumentDetail:
    document_version_id: str
    title: str
    markdown: str
    canonical_url: str
    source_name: str
    published_at: str
```

"LLM 폴백" 섹션(`test_answer_falls_back_to_llm_when_no_wiki_answer` 앞) 바로 위에 새 섹션과 테스트 3개를 추가:

```python
# ---------------------------------------------------------------------------
# 원문 문서 그라운딩 — 위키에 근거가 없어도 수집된 원문(뉴스+DART)에 근거가
# 있으면 그걸로 답변한다. citations[0].wiki_slug는 위키 페이지가 아니므로 None.
# ---------------------------------------------------------------------------

def test_answer_uses_document_answer_when_wiki_has_no_answer(agent, wiki_tools, monkeypatch):
    wiki_tools.search_documents.return_value = [
        FakeDocumentSearchHit(document_version_id="doc-ver-1", title="SK하이닉스 ADR 상장 공시", score=0.7)
    ]
    wiki_tools.read_document.return_value = FakeDocumentDetail(
        document_version_id="doc-ver-1",
        title="SK하이닉스 ADR 상장 공시",
        markdown="SK하이닉스가 나스닥에 ADR을 상장했다.",
        canonical_url="https://dart.fss.or.kr/example",
        source_name="DART - SK하이닉스",
        published_at="2026-07-10T00:00:00+00:00",
    )
    citation = {
        "document_version_id": "doc-ver-1",
        "quote": "SK하이닉스가 나스닥에 ADR을 상장했다.",
        "relevance_score": 0.9,
    }
    responses = [
        tool_call_response(("call-1", "submit_no_answer", {"reason": "위키에 관련 문서 없음"})),
        tool_call_response(("call-2", "search_documents", {"query": "SK하이닉스 ADR 상장"})),
        tool_call_response(("call-3", "read_document", {"document_version_id": "doc-ver-1"})),
        tool_call_response(("call-4", "submit_answer", {
            "answer": "SK하이닉스가 나스닥에 ADR을 상장했다. [1]",
            "citations": [citation],
        })),
    ]
    monkeypatch.setattr(agent, "_call_model", MagicMock(side_effect=responses))

    result = agent.answer("SK하이닉스 ADR 상장 공시가 뭐야?")

    assert result.has_answer is True
    assert result.is_llm_fallback is False
    assert len(result.citations) == 1
    assert result.citations[0].document_version_id == "doc-ver-1"
    assert result.citations[0].wiki_slug is None
    wiki_tools.search_documents.assert_called_once_with("SK하이닉스 ADR 상장")
    wiki_tools.read_document.assert_called_once_with("doc-ver-1")


def test_answer_falls_back_to_llm_when_wiki_and_documents_both_have_no_answer(agent, wiki_tools, monkeypatch):
    responses = [
        tool_call_response(("call-1", "submit_no_answer", {"reason": "위키에 관련 문서 없음"})),
        tool_call_response(("call-2", "submit_no_answer", {"reason": "원문에도 관련 문서 없음"})),
        plain_text_response("SK하이닉스는 국내 반도체 기업이다."),
    ]
    monkeypatch.setattr(agent, "_call_model", MagicMock(side_effect=responses))

    result = agent.answer("아무 질문")

    assert result.has_answer is True
    assert result.is_llm_fallback is True
    assert result.citations == []


def test_answer_falls_back_to_llm_when_document_answer_raises(agent, wiki_tools, monkeypatch):
    """_document_answer 도중 예외(OpenRouter 응답 이상 등)가 나도 500으로 죽지 않고
    다음 단계(LLM 폴백)로 넘어가야 한다 — _wiki_answer에 이미 있는 크래시 내성과 동일."""
    call_count = {"n": 0}

    def fake_call_model(messages, use_tools=True, tools=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return tool_call_response(("call-1", "submit_no_answer", {"reason": "위키에 관련 문서 없음"}))
        if not use_tools:
            return plain_text_response("일반 지식 답변")
        raise RuntimeError("OpenRouter returned no choices")

    monkeypatch.setattr(agent, "_call_model", fake_call_model)

    result = agent.answer("질문")

    assert result.has_answer is True
    assert result.is_llm_fallback is True
    assert result.answer == "일반 지식 답변"
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_agent_core.py -k "document_answer or wiki_and_documents" -v`
Expected: FAIL — `AttributeError: Mock object has no attribute 'search_documents'` 또는 `assert 0 == 1`(원문 단계가 아직 없어 바로 LLM 폴백으로 빠짐)

- [ ] **Step 3: `_document_answer` 추가 + `answer()` 3단계로 확장**

`src/agent/core.py`에서 `DOCUMENT_ANSWER_SYSTEM_PROMPT`/`DOCUMENT_TOOLS`를 `LLM_FALLBACK_SYSTEM_PROMPT` 정의(현재 64~70행) 바로 뒤, `TOOLS` 정의(72행) 앞에 추가:

```python
# 위키에는 없지만 수집된 원문(뉴스+DART)에는 있을 수 있는 경우에 쓰는 시스템 프롬프트.
# _wiki_answer가 실패했을 때만 시도하는 2차 그라운딩 단계.
DOCUMENT_ANSWER_SYSTEM_PROMPT = """\
너는 myWiki의 답변 Agent다. 위키에는 정리된 문서가 없지만, 수집된 원문(뉴스 기사·
DART 공시) 중에 관련 있는 게 있는지 찾는 단계다. 규칙:
1. 반드시 read_document로 실제 읽은 원문 내용만 근거로 답변해라. 사전 지식이나
   추측으로 빈틈을 채우지 마라.
2. search_documents로 질문의 핵심 키워드와 관련된 원문을 먼저 찾고, read_document로
   내용을 확인해라. 필요하면 여러 문서를 읽어도 된다.
3. 답을 뒷받침할 근거를 찾았으면 submit_answer를 호출해라. 문장마다 어떤 근거
   (citations)를 썼는지 반드시 포함하고, citations의 document_version_id는
   read_document 결과에서 실제로 읽은 것 중에서만 골라라 (지어내지 마라). 답변
   본문에 쓰는 근거 번호 [N]은 반드시 citations 배열의 N번째(1부터 시작) 항목과
   정확히 대응해야 한다 — citations에 없는 번호는 절대 쓰지 마라.
4. 근거를 찾지 못했거나 근거가 불충분하면 submit_answer 대신 반드시
   submit_no_answer를 호출해라.
5. 톤은 직접적이고 전문적으로, 가벼운 대화체는 쓰지 마라.
"""
```

`TOOLS` 리스트 정의(현재 72~157행) 바로 뒤에 `DOCUMENT_TOOLS`를 추가:

```python
_SUBMIT_ANSWER_TOOL = next(t for t in TOOLS if t["function"]["name"] == "submit_answer")
_SUBMIT_NO_ANSWER_TOOL = next(t for t in TOOLS if t["function"]["name"] == "submit_no_answer")

DOCUMENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": (
                "질문 키워드로 수집된 원문(뉴스 기사·DART 공시, 위키 발행 여부 무관)을 "
                "제목+본문 관련도 순으로 찾는다."
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
    {
        "type": "function",
        "function": {
            "name": "read_document",
            "description": "특정 원문 문서의 전체 내용과 출처(매체명·게시일·원문 링크)를 반환한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "document_version_id": {
                        "type": "string",
                        "description": "search_documents 결과의 document_version_id",
                    },
                },
                "required": ["document_version_id"],
            },
        },
    },
    _SUBMIT_ANSWER_TOOL,
    _SUBMIT_NO_ANSWER_TOOL,
]
```

`answer()`(현재 188~205행)를 교체:

```python
    def answer(self, question: str, history: Optional[list[dict]] = None) -> AgentResult:
        """3단계로 근거를 찾는다: 위키(_wiki_answer) -> 수집된 원문(_document_answer) ->
        위키 근거 없이 일반 지식(_llm_fallback_answer). 앞 두 그라운딩 단계는 예외가
        나도(OpenRouter 응답 이상 등) 그대로 새 나가지 않고 다음 단계로 넘어간다 —
        500으로 죽는 대신 최소한 다음 단계 결과(또는 일반 지식 폴백)라도 낸다."""
        result = self._safe_run(
            self._wiki_answer, question, history, no_answer_reason="위키 근거 조회 중 오류 발생"
        )
        if result.has_answer:
            return result
        result = self._safe_run(
            self._document_answer, question, history, no_answer_reason="원문 문서 조회 중 오류 발생"
        )
        if result.has_answer:
            return result
        fallback = self._llm_fallback_answer(question, history)
        return fallback if fallback is not None else result

    def _safe_run(
        self,
        method: Callable[[str, Optional[list[dict]]], AgentResult],
        question: str,
        history: Optional[list[dict]],
        *,
        no_answer_reason: str,
    ) -> AgentResult:
        try:
            return method(question, history)
        except Exception:  # noqa: BLE001 - OpenRouter 응답 이상 등, 다음 단계로 넘긴다
            logger.warning("grounded_answer_step_failed", exc_info=True, extra={"step": method.__name__})
            return AgentResult(has_answer=False, no_answer_reason=no_answer_reason)
```

`_wiki_answer` 메서드(Task 4에서 리팩터링된 버전) 바로 뒤에 `_document_answer`를 추가:

```python
    def _document_answer(self, question: str, history: Optional[list[dict]] = None) -> AgentResult:
        def handle_search_documents(args: dict, seen: set[str]) -> object:
            hits = self.wiki_tools.search_documents(args["query"])
            return [h.__dict__ for h in hits]

        def handle_read_document(args: dict, seen: set[str]) -> object:
            document = self.wiki_tools.read_document(args["document_version_id"])
            if document is None:
                return {"error": "문서를 찾을 수 없음"}
            seen.add(document.document_version_id)
            return {
                "title": document.title,
                "markdown": document.markdown,
                "canonical_url": document.canonical_url,
                "source_name": document.source_name,
                "published_at": document.published_at,
            }

        return self._run_grounded_answer(
            question,
            history,
            system_prompt=DOCUMENT_ANSWER_SYSTEM_PROMPT,
            tools=DOCUMENT_TOOLS,
            tool_handlers={
                "search_documents": handle_search_documents,
                "read_document": handle_read_document,
            },
        )
```

- [ ] **Step 4: 신규 테스트 통과 확인**

Run: `pytest tests/test_agent_core.py -k "document_answer or wiki_and_documents" -v`
Expected: 3개 PASS

- [ ] **Step 5: 전체 회귀 확인**

Run: `pytest tests/test_agent_core.py -v`
Expected: 24(기존) + 3(신규) = 27 passed

- [ ] **Step 6: 커밋**

```bash
git add src/agent/core.py tests/test_agent_core.py
git commit -m "feat: 위키 근거 없을 때 원문 문서(뉴스+DART) 근거로 답변하는 2차 그라운딩 단계 추가"
```

---

### Task 6: 전체 회귀 + 실제 DB로 최종 검증

**Files:** 없음(검증 전용 태스크)

**Interfaces:** 없음

- [ ] **Step 1: 전체 테스트 스위트 실행**

Run: `pytest tests/ -q`
Expected: 이 플랜에서 추가한 파일들의 테스트가 전부 통과하고, 그 외 실패가 있다면 이 브랜치 작업 전부터 있던 것인지 `git stash`로 baseline과 비교해 확인한다(이 세션에서 반복해온 방식 — 새 실패가 이 변경 때문인지 반드시 구분한다).

- [ ] **Step 2: 실제 DB로 원문 그라운딩 재현**

`WORKSPACE_ID`는 실제 workspace id로 교체해서 실행:

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
result = agent.answer('위키에 없고 원문에만 있을 법한 질문')
print('has_answer:', result.has_answer, 'is_llm_fallback:', result.is_llm_fallback)
for c in result.citations:
    print('citation:', c.document_version_id, c.wiki_slug)
"
```

Expected: 위키에 근거가 없는 질문인데도 `has_answer=True`, `is_llm_fallback=False`, `citations[0].wiki_slug is None`인 경우가 나오면(원문에 실제로 관련 내용이 있는 질문일 때) 원문 그라운딩이 실제로 동작한 것이다. `CitationOut.source_url`이 채워지는지는 `src/api/db.py::_enrich_message_citations`가 이미 검증돼 있으므로(기존 위키 citation과 동일 경로) 별도 확인 불필요.

- [ ] **Step 3: 최종 커밋 없음 — Task 1~5의 커밋이 이미 완료 상태**

이 태스크는 검증 전용이라 코드 변경이 없다. 문제를 발견하면 해당 Task로 돌아가 수정 후 그 Task의 커밋을 새로 만든다(이미 만든 커밋을 amend하지 않는다).

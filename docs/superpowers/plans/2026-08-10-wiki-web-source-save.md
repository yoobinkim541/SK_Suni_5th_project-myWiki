# 웹검색 근거 답변의 위키 저장 지원 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 웹검색/DART 근거로 답한 에이전트 메시지를 "위키에 저장"했을 때 `wiki_page_sources.document_version_id` NOT NULL 제약 위반으로 실패하던 걸 고쳐서, 문서 근거와 동일하게 저장·조회되게 한다.

**Architecture:** `message_citations`가 이미 쓰고 있는 "document_version_id nullable + source_url/source_title/published_at 컬럼" 패턴을 `wiki_page_sources`에도 그대로 이식한다. 쓰기 경로(`_build_source_rows`, `save_message_to_wiki`)와 읽기 경로(`_enrich_sources`)를 각각 이 새 필드를 다루도록 확장한다. 프론트엔드는 이미 `sourceName`/`url` 없는 근거를 정상 처리하므로 변경하지 않는다.

**Tech Stack:** Python, Supabase(Postgres), pydantic/dataclass DTO, pytest(FakeSupabase 단위 테스트 + 일부는 실제 Supabase 연동 테스트).

## Global Constraints

- 문서 근거(`document_version_id` 있는 행)의 기존 동작(라이브 조인으로 제목·매체명·게시일·신뢰도 표시)은 절대 퇴화시키지 않는다.
- `document_version_id`도 `source_url`도 없는 근거 행은 DB CHECK 제약으로 막는다.
- `published_at`은 TEXT 타입으로 저장한다 — `message_citations`가 이미 이 타입을 쓰는 관례를 따른다.
- 프론트엔드 코드는 변경하지 않는다.
- 새 모델/설정 분기점을 만들지 않는다(이번 작업은 LLM 호출이 없다 — 해당 없음).

---

### Task 1: DB 마이그레이션 — `wiki_page_sources` 스키마 확장

**Files:**
- Create: `supabase/migrations/20260810010000_wiki_page_sources_web_search.sql`

**Interfaces:**
- Produces: `wiki_page_sources.document_version_id`(nullable로 변경), `wiki_page_sources.source_url`/`source_title`/`published_at`(신규 TEXT nullable 컬럼), CHECK 제약 `ck_wps_has_identifier`.

- [ ] **Step 1: 마이그레이션 파일 작성**

`supabase/migrations/20260808010000_message_citations_web_search.sql`이 `message_citations`에 이미 적용한 것과 정확히 같은 패턴이다. 새 파일에 아래 내용을 그대로 작성:

```sql
ALTER TABLE public.wiki_page_sources ALTER COLUMN document_version_id DROP NOT NULL;

ALTER TABLE public.wiki_page_sources ADD COLUMN IF NOT EXISTS source_url TEXT;
ALTER TABLE public.wiki_page_sources ADD COLUMN IF NOT EXISTS source_title TEXT;
ALTER TABLE public.wiki_page_sources ADD COLUMN IF NOT EXISTS published_at TEXT;

ALTER TABLE public.wiki_page_sources
ADD CONSTRAINT ck_wps_has_identifier CHECK (document_version_id IS NOT NULL OR source_url IS NOT NULL);
```

- [ ] **Step 2: 라이브 Supabase에 적용**

Supabase MCP(`mcp__c2efe9a0-2e64-4e70-a81f-15d0dabd2f27__apply_migration`, project_id는 `uhzjshqmnlahhvqzygkp`)로 Step 1의 SQL을 적용한다. `name` 파라미터는 `wiki_page_sources_web_search`로 준다.

- [ ] **Step 3: 적용 확인**

Supabase MCP(`mcp__c2efe9a0-2e64-4e70-a81f-15d0dabd2f27__execute_sql`, 같은 project_id)로 아래 쿼리를 실행해 컬럼이 정확히 반영됐는지 확인:

```sql
select column_name, is_nullable, data_type from information_schema.columns
where table_name = 'wiki_page_sources'
and column_name in ('document_version_id', 'source_url', 'source_title', 'published_at')
order by column_name;
```

Expected: `document_version_id`가 `is_nullable=YES`, `source_url`/`source_title`/`published_at` 3개 행이 각각 `is_nullable=YES`, `data_type=text`로 나와야 한다.

- [ ] **Step 4: 커밋**

```bash
git add supabase/migrations/20260810010000_wiki_page_sources_web_search.sql
git commit -m "Feat: wiki_page_sources에 웹 근거 저장을 위한 컬럼 추가"
```

---

### Task 2: 쓰기 경로 — DTO 확장 + 근거 행 그룹핑 수정 + 저장 배선

**Files:**
- Modify: `src/wiki/interface.py`
- Modify: `src/wiki/service.py`
- Modify: `src/api/main.py`
- Test: `tests/test_wiki_service.py`
- Test: `tests/test_chat_sessions.py`

**Interfaces:**
- Consumes: Task 1의 `wiki_page_sources.source_url`/`source_title`/`published_at` 컬럼(DB에 이미 존재해야 이 태스크의 insert가 성공한다 — Task 1이 선행돼야 함).
- Produces: `WikiSourceInput(document_version_id: Optional[str] = None, source_url: Optional[str] = None, source_title: Optional[str] = None, published_at: Optional[str] = None, claim_text: str, source_start_line=None, source_end_line=None, support_type="supports", citation_order=None)`.

- [ ] **Step 1: 실패 테스트 작성 — `_build_source_rows`가 서로 다른 웹 출처를 안 뭉개는지**

`tests/test_wiki_service.py`의 `test_build_source_rows_still_dedupes_identical_repeats` 함수 바로 다음에 추가:

```python
def test_build_source_rows_keeps_distinct_web_sources_separate():
    """document_version_id가 없는(웹검색 근거) 소스는 전부 None이 같은 값이라, document_version_id만
    묶음 키로 쓰면 서로 다른 웹 출처 두 개가 한 행으로 뭉개진다 — source_url이 다르면 별도 행이어야 한다."""
    rows = _build_source_rows(
        "version-1",
        [
            WikiSourceInput(
                document_version_id=None, source_url="https://a.example/1", source_title="기사 A",
                published_at="2026-08-01", claim_text="주장 A", citation_order=1,
            ),
            WikiSourceInput(
                document_version_id=None, source_url="https://b.example/2", source_title="기사 B",
                published_at="2026-08-02", claim_text="주장 B", citation_order=2,
            ),
        ],
    )

    assert len(rows) == 2
    row_a = next(r for r in rows if r["source_url"] == "https://a.example/1")
    row_b = next(r for r in rows if r["source_url"] == "https://b.example/2")
    assert row_a["document_version_id"] is None
    assert row_a["source_title"] == "기사 A"
    assert row_a["published_at"] == "2026-08-01"
    assert row_a["claim_text"] == "주장 A"
    assert row_b["claim_text"] == "주장 B"


def test_build_source_rows_merges_identical_web_source_repeats():
    """같은 source_url을 가리키는 웹 근거가 여러 번 들어오면(같은 문서 다른 정보) 문서 근거와
    동일하게 한 행으로 합쳐지고 claim_text가 이어붙는지 확인한다."""
    rows = _build_source_rows(
        "version-1",
        [
            WikiSourceInput(
                document_version_id=None, source_url="https://a.example/1", source_title="기사 A",
                claim_text="주장 A",
            ),
            WikiSourceInput(
                document_version_id=None, source_url="https://a.example/1", source_title="기사 A",
                claim_text="주장 A-2",
            ),
        ],
    )

    assert len(rows) == 1
    assert "주장 A" in rows[0]["claim_text"]
    assert "주장 A-2" in rows[0]["claim_text"]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_wiki_service.py -k build_source_rows -v`
Expected: FAIL — `WikiSourceInput.__init__() got an unexpected keyword argument 'source_url'`(아직 필드 없음).

- [ ] **Step 3: `WikiSourceInput`/`WikiSource`에 필드 추가**

`src/wiki/interface.py`의 `WikiSourceInput`을:
```python
class WikiSourceInput:
    """Input row for `wiki_page_sources`."""

    document_version_id: str
    claim_text: str
    source_start_line: Optional[int] = None
    source_end_line: Optional[int] = None
    support_type: SupportType = "supports"
    citation_order: Optional[int] = None
```
다음으로 교체:
```python
class WikiSourceInput:
    """Input row for `wiki_page_sources`."""

    claim_text: str
    document_version_id: Optional[str] = None
    source_url: Optional[str] = None
    source_title: Optional[str] = None
    published_at: Optional[str] = None
    source_start_line: Optional[int] = None
    source_end_line: Optional[int] = None
    support_type: SupportType = "supports"
    citation_order: Optional[int] = None
```
(`document_version_id`를 기본값 있는 필드들 사이로 옮기면서 `Optional`로 바꿨다 — 이 dataclass는 기본값 없는 필드가 기본값 있는 필드보다 먼저 와야 하므로, `claim_text`를 맨 앞으로 옮겼다. 기존 호출부는 전부 키워드 인자로 호출하므로 순서 변경은 영향 없다 — `src/wiki/generation.py`/`src/wiki/dedup.py`/`src/api/main.py`에서 `WikiSourceInput(document_version_id=..., claim_text=..., ...)`처럼 전부 키워드로 부른다.)

같은 파일의 `WikiSource`를:
```python
class WikiSource:
    """Traceable source attached to a wiki claim."""

    document_version_id: str
    citation_order: Optional[int]
    claim_text: Optional[str]
    support_type: Optional[str]
    source_start_line: Optional[int]
    source_end_line: Optional[int]
    document_title: Optional[str] = None
    source_name: Optional[str] = None
    canonical_url: Optional[str] = None
    published_at: Optional[str] = None
    reliability_score: Optional[int] = None
```
다음으로 교체(`document_version_id`만 `Optional`로):
```python
class WikiSource:
    """Traceable source attached to a wiki claim."""

    document_version_id: Optional[str]
    citation_order: Optional[int]
    claim_text: Optional[str]
    support_type: Optional[str]
    source_start_line: Optional[int]
    source_end_line: Optional[int]
    document_title: Optional[str] = None
    source_name: Optional[str] = None
    canonical_url: Optional[str] = None
    published_at: Optional[str] = None
    reliability_score: Optional[int] = None
```

- [ ] **Step 4: `_build_source_rows` 그룹핑 키 수정 + 새 필드 전달**

`src/wiki/service.py`의 `_build_source_rows` 함수 전체를:
```python
def _build_source_rows(version_id: str, sources: list[WikiSourceInput]) -> list[dict[str, object]]:
    """Collapse to one row per document_version_id so the same source never renders
    twice in the "근거 문서" list — even when several distinct claims (e.g. from a
    wiki dedup-merge that carries claims over from two source pages) cite the same
    document. Distinct claim texts are merged into the row instead of dropped;
    exact-repeat claim texts collapse as before.
    """

    rows_by_document: dict[str, dict[str, object]] = {}
    claim_texts_by_document: dict[str, set[str]] = {}
    order: list[str] = []

    for source in sources:
        doc_id = source.document_version_id
        if doc_id not in rows_by_document:
            order.append(doc_id)
            rows_by_document[doc_id] = {
                "wiki_version_id": version_id,
                "document_version_id": doc_id,
                "claim_text": source.claim_text,
                "support_type": source.support_type,
                "source_start_line": source.source_start_line,
                "source_end_line": source.source_end_line,
                "citation_order": source.citation_order,
            }
            claim_texts_by_document[doc_id] = {source.claim_text}
            continue

        seen_claims = claim_texts_by_document[doc_id]
        if source.claim_text and source.claim_text not in seen_claims:
            seen_claims.add(source.claim_text)
            row = rows_by_document[doc_id]
            row["claim_text"] = f"{row['claim_text']} / {source.claim_text}" if row["claim_text"] else source.claim_text
        if rows_by_document[doc_id]["citation_order"] is None and source.citation_order is not None:
            rows_by_document[doc_id]["citation_order"] = source.citation_order

    rows = [rows_by_document[doc_id] for doc_id in order]
    for index, row in enumerate(rows):
        if row["citation_order"] is None:
            row["citation_order"] = index + 1
    return rows
```
다음으로 교체:
```python
def _build_source_rows(version_id: str, sources: list[WikiSourceInput]) -> list[dict[str, object]]:
    """Collapse to one row per source identity so the same source never renders
    twice in the "근거 문서" list — even when several distinct claims (e.g. from a
    wiki dedup-merge that carries claims over from two source pages) cite the same
    document. Distinct claim texts are merged into the row instead of dropped;
    exact-repeat claim texts collapse as before.

    document_version_id가 없는(웹검색 근거) 소스는 전부 None이 같은 값이라, 그것만
    묶음 키로 쓰면 서로 다른 웹 출처가 한 행으로 뭉개진다 — document_version_id가
    있으면 그걸, 없으면 source_url을 묶음 키로 쓴다.
    """

    rows_by_key: dict[str, dict[str, object]] = {}
    claim_texts_by_key: dict[str, set[str]] = {}
    order: list[str] = []

    for source in sources:
        key = source.document_version_id or f"web:{source.source_url}"
        if key not in rows_by_key:
            order.append(key)
            rows_by_key[key] = {
                "wiki_version_id": version_id,
                "document_version_id": source.document_version_id,
                "source_url": source.source_url,
                "source_title": source.source_title,
                "published_at": source.published_at,
                "claim_text": source.claim_text,
                "support_type": source.support_type,
                "source_start_line": source.source_start_line,
                "source_end_line": source.source_end_line,
                "citation_order": source.citation_order,
            }
            claim_texts_by_key[key] = {source.claim_text}
            continue

        seen_claims = claim_texts_by_key[key]
        if source.claim_text and source.claim_text not in seen_claims:
            seen_claims.add(source.claim_text)
            row = rows_by_key[key]
            row["claim_text"] = f"{row['claim_text']} / {source.claim_text}" if row["claim_text"] else source.claim_text
        if rows_by_key[key]["citation_order"] is None and source.citation_order is not None:
            rows_by_key[key]["citation_order"] = source.citation_order

    rows = [rows_by_key[key] for key in order]
    for index, row in enumerate(rows):
        if row["citation_order"] is None:
            row["citation_order"] = index + 1
    return rows
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest tests/test_wiki_service.py -k build_source_rows -v`
Expected: PASS 전부(기존 2개 + 신규 2개, 총 4개)

- [ ] **Step 6: `save_message_to_wiki`가 웹 근거 필드를 전달하도록 배선**

`src/api/main.py`의 `save_message_to_wiki` 안, `sources=[...]` 목록 생성부를:
```python
        sources=[
            WikiSourceInput(
                document_version_id=c["document_version_id"],
                claim_text=c.get("quoted_text") or "",
                source_start_line=c.get("source_start_line"),
                source_end_line=c.get("source_end_line"),
                support_type="supports",
                citation_order=c.get("citation_order"),
            )
            for c in citations
        ],
```
다음으로 교체:
```python
        sources=[
            WikiSourceInput(
                document_version_id=c["document_version_id"],
                source_url=c.get("source_url"),
                source_title=c.get("document_title"),
                published_at=c.get("published_at"),
                claim_text=c.get("quoted_text") or "",
                source_start_line=c.get("source_start_line"),
                source_end_line=c.get("source_end_line"),
                support_type="supports",
                citation_order=c.get("citation_order"),
            )
            for c in citations
        ],
```

- [ ] **Step 7: 실패 테스트 작성 — `save_message_to_wiki`가 웹 근거로 저장 성공하는지**

`tests/test_chat_sessions.py`의 `test_save_to_wiki_with_citations_creates_wiki_version` 함수 바로 다음에 새 테스트 추가(이 파일 상단의 `PRIVATE_SESSION`/`ASSISTANT_MESSAGE`/`USER_QUESTION`/`OWNER_ID` 등 기존 fixture를 그대로 재사용):

```python
WEB_CITATION = {
    "document_version_id": None,
    "document_title": "SK하이닉스 HBM4 로드맵 - 어떤매체",
    "source_url": "https://example.com/news/1",
    "published_at": "2026-08-01T00:00:00Z",
    "quoted_text": "HBM4는 6.4Gbps 이상을 목표로 한다.",
    "source_start_line": None,
    "source_end_line": None,
    "citation_order": 1,
}


def test_save_to_wiki_with_web_search_citation_succeeds(make_client, monkeypatch):
    """웹검색/DART 그라운딩 답변(document_version_id가 없는 citation)도 저장이 성공해야 한다 —
    document_version_id NOT NULL 제약 위반으로 실패하던 버그의 회귀 테스트."""
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: PRIVATE_SESSION if uid == OWNER_ID else None)
    monkeypatch.setattr(db, "get_chat_message", lambda mid: ASSISTANT_MESSAGE if mid == ASSISTANT_MESSAGE["id"] else None)
    monkeypatch.setattr(db, "list_message_citations", lambda mid: [WEB_CITATION])
    monkeypatch.setattr(db, "get_preceding_user_message", lambda sid, before: USER_QUESTION)
    monkeypatch.setattr(
        main_module, "compose_chat_wiki_draft",
        lambda question, answer, citations: chat_wiki.ChatWikiDraft(title="t", markdown="m"),
    )
    monkeypatch.setattr(main_module, "upsert_wiki_page", lambda workspace_id, slug, title, page_type: "page-1")
    monkeypatch.setattr(main_module, "update_wiki_page_title", lambda page_id, title: None)

    captured = {}

    def fake_create_wiki_version(draft):
        captured["draft"] = draft
        return "version-1"

    monkeypatch.setattr(main_module, "create_wiki_version", fake_create_wiki_version)
    monkeypatch.setattr(main_module, "record_wiki_validation", lambda *a, **kw: None)
    monkeypatch.setattr(main_module, "review_wiki_version", lambda *a, **kw: None)
    monkeypatch.setattr(main_module, "publish_wiki_version", lambda *a, **kw: None)

    res = make_client(OWNER_ID).post(
        f"/chat/sessions/{PRIVATE_SESSION['id']}/messages/{ASSISTANT_MESSAGE['id']}/save-to-wiki"
    )

    assert res.status_code == 200
    source = captured["draft"].sources[0]
    assert source.document_version_id is None
    assert source.source_url == "https://example.com/news/1"
    assert source.source_title == "SK하이닉스 HBM4 로드맵 - 어떤매체"
    assert source.published_at == "2026-08-01T00:00:00Z"
```

- [ ] **Step 8: 테스트 실패 확인**

Run: `pytest tests/test_chat_sessions.py -k web_search_citation -v`
Expected: FAIL — Step 6을 아직 안 했다면 `AssertionError: assert None == "https://example.com/news/1"`(source_url이 안 채워짐). Step 6을 이미 했다면(순서상 Step 6이 먼저이므로) 이 스텝은 곧바로 통과할 것이다 — 순서를 바꿔 실행해 실패를 실제로 재현하고 싶다면 Step 6 이전에 임시로 되돌려 확인해도 되지만 필수는 아니다.

- [ ] **Step 9: 테스트 통과 확인**

Run: `pytest tests/test_chat_sessions.py -k web_search_citation -v`
Expected: PASS

- [ ] **Step 10: 커밋**

```bash
git add src/wiki/interface.py src/wiki/service.py src/api/main.py tests/test_wiki_service.py tests/test_chat_sessions.py
git commit -m "Feat: 웹검색 근거를 위키 소스로 저장할 수 있게 함"
```

---

### Task 3: 읽기 경로 — `_enrich_sources`가 웹 근거를 정상 표시

**Files:**
- Modify: `src/wiki/query.py`
- Test: `tests/test_wiki_service.py`

**Interfaces:**
- Consumes: Task 2에서 확장된 `WikiSource(document_version_id: Optional[str], ...)`.
- Produces: `_enrich_sources`가 `document_version_id`가 없는 행도 크래시 없이 `WikiSource`로 변환.

- [ ] **Step 1: `get_published_wiki_page`의 select 필드 확장**

`src/wiki/query.py`의 `get_published_wiki_page` 안, `wiki_page_sources` 조회부를:
```python
    sources_res = (
        db.table("wiki_page_sources")
        .select(
            "document_version_id, citation_order, claim_text,"
            " support_type, source_start_line, source_end_line"
        )
        .eq("wiki_version_id", version_id)
        .order("citation_order")
        .execute()
    )
```
다음으로 교체:
```python
    sources_res = (
        db.table("wiki_page_sources")
        .select(
            "document_version_id, citation_order, claim_text,"
            " support_type, source_start_line, source_end_line,"
            " source_url, source_title, published_at"
        )
        .eq("wiki_version_id", version_id)
        .order("citation_order")
        .execute()
    )
```

- [ ] **Step 2: `_enrich_sources` 웹 근거 분기 처리**

`src/wiki/query.py`의 `_enrich_sources` 함수 전체를:
```python
def _enrich_sources(db: Client, workspace_id: str, rows: list[dict]) -> tuple[WikiSource, ...]:
    """
    wiki_page_sources 원본 행에 문서 제목·매체명·게시일·개별 신뢰도를 붙인다.

    PostgREST embedded join 대신 순차 조회를 쓴다(이 모듈·generation_repository.py의
    기존 관례) — document_version_id -> document_versions.document_id -> documents
    (title/canonical_url/published_at/source_id) -> sources.name, 그리고 별도로
    document_analysis_results.reliability_score. 화면의 "평균 신뢰도"는 여기서
    평균 내지 않고 개별 점수만 내려준다 — "근거 문서 건수"처럼 프론트에서
    배열 기준으로 계산하게 둔다(집계 로직이 백엔드/프론트 두 곳에 흩어지지 않게).
    """
    if not rows:
        return tuple()

    document_version_ids = list({row["document_version_id"] for row in rows})

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
            .eq("workspace_id", workspace_id)
            .in_("id", document_ids)
            .execute()
        )
        documents_by_id = {row["id"]: row for row in documents_res.data}

    source_ids = list({row["source_id"] for row in documents_by_id.values() if row.get("source_id")})
    source_name_by_id: dict[str, str] = {}
    if source_ids:
        sources_res = (
            db.table("sources")
            .select("id, name")
            .eq("workspace_id", workspace_id)
            .in_("id", source_ids)
            .execute()
        )
        source_name_by_id = {row["id"]: row["name"] for row in sources_res.data}

    analysis_res = (
        db.table("document_analysis_results")
        .select("document_version_id, reliability_score")
        .eq("workspace_id", workspace_id)
        .in_("document_version_id", document_version_ids)
        .execute()
    )
    reliability_by_version = {
        row["document_version_id"]: row["reliability_score"]
        for row in analysis_res.data
        if row.get("reliability_score") is not None
    }

    enriched = []
    for row in rows:
        document_id = document_id_by_version.get(row["document_version_id"])
        document = documents_by_id.get(document_id) if document_id else None
        enriched.append(
            WikiSource(
                document_version_id=row["document_version_id"],
                citation_order=row.get("citation_order"),
                claim_text=row.get("claim_text"),
                support_type=row.get("support_type"),
                source_start_line=row.get("source_start_line"),
                source_end_line=row.get("source_end_line"),
                document_title=document.get("title") if document else None,
                canonical_url=document.get("canonical_url") if document else None,
                published_at=document.get("published_at") if document else None,
                source_name=source_name_by_id.get(document.get("source_id")) if document else None,
                reliability_score=reliability_by_version.get(row["document_version_id"]),
            )
        )
    return tuple(enriched)
```
다음으로 교체:
```python
def _enrich_sources(db: Client, workspace_id: str, rows: list[dict]) -> tuple[WikiSource, ...]:
    """
    wiki_page_sources 원본 행에 문서 제목·매체명·게시일·개별 신뢰도를 붙인다.

    PostgREST embedded join 대신 순차 조회를 쓴다(이 모듈·generation_repository.py의
    기존 관례) — document_version_id -> document_versions.document_id -> documents
    (title/canonical_url/published_at/source_id) -> sources.name, 그리고 별도로
    document_analysis_results.reliability_score. 화면의 "평균 신뢰도"는 여기서
    평균 내지 않고 개별 점수만 내려준다 — "근거 문서 건수"처럼 프론트에서
    배열 기준으로 계산하게 둔다(집계 로직이 백엔드/프론트 두 곳에 흩어지지 않게).

    document_version_id가 없는 행(웹검색 근거)은 저장 시점에 이미 자기 행에
    source_url/source_title/published_at을 직접 채워뒀으므로(조인할 DB 행 자체가
    없음) 그 값을 그대로 쓰고, source_name/reliability_score는 개념이 없어 None으로 둔다.
    """
    if not rows:
        return tuple()

    document_version_ids = list({
        row["document_version_id"] for row in rows if row["document_version_id"] is not None
    })

    document_id_by_version: dict[str, str] = {}
    if document_version_ids:
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
            .eq("workspace_id", workspace_id)
            .in_("id", document_ids)
            .execute()
        )
        documents_by_id = {row["id"]: row for row in documents_res.data}

    source_ids = list({row["source_id"] for row in documents_by_id.values() if row.get("source_id")})
    source_name_by_id: dict[str, str] = {}
    if source_ids:
        sources_res = (
            db.table("sources")
            .select("id, name")
            .eq("workspace_id", workspace_id)
            .in_("id", source_ids)
            .execute()
        )
        source_name_by_id = {row["id"]: row["name"] for row in sources_res.data}

    reliability_by_version: dict[str, int] = {}
    if document_version_ids:
        analysis_res = (
            db.table("document_analysis_results")
            .select("document_version_id, reliability_score")
            .eq("workspace_id", workspace_id)
            .in_("document_version_id", document_version_ids)
            .execute()
        )
        reliability_by_version = {
            row["document_version_id"]: row["reliability_score"]
            for row in analysis_res.data
            if row.get("reliability_score") is not None
        }

    enriched = []
    for row in rows:
        if row["document_version_id"] is None:
            enriched.append(
                WikiSource(
                    document_version_id=None,
                    citation_order=row.get("citation_order"),
                    claim_text=row.get("claim_text"),
                    support_type=row.get("support_type"),
                    source_start_line=row.get("source_start_line"),
                    source_end_line=row.get("source_end_line"),
                    document_title=row.get("source_title"),
                    canonical_url=row.get("source_url"),
                    published_at=row.get("published_at"),
                    source_name=None,
                    reliability_score=None,
                )
            )
            continue
        document_id = document_id_by_version.get(row["document_version_id"])
        document = documents_by_id.get(document_id) if document_id else None
        enriched.append(
            WikiSource(
                document_version_id=row["document_version_id"],
                citation_order=row.get("citation_order"),
                claim_text=row.get("claim_text"),
                support_type=row.get("support_type"),
                source_start_line=row.get("source_start_line"),
                source_end_line=row.get("source_end_line"),
                document_title=document.get("title") if document else None,
                canonical_url=document.get("canonical_url") if document else None,
                published_at=document.get("published_at") if document else None,
                source_name=source_name_by_id.get(document.get("source_id")) if document else None,
                reliability_score=reliability_by_version.get(row["document_version_id"]),
            )
        )
    return tuple(enriched)
```

- [ ] **Step 3: 실패 테스트 작성 — 웹 근거와 문서 근거가 섞여도 둘 다 정확히 나오는지(실제 Supabase 연동)**

`tests/test_wiki_service.py`의 `test_published_page_sources_include_document_metadata` 함수 바로 다음에 추가(이 파일의 `workspace_id` 픽스처·`_get_client`·`create_wiki_version`·`record_wiki_validation`·`review_wiki_version`·`publish_wiki_version`·`get_published_wiki_page` import를 그대로 재사용):

```python
def test_published_page_sources_include_web_source_metadata(workspace_id):
    """document_version_id가 없는(웹검색 근거) 소스가 문서 근거와 섞여 저장돼도, 웹 근거는
    저장된 source_url/source_title/published_at을 그대로 돌려주고 문서 근거는 기존처럼
    라이브 조인 값을 돌려주는지 확인한다(회귀 방지)."""
    db = _get_client()
    analyzed = (
        db.table("document_analysis_results")
        .select("document_version_id")
        .eq("workspace_id", workspace_id)
        .not_.is_("reliability_score", "null")
        .limit(1)
        .execute()
    )
    if not analyzed.data:
        pytest.skip("신뢰도 점수가 있는 document_analysis_results 데이터 없음")
    doc_ver_id = analyzed.data[0]["document_version_id"]

    slug = f"test-web-src-{uuid.uuid4().hex[:8]}"
    draft = WikiDraftInput(
        workspace_id=workspace_id,
        slug=slug,
        title="웹 출처 테스트",
        page_type="term",
        markdown="근거 있는 내용",
        sources=[
            WikiSourceInput(document_version_id=doc_ver_id, claim_text="문서 근거 주장"),
            WikiSourceInput(
                document_version_id=None, source_url="https://example.com/web-src",
                source_title="웹 기사 제목", published_at="2026-08-01T00:00:00Z",
                claim_text="웹 근거 주장",
            ),
        ],
    )
    version_id = create_wiki_version(draft)
    ver = db.table("wiki_page_versions").select("page_id,markdown_object_key").eq("id", version_id).single().execute()
    page_id = ver.data["page_id"]
    obj_key = ver.data["markdown_object_key"]

    record_wiki_validation(version_id, "passed", 0.95)
    profile = db.table("profiles").select("id").limit(1).execute()
    if not profile.data:
        pytest.skip("profiles 데이터 없음")
    review_wiki_version(version_id, profile.data[0]["id"], "approved")
    publish_wiki_version(page_id, version_id)

    published = get_published_wiki_page(workspace_id, slug)
    assert published is not None
    assert len(published.sources) == 2

    doc_source = next(s for s in published.sources if s.document_version_id == str(doc_ver_id))
    assert doc_source.document_title is not None
    assert doc_source.reliability_score is not None

    web_source = next(s for s in published.sources if s.document_version_id is None)
    assert web_source.canonical_url == "https://example.com/web-src"
    assert web_source.document_title == "웹 기사 제목"
    assert web_source.published_at == "2026-08-01T00:00:00Z"
    assert web_source.source_name is None
    assert web_source.reliability_score is None

    db.table("wiki_pages").update({"current_version_id": None}).eq("id", page_id).execute()
    db.storage.from_("wiki").remove([obj_key])
    db.table("wiki_page_sources").delete().eq("wiki_version_id", version_id).execute()
    db.table("wiki_page_versions").delete().eq("id", version_id).execute()
    db.table("wiki_pages").delete().eq("id", page_id).execute()
```

- [ ] **Step 4: 테스트 실행**

Run: `pytest tests/test_wiki_service.py -k web_source_metadata -v`
Expected: PASS (Supabase 서비스 자격 증명이 로컬 `.env`에 있으므로 `workspace_id` 픽스처가 skip되지 않고 실제로 실행된다 — Task 1의 마이그레이션이 라이브 DB에 이미 적용돼 있어야 이 테스트가 통과한다).

- [ ] **Step 5: 전체 스위트 재확인**

Run: `pytest tests/test_wiki_service.py tests/test_wiki_query.py tests/test_wiki_router.py -v`
Expected: PASS 전부(회귀 없음 확인)

- [ ] **Step 6: 커밋**

```bash
git add src/wiki/query.py tests/test_wiki_service.py
git commit -m "Feat: 위키 근거 조회가 웹검색 출처도 정상 표시하게 함"
```

---

### Task 4: ERDCloud + docs 동기화

**Files:**
- Modify: `docs/architecture/myWiki_v2.sql`
- ERDCloud 다이어그램(https://www.erdcloud.com/d/qgLNBqodLMJAqG9FG) — `wiki_page_sources`, `message_citations` 테이블

**Interfaces:**
- Consumes: Task 1에서 실제 적용된 라이브 스키마(진실의 원천).

- [ ] **Step 1: `docs/architecture/myWiki_v2.sql`의 `wiki_page_sources` 정의 갱신**

파일에서 `CREATE TABLE `wiki_page_sources`` 블록을:
```sql
CREATE TABLE `wiki_page_sources` (
    `id`                    UUID         NOT NULL DEFAULT gen_random_uuid(),
    `wiki_version_id`       UUID         NOT NULL,
    `document_version_id`   UUID         NOT NULL,
    `claim_text`            TEXT,
    `source_start_line`     INTEGER,
    `source_end_line`       INTEGER,
    `support_type`          VARCHAR(20),
    `citation_order`        INTEGER,
    `created_at`            TIMESTAMPTZ  NOT NULL DEFAULT now()
);
```
다음으로 교체:
```sql
CREATE TABLE `wiki_page_sources` (
    `id`                    UUID         NOT NULL DEFAULT gen_random_uuid(),
    `wiki_version_id`       UUID         NOT NULL,
    `document_version_id`   UUID,
    `source_url`            TEXT,
    `source_title`          TEXT,
    `published_at`          TEXT,
    `claim_text`            TEXT,
    `source_start_line`     INTEGER,
    `source_end_line`       INTEGER,
    `support_type`          VARCHAR(20),
    `citation_order`        INTEGER,
    `created_at`            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT `ck_wps_has_identifier` CHECK (`document_version_id` IS NOT NULL OR `source_url` IS NOT NULL)
);
```

같은 파일에서 `CREATE TABLE `message_citations`` 블록(이미 라이브 DB와 어긋나 있던 것도 이번에 같이 정정)을:
```sql
CREATE TABLE `message_citations` (
    `id`                    UUID          NOT NULL DEFAULT gen_random_uuid(),
    `message_id`            UUID          NOT NULL,
    `document_version_id`   UUID          NOT NULL,
    `qmd_uri`               TEXT,
    `source_start_line`     INTEGER,
    `source_end_line`       INTEGER,
    `quoted_text`           TEXT,
    `relevance_score`       NUMERIC(5,4),
    `citation_order`        INTEGER,
    `created_at`            TIMESTAMPTZ   NOT NULL DEFAULT now()
);
```
다음으로 교체:
```sql
CREATE TABLE `message_citations` (
    `id`                    UUID          NOT NULL DEFAULT gen_random_uuid(),
    `message_id`            UUID          NOT NULL,
    `document_version_id`   UUID,
    `source_url`            TEXT,
    `source_title`          TEXT,
    `published_at`          TEXT,
    `qmd_uri`               TEXT,
    `source_start_line`     INTEGER,
    `source_end_line`       INTEGER,
    `quoted_text`           TEXT,
    `relevance_score`       NUMERIC(5,4),
    `citation_order`        INTEGER,
    `created_at`            TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT `ck_mc_has_identifier` CHECK (`document_version_id` IS NOT NULL OR `source_url` IS NOT NULL)
);
```

같은 파일 하단의 `ALTER TABLE` FK 제약 목록에서, `wiki_page_sources`/`message_citations`의 `document_version_id` FK 제약(`fk_wps_document_version`/이에 해당하는 `message_citations` 제약이 있다면)에 nullable 컬럼에 건 FK라는 주석을 한 줄 남긴다(NOT VALID/조건부 FK 문법을 새로 도입하지 않는다 — Postgres FK는 컬럼이 nullable이어도 그대로 동작하고 NULL 값에는 아예 적용되지 않으므로 제약 자체는 변경 불필요, 문서상 헷갈리지 않게 주석만 추가):
```sql
ALTER TABLE `wiki_page_sources`   ADD CONSTRAINT `fk_wps_document_version`        FOREIGN KEY (`document_version_id`) REFERENCES `document_versions`(`id`);
-- 위 FK는 document_version_id가 NULL인 행(웹검색 근거)에는 적용되지 않는다 — Postgres FK는 NULL을 항상 통과시킨다.
```

- [ ] **Step 2: ERDCloud 다이어그램 갱신**

ERDCloud MCP로 `https://www.erdcloud.com/d/qgLNBqodLMJAqG9FG` 다이어그램의 `wiki_page_sources` 테이블에:
1. `document_version_id` 컬럼을 nullable로 표시(체크박스/속성 갱신 — `update_column`/`update_columns` 사용).
2. `source_url`(TEXT, nullable), `source_title`(TEXT, nullable), `published_at`(TEXT, nullable) 3개 컬럼을 `add_column`으로 추가.

`message_citations` 테이블도 같은 방식으로 `source_url`/`source_title`/`published_at`이 이미 있는지 확인하고 없으면 추가, `document_version_id`도 nullable로 표시돼 있는지 확인한다(2026-08-08에 이미 반영됐어야 하지만, 이번에 실제 스키마와 다시 한번 대조해 어긋나 있으면 바로잡는다).

큰 편집 전에 다이어그램 스냅샷을 한 번 떠 둔다(`get_snapshot` 또는 사용자에게 백업 권고).

- [ ] **Step 3: 커밋**

```bash
git add docs/architecture/myWiki_v2.sql
git commit -m "Docs: wiki_page_sources/message_citations 웹 근거 스키마를 문서에 반영"
```

---

## PR 생성 체크리스트 (구현 완료 후)

- `gh pr list --state open`로 중복 PR 없는지 확인
- 브랜치명 `feature/wiki-web-source-save`, 커밋 접두사 `Feat:`/`Docs:` (collaboration_rule.md 준수)
- PR 본문에 작업내용/변경이유/테스트결과/참고사항 포함(라이브 DB에 이미 마이그레이션이 적용된 상태이므로, PR 자체는 애플리케이션 코드+문서만 담고 있다는 점을 명시)
- 스쿼시 머지 후 배포(develop push → deploy-backend.yml, `src/api/**`/`src/wiki/**` 경로 포함이라 트리거됨) 확인
- 라이브 검증: 배포 후 실제 로그인 세션에서 "웹에서 찾아줘"로 웹검색 그라운딩 답변을 받고, "위키에 저장" 클릭 시 성공하는지, 저장된 위키 페이지의 "근거 출처"에 웹 근거가 (제목 · 날짜, 클릭 시 원문 이동) 형태로 나오는지 확인

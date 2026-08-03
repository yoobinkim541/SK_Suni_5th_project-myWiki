# 이슈 위키 페이지 중복 생성 방지 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 같은 사건이 여러 리포트/갱신 주기에 걸쳐 보도될 때, 매번 새 이슈 위키 페이지가 생기는 대신 기존 페이지에 새 버전만 추가되도록 한다.

**Architecture:** 신규 조회 함수 `find_matching_issue_page`가 카테고리+근거 문서 과반수 겹침으로 최근 7일 이내 발행된 기존 이슈 페이지를 찾고, `_generate_issue_page`가 매칭 결과에 따라 `_generate_topic_page`의 update_existing과 동일한 패턴(기존 identity로 draft 조립)을 쓰거나 기존처럼 신규 생성한다.

**Tech Stack:** Python 3.12, Pydantic v2, Supabase Python client, pytest.

## Global Constraints

- `report/grouper.py`는 수정하지 않는다 — `issue_key` 자체는 그대로 둔다.
- `wiki_pages`에 컬럼을 추가하지 않는다 — category는 매칭 시점에 `document_analysis_results.primary_category`로 역조회한다.
- 매칭 후보는 `page_type='issue'`, `status='published'`, 현재 버전이 최근 7일(`within_days=7` 기본값) 이내 생성된 페이지로 제한한다.
- 매칭 조건: (a) 후보의 출처 문서 중 이번 카테고리와 같은 게 하나라도 있음, (b) 겹치는 근거 문서 수 / 이번 이슈 근거 문서 수 >= 0.5. 둘 다 통과해야 매칭.
- 여러 후보가 통과하면 겹침 비율 최고 → 동률이면 최신 버전 순으로 하나를 고른다.
- 매칭되면 `_generate_topic_page`의 update_existing과 동일하게 기존 페이지의 slug/title/page_type/parent_page_id를 그대로 쓰고, markdown 본문만 이번 섹션의 최신 스냅샷으로 교체한다. confidence 게이트 없이 항상 자동 발행하는 기존 이슈 페이지 동작은 그대로 유지한다.
- `WikiPageIdentity.page_type`은 이미 `TopicPageType | Literal["issue"]`로 확장돼 있다(커밋 `507fb05`, 이 플랜 시작 전 완료) — `find_matching_issue_page`가 매칭된 이슈 페이지의 identity를 반환할 때 Pydantic 검증이 통과한다. `TopicPageType` 자체(주제 페이지 전용 계약)는 그대로 두었으니 Task 1에서 다시 건드릴 필요 없다.

---

## File Structure

```
src/wiki/
├── generation_repository.py   # 수정 — find_matching_issue_page 추가
└── generation.py               # 수정 — _generate_issue_page가 매칭 결과 분기

tests/
├── test_wiki_generation_repository.py   # 수정 — find_matching_issue_page 테스트 추가
└── test_wiki_generation.py              # 수정 — _generate_issue_page 매칭 테스트 추가
```

---

### Task 1: `find_matching_issue_page` — 매칭 조회 함수

**Files:**
- Modify: `src/wiki/generation_repository.py` (파일 끝에 함수 추가)
- Modify: `tests/test_wiki_generation_repository.py` (테스트 추가)

**Interfaces:**
- Consumes: `WikiPageIdentity`(`generation_models.py`, 이미 있음)
- Produces: `find_matching_issue_page(workspace_id: str, *, category: str, document_version_ids: list[str], within_days: int = 7, supabase: Client | None = None) -> WikiPageIdentity | None`

이 태스크의 기존 `tests/test_wiki_generation_repository.py`의 `FakeTable`/`FakeSupabase`(이미 파일에 있음, `select`/`eq`/`is_`/`in_`/`lt`/`limit`/`execute`/`update` 지원)를 그대로 재사용해라. 새로 추가해야 하는 메서드가 있으면(예: 이 함수가 `.gte()`를 쓴다면) `FakeTable`에 `lt`와 같은 방식으로 추가해라.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wiki_generation_repository.py 에 이어서 추가
from src.wiki.generation_repository import find_matching_issue_page


def _wiki_page(id_, *, slug, title="제목", page_type="issue", parent_page_id=None, status="published", current_version_id=None, workspace_id="ws-1"):
    return {
        "id": id_, "workspace_id": workspace_id, "slug": slug, "title": title,
        "page_type": page_type, "parent_page_id": parent_page_id, "status": status,
        "current_version_id": current_version_id,
    }


def _wiki_version(id_, *, page_id, created_at):
    return {"id": id_, "page_id": page_id, "created_at": created_at}


def _wiki_source(*, wiki_version_id, document_version_id):
    return {"wiki_version_id": wiki_version_id, "document_version_id": document_version_id}


def _analysis_row(*, document_version_id, primary_category, workspace_id="ws-1"):
    return {"document_version_id": document_version_id, "primary_category": primary_category, "workspace_id": workspace_id}


def test_find_matching_issue_page_matches_on_category_and_majority_overlap():
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=1)).isoformat()
    supabase = FakeSupabase(
        {
            "wiki_pages": [_wiki_page("page-1", slug="issue-old", current_version_id="v1")],
            "wiki_page_versions": [_wiki_version("v1", page_id="page-1", created_at=recent)],
            "wiki_page_sources": [
                _wiki_source(wiki_version_id="v1", document_version_id="doc-1"),
                _wiki_source(wiki_version_id="v1", document_version_id="doc-2"),
            ],
            "document_analysis_results": [
                _analysis_row(document_version_id="doc-1", primary_category="제품·기술"),
                _analysis_row(document_version_id="doc-2", primary_category="제품·기술"),
            ],
        }
    )

    # 이번 이슈 근거 2건 중 1건(doc-1)이 겹침 -> 50% 이상, 카테고리도 일치
    result = find_matching_issue_page(
        "ws-1", category="제품·기술", document_version_ids=["doc-1", "doc-3"], supabase=supabase,
    )

    assert result is not None
    assert result.page_id == "page-1"
    assert result.slug == "issue-old"


def test_find_matching_issue_page_rejects_category_mismatch():
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=1)).isoformat()
    supabase = FakeSupabase(
        {
            "wiki_pages": [_wiki_page("page-1", slug="issue-old", current_version_id="v1")],
            "wiki_page_versions": [_wiki_version("v1", page_id="page-1", created_at=recent)],
            "wiki_page_sources": [_wiki_source(wiki_version_id="v1", document_version_id="doc-1")],
            "document_analysis_results": [_analysis_row(document_version_id="doc-1", primary_category="경쟁사")],
        }
    )

    result = find_matching_issue_page(
        "ws-1", category="제품·기술", document_version_ids=["doc-1"], supabase=supabase,
    )

    assert result is None


def test_find_matching_issue_page_rejects_below_majority_overlap():
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=1)).isoformat()
    supabase = FakeSupabase(
        {
            "wiki_pages": [_wiki_page("page-1", slug="issue-old", current_version_id="v1")],
            "wiki_page_versions": [_wiki_version("v1", page_id="page-1", created_at=recent)],
            "wiki_page_sources": [_wiki_source(wiki_version_id="v1", document_version_id="doc-1")],
            "document_analysis_results": [_analysis_row(document_version_id="doc-1", primary_category="제품·기술")],
        }
    )

    # 이번 이슈 근거 3건 중 1건만 겹침 -> 33%, 50% 미달
    result = find_matching_issue_page(
        "ws-1", category="제품·기술", document_version_ids=["doc-1", "doc-2", "doc-3"], supabase=supabase,
    )

    assert result is None


def test_find_matching_issue_page_excludes_pages_older_than_within_days():
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=10)).isoformat()
    supabase = FakeSupabase(
        {
            "wiki_pages": [_wiki_page("page-1", slug="issue-old", current_version_id="v1")],
            "wiki_page_versions": [_wiki_version("v1", page_id="page-1", created_at=old)],
            "wiki_page_sources": [_wiki_source(wiki_version_id="v1", document_version_id="doc-1")],
            "document_analysis_results": [_analysis_row(document_version_id="doc-1", primary_category="제품·기술")],
        }
    )

    result = find_matching_issue_page(
        "ws-1", category="제품·기술", document_version_ids=["doc-1"], within_days=7, supabase=supabase,
    )

    assert result is None


def test_find_matching_issue_page_excludes_non_issue_page_type():
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=1)).isoformat()
    supabase = FakeSupabase(
        {
            "wiki_pages": [_wiki_page("page-1", slug="topic-page", page_type="technology", current_version_id="v1")],
            "wiki_page_versions": [_wiki_version("v1", page_id="page-1", created_at=recent)],
            "wiki_page_sources": [_wiki_source(wiki_version_id="v1", document_version_id="doc-1")],
            "document_analysis_results": [_analysis_row(document_version_id="doc-1", primary_category="제품·기술")],
        }
    )

    result = find_matching_issue_page(
        "ws-1", category="제품·기술", document_version_ids=["doc-1"], supabase=supabase,
    )

    assert result is None


def test_find_matching_issue_page_returns_none_for_empty_document_version_ids():
    supabase = FakeSupabase({"wiki_pages": []})
    result = find_matching_issue_page("ws-1", category="제품·기술", document_version_ids=[], supabase=supabase)
    assert result is None


def test_find_matching_issue_page_picks_highest_overlap_among_multiple_matches():
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=1)).isoformat()
    supabase = FakeSupabase(
        {
            "wiki_pages": [
                _wiki_page("page-low", slug="issue-low", current_version_id="v-low"),
                _wiki_page("page-high", slug="issue-high", current_version_id="v-high"),
            ],
            "wiki_page_versions": [
                _wiki_version("v-low", page_id="page-low", created_at=recent),
                _wiki_version("v-high", page_id="page-high", created_at=recent),
            ],
            "wiki_page_sources": [
                _wiki_source(wiki_version_id="v-low", document_version_id="doc-1"),
                _wiki_source(wiki_version_id="v-high", document_version_id="doc-1"),
                _wiki_source(wiki_version_id="v-high", document_version_id="doc-2"),
            ],
            "document_analysis_results": [
                _analysis_row(document_version_id="doc-1", primary_category="제품·기술"),
                _analysis_row(document_version_id="doc-2", primary_category="제품·기술"),
            ],
        }
    )

    # 이번 이슈 근거: doc-1, doc-2 둘 다.
    # issue-low는 doc-1만 겹침(50%), issue-high는 doc-1,doc-2 다 겹침(100%) -> issue-high가 이겨야 함
    result = find_matching_issue_page(
        "ws-1", category="제품·기술", document_version_ids=["doc-1", "doc-2"], supabase=supabase,
    )

    assert result is not None
    assert result.page_id == "page-high"
```

`FakeSupabase`가 `in_()`으로 여러 필드를 동시에 필터링해야 하는 경우(예: `wiki_page_sources`를 `wiki_version_id in [...]`로 조회)가 기존 `FakeTable`로 이미 커버되는지 확인해라 — 안 되면 `FakeTable.in_`이 여러 번 호출될 때 각각 별도 필터로 누적되는지(AND 조건) 확인하고, 안 되면 고쳐라.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wiki_generation_repository.py -v -k find_matching_issue_page`
Expected: FAIL with `ImportError: cannot import name 'find_matching_issue_page'`

- [ ] **Step 3: Write minimal implementation**

`src/wiki/generation_repository.py` 파일 끝에 추가:

```python
def find_matching_issue_page(
    workspace_id: str,
    *,
    category: str,
    document_version_ids: list[str],
    within_days: int = 7,
    supabase: Client | None = None,
) -> WikiPageIdentity | None:
    """같은 사건이 여러 주기에 걸쳐 보도될 때 매번 새 이슈 페이지가 생기는 걸 막는다.
    최근 within_days 이내 발행된 issue 타입 페이지 중, 카테고리가 같고 이번 근거 문서와
    과반수 이상 겹치는 게 있으면 그 페이지를 반환한다."""
    if not document_version_ids:
        return None

    db = supabase or get_supabase()
    pages = (
        db.table("wiki_pages")
        .select("id, slug, title, page_type, parent_page_id, current_version_id")
        .eq("workspace_id", workspace_id)
        .eq("page_type", "issue")
        .eq("status", "published")
        .execute()
        .data
    )
    pages = [p for p in pages if p.get("current_version_id")]
    if not pages:
        return None

    version_ids = [p["current_version_id"] for p in pages]
    versions = (
        db.table("wiki_page_versions")
        .select("id, created_at")
        .in_("id", version_ids)
        .execute()
        .data
    )
    threshold = datetime.now(timezone.utc) - timedelta(days=within_days)
    created_at_by_version = {}
    for row in versions:
        created_at = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
        if created_at >= threshold:
            created_at_by_version[row["id"]] = created_at

    candidate_pages = [p for p in pages if p["current_version_id"] in created_at_by_version]
    if not candidate_pages:
        return None

    candidate_version_ids = [p["current_version_id"] for p in candidate_pages]
    source_rows = (
        db.table("wiki_page_sources")
        .select("wiki_version_id, document_version_id")
        .in_("wiki_version_id", candidate_version_ids)
        .execute()
        .data
    )
    docs_by_version: dict[str, set[str]] = {}
    for row in source_rows:
        docs_by_version.setdefault(row["wiki_version_id"], set()).add(row["document_version_id"])

    all_candidate_doc_ids = list({did for docs in docs_by_version.values() for did in docs})
    if not all_candidate_doc_ids:
        return None
    analysis_rows = (
        db.table("document_analysis_results")
        .select("document_version_id, primary_category")
        .eq("workspace_id", workspace_id)
        .in_("document_version_id", all_candidate_doc_ids)
        .execute()
        .data
    )
    category_by_doc = {row["document_version_id"]: row["primary_category"] for row in analysis_rows}

    new_doc_ids = set(document_version_ids)
    best_page: dict | None = None
    best_ratio = -1.0
    best_created_at: datetime | None = None
    for page in candidate_pages:
        candidate_docs = docs_by_version.get(page["current_version_id"], set())
        if not candidate_docs:
            continue
        has_matching_category = any(category_by_doc.get(did) == category for did in candidate_docs)
        if not has_matching_category:
            continue
        overlap = len(candidate_docs & new_doc_ids)
        ratio = overlap / len(new_doc_ids)
        if ratio < 0.5:
            continue
        created_at = created_at_by_version[page["current_version_id"]]
        if ratio > best_ratio or (ratio == best_ratio and (best_created_at is None or created_at > best_created_at)):
            best_page = page
            best_ratio = ratio
            best_created_at = created_at

    if best_page is None:
        return None

    return WikiPageIdentity(
        page_id=str(best_page["id"]),
        slug=best_page["slug"],
        title=best_page["title"],
        page_type=best_page["page_type"],
        parent_page_id=str(best_page["parent_page_id"]) if best_page.get("parent_page_id") else None,
    )
```

`datetime`/`timedelta`/`timezone`은 이미 이 파일 상단에 import돼 있다(Task 3에서 추가됨) — 없으면 추가해라.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_wiki_generation_repository.py -v`
Expected: PASS (기존 8개 + 신규 7개 = 15 passed)

- [ ] **Step 5: Commit**

```bash
git add src/wiki/generation_repository.py tests/test_wiki_generation_repository.py
git commit -m "Feat: 카테고리+근거 과반수 겹침으로 기존 이슈 페이지 매칭하는 함수 추가"
```

---

### Task 2: `_generate_issue_page` — 매칭 결과에 따라 분기

**Files:**
- Modify: `src/wiki/generation.py`
- Modify: `tests/test_wiki_generation.py`

**Interfaces:**
- Consumes: `find_matching_issue_page`(Task 1)
- Produces: `_generate_issue_page`의 동작 변경(시그니처는 그대로 — 실제 현재 시그니처는 `_generate_issue_page(section, *, workspace_id, requested_by, parent_page_id=None, evidence_texts=None, supabase=None) -> tuple[str, str]`이며 바뀌지 않는다)

이 태스크는 `tests/test_wiki_generation.py`에 이미 있는 `_section(...)` 헬퍼와 `generation` 모듈 import, `monkeypatch` 패턴을 그대로 재사용해라. 실제 `_generate_issue_page`가 `create_wiki_version`/`record_wiki_validation`/`review_wiki_version`/`publish_wiki_version` 전부를 `supabase=supabase` 키워드까지 붙여서 호출한다는 점에 주의해라(테스트의 monkeypatch 스텁은 `**k`로 받으므로 문제 없음).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wiki_generation.py 에 이어서 추가
def test_generate_issue_page_reuses_matched_page_identity(monkeypatch):
    calls = []
    matched = generation.WikiPageIdentity(
        page_id="page-existing", slug="issue-existing", title="기존 제목",
        page_type="issue", parent_page_id="page-parent-existing",
    )
    monkeypatch.setattr(generation, "find_matching_issue_page", lambda *a, **k: calls.append(("find", k)) or matched)
    monkeypatch.setattr(generation, "upsert_wiki_page", lambda *a, **k: calls.append(("upsert", a)) or "should-not-be-used")
    monkeypatch.setattr(
        generation, "create_wiki_version",
        lambda draft, **k: calls.append(("create", draft.slug, draft.title, draft.page_type, draft.parent_page_id)) or "version-new",
    )
    monkeypatch.setattr(generation, "record_wiki_validation", lambda *a, **k: None)
    monkeypatch.setattr(generation, "review_wiki_version", lambda *a, **k: None)
    monkeypatch.setattr(generation, "publish_wiki_version", lambda *a, **k: calls.append(("publish", a)))

    page_id, version_id = generation._generate_issue_page(_section(), workspace_id="ws-1", requested_by=None)

    assert page_id == "page-existing"
    assert version_id == "version-new"
    assert not any(call[0] == "upsert" for call in calls)  # 매칭됐으면 upsert_wiki_page를 호출하지 않는다
    create_call = next(call for call in calls if call[0] == "create")
    assert create_call[1:] == ("issue-existing", "기존 제목", "issue", "page-parent-existing")
    assert ("publish", ("page-existing", "version-new")) in calls
    find_call = next(call for call in calls if call[0] == "find")
    assert find_call[1]["category"] == _section().category.value


def test_generate_issue_page_creates_new_when_no_match(monkeypatch):
    calls = []
    monkeypatch.setattr(generation, "find_matching_issue_page", lambda *a, **k: None)
    monkeypatch.setattr(generation, "upsert_wiki_page", lambda *a, **k: calls.append(("upsert", a)) or "page-new")
    monkeypatch.setattr(generation, "create_wiki_version", lambda draft, **k: calls.append(("create", draft.slug)) or "version-new")
    monkeypatch.setattr(generation, "record_wiki_validation", lambda *a, **k: None)
    monkeypatch.setattr(generation, "review_wiki_version", lambda *a, **k: None)
    monkeypatch.setattr(generation, "publish_wiki_version", lambda *a, **k: None)

    page_id, version_id = generation._generate_issue_page(_section("issue-hbm4-supply"), workspace_id="ws-1", requested_by=None)

    assert page_id == "page-new"
    upsert_call = next(call for call in calls if call[0] == "upsert")
    assert upsert_call[1][1] == "issue-hbm4-supply"  # section.issue_key 그대로 slug로 씀
```

`_section(...)`이 이 테스트 파일에 이미 정의돼 있는 헬퍼인지, 첫 인자로 `issue_key`를 받는지, `category`/`news_citations` 필드를 어떻게 채우는지 파일 상단을 먼저 확인해라 — 다르면 기존 정의에 맞춰 테스트 코드를 조정해라(단, 검증하는 동작 자체는 위와 동일하게 유지).

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wiki_generation.py -v -k generate_issue_page_reuses_matched`
Expected: FAIL — `AttributeError: module 'src.wiki.generation' has no attribute 'find_matching_issue_page'` (아직 import 안 됨)

- [ ] **Step 3: Write minimal implementation**

`src/wiki/generation.py` import 블록에 `find_matching_issue_page`를 추가해라 — 이미 있는 `from .generation_repository import (archive_wiki_page, filter_to_topic_page_ids, find_stale_published_page_ids, get_wiki_page_identity, list_top_level_topic_pages)` 블록에 알파벳 순으로 끼워 넣으면 된다.

`_generate_issue_page` 함수를 아래로 교체(기존 함수 본문을 이걸로 바꾼다 — 시그니처는 `evidence_texts`/`supabase` 포함 동일하게 유지):

```python
def _generate_issue_page(
    section: ReportSectionDraft,
    *,
    workspace_id: str,
    requested_by: str | None,
    parent_page_id: str | None = None,
    evidence_texts: dict[str, str] | None = None,
    supabase: Client | None = None,
) -> tuple[str, str]:
    matched = find_matching_issue_page(
        workspace_id,
        category=section.category.value,
        document_version_ids=[c.document_version_id for c in section.news_citations],
        supabase=supabase,
    )

    if matched is not None:
        page_id = matched.page_id
        draft_slug = matched.slug
        draft_title = matched.title
        draft_page_type = matched.page_type
        draft_parent_page_id = matched.parent_page_id
    else:
        page_id = upsert_wiki_page(
            workspace_id,
            section.issue_key,
            section.title,
            "issue",
            parent_page_id,
            supabase=supabase,
        )
        draft_slug = section.issue_key
        draft_title = section.title
        draft_page_type = "issue"
        draft_parent_page_id = parent_page_id

    draft = WikiDraftInput(
        workspace_id=workspace_id,
        slug=draft_slug,
        title=draft_title,
        page_type=draft_page_type,
        parent_page_id=draft_parent_page_id,
        markdown=_build_issue_page_markdown(section, evidence_texts),
        sources=_build_issue_page_sources(section, evidence_texts),
        change_summary="리포트 파이프라인에서 자동 생성",
        created_by=requested_by,
        generated_by="llm",
    )
    version_id = create_wiki_version(draft, supabase=supabase)
    record_wiki_validation(version_id, "passed", None, supabase=supabase)
    review_wiki_version(version_id, None, "approved", supabase=supabase)
    publish_wiki_version(page_id, version_id, supabase=supabase)
    return page_id, version_id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_wiki_generation.py -v`
Expected: PASS (전체 — 기존 16개 + 신규 2개)

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -q`
Expected: 신규 9개(Task1 7개 + Task2 2개) 추가 통과, 그 외 실패 없음(로컬 `.env` placeholder로 인한 기존 4건 `test_missing_api_key_*` 실패는 무관 — 무시)

- [ ] **Step 6: Commit**

```bash
git add src/wiki/generation.py tests/test_wiki_generation.py
git commit -m "Feat: 이슈 페이지 생성 시 기존 매칭 페이지가 있으면 재사용"
```

---

## Post-Implementation Checklist

- [ ] `python -m pytest tests/ -q` 전체 통과 (알려진 4건 제외)
- [ ] `report/grouper.py`가 이번 변경으로 수정되지 않았는지 `git diff --stat`로 확인
- [ ] `wiki_pages`에 컬럼 추가가 없는지(마이그레이션 파일이 생기지 않았는지) 확인

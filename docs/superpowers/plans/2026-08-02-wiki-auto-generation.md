# Wiki 자동 생성 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 분석/리포트 파이프라인 결과를 근거로 Wiki 페이지(이슈 페이지 + 계층적 주제 페이지)를 사람 개입 없이 생성·갱신·자동승인·발행하고, 90일 이상 갱신 없는 페이지를 자동 아카이빙한다.

**Architecture:** `report/interface.py`의 `generate_daily_report()`에서 `compose_sections` 직후 `src/wiki/generation.py`의 `generate_wiki_drafts_for_sections()`를 호출한다. 이슈 페이지는 이미 검증된 리포트 섹션 필드를 템플릿 조립해 항상 자동 발행하고, 주제 페이지는 OpenRouter LLM이 기존 본문+새 근거를 종합해 confidence_score 게이트(≥0.6)를 통과한 것만 자동 발행한다. 아카이빙은 `archive_stale_wiki_pages()`로 별도 스케줄에서 독립 실행한다.

**Tech Stack:** Python 3.12, Pydantic v2, Supabase Python client, OpenRouter(OpenAI 호환 API), pytest.

## Global Constraints

- 근거(`document_version_id`) 없는 주장은 절대 생성하지 않는다 — `claims`가 비면 주제 페이지 갱신을 스킵한다.
- 기존 위키 문단은 삭제하지 않는다 — 갱신은 새 버전 추가이며 "변경 이력" 섹션에 사유를 남긴다.
- confidence_score < 0.6이면 자동 승인/발행하지 않고 `pending` 상태로 남긴다(이슈 페이지는 예외 — 항상 자동 발행).
- 이슈 단위 실패는 다른 이슈나 리포트 생성 자체를 막지 않는다.
- 이 프로젝트의 기존 컨벤션을 따른다: `from __future__ import annotations`, `*`-only 키워드 인자, `Client | None = None` 형태의 테스트 주입 지점, LLM 호출은 `create_json_completion`/`parse_json_response`(`src/analysis/classifier.py`) 재사용.

---

## File Structure

```
src/wiki/
├── generation_models.py       # 신규 — LLM 입출력/결과 Pydantic 모델
├── generation_repository.py   # 신규 — 최상위 주제 페이지 조회, 아카이빙 대상 조회/갱신
├── generation_prompts.py      # 신규 — 주제 페이지 LLM 시스템/유저 프롬프트
├── generation.py              # 신규 — 오케스트레이션 (이슈/주제 페이지 생성, 아카이빙)
├── interface.py                # 수정 — review_wiki_version 시그니처만 확장
└── service.py                  # 수정 — review_wiki_version 구현 시그니처만 확장

src/report/
└── interface.py                 # 수정 — generate_daily_report()에 위키 생성 단계 1개 추가

scripts/
└── archive_stale_wiki_pages.py  # 신규 — archive_stale_wiki_pages() CLI

tests/
├── test_wiki_generation_models.py
├── test_wiki_generation_repository.py
├── test_wiki_generation_prompts.py
├── test_wiki_generation.py            # _generate_issue_page, _generate_topic_page, 오케스트레이션, 아카이빙
└── test_report_interface.py           # 기존 파일에 통합 케이스 추가
```

---

### Task 1: generation_models.py — 데이터 모델

**Files:**
- Create: `src/wiki/generation_models.py`
- Test: `tests/test_wiki_generation_models.py`

**Interfaces:**
- Consumes: 없음 (최하위 계층)
- Produces:
  - `WikiClaim(document_version_id: str, claim_text: str, citation_order: int)`
  - `TopicPageCandidate(wiki_page_id: str, title: str, content: str | None, similarity_score: float | None)`
  - `TopLevelTopicPage(wiki_page_id: str, title: str, page_type: Literal["industry","company","technology","term"])`
  - `WikiTopicLLMResult(action, target_wiki_page_id, slug, title, page_type, parent_page_id, markdown, change_summary, claims, confidence_score)`
  - `WikiDraftGenerationResult(issue_key, issue_page_id, issue_version_id, topic_action, topic_page_id, topic_version_id, error_message)`
  - `WikiPageIdentity(page_id, slug, title, page_type, parent_page_id)` — 기존 페이지 갱신 시 `create_wiki_version()`이 내부적으로 다시 실행하는 `upsert_wiki_page()`가 같은 slug/title/page_type/parent_page_id로 멱등하게 맞아떨어지도록 기존 값을 실어나르는 용도

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wiki_generation_models.py
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.wiki.generation_models import (
    TopicPageCandidate,
    TopLevelTopicPage,
    WikiClaim,
    WikiDraftGenerationResult,
    WikiPageIdentity,
    WikiTopicLLMResult,
)


def test_wiki_claim_requires_positive_citation_order():
    claim = WikiClaim(document_version_id="doc-1", claim_text="근거 문장", citation_order=1)
    assert claim.citation_order == 1
    with pytest.raises(ValidationError):
        WikiClaim(document_version_id="doc-1", claim_text="근거 문장", citation_order=0)


def test_topic_page_candidate_defaults():
    candidate = TopicPageCandidate(wiki_page_id="page-1", title="HBM4 수급현황")
    assert candidate.content is None
    assert candidate.similarity_score is None


def test_top_level_topic_page_rejects_issue_page_type():
    with pytest.raises(ValidationError):
        TopLevelTopicPage(wiki_page_id="page-1", title="이슈 페이지", page_type="issue")


def test_wiki_topic_llm_result_confidence_score_bounds():
    with pytest.raises(ValidationError):
        WikiTopicLLMResult(action="skip", confidence_score=1.5)
    result = WikiTopicLLMResult(action="skip", confidence_score=0.4)
    assert result.claims == []


def test_wiki_topic_llm_result_update_existing_with_claims():
    result = WikiTopicLLMResult(
        action="update_existing",
        target_wiki_page_id="page-1",
        markdown="# 갱신된 본문",
        change_summary="신규 근거 반영",
        claims=[WikiClaim(document_version_id="doc-1", claim_text="근거", citation_order=1)],
        confidence_score=0.8,
    )
    assert result.claims[0].document_version_id == "doc-1"


def test_wiki_draft_generation_result_defaults_topic_fields_to_none():
    result = WikiDraftGenerationResult(
        issue_key="issue-1",
        issue_page_id="page-1",
        issue_version_id="ver-1",
        topic_action="skip",
    )
    assert result.topic_page_id is None
    assert result.error_message is None


def test_wiki_page_identity_requires_page_type():
    identity = WikiPageIdentity(
        page_id="page-1", slug="hbm4-supply", title="HBM4_수급현황", page_type="technology", parent_page_id=None,
    )
    assert identity.slug == "hbm4-supply"
    with pytest.raises(ValidationError):
        WikiPageIdentity(page_id="page-1", slug="s", title="t", page_type="issue", parent_page_id=None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wiki_generation_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.wiki.generation_models'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/wiki/generation_models.py
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

TopicPageType = Literal["industry", "company", "technology", "term"]
WikiTopicAction = Literal["update_existing", "create_new", "skip"]


class WikiClaim(BaseModel):
    document_version_id: str
    claim_text: str
    citation_order: int = Field(ge=1)


class TopicPageCandidate(BaseModel):
    wiki_page_id: str
    title: str
    content: str | None = None
    similarity_score: float | None = Field(default=None, ge=0.0, le=1.0)


class TopLevelTopicPage(BaseModel):
    wiki_page_id: str
    title: str
    page_type: TopicPageType


class WikiTopicLLMResult(BaseModel):
    action: WikiTopicAction
    target_wiki_page_id: str | None = None
    slug: str | None = None
    title: str | None = None
    page_type: TopicPageType | None = None
    parent_page_id: str | None = None
    markdown: str | None = None
    change_summary: str | None = None
    claims: list[WikiClaim] = Field(default_factory=list)
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)


class WikiDraftGenerationResult(BaseModel):
    issue_key: str
    issue_page_id: str
    issue_version_id: str
    topic_action: Literal["update_existing", "create_new", "skip", "failed"]
    topic_page_id: str | None = None
    topic_version_id: str | None = None
    error_message: str | None = None


class WikiPageIdentity(BaseModel):
    page_id: str
    slug: str
    title: str
    page_type: TopicPageType
    parent_page_id: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_wiki_generation_models.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add src/wiki/generation_models.py tests/test_wiki_generation_models.py
git commit -m "Feat: 위키 자동생성 데이터 모델 추가"
```

---

### Task 2: `review_wiki_version` 시그니처 확장 (배치 자동승인 지원)

**Files:**
- Modify: `src/wiki/interface.py:172-183` (review_wiki_version)
- Modify: `src/wiki/service.py:164-176` (review_wiki_version)
- Test: `tests/test_wiki_service.py` (기존 파일에 케이스 추가 — 라이브 Supabase 필요, 자격증명 없으면 스킵되는 기존 fixture 그대로 사용)

**Interfaces:**
- Consumes: 없음
- Produces: `review_wiki_version(version_id: str, reviewer_id: str | None, decision: ReviewDecision) -> None` — `reviewer_id=None`이면 `reviewed_by`를 NULL로 저장(배치 자동승인 표시)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wiki_service.py 맨 끝에 추가
def test_review_wiki_version_accepts_none_reviewer_for_auto_approval(workspace_id):
    slug = f"test-auto-{uuid.uuid4().hex[:8]}"
    draft = WikiDraftInput(
        workspace_id=workspace_id,
        slug=slug,
        title="자동승인 테스트",
        page_type="term",
        markdown="# 테스트\n내용",
        sources=[],
        generated_by="llm",
    )
    version_id = create_wiki_version(draft)

    review_wiki_version(version_id, None, "approved")

    db = _get_client()
    ver = db.table("wiki_page_versions").select("review_status, reviewed_by").eq("id", version_id).single().execute()
    assert ver.data["review_status"] == "approved"
    assert ver.data["reviewed_by"] is None

    page = db.table("wiki_pages").select("id").eq("workspace_id", workspace_id).eq("slug", slug).single().execute()
    db.table("wiki_page_versions").delete().eq("id", version_id).execute()
    db.table("wiki_pages").delete().eq("id", page.data["id"]).execute()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wiki_service.py::test_review_wiki_version_accepts_none_reviewer_for_auto_approval -v`
Expected: 실제 Supabase 자격증명이 `.env`에 있으면 FAIL (타입 힌트는 런타임에 강제되지 않아 기존 코드로도 통과할 수 있음 — 이 단계의 목적은 동작 확인이 아니라 시그니처 문서화이므로, 자격증명이 없으면 SKIP도 정상. 자격증명이 있는 환경에서는 이 스텝이 그대로 PASS해도 무방하다. 다음 스텝에서 타입 힌트를 명시적으로 맞춘다.

- [ ] **Step 3: Write minimal implementation**

`src/wiki/interface.py`의 `review_wiki_version` 정의를 아래로 교체:

```python
def review_wiki_version(
    version_id: str,
    reviewer_id: Optional[str],
    decision: ReviewDecision,
) -> None:
    """Record the review result without publishing the version.

    reviewer_id=None means an automated (non-human) approval — used by the
    wiki auto-generation pipeline. reviewed_by is stored as NULL in that case.
    """

    from .service import review_wiki_version as _impl

    return _impl(version_id, reviewer_id, decision)
```

`src/wiki/service.py`의 `review_wiki_version` 정의를 아래로 교체:

```python
def review_wiki_version(
    version_id: str,
    reviewer_id: Optional[str],
    decision: str,
) -> None:
    db = _get_client()
    db.table("wiki_page_versions").update(
        {
            "review_status": decision,
            "reviewed_by": reviewer_id,
            "reviewed_at": datetime.datetime.utcnow().isoformat() + "Z",
        }
    ).eq("id", version_id).execute()
```

(`service.py` 상단에 `Optional`이 이미 import돼 있는지 확인 — 없으면 `from typing import Optional` 추가)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_wiki_service.py -v`
Expected: PASS (자격증명이 없는 환경은 전부 SKIP, 있는 환경은 전부 PASS)

- [ ] **Step 5: Commit**

```bash
git add src/wiki/interface.py src/wiki/service.py tests/test_wiki_service.py
git commit -m "Feat: review_wiki_version이 reviewer_id=None(자동승인)을 받도록 확장"
```

---

### Task 3: generation_repository.py — 최상위 주제 페이지 조회 & 아카이빙 대상 조회

**Files:**
- Create: `src/wiki/generation_repository.py`
- Test: `tests/test_wiki_generation_repository.py` (fake Supabase client, 실제 네트워크 없음)

**Interfaces:**
- Consumes: `TopLevelTopicPage`, `WikiPageIdentity`(Task 1)
- Produces:
  - `list_top_level_topic_pages(workspace_id: str, *, supabase: Client | None = None) -> list[TopLevelTopicPage]`
  - `find_stale_published_page_ids(workspace_id: str, *, staleness_days: int, supabase: Client | None = None) -> list[str]`
  - `archive_wiki_page(page_id: str, *, supabase: Client | None = None) -> None`
  - `get_wiki_page_identity(page_id: str, *, supabase: Client | None = None) -> WikiPageIdentity | None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wiki_generation_repository.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.wiki.generation_repository import (
    archive_wiki_page,
    find_stale_published_page_ids,
    get_wiki_page_identity,
    list_top_level_topic_pages,
)


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, supabase, name):
        self.supabase = supabase
        self.name = name
        self.rows = supabase.tables.setdefault(name, [])
        self.filters = []
        self.is_filters = []
        self.update_payload = None
        self._limit = None

    def select(self, _fields):
        return self

    def limit(self, value):
        self._limit = value
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def is_(self, field, value):
        self.is_filters.append((field, value))
        return self

    def in_(self, field, values):
        values = set(values)
        self.filters.append((field, values))
        return self

    def lt(self, field, value):
        self.filters.append((f"lt:{field}", value))
        return self

    def update(self, payload):
        self.update_payload = dict(payload)
        return self

    def execute(self):
        if self.update_payload is not None:
            for row in self._filtered_rows():
                row.update(self.update_payload)
            return FakeResult([dict(row) for row in self._filtered_rows()])
        rows = self._filtered_rows()
        if self._limit is not None:
            rows = rows[: self._limit]
        return FakeResult([dict(row) for row in rows])

    def _filtered_rows(self):
        rows = self.rows
        for field, value in self.is_filters:
            rows = [row for row in rows if row.get(field) is value]
        for field, value in self.filters:
            if isinstance(field, str) and field.startswith("lt:"):
                real_field = field[3:]
                rows = [row for row in rows if row.get(real_field) is not None and row[real_field] < value]
            elif isinstance(value, set):
                rows = [row for row in rows if row.get(field) in value]
            else:
                rows = [row for row in rows if row.get(field) == value]
        return rows


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return FakeTable(self, name)


def test_list_top_level_topic_pages_excludes_issue_and_child_pages():
    supabase = FakeSupabase(
        {
            "wiki_pages": [
                {"id": "p1", "workspace_id": "ws-1", "title": "SK하이닉스", "page_type": "company", "parent_page_id": None, "status": "published"},
                {"id": "p2", "workspace_id": "ws-1", "title": "HBM4", "page_type": "technology", "parent_page_id": "p1", "status": "published"},
                {"id": "p3", "workspace_id": "ws-1", "title": "이슈 2026-08-02", "page_type": "issue", "parent_page_id": None, "status": "published"},
                {"id": "p4", "workspace_id": "ws-1", "title": "미공개 주제", "page_type": "industry", "parent_page_id": None, "status": "draft"},
            ]
        }
    )
    pages = list_top_level_topic_pages("ws-1", supabase=supabase)
    assert [page.wiki_page_id for page in pages] == ["p1"]


def test_find_stale_published_page_ids_only_returns_pages_past_threshold():
    now = datetime.now(timezone.utc)
    stale_time = (now - timedelta(days=91)).isoformat()
    fresh_time = (now - timedelta(days=10)).isoformat()
    supabase = FakeSupabase(
        {
            "wiki_pages": [
                {"id": "p1", "workspace_id": "ws-1", "status": "published", "current_version_id": "v1"},
                {"id": "p2", "workspace_id": "ws-1", "status": "published", "current_version_id": "v2"},
                {"id": "p3", "workspace_id": "ws-1", "status": "draft", "current_version_id": "v3"},
            ],
            "wiki_page_versions": [
                {"id": "v1", "page_id": "p1", "created_at": stale_time},
                {"id": "v2", "page_id": "p2", "created_at": fresh_time},
                {"id": "v3", "page_id": "p3", "created_at": stale_time},
            ],
        }
    )
    stale_ids = find_stale_published_page_ids("ws-1", staleness_days=90, supabase=supabase)
    assert stale_ids == ["p1"]


def test_archive_wiki_page_sets_status_archived():
    supabase = FakeSupabase(
        {"wiki_pages": [{"id": "p1", "workspace_id": "ws-1", "status": "published"}]}
    )
    archive_wiki_page("p1", supabase=supabase)
    assert supabase.tables["wiki_pages"][0]["status"] == "archived"


def test_get_wiki_page_identity_returns_slug_title_type_parent():
    supabase = FakeSupabase(
        {
            "wiki_pages": [
                {
                    "id": "page-existing",
                    "slug": "hbm4-supply",
                    "title": "HBM4_수급현황",
                    "page_type": "technology",
                    "parent_page_id": "page-parent",
                }
            ]
        }
    )
    identity = get_wiki_page_identity("page-existing", supabase=supabase)
    assert identity is not None
    assert identity.slug == "hbm4-supply"
    assert identity.title == "HBM4_수급현황"
    assert identity.page_type == "technology"
    assert identity.parent_page_id == "page-parent"


def test_get_wiki_page_identity_returns_none_when_missing():
    supabase = FakeSupabase({"wiki_pages": []})
    assert get_wiki_page_identity("page-missing", supabase=supabase) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wiki_generation_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.wiki.generation_repository'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/wiki/generation_repository.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from supabase import Client

from ..analysis.repository import get_supabase
from .generation_models import TopLevelTopicPage, WikiPageIdentity

TOP_LEVEL_TOPIC_PAGE_TYPES = ("industry", "company", "technology", "term")


def list_top_level_topic_pages(
    workspace_id: str,
    *,
    supabase: Client | None = None,
) -> list[TopLevelTopicPage]:
    db = supabase or get_supabase()
    rows = (
        db.table("wiki_pages")
        .select("id, title, page_type")
        .eq("workspace_id", workspace_id)
        .eq("status", "published")
        .is_("parent_page_id", None)
        .in_("page_type", list(TOP_LEVEL_TOPIC_PAGE_TYPES))
        .execute()
        .data
    )
    return [
        TopLevelTopicPage(wiki_page_id=str(row["id"]), title=row["title"], page_type=row["page_type"])
        for row in rows
    ]


def find_stale_published_page_ids(
    workspace_id: str,
    *,
    staleness_days: int,
    supabase: Client | None = None,
) -> list[str]:
    db = supabase or get_supabase()
    pages = (
        db.table("wiki_pages")
        .select("id, current_version_id")
        .eq("workspace_id", workspace_id)
        .eq("status", "published")
        .execute()
        .data
    )
    version_ids = [row["current_version_id"] for row in pages if row.get("current_version_id")]
    if not version_ids:
        return []

    versions = (
        db.table("wiki_page_versions")
        .select("id, created_at")
        .in_("id", version_ids)
        .execute()
        .data
    )
    created_at_by_version = {str(row["id"]): row["created_at"] for row in versions}

    threshold = datetime.now(timezone.utc) - timedelta(days=staleness_days)
    stale_page_ids: list[str] = []
    for page in pages:
        version_id = page.get("current_version_id")
        if not version_id:
            continue
        created_at_raw = created_at_by_version.get(str(version_id))
        if not created_at_raw:
            continue
        created_at = datetime.fromisoformat(str(created_at_raw).replace("Z", "+00:00"))
        if created_at < threshold:
            stale_page_ids.append(str(page["id"]))
    return stale_page_ids


def archive_wiki_page(page_id: str, *, supabase: Client | None = None) -> None:
    db = supabase or get_supabase()
    db.table("wiki_pages").update({"status": "archived"}).eq("id", page_id).execute()


def get_wiki_page_identity(page_id: str, *, supabase: Client | None = None) -> WikiPageIdentity | None:
    """기존 페이지 갱신 시 create_wiki_version() 내부의 upsert_wiki_page() 재실행이
    같은 slug/title/page_type/parent_page_id로 멱등하게 맞아떨어지도록 조회한다."""
    db = supabase or get_supabase()
    rows = (
        db.table("wiki_pages")
        .select("id, slug, title, page_type, parent_page_id")
        .eq("id", page_id)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        return None
    row = rows[0]
    return WikiPageIdentity(
        page_id=str(row["id"]),
        slug=row["slug"],
        title=row["title"],
        page_type=row["page_type"],
        parent_page_id=str(row["parent_page_id"]) if row.get("parent_page_id") else None,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_wiki_generation_repository.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/wiki/generation_repository.py tests/test_wiki_generation_repository.py
git commit -m "Feat: 최상위 주제 페이지 조회 및 아카이빙 대상 조회 리포지토리 추가"
```

---

### Task 4: generation_prompts.py — 주제 페이지 LLM 프롬프트

**Files:**
- Create: `src/wiki/generation_prompts.py`
- Test: `tests/test_wiki_generation_prompts.py`

**Interfaces:**
- Consumes: `TopicPageCandidate`, `TopLevelTopicPage` (Task 1), `ReportSectionDraft`(`src/report/models.py`, 이미 존재)
- Produces: `WIKI_TOPIC_SYSTEM_PROMPT: str`, `build_wiki_topic_user_prompt(*, section: ReportSectionDraft, candidates: list[TopicPageCandidate], top_level_pages: list[TopLevelTopicPage]) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wiki_generation_prompts.py
from __future__ import annotations

from src.analysis.models import Category
from src.report.models import ReportCitationDraft, ReportSectionDraft
from src.wiki.generation_models import TopicPageCandidate, TopLevelTopicPage
from src.wiki.generation_prompts import WIKI_TOPIC_SYSTEM_PROMPT, build_wiki_topic_user_prompt


def _section() -> ReportSectionDraft:
    return ReportSectionDraft(
        issue_key="issue-hbm4-supply",
        representative_analysis_result_id="analysis-1",
        category=Category.PRODUCT_TECHNOLOGY,
        title="HBM4 공급 부족 심화",
        current_summary="HBM4 공급이 예상보다 더 타이트해지고 있다.",
        key_facts=["주요 고객사 수요 증가", "생산 capa 제약"],
        implications=["SK하이닉스 협상력 강화"],
        watch_points=["경쟁사 증설 발표 여부"],
        news_citations=[
            ReportCitationDraft(analysis_result_id="analysis-1", document_version_id="doc-1", citation_order=1, evidence_text="HBM4 수요가 급증했다")
        ],
    )


def test_system_prompt_forbids_unsupported_claims():
    assert "근거" in WIKI_TOPIC_SYSTEM_PROMPT
    assert "JSON" in WIKI_TOPIC_SYSTEM_PROMPT


def test_user_prompt_includes_section_and_candidates():
    prompt = build_wiki_topic_user_prompt(
        section=_section(),
        candidates=[TopicPageCandidate(wiki_page_id="page-1", title="HBM4_수급현황", content="기존 본문")],
        top_level_pages=[TopLevelTopicPage(wiki_page_id="page-top-1", title="SK하이닉스", page_type="company")],
    )
    assert "HBM4 공급 부족 심화" in prompt
    assert "HBM4_수급현황" in prompt
    assert "기존 본문" in prompt
    assert "SK하이닉스" in prompt
    assert "doc-1" in prompt


def test_user_prompt_handles_no_candidates():
    prompt = build_wiki_topic_user_prompt(section=_section(), candidates=[], top_level_pages=[])
    assert "HBM4 공급 부족 심화" in prompt
    assert "없음" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wiki_generation_prompts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.wiki.generation_prompts'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/wiki/generation_prompts.py
from __future__ import annotations

from ..report.models import ReportSectionDraft
from .generation_models import TopicPageCandidate, TopLevelTopicPage

WIKI_TOPIC_SYSTEM_PROMPT = """당신은 SK하이닉스 반도체 산업 위키를 관리하는 편집자입니다.

새로 들어온 이슈 근거를 바탕으로, 기존 주제 위키 문서를 갱신할지 새로 만들지 판단하고
본문을 작성하십시오.

절대 규칙:
- claims에 없는 문장(document_version_id로 뒷받침되지 않는 주장)은 markdown에 쓰지 마십시오.
- 뒷받침할 근거가 부족하면 action을 "skip"으로 반환하고 markdown/claims를 비우십시오.
- 기존 본문의 문단을 삭제하지 말고, 새 근거를 통합해 재작성하되 기존 사실관계는 보존하십시오.
- markdown은 반드시 아래 섹션 순서를 따르십시오: 현재 상황 -> 수급 구조 -> 종합 판단 -> 변경 이력 -> 관련 문서 -> 출처.
- "변경 이력" 섹션에는 기존 이력을 지우지 말고 이번 갱신 사유를 한 줄 추가하십시오.
- 새 주제를 만들 때는 [기존 최상위 주제 목록] 중 하나를 parent_page_id로 고르거나,
  어디에도 속하지 않으면 parent_page_id를 null로 반환해 최상위 주제로 만드십시오.
- confidence_score(0~1)에 이번 갱신이 얼마나 근거로 잘 뒷받침되는지 스스로 평가해 반환하십시오.
- 마크다운 코드블록 없이 지정된 JSON 구조로만 응답하십시오.

JSON 출력 형식:
{
  "action": "update_existing" | "create_new" | "skip",
  "target_wiki_page_id": "기존 페이지 id 또는 null",
  "slug": "새 페이지일 때만, 영문/숫자/언더스코어",
  "title": "새 페이지일 때만",
  "page_type": "industry" | "company" | "technology" | "term",
  "parent_page_id": "기존 최상위 페이지 id 또는 null",
  "markdown": "전체 새 버전 본문",
  "change_summary": "변경 이력에 들어갈 한 줄",
  "claims": [{"document_version_id": "...", "claim_text": "...", "citation_order": 1}],
  "confidence_score": 0.0
}"""


def build_wiki_topic_user_prompt(
    *,
    section: ReportSectionDraft,
    candidates: list[TopicPageCandidate],
    top_level_pages: list[TopLevelTopicPage],
) -> str:
    lines: list[str] = [
        "[이슈 정보]",
        f"제목: {section.title}",
        f"카테고리: {section.category.value}",
        f"현재 상황 요약: {section.current_summary or ''}",
        "핵심 사실:",
    ]
    lines.extend(f"- {fact}" for fact in section.key_facts)
    lines.append("시사점:")
    lines.extend(f"- {implication}" for implication in section.implications)
    lines.append("주시할 지점:")
    lines.extend(f"- {watch_point}" for watch_point in section.watch_points)

    lines.append("")
    lines.append("[근거 문서]")
    if section.news_citations:
        for citation in section.news_citations:
            lines.append(
                f"- document_version_id={citation.document_version_id} citation_order={citation.citation_order}: "
                f"{citation.evidence_text or ''}"
            )
    else:
        lines.append("없음")

    lines.append("")
    lines.append("[관련 기존 주제 페이지 후보 (유사도 순)]")
    if candidates:
        for candidate in candidates:
            lines.append(f"- wiki_page_id={candidate.wiki_page_id} title={candidate.title}")
            lines.append(f"  기존 본문:\n{candidate.content or ''}")
    else:
        lines.append("없음")

    lines.append("")
    lines.append("[기존 최상위 주제 목록 (parent_page_id 선택용)]")
    if top_level_pages:
        for page in top_level_pages:
            lines.append(f"- wiki_page_id={page.wiki_page_id} title={page.title} page_type={page.page_type}")
    else:
        lines.append("없음")

    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_wiki_generation_prompts.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/wiki/generation_prompts.py tests/test_wiki_generation_prompts.py
git commit -m "Feat: 주제 페이지 갱신용 LLM 프롬프트 추가"
```

---

### Task 5: generation.py — 이슈 페이지 생성 (`_generate_issue_page`)

**Files:**
- Create: `src/wiki/generation.py`
- Test: `tests/test_wiki_generation.py` (신규 파일 시작)

**Interfaces:**
- Consumes: `ReportSectionDraft`(`report/models.py`), `WikiDraftInput`/`WikiSourceInput`/`create_wiki_version`/`record_wiki_validation`/`review_wiki_version`/`publish_wiki_version`(`wiki/interface.py`)
- Produces: `_generate_issue_page(section: ReportSectionDraft, *, workspace_id: str, requested_by: str | None, parent_page_id: str | None = None) -> tuple[str, str]` (반환: `(page_id, version_id)`)

`parent_page_id`는 Task 7에서 주제 페이지가 먼저 결정된 뒤 이슈 페이지의 부모로 연결하기 위한 것이다(이슈 -> 주제 순서가 아니라 **주제를 먼저 정하고 이슈를 만드는 순서**로 오케스트레이션한다 — `upsert_wiki_page`가 `ignore_duplicates=True`라서 기존 페이지의 `parent_page_id`를 나중에 수정할 방법이 없기 때문에, 최초 INSERT 시점에 맞는 값을 넣어야 한다).

이 태스크는 `wiki.interface`의 함수들을 **monkeypatch로 대체**해서 실제 DB/LLM 없이 오케스트레이션 로직만 검증한다(각 함수 자체는 이미 다른 곳에서 테스트됨).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wiki_generation.py
from __future__ import annotations

import pytest

from src.analysis.models import Category
from src.report.models import ReportCitationDraft, ReportSectionDraft
from src.wiki import generation


def _section(issue_key: str = "issue-hbm4-supply") -> ReportSectionDraft:
    return ReportSectionDraft(
        issue_key=issue_key,
        representative_analysis_result_id="analysis-1",
        category=Category.PRODUCT_TECHNOLOGY,
        title="HBM4 공급 부족 심화",
        current_summary="HBM4 공급이 예상보다 더 타이트해지고 있다.",
        key_facts=["주요 고객사 수요 증가"],
        implications=["SK하이닉스 협상력 강화"],
        watch_points=["경쟁사 증설 발표 여부"],
        news_citations=[
            ReportCitationDraft(
                analysis_result_id="analysis-1",
                document_version_id="doc-1",
                citation_order=1,
                evidence_text="HBM4 수요가 급증했다",
            )
        ],
    )


def test_generate_issue_page_creates_and_auto_publishes(monkeypatch):
    calls = []

    def fake_upsert_wiki_page(workspace_id, slug, title, page_type, parent_page_id=None):
        calls.append(("upsert", slug, page_type, parent_page_id))
        return "page-1"

    def fake_create_wiki_version(draft):
        calls.append(("create", draft.slug, draft.page_type, [s.document_version_id for s in draft.sources]))
        return "version-1"

    def fake_record_wiki_validation(version_id, validation_status, confidence_score):
        calls.append(("validate", version_id, validation_status, confidence_score))

    def fake_review_wiki_version(version_id, reviewer_id, decision):
        calls.append(("review", version_id, reviewer_id, decision))

    def fake_publish_wiki_version(page_id, version_id):
        calls.append(("publish", page_id, version_id))

    monkeypatch.setattr(generation, "upsert_wiki_page", fake_upsert_wiki_page)
    monkeypatch.setattr(generation, "create_wiki_version", fake_create_wiki_version)
    monkeypatch.setattr(generation, "record_wiki_validation", fake_record_wiki_validation)
    monkeypatch.setattr(generation, "review_wiki_version", fake_review_wiki_version)
    monkeypatch.setattr(generation, "publish_wiki_version", fake_publish_wiki_version)

    page_id, version_id = generation._generate_issue_page(
        _section(), workspace_id="ws-1", requested_by=None, parent_page_id="page-topic",
    )

    assert page_id == "page-1"
    assert version_id == "version-1"
    assert ("upsert", "issue-hbm4-supply", "issue", "page-topic") in calls
    assert ("validate", "version-1", "passed", None) in calls
    assert ("review", "version-1", None, "approved") in calls
    assert ("publish", "page-1", "version-1") in calls

    create_call = next(call for call in calls if call[0] == "create")
    assert create_call[3] == ["doc-1"]


def test_generate_issue_page_defaults_parent_to_none(monkeypatch):
    calls = []
    monkeypatch.setattr(generation, "upsert_wiki_page", lambda *a, **k: calls.append(("upsert", a)) or "page-1")
    monkeypatch.setattr(generation, "create_wiki_version", lambda draft: "version-1")
    monkeypatch.setattr(generation, "record_wiki_validation", lambda *a, **k: None)
    monkeypatch.setattr(generation, "review_wiki_version", lambda *a, **k: None)
    monkeypatch.setattr(generation, "publish_wiki_version", lambda *a, **k: None)

    generation._generate_issue_page(_section(), workspace_id="ws-1", requested_by=None)

    upsert_call = next(call for call in calls if call[0] == "upsert")
    assert upsert_call[1] == ("ws-1", "issue-hbm4-supply", "HBM4 공급 부족 심화", "issue", None)


def test_generate_issue_page_markdown_contains_all_sections():
    markdown = generation._build_issue_page_markdown(_section())
    assert "HBM4 공급 부족 심화" in markdown
    assert "HBM4 공급이 예상보다 더 타이트해지고 있다." in markdown
    assert "주요 고객사 수요 증가" in markdown
    assert "SK하이닉스 협상력 강화" in markdown
    assert "경쟁사 증발 발표 여부" not in markdown  # 오탈자 없이 원문 그대로 들어가는지
    assert "경쟁사 증설 발표 여부" in markdown
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wiki_generation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.wiki.generation'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/wiki/generation.py
from __future__ import annotations

import logging

from ..report.models import ReportSectionDraft
from .interface import (
    WikiDraftInput,
    WikiSourceInput,
    create_wiki_version,
    publish_wiki_version,
    record_wiki_validation,
    review_wiki_version,
    upsert_wiki_page,
)

logger = logging.getLogger(__name__)

AUTO_PUBLISH_CONFIDENCE_THRESHOLD = 0.6


def _build_issue_page_markdown(section: ReportSectionDraft) -> str:
    lines = [f"# {section.title}", "", "## 현재 상황", section.current_summary or "", ""]
    lines.append("## 핵심 사실")
    lines.extend(f"- {fact}" for fact in section.key_facts)
    lines.append("")
    lines.append("## 시사점")
    lines.extend(f"- {implication}" for implication in section.implications)
    lines.append("")
    lines.append("## 주시할 지점")
    lines.extend(f"- {watch_point}" for watch_point in section.watch_points)
    lines.append("")
    lines.append("## 출처")
    for citation in section.news_citations:
        lines.append(f"- {citation.evidence_text or ''} (document_version_id={citation.document_version_id})")
    return "\n".join(lines)


def _build_issue_page_sources(section: ReportSectionDraft) -> list[WikiSourceInput]:
    return [
        WikiSourceInput(
            document_version_id=citation.document_version_id,
            claim_text=citation.evidence_text or "",
            source_start_line=citation.source_start_line,
            source_end_line=citation.source_end_line,
            citation_order=citation.citation_order,
        )
        for citation in section.news_citations
    ]


def _generate_issue_page(
    section: ReportSectionDraft,
    *,
    workspace_id: str,
    requested_by: str | None,
    parent_page_id: str | None = None,
) -> tuple[str, str]:
    page_id = upsert_wiki_page(
        workspace_id,
        section.issue_key,
        section.title,
        "issue",
        parent_page_id,
    )
    draft = WikiDraftInput(
        workspace_id=workspace_id,
        slug=section.issue_key,
        title=section.title,
        page_type="issue",
        parent_page_id=parent_page_id,
        markdown=_build_issue_page_markdown(section),
        sources=_build_issue_page_sources(section),
        change_summary="리포트 파이프라인에서 자동 생성",
        created_by=requested_by,
        generated_by="llm",
    )
    version_id = create_wiki_version(draft)
    record_wiki_validation(version_id, "passed", None)
    review_wiki_version(version_id, None, "approved")
    publish_wiki_version(page_id, version_id)
    return page_id, version_id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_wiki_generation.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/wiki/generation.py tests/test_wiki_generation.py
git commit -m "Feat: 이슈 위키 페이지 자동 생성 + 항상 자동발행"
```

---

### Task 6: generation.py — 주제 페이지 생성 (`_generate_topic_page`)

**Files:**
- Modify: `src/wiki/generation.py`
- Modify: `tests/test_wiki_generation.py`

**Interfaces:**
- Consumes: `WikiContext`(`report/models.py`), `TopicPageCandidate`/`WikiTopicLLMResult`(Task 1), `list_top_level_topic_pages`(Task 3), `build_wiki_topic_user_prompt`/`WIKI_TOPIC_SYSTEM_PROMPT`(Task 4), `create_json_completion`/`parse_json_response`(`analysis/classifier.py`)
- Produces: `_generate_topic_page(section: ReportSectionDraft, wiki_contexts: list[WikiContext], *, workspace_id: str, requested_by: str | None) -> WikiDraftGenerationResult 부분 필드(topic_action, topic_page_id, topic_version_id)를 담은 tuple[str, str | None, str | None]` — 정확히는 `(action, topic_page_id, topic_version_id)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wiki_generation.py 에 이어서 추가
import json

from src.report.models import WikiContext


def test_generate_topic_page_skips_when_llm_returns_skip(monkeypatch):
    monkeypatch.setattr(generation, "list_top_level_topic_pages", lambda workspace_id, supabase=None: [])
    monkeypatch.setattr(
        generation,
        "create_json_completion",
        lambda **kwargs: json.dumps({"action": "skip", "claims": [], "confidence_score": 0.1}),
    )

    action, page_id, version_id = generation._generate_topic_page(
        _section(), [], workspace_id="ws-1", requested_by=None,
    )

    assert action == "skip"
    assert page_id is None
    assert version_id is None


def test_generate_topic_page_updates_existing_when_confidence_high(monkeypatch):
    calls = []
    monkeypatch.setattr(generation, "list_top_level_topic_pages", lambda workspace_id, supabase=None: [])
    monkeypatch.setattr(
        generation,
        "get_wiki_page_identity",
        lambda page_id, supabase=None: generation.WikiPageIdentity(
            page_id="page-existing", slug="hbm4-supply", title="HBM4_수급현황",
            page_type="technology", parent_page_id="page-parent",
        ),
    )
    monkeypatch.setattr(
        generation,
        "create_json_completion",
        lambda **kwargs: json.dumps(
            {
                "action": "update_existing",
                "target_wiki_page_id": "page-existing",
                "markdown": "# 갱신된 본문",
                "change_summary": "신규 근거 반영",
                "claims": [{"document_version_id": "doc-1", "claim_text": "근거", "citation_order": 1}],
                "confidence_score": 0.9,
            }
        ),
    )
    monkeypatch.setattr(
        generation, "create_wiki_version",
        lambda draft: calls.append(("create", draft.slug, draft.page_type, draft.parent_page_id)) or "version-2",
    )
    monkeypatch.setattr(generation, "record_wiki_validation", lambda *a, **k: calls.append(("validate", a)))
    monkeypatch.setattr(generation, "review_wiki_version", lambda *a, **k: calls.append(("review", a)))
    monkeypatch.setattr(generation, "publish_wiki_version", lambda *a, **k: calls.append(("publish", a)))

    wiki_context = WikiContext(wiki_page_id="page-existing", title="HBM4_수급현황", content="기존 본문")
    action, page_id, version_id = generation._generate_topic_page(
        _section(), [wiki_context], workspace_id="ws-1", requested_by=None,
    )

    assert action == "update_existing"
    assert page_id == "page-existing"
    assert version_id == "version-2"
    assert ("create", "hbm4-supply", "technology", "page-parent") in calls
    assert ("publish", ("page-existing", "version-2")) in calls


def test_generate_topic_page_skips_when_target_page_identity_missing(monkeypatch):
    monkeypatch.setattr(generation, "list_top_level_topic_pages", lambda workspace_id, supabase=None: [])
    monkeypatch.setattr(generation, "get_wiki_page_identity", lambda page_id, supabase=None: None)
    monkeypatch.setattr(
        generation,
        "create_json_completion",
        lambda **kwargs: json.dumps(
            {
                "action": "update_existing",
                "target_wiki_page_id": "page-deleted",
                "markdown": "# 갱신된 본문",
                "claims": [{"document_version_id": "doc-1", "claim_text": "근거", "citation_order": 1}],
                "confidence_score": 0.9,
            }
        ),
    )

    action, page_id, version_id = generation._generate_topic_page(
        _section(), [], workspace_id="ws-1", requested_by=None,
    )

    assert action == "skip"
    assert page_id is None
    assert version_id is None


def test_generate_topic_page_creates_new_under_chosen_parent(monkeypatch):
    calls = []
    top_level = generation.TopLevelTopicPage(wiki_page_id="page-parent", title="SK하이닉스", page_type="company")
    monkeypatch.setattr(generation, "list_top_level_topic_pages", lambda workspace_id, supabase=None: [top_level])
    monkeypatch.setattr(
        generation,
        "create_json_completion",
        lambda **kwargs: json.dumps(
            {
                "action": "create_new",
                "slug": "hbm4-supply",
                "title": "HBM4_수급현황",
                "page_type": "technology",
                "parent_page_id": "page-parent",
                "markdown": "# HBM4_수급현황",
                "change_summary": "최초 생성",
                "claims": [{"document_version_id": "doc-1", "claim_text": "근거", "citation_order": 1}],
                "confidence_score": 0.85,
            }
        ),
    )
    monkeypatch.setattr(generation, "upsert_wiki_page", lambda *a, **k: calls.append(("upsert", a)) or "page-new")
    monkeypatch.setattr(generation, "create_wiki_version", lambda draft: "version-4")
    monkeypatch.setattr(generation, "record_wiki_validation", lambda *a, **k: None)
    monkeypatch.setattr(generation, "review_wiki_version", lambda *a, **k: None)
    monkeypatch.setattr(generation, "publish_wiki_version", lambda *a, **k: None)

    action, page_id, version_id = generation._generate_topic_page(
        _section(), [], workspace_id="ws-1", requested_by=None,
    )

    assert action == "create_new"
    assert page_id == "page-new"
    upsert_call = next(call for call in calls if call[0] == "upsert")
    assert upsert_call[1] == ("ws-1", "hbm4-supply", "HBM4_수급현황", "technology", "page-parent")


def test_generate_topic_page_leaves_pending_when_confidence_low(monkeypatch):
    calls = []
    monkeypatch.setattr(generation, "list_top_level_topic_pages", lambda workspace_id, supabase=None: [])
    monkeypatch.setattr(
        generation,
        "create_json_completion",
        lambda **kwargs: json.dumps(
            {
                "action": "create_new",
                "slug": "new-topic",
                "title": "새 주제",
                "page_type": "technology",
                "parent_page_id": None,
                "markdown": "# 새 주제",
                "change_summary": "최초 생성",
                "claims": [{"document_version_id": "doc-1", "claim_text": "근거", "citation_order": 1}],
                "confidence_score": 0.3,
            }
        ),
    )
    monkeypatch.setattr(generation, "upsert_wiki_page", lambda *a, **k: "page-new")
    monkeypatch.setattr(generation, "create_wiki_version", lambda draft: "version-3")
    monkeypatch.setattr(generation, "record_wiki_validation", lambda *a, **k: calls.append(("validate", a)))
    monkeypatch.setattr(generation, "review_wiki_version", lambda *a, **k: calls.append(("review", a)))
    monkeypatch.setattr(generation, "publish_wiki_version", lambda *a, **k: calls.append(("publish", a)))

    action, page_id, version_id = generation._generate_topic_page(
        _section(), [], workspace_id="ws-1", requested_by=None,
    )

    assert action == "create_new"
    assert page_id == "page-new"
    assert version_id == "version-3"
    assert not any(call[0] in ("review", "publish") for call in calls)
    assert ("validate", ("version-3", "pending", 0.3)) in calls
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wiki_generation.py -v`
Expected: FAIL — `AttributeError: module 'src.wiki.generation' has no attribute '_generate_topic_page'`

- [ ] **Step 3: Write minimal implementation**

`src/wiki/generation.py` 상단 import에 추가:

```python
from ..analysis.classifier import create_json_completion, get_openrouter_settings, parse_json_response
from ..report.models import WikiContext
from .generation_models import TopicPageCandidate, TopLevelTopicPage, WikiPageIdentity, WikiTopicLLMResult
from .generation_prompts import WIKI_TOPIC_SYSTEM_PROMPT, build_wiki_topic_user_prompt
from .generation_repository import get_wiki_page_identity, list_top_level_topic_pages
```

(`TopLevelTopicPage`/`WikiPageIdentity`를 `generation.py` 이름공간으로 가져오는 이유: Task 6 테스트가 `generation.TopLevelTopicPage(...)`/`generation.WikiPageIdentity(...)`로 픽스처를 만들기 때문 — 별도 모듈에서 직접 import해도 동작은 같지만, 테스트가 `generation` 모듈을 통해서만 monkeypatch하므로 편의상 재노출한다.)

파일 끝에 추가:

```python
def _wiki_contexts_to_candidates(wiki_contexts: list[WikiContext]) -> list[TopicPageCandidate]:
    return [
        TopicPageCandidate(
            wiki_page_id=context.wiki_page_id,
            title=context.title,
            content=context.content,
            similarity_score=context.similarity_score,
        )
        for context in wiki_contexts
    ]


def _generate_topic_page(
    section: ReportSectionDraft,
    wiki_contexts: list[WikiContext],
    *,
    workspace_id: str,
    requested_by: str | None,
) -> tuple[str, str | None, str | None]:
    settings = get_openrouter_settings()
    candidates = _wiki_contexts_to_candidates(wiki_contexts)
    top_level_pages = list_top_level_topic_pages(workspace_id)

    response_text = create_json_completion(
        system_prompt=WIKI_TOPIC_SYSTEM_PROMPT,
        user_prompt=build_wiki_topic_user_prompt(
            section=section, candidates=candidates, top_level_pages=top_level_pages,
        ),
        model=settings.model,
    )
    payload = parse_json_response(response_text)
    result = WikiTopicLLMResult.model_validate(payload)

    if result.action == "skip" or not result.claims:
        return "skip", None, None

    sources = [
        WikiSourceInput(
            document_version_id=claim.document_version_id,
            claim_text=claim.claim_text,
            citation_order=claim.citation_order,
        )
        for claim in result.claims
    ]

    if result.action == "update_existing":
        if not result.target_wiki_page_id:
            return "skip", None, None
        # create_wiki_version()이 내부적으로 upsert_wiki_page()를 다시 실행하므로,
        # 기존 페이지의 실제 slug/title/page_type/parent_page_id를 그대로 넘겨
        # 같은 페이지로 멱등하게 귀결되도록 한다 (LLM은 update 시 이 값들을 안 줌).
        identity = get_wiki_page_identity(result.target_wiki_page_id)
        if identity is None:
            return "skip", None, None
        page_id = identity.page_id
        draft_slug = identity.slug
        draft_title = identity.title
        draft_page_type = identity.page_type
        draft_parent_page_id = identity.parent_page_id
    else:
        if not (result.slug and result.title and result.page_type):
            return "skip", None, None
        page_id = upsert_wiki_page(
            workspace_id, result.slug, result.title, result.page_type, result.parent_page_id,
        )
        draft_slug = result.slug
        draft_title = result.title
        draft_page_type = result.page_type
        draft_parent_page_id = result.parent_page_id

    draft = WikiDraftInput(
        workspace_id=workspace_id,
        slug=draft_slug,
        title=draft_title,
        page_type=draft_page_type,
        parent_page_id=draft_parent_page_id,
        markdown=result.markdown or "",
        sources=sources,
        change_summary=result.change_summary,
        created_by=requested_by,
        generated_by="llm",
    )
    version_id = create_wiki_version(draft)

    confidence = result.confidence_score
    if confidence is not None and confidence >= AUTO_PUBLISH_CONFIDENCE_THRESHOLD:
        record_wiki_validation(version_id, "passed", confidence)
        review_wiki_version(version_id, None, "approved")
        publish_wiki_version(page_id, version_id)
    else:
        record_wiki_validation(version_id, "pending", confidence)

    return result.action, page_id, version_id
```

`_generate_topic_page`가 `WikiSourceInput`/`WikiDraftInput`/`upsert_wiki_page`/`create_wiki_version`/`record_wiki_validation`/`review_wiki_version`/`publish_wiki_version`을 이미 Task 5에서 import했으므로 추가 import는 위 6줄만 필요.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_wiki_generation.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add src/wiki/generation.py tests/test_wiki_generation.py
git commit -m "Feat: 주제 페이지 LLM 종합 생성 + confidence 게이트 추가"
```

---

### Task 7: generation.py — 오케스트레이션 (`generate_wiki_drafts_for_sections`)

**Files:**
- Modify: `src/wiki/generation.py`
- Modify: `tests/test_wiki_generation.py`

**Interfaces:**
- Consumes: `_generate_issue_page`, `_generate_topic_page`(Task 5, 6), `EnrichedIssueGroup`(`report/models.py`), `WikiDraftGenerationResult`(Task 1)
- Produces: `generate_wiki_drafts_for_sections(sections: list[ReportSectionDraft], enriched_groups: list[EnrichedIssueGroup], *, workspace_id: str, requested_by: str | None = None) -> list[WikiDraftGenerationResult]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wiki_generation.py 에 이어서 추가
from src.report.models import EnrichedIssueGroup, IssueGroup, ReportCandidate


def _enriched_group(issue_key: str, wiki_contexts=None) -> EnrichedIssueGroup:
    candidate = ReportCandidate(
        analysis_result_id="analysis-1",
        document_version_id="doc-1",
        title="HBM4 공급 부족 심화",
        primary_category=Category.PRODUCT_TECHNOLOGY,
        reliability_score=80,
        importance_score=85,
        ranking_score=90,
    )
    return EnrichedIssueGroup(
        issue_group=IssueGroup(issue_key=issue_key, category=Category.PRODUCT_TECHNOLOGY, candidates=[candidate]),
        wiki_contexts=wiki_contexts or [],
    )


def test_generate_wiki_drafts_for_sections_isolates_issue_page_failures(monkeypatch):
    """토픽 생성은 성공했는데 이슈 페이지 생성이 실패해도, 다른 이슈 처리는 막지 않는다."""
    section_ok = _section("issue-ok")
    section_fail = _section("issue-fail")

    def fake_generate_topic_page(section, wiki_contexts, *, workspace_id, requested_by):
        return "skip", None, None

    def fake_generate_issue_page(section, *, workspace_id, requested_by, parent_page_id=None):
        if section.issue_key == "issue-fail":
            raise RuntimeError("Storage 업로드 실패")
        return "page-ok", "version-ok"

    monkeypatch.setattr(generation, "_generate_topic_page", fake_generate_topic_page)
    monkeypatch.setattr(generation, "_generate_issue_page", fake_generate_issue_page)

    results = generation.generate_wiki_drafts_for_sections(
        [section_ok, section_fail],
        [_enriched_group("issue-ok"), _enriched_group("issue-fail")],
        workspace_id="ws-1",
    )

    assert len(results) == 2
    ok_result = next(r for r in results if r.issue_key == "issue-ok")
    fail_result = next(r for r in results if r.issue_key == "issue-fail")
    assert ok_result.issue_page_id == "page-ok"
    assert fail_result.issue_page_id == ""
    assert fail_result.error_message is not None


def test_generate_wiki_drafts_for_sections_isolates_topic_page_failures(monkeypatch):
    """토픽 생성이 LLM 오류로 실패해도 이슈 페이지는 정상 생성된다."""

    def fake_generate_topic_page(section, wiki_contexts, *, workspace_id, requested_by):
        raise RuntimeError("LLM JSON 파싱 실패")

    def fake_generate_issue_page(section, *, workspace_id, requested_by, parent_page_id=None):
        return "page-ok", "version-ok"

    monkeypatch.setattr(generation, "_generate_topic_page", fake_generate_topic_page)
    monkeypatch.setattr(generation, "_generate_issue_page", fake_generate_issue_page)

    results = generation.generate_wiki_drafts_for_sections(
        [_section("issue-ok")],
        [_enriched_group("issue-ok")],
        workspace_id="ws-1",
    )

    assert len(results) == 1
    assert results[0].issue_page_id == "page-ok"
    assert results[0].topic_action == "failed"
    assert results[0].error_message is not None


def test_generate_wiki_drafts_for_sections_links_issue_page_to_resolved_topic(monkeypatch):
    """토픽 페이지가 만들어지면, 이슈 페이지의 parent_page_id로 그 id가 전달된다."""
    seen_parent_ids = []

    monkeypatch.setattr(
        generation, "_generate_topic_page",
        lambda section, wiki_contexts, **kwargs: ("create_new", "page-topic", "version-topic"),
    )

    def fake_generate_issue_page(section, *, workspace_id, requested_by, parent_page_id=None):
        seen_parent_ids.append(parent_page_id)
        return "page-issue", "version-issue"

    monkeypatch.setattr(generation, "_generate_issue_page", fake_generate_issue_page)

    generation.generate_wiki_drafts_for_sections(
        [_section("issue-ok")], [_enriched_group("issue-ok")], workspace_id="ws-1",
    )

    assert seen_parent_ids == ["page-topic"]


def test_generate_wiki_drafts_for_sections_passes_matching_wiki_contexts(monkeypatch):
    seen_contexts = []

    def fake_generate_topic_page(section, wiki_contexts, **kwargs):
        seen_contexts.append(wiki_contexts)
        return "skip", None, None

    monkeypatch.setattr(generation, "_generate_topic_page", fake_generate_topic_page)
    monkeypatch.setattr(
        generation, "_generate_issue_page", lambda section, **kwargs: ("page-1", "version-1")
    )

    wiki_context = WikiContext(wiki_page_id="page-existing", title="HBM4_수급현황", content="본문")
    generation.generate_wiki_drafts_for_sections(
        [_section("issue-ok")],
        [_enriched_group("issue-ok", wiki_contexts=[wiki_context])],
        workspace_id="ws-1",
    )

    assert seen_contexts == [[wiki_context]]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wiki_generation.py -v`
Expected: FAIL — `AttributeError: module 'src.wiki.generation' has no attribute 'generate_wiki_drafts_for_sections'`

- [ ] **Step 3: Write minimal implementation**

`src/wiki/generation.py` 파일 끝에 추가:

```python
from .generation_models import WikiDraftGenerationResult
from ..report.models import EnrichedIssueGroup


def generate_wiki_drafts_for_sections(
    sections: list[ReportSectionDraft],
    enriched_groups: list[EnrichedIssueGroup],
    *,
    workspace_id: str,
    requested_by: str | None = None,
) -> list[WikiDraftGenerationResult]:
    wiki_contexts_by_issue_key = {
        group.issue_group.issue_key: group.wiki_contexts for group in enriched_groups
    }

    # 주제 페이지를 먼저 정해야 이슈 페이지의 parent_page_id로 연결할 수 있다.
    # (upsert_wiki_page는 ignore_duplicates=True라 기존 페이지의 parent_page_id를
    #  나중에 수정할 방법이 없으므로, 이슈 페이지를 처음 만들 때 값을 넣어야 한다.)
    results: list[WikiDraftGenerationResult] = []
    for section in sections:
        wiki_contexts = wiki_contexts_by_issue_key.get(section.issue_key, [])

        topic_action: str = "skip"
        topic_page_id: str | None = None
        topic_version_id: str | None = None
        topic_error: str | None = None
        try:
            topic_action, topic_page_id, topic_version_id = _generate_topic_page(
                section, wiki_contexts, workspace_id=workspace_id, requested_by=requested_by,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("wiki_topic_page_generation_failed", extra={"issue_key": section.issue_key})
            topic_action, topic_page_id, topic_version_id = "failed", None, None
            topic_error = str(exc)

        try:
            issue_page_id, issue_version_id = _generate_issue_page(
                section,
                workspace_id=workspace_id,
                requested_by=requested_by,
                parent_page_id=topic_page_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("wiki_issue_page_generation_failed", extra={"issue_key": section.issue_key})
            results.append(
                WikiDraftGenerationResult(
                    issue_key=section.issue_key,
                    issue_page_id="",
                    issue_version_id="",
                    topic_action=topic_action,
                    topic_page_id=topic_page_id,
                    topic_version_id=topic_version_id,
                    error_message=str(exc) if topic_error is None else f"{topic_error}; {exc}",
                )
            )
            continue

        results.append(
            WikiDraftGenerationResult(
                issue_key=section.issue_key,
                issue_page_id=issue_page_id,
                issue_version_id=issue_version_id,
                topic_action=topic_action,
                topic_page_id=topic_page_id,
                topic_version_id=topic_version_id,
                error_message=topic_error,
            )
        )

    return results
```

(파일 상단 import 블록으로 `WikiDraftGenerationResult`, `EnrichedIssueGroup`를 옮겨도 되지만, 최소 변경 원칙상 함수 앞에 지역 import로 추가해도 동작에는 문제 없음 — 다만 실제 구현 시에는 파일 최상단 import 섹션으로 정리할 것.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_wiki_generation.py -v`
Expected: PASS (12 passed)

- [ ] **Step 5: Commit**

```bash
git add src/wiki/generation.py tests/test_wiki_generation.py
git commit -m "Feat: 섹션별 위키 생성 오케스트레이션 (주제 먼저 -> 이슈에 연결, 단계별 실패 격리)"
```

---

### Task 8: generation.py — `archive_stale_wiki_pages` + CLI 스크립트

**Files:**
- Modify: `src/wiki/generation.py`
- Create: `scripts/archive_stale_wiki_pages.py`
- Modify: `tests/test_wiki_generation.py`

**Interfaces:**
- Consumes: `find_stale_published_page_ids`, `archive_wiki_page`(Task 3)
- Produces: `archive_stale_wiki_pages(workspace_id: str, *, staleness_days: int = 90, supabase: Client | None = None) -> list[str]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wiki_generation.py 에 이어서 추가
def test_archive_stale_wiki_pages_archives_each_stale_id(monkeypatch):
    archived = []
    monkeypatch.setattr(
        generation, "find_stale_published_page_ids",
        lambda workspace_id, *, staleness_days, supabase=None: ["page-1", "page-2"],
    )
    monkeypatch.setattr(generation, "archive_wiki_page", lambda page_id, supabase=None: archived.append(page_id))

    result = generation.archive_stale_wiki_pages("ws-1", staleness_days=90)

    assert result == ["page-1", "page-2"]
    assert archived == ["page-1", "page-2"]


def test_archive_stale_wiki_pages_returns_empty_when_none_stale(monkeypatch):
    monkeypatch.setattr(
        generation, "find_stale_published_page_ids",
        lambda workspace_id, *, staleness_days, supabase=None: [],
    )
    result = generation.archive_stale_wiki_pages("ws-1")
    assert result == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wiki_generation.py -v`
Expected: FAIL — `AttributeError: module 'src.wiki.generation' has no attribute 'archive_stale_wiki_pages'`

- [ ] **Step 3: Write minimal implementation**

`src/wiki/generation.py` import 블록에 추가:

```python
from supabase import Client

from .generation_repository import archive_wiki_page, find_stale_published_page_ids
```

파일 끝에 추가:

```python
def archive_stale_wiki_pages(
    workspace_id: str,
    *,
    staleness_days: int = 90,
    supabase: Client | None = None,
) -> list[str]:
    stale_page_ids = find_stale_published_page_ids(
        workspace_id, staleness_days=staleness_days, supabase=supabase,
    )
    for page_id in stale_page_ids:
        archive_wiki_page(page_id, supabase=supabase)
    return stale_page_ids
```

`scripts/archive_stale_wiki_pages.py` 신규 작성:

```python
"""90일 이상 갱신 없는 published Wiki 페이지를 archived로 전환하는 배치.

리포트/위키 생성 파이프라인과 완전히 독립된 스케줄로 돌린다.

사용법:
    python scripts/archive_stale_wiki_pages.py
    python scripts/archive_stale_wiki_pages.py --staleness-days 30
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.pipeline_common.db import get_client
from src.wiki.generation import archive_stale_wiki_pages


def get_workspace_id() -> str:
    rows = get_client().table("workspaces").select("id, name").limit(2).execute().data
    if len(rows) != 1:
        raise SystemExit(f"workspace_id를 자동으로 하나로 못 정했다 (workspaces 행 {len(rows)}개).")
    return str(rows[0]["id"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staleness-days", type=int, default=90)
    args = parser.parse_args()

    workspace_id = get_workspace_id()
    archived_ids = archive_stale_wiki_pages(workspace_id, staleness_days=args.staleness_days)
    print(f"[archive] {len(archived_ids)}개 페이지 아카이빙: {archived_ids}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_wiki_generation.py -v`
Expected: PASS (14 passed)

- [ ] **Step 5: Commit**

```bash
git add src/wiki/generation.py scripts/archive_stale_wiki_pages.py tests/test_wiki_generation.py
git commit -m "Feat: 90일 무갱신 위키 페이지 자동 아카이빙 배치 추가"
```

---

### Task 9: report/interface.py 통합

**Files:**
- Modify: `src/report/interface.py:1-30` (import 추가), `:170-180` (호출 추가)
- Test: `tests/test_report_interface.py` (기존 파일에 케이스 추가)

**Interfaces:**
- Consumes: `generate_wiki_drafts_for_sections`(Task 7)
- Produces: 없음 (최종 통합 지점)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report_interface.py 에 이어서 추가 (기존 파일의 monkeypatch 픽스처 패턴을 따름 — fake_create 등 이미 있는 스타일 그대로)
def test_generate_daily_report_calls_wiki_draft_generation(monkeypatch):
    calls = []
    # 기존 테스트 파일 상단에 이미 있는 fake_create/fake_candidates 등 monkeypatch들을
    # 그대로 적용한 상태에서, 아래 한 줄만 추가로 patch한다.
    monkeypatch.setattr(
        "src.report.interface.generate_wiki_drafts_for_sections",
        lambda sections, enriched_groups, *, workspace_id, requested_by=None: calls.append(
            (len(sections), len(enriched_groups), workspace_id)
        ) or [],
    )

    # 이 테스트 파일의 기존 `test_generate_daily_report_runs_pipeline_in_order`와 동일한
    # 방식으로 나머지 단계(create_report_version, get_report_candidates, select_report_candidates,
    # group_report_candidates, enrich_issue_groups, compose_report_sections, assemble_generated_report,
    # save_report_sections, create_and_save_markdown_artifact, mark_report_completed)를 monkeypatch한 뒤
    # generate_daily_report(request)를 호출한다.
    # ... (기존 테스트의 셋업 재사용)

    assert len(calls) == 1
    assert calls[0][2] == "ws-1"


def test_generate_daily_report_survives_wiki_draft_generation_failure(monkeypatch):
    # 위와 동일한 셋업에서, generate_wiki_drafts_for_sections가 예외를 던지도록 patch.
    monkeypatch.setattr(
        "src.report.interface.generate_wiki_drafts_for_sections",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("wiki 생성 실패")),
    )
    # generate_daily_report(request) 호출이 예외 없이 정상적으로 리포트를 완료 상태로 반환하는지 확인.
    # result = generate_daily_report(request, ...)
    # assert result.report.status == ReportStatus.COMPLETED
```

(이 테스트 두 개는 `tests/test_report_interface.py`의 기존 `test_generate_daily_report_runs_pipeline_in_order` 테스트의 monkeypatch 셋업 블록을 그대로 복사해서 시작하고, 위에서 설명한 대로 `generate_wiki_drafts_for_sections`만 추가로 patch한다. 실제 작성 시 기존 파일을 먼저 Read해서 정확한 fixture 이름과 셋업 코드를 그대로 재사용할 것.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_report_interface.py -v -k wiki_draft`
Expected: FAIL — `generate_wiki_drafts_for_sections`가 아직 `src.report.interface`에 없어서 `monkeypatch.setattr`이 `AttributeError` 발생

- [ ] **Step 3: Write minimal implementation**

`src/report/interface.py` import 블록에 추가 (다른 `from ..` import들 근처):

```python
from ..wiki.generation import generate_wiki_drafts_for_sections
```

`generate_daily_report()` 내부, `_validate_section_drafts(section_drafts, expected_count=len(issue_groups))` 다음 줄, `stage = "assemble_report"` 이전에 추가:

```python
        stage = "generate_wiki_drafts"
        try:
            generate_wiki_drafts_for_sections(
                section_drafts,
                enriched_groups,
                workspace_id=request.workspace_id,
                requested_by=pipeline_config.requested_by,
            )
        except Exception:
            logger.exception(
                "wiki_draft_generation_failed",
                extra={
                    "stage": stage,
                    "report_id": report.report_id,
                    "workspace_id": request.workspace_id,
                },
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_report_interface.py -v`
Expected: PASS (전체 — 기존 테스트 포함 모두 통과)

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -q`
Expected: 전부 PASS (신규 테스트 포함, 기존 313 passed + 신규 약 33개)

- [ ] **Step 6: Commit**

```bash
git add src/report/interface.py tests/test_report_interface.py
git commit -m "Feat: generate_daily_report()에 위키 자동생성 단계 연결"
```

---

## Post-Implementation Checklist

- [ ] `python -m pytest tests/ -q` 전체 통과
- [ ] `docs/architecture/mywiki-erd.md` — 이번 기능은 기존 테이블만 사용하므로 스키마 변경 없음. 변경 없음을 확인만 하고 문서 갱신은 불필요.
- [ ] `.env`에 실제 `OPENROUTER_API_KEY`/`SUPABASE_SERVICE_ROLE_KEY`를 채운 로컬 환경에서 `python scripts/run_local_pipeline.py --limit 3` 실행 → `wiki_pages`에 이슈 페이지 + (근거가 충분하면) 주제 페이지가 실제로 생성/발행되는지 확인
- [ ] `python scripts/archive_stale_wiki_pages.py --staleness-days 90` 실행 확인(신규 환경에선 대상 0건이 정상)

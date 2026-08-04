# 위키 중복 정리(Dedup) 배치 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 프로덕션에 이미 쌓인 중복 위키 페이지(토픽-이슈, 이슈-이슈)를 LLM이 스스로 찾아 하나로 병합하고 나머지는 아카이빙하는 매일 1회 배치를 만든다.

**Architecture:** `src/wiki/dedup_repository.py`(DB 조회 — 후보 탐지, 재부모연결)와 `src/wiki/dedup.py`(오케스트레이션 — LLM 판단, 병합 적용)를 `src/wiki/generation.py`/`generation_repository.py`와 같은 분리 패턴으로 새로 만든다. 후보 탐지는 "공유 근거 문서" OR "제목 유사도"(신규 공용 모듈 `text_similarity.py`) 두 신호를 쓰고, 최종 병합 여부·방법은 전적으로 LLM 판단에 맡긴다. 실행은 `scripts/dedup_wiki_scheduled.py` + GitHub Actions cron(`wiki-dedup-batch.yml`), 기존 `refresh_wiki_scheduled.py`/`wiki-refresh-gate.yml`과 동일한 패턴.

**Tech Stack:** Python 3.12, Supabase(Postgres+Storage), OpenRouter(OpenAI 호환 API, `src/analysis/classifier.py`의 `create_json_completion`), pytest, GitHub Actions.

## Global Constraints

- 삭제 금지 — 아카이빙(`status='archived'`)만 사용. `wiki_pages`/`wiki_page_versions`/`wiki_page_sources` 어떤 행도 지우지 않는다.
- claims에 없는 문장(document_version_id로 뒷받침 안 되는 주장)은 markdown에 쓰지 않는다 — 기존 생성 파이프라인(`generation.py`)과 동일한 절대 규칙.
- 최종 "진짜 중복인가/병합할까"는 LLM 판단, 코드는 후보만 좁히고 결과만 적용한다.
- 이 브랜치는 `fix/wiki-topic-issue-duplicate-title`(PR #59) 위에서 시작한다 — `_is_duplicate_title`/`_title_tokens`를 Task 1에서 옮겨올 원본이 그 커밋에 있다. PR #59가 먼저 머지되면 이 브랜치를 `develop`으로 rebase 한 번 더 하고 진행한다.

---

### Task 1: `text_similarity.py`로 제목 유사도 로직 추출

**Files:**
- Create: `src/wiki/text_similarity.py`
- Modify: `src/wiki/generation.py:1-70` (import 정리, 로컬 정의 제거)
- Test: `tests/test_wiki_text_similarity.py` (신규), `tests/test_wiki_generation.py`(기존 테스트 그대로 통과해야 함, 수정 없음)

**Interfaces:**
- Produces: `is_duplicate_title(candidate_title: str, issue_title: str, *, threshold: float = 0.8) -> bool`, `title_similarity(a: str, b: str) -> float` (0.0~1.0, 토큰 자카드 유사도) — Task 3에서 후보 탐지 스코어링에 사용.

- [ ] **Step 1: 새 모듈에 실패하는 테스트부터 작성**

`tests/test_wiki_text_similarity.py`:
```python
from __future__ import annotations

from src.wiki.text_similarity import is_duplicate_title, title_similarity


def test_title_similarity_exact_match_is_one():
    assert title_similarity("HBM4 공급 부족 심화", "HBM4 공급 부족 심화") == 1.0


def test_title_similarity_unrelated_titles_is_low():
    assert title_similarity("SK하이닉스", "HBM4 공급 부족 심화") < 0.2


def test_is_duplicate_title_true_for_exact_match():
    assert is_duplicate_title("SK하이닉스, 무디스 신용등급 'A3' 상향과 중기 시장 기회",
                               "SK하이닉스, 무디스 신용등급 'A3' 상향과 중기 시장 기회") is True


def test_is_duplicate_title_false_for_meaningfully_different_titles():
    assert is_duplicate_title("HBM4_수급현황", "HBM4 공급 부족 심화") is False


def test_is_duplicate_title_false_when_either_title_is_empty():
    assert is_duplicate_title("", "HBM4 공급 부족 심화") is False
    assert is_duplicate_title("HBM4 공급 부족 심화", "") is False


def test_is_duplicate_title_respects_custom_threshold():
    # "HBM4 공급"과 "HBM4 공급 부족 심화"는 토큰 일부만 겹침 — 낮은 threshold면 True.
    assert is_duplicate_title("HBM4 공급", "HBM4 공급 부족 심화", threshold=0.3) is True
    assert is_duplicate_title("HBM4 공급", "HBM4 공급 부족 심화", threshold=0.9) is False
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `python -m pytest tests/test_wiki_text_similarity.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.wiki.text_similarity'`

- [ ] **Step 3: `src/wiki/text_similarity.py` 작성 (generation.py의 기존 로직을 그대로 옮기고 threshold를 인자로 뺌)**

```python
from __future__ import annotations

import re
import unicodedata

# 두 제목이 이 이상 겹치면 "사실상 같은 제목"으로 본다(토큰 자카드 유사도).
DEFAULT_DUPLICATE_TITLE_THRESHOLD = 0.8
_TOKEN_SPLIT_PATTERN = re.compile(r"[\s\W_]+", re.UNICODE)


def _title_tokens(title: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", title or "").strip().lower()
    return {token for token in _TOKEN_SPLIT_PATTERN.split(normalized) if token}


def title_similarity(a: str, b: str) -> float:
    """두 제목의 토큰 자카드 유사도(0.0~1.0). 둘 중 하나라도 비어있으면 0.0."""
    tokens_a = _title_tokens(a)
    tokens_b = _title_tokens(b)
    if not tokens_a or not tokens_b:
        return 0.0
    union = tokens_a | tokens_b
    return len(tokens_a & tokens_b) / len(union)


def is_duplicate_title(
    candidate_title: str,
    issue_title: str,
    *,
    threshold: float = DEFAULT_DUPLICATE_TITLE_THRESHOLD,
) -> bool:
    """두 제목이 사실상 같은 제목인지 판단한다.

    위키 토픽 페이지가 이슈 페이지를 그대로 복제하는 문제(실사용 데이터에서 확인된
    버그)를 막기 위해, LLM 판단에만 맡기지 않고 코드에서 결정적으로 검사한다.
    """
    return title_similarity(candidate_title, issue_title) >= threshold
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `python -m pytest tests/test_wiki_text_similarity.py -v`
Expected: 6 passed

- [ ] **Step 5: `generation.py`가 새 모듈을 쓰도록 정리**

`src/wiki/generation.py` 상단(1~70번째 줄 부근)을 다음과 같이 바꾼다 — `import re`/`import unicodedata`,
`_DUPLICATE_TITLE_JACCARD_THRESHOLD`/`_TOKEN_SPLIT_PATTERN`/`_title_tokens`/`_is_duplicate_title` 정의를
전부 삭제하고 새 모듈에서 import한다:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from collections.abc import Callable

from pydantic import ValidationError
from supabase import Client

from ..analysis.classifier import create_json_completion, get_openrouter_settings, parse_json_response
from ..report.candidate_provider import get_recently_analyzed_candidates
from ..report.composer import compose_report_sections
from ..report.grouper import group_report_candidates
from ..report.models import EnrichedIssueGroup, ReportSectionDraft, WikiContext
from ..report.selector import select_report_candidates
from ..report.wiki_context import enrich_issue_groups
from .generation_models import TopicPageCandidate, TopLevelTopicPage, WikiDraftGenerationResult, WikiPageIdentity, WikiTopicLLMResult
from .generation_prompts import WIKI_TOPIC_SYSTEM_PROMPT, build_wiki_topic_user_prompt
from .generation_repository import (
    archive_wiki_page,
    filter_to_topic_page_ids,
    find_matching_issue_page,
    find_stale_published_page_ids,
    get_wiki_page_identity,
    list_top_level_topic_pages,
)
from .interface import (
    WikiDraftInput,
    WikiSourceInput,
    create_wiki_version,
    publish_wiki_version,
    record_wiki_validation,
    review_wiki_version,
    search_wiki_contexts,
    upsert_wiki_page,
)
from .text_similarity import is_duplicate_title
from ..notifications.service import send_wiki_notification

logger = logging.getLogger(__name__)

# (system_prompt, user_prompt, model) -> raw JSON 문자열.
# src/report/composer.py의 llm_client 주입 패턴과 같은 형태의 호출 가능 객체다.
WikiTopicLLMClient = Callable[[str, str, str | None], str]
```

그리고 파일 안에서 `_is_duplicate_title(result.title, section.title)`로 호출하던 부분(`_generate_topic_page`
안)을 `is_duplicate_title(result.title, section.title)`로 바꾼다(밑줄 하나만 제거).

- [ ] **Step 6: 기존 테스트가 그대로 통과하는지 확인**

Run: `python -m pytest tests/test_wiki_generation.py -v`
Expected: 45 passed (기존 로직 변경 없음, import만 바뀜)

- [ ] **Step 7: 커밋**

```bash
git add src/wiki/text_similarity.py src/wiki/generation.py tests/test_wiki_text_similarity.py
git commit -m "Refactor: 제목 유사도 로직을 text_similarity.py로 추출 (dedup 배치와 공용)"
```

---

### Task 2: `dedup_models.py` — 데이터 모델

**Files:**
- Create: `src/wiki/dedup_models.py`
- Test: 별도 테스트 없음(순수 데이터 클래스, Task 3/4에서 간접 검증)

**Interfaces:**
- Consumes: 없음
- Produces:
  - `DedupPageInfo(page_id: str, slug: str, title: str, page_type: str, parent_page_id: str | None = None)`
  - `DedupCandidatePair(page_a: DedupPageInfo, page_b: DedupPageInfo, shared_source_count: int, title_similarity: float)`
  - `WikiDedupClaim(document_version_id: str, claim_text: str, citation_order: int)`
  - `WikiDedupDecision = Literal["merge", "not_duplicate"]`
  - `WikiDedupLLMResult(decision: WikiDedupDecision, representative_page_id: str | None = None, markdown: str | None = None, change_summary: str | None = None, claims: list[WikiDedupClaim] = [])`
  - `DedupResult(page_a_id: str, page_b_id: str, decision: Literal["merged", "not_duplicate", "failed"], representative_page_id: str | None = None, archived_page_id: str | None = None, version_id: str | None = None, error_message: str | None = None)`

- [ ] **Step 1: 파일 작성**

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

WikiDedupDecision = Literal["merge", "not_duplicate"]


class DedupPageInfo(BaseModel):
    page_id: str
    slug: str
    title: str
    page_type: str
    parent_page_id: str | None = None


class DedupCandidatePair(BaseModel):
    page_a: DedupPageInfo
    page_b: DedupPageInfo
    shared_source_count: int = Field(ge=0)
    title_similarity: float = Field(ge=0.0, le=1.0)


class WikiDedupClaim(BaseModel):
    document_version_id: str
    claim_text: str
    citation_order: int = Field(ge=1)


class WikiDedupLLMResult(BaseModel):
    decision: WikiDedupDecision
    representative_page_id: str | None = None
    markdown: str | None = None
    change_summary: str | None = None
    claims: list[WikiDedupClaim] = Field(default_factory=list)


class DedupResult(BaseModel):
    page_a_id: str
    page_b_id: str
    decision: Literal["merged", "not_duplicate", "failed"]
    representative_page_id: str | None = None
    archived_page_id: str | None = None
    version_id: str | None = None
    error_message: str | None = None
```

- [ ] **Step 2: import 확인(문법 오류만 체크)**

Run: `python -c "from src.wiki.dedup_models import DedupPageInfo, DedupCandidatePair, WikiDedupClaim, WikiDedupLLMResult, DedupResult; print('ok')"`
Expected: `ok`

- [ ] **Step 3: 커밋**

```bash
git add src/wiki/dedup_models.py
git commit -m "Feat: 위키 dedup 배치 데이터 모델 추가"
```

---

### Task 3: `find_duplicate_candidate_pairs()` — 중복 후보 탐지

**Files:**
- Create: `src/wiki/dedup_repository.py`
- Test: `tests/test_wiki_dedup_repository.py` (신규)

**Interfaces:**
- Consumes: `DedupCandidatePair`, `DedupPageInfo` (Task 2), `title_similarity` (Task 1)
- Produces: `find_duplicate_candidate_pairs(workspace_id: str, *, max_pairs: int = 20, min_shared_source_count: int = 1, title_similarity_threshold: float = 0.8, supabase: Client | None = None) -> list[DedupCandidatePair]` — Task 6(`run_wiki_dedup_batch`)이 사용.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_wiki_dedup_repository.py` (fake DB는 `tests/test_wiki_query_related_pages.py`의 `FakeTable`/`FakeSupabase` 패턴을 그대로 재사용 — `neq`는 이번엔 필요 없고 `select`/`eq`/`in_`/`execute`만 필요):

```python
from __future__ import annotations

from src.wiki.dedup_models import DedupCandidatePair
from src.wiki.dedup_repository import find_duplicate_candidate_pairs

WORKSPACE_ID = "ws-1"


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []

    def select(self, _fields):
        return self

    def eq(self, field, value):
        self.filters.append(("eq", field, value))
        return self

    def in_(self, field, values):
        self.filters.append(("in", field, set(values)))
        return self

    def execute(self):
        return FakeResult([dict(r) for r in self._filtered_rows()])

    def _filtered_rows(self):
        rows = self.rows
        for op, field, value in self.filters:
            if op == "eq":
                rows = [r for r in rows if r.get(field) == value]
            elif op == "in":
                rows = [r for r in rows if r.get(field) in value]
        return rows


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return FakeTable(self.tables[name])


def _page(page_id, slug, title, page_type="issue", parent_page_id=None, current_version_id=None):
    return {
        "id": page_id, "workspace_id": WORKSPACE_ID, "slug": slug, "title": title,
        "page_type": page_type, "parent_page_id": parent_page_id, "status": "published",
        "current_version_id": current_version_id or f"v-{page_id}",
    }


def test_pairs_with_shared_source_become_candidates():
    db = FakeSupabase(
        {
            "wiki_pages": [
                _page("page-a", "a", "제목 A"),
                _page("page-b", "b", "제목 B"),
            ],
            "wiki_page_sources": [
                {"wiki_version_id": "v-page-a", "document_version_id": "doc-1"},
                {"wiki_version_id": "v-page-b", "document_version_id": "doc-1"},
            ],
        }
    )
    pairs = find_duplicate_candidate_pairs(WORKSPACE_ID, supabase=db)
    assert len(pairs) == 1
    assert {pairs[0].page_a.page_id, pairs[0].page_b.page_id} == {"page-a", "page-b"}
    assert pairs[0].shared_source_count == 1


def test_pairs_with_similar_title_but_no_shared_source_become_candidates():
    db = FakeSupabase(
        {
            "wiki_pages": [
                _page("page-a", "china-reg", "china_semiconductor_design_protection_regulation"),
                _page("page-b", "china-reg-2026", "china_semiconductor_design_protection_regulation_2026"),
            ],
            "wiki_page_sources": [
                {"wiki_version_id": "v-page-a", "document_version_id": "doc-1"},
                {"wiki_version_id": "v-page-b", "document_version_id": "doc-2"},  # 겹치는 근거 없음
            ],
        }
    )
    pairs = find_duplicate_candidate_pairs(WORKSPACE_ID, supabase=db)
    assert len(pairs) == 1
    assert pairs[0].shared_source_count == 0
    assert pairs[0].title_similarity > 0.8


def test_unrelated_pages_are_not_candidates():
    db = FakeSupabase(
        {
            "wiki_pages": [
                _page("page-a", "a", "SK하이닉스"),
                _page("page-b", "b", "HBM4 공급 부족 심화"),
            ],
            "wiki_page_sources": [
                {"wiki_version_id": "v-page-a", "document_version_id": "doc-1"},
                {"wiki_version_id": "v-page-b", "document_version_id": "doc-2"},
            ],
        }
    )
    pairs = find_duplicate_candidate_pairs(WORKSPACE_ID, supabase=db)
    assert pairs == []


def test_max_pairs_caps_and_prioritizes_highest_score():
    db = FakeSupabase(
        {
            "wiki_pages": [
                _page("page-a", "a", "제목 A"),
                _page("page-b", "b", "제목 A"),  # 완전 동일 제목(가장 강한 후보)
                _page("page-c", "c", "제목 C"),
            ],
            "wiki_page_sources": [
                {"wiki_version_id": "v-page-a", "document_version_id": "doc-1"},
                {"wiki_version_id": "v-page-b", "document_version_id": "doc-1"},
                {"wiki_version_id": "v-page-c", "document_version_id": "doc-1"},
            ],
        }
    )
    pairs = find_duplicate_candidate_pairs(WORKSPACE_ID, supabase=db, max_pairs=1)
    assert len(pairs) == 1
    assert {pairs[0].page_a.slug, pairs[0].page_b.slug} == {"a", "b"}  # 제목까지 겹치는 쌍이 우선


def test_parent_page_id_is_carried_through():
    db = FakeSupabase(
        {
            "wiki_pages": [
                _page("page-a", "a", "제목 A", page_type="market", parent_page_id="page-parent"),
                _page("page-b", "b", "제목 A"),
            ],
            "wiki_page_sources": [
                {"wiki_version_id": "v-page-a", "document_version_id": "doc-1"},
                {"wiki_version_id": "v-page-b", "document_version_id": "doc-1"},
            ],
        }
    )
    pairs = find_duplicate_candidate_pairs(WORKSPACE_ID, supabase=db)
    page_a_info = next(p for p in (pairs[0].page_a, pairs[0].page_b) if p.slug == "a")
    assert page_a_info.parent_page_id == "page-parent"
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `python -m pytest tests/test_wiki_dedup_repository.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.wiki.dedup_repository'`

- [ ] **Step 3: `src/wiki/dedup_repository.py` 작성**

```python
from __future__ import annotations

import logging
from itertools import combinations

from supabase import Client

from ..analysis.repository import get_supabase
from .dedup_models import DedupCandidatePair, DedupPageInfo
from .text_similarity import DEFAULT_DUPLICATE_TITLE_THRESHOLD, title_similarity

logger = logging.getLogger(__name__)

DEFAULT_MAX_PAIRS = 20


def find_duplicate_candidate_pairs(
    workspace_id: str,
    *,
    max_pairs: int = DEFAULT_MAX_PAIRS,
    min_shared_source_count: int = 1,
    title_similarity_threshold: float = DEFAULT_DUPLICATE_TITLE_THRESHOLD,
    supabase: Client | None = None,
) -> list[DedupCandidatePair]:
    """공유 근거 문서 OR 제목 유사도, 둘 중 하나라도 걸리면 후보 쌍으로 올린다.

    최종 판단(진짜 중복인지, 병합할지)은 LLM에게 맡긴다 — 여기서는 후보만 좁히고
    점수(공유 근거 수 + 제목 유사도) 내림차순으로 상위 max_pairs개만 반환한다.
    """
    db = supabase or get_supabase()

    pages = (
        db.table("wiki_pages")
        .select("id, slug, title, page_type, parent_page_id, current_version_id")
        .eq("workspace_id", workspace_id)
        .eq("status", "published")
        .execute()
        .data
    )
    pages = [p for p in pages if p.get("current_version_id")]
    if len(pages) < 2:
        return []

    version_ids = list({str(p["current_version_id"]) for p in pages})
    source_rows = (
        db.table("wiki_page_sources")
        .select("wiki_version_id, document_version_id")
        .in_("wiki_version_id", version_ids)
        .execute()
        .data
    )
    docs_by_version: dict[str, set[str]] = {}
    for row in source_rows:
        docs_by_version.setdefault(str(row["wiki_version_id"]), set()).add(row["document_version_id"])

    scored: list[tuple[float, DedupCandidatePair]] = []
    for page_a, page_b in combinations(pages, 2):
        docs_a = docs_by_version.get(str(page_a["current_version_id"]), set())
        docs_b = docs_by_version.get(str(page_b["current_version_id"]), set())
        shared_count = len(docs_a & docs_b)
        similarity = title_similarity(page_a["title"], page_b["title"])
        if shared_count < min_shared_source_count and similarity < title_similarity_threshold:
            continue
        scored.append((
            shared_count + similarity,
            DedupCandidatePair(
                page_a=_to_page_info(page_a),
                page_b=_to_page_info(page_b),
                shared_source_count=shared_count,
                title_similarity=similarity,
            ),
        ))

    scored.sort(key=lambda item: item[0], reverse=True)
    if len(scored) > max_pairs:
        logger.info(
            "wiki_dedup_candidates_capped",
            extra={"workspace_id": workspace_id, "total_candidates": len(scored), "processed": max_pairs},
        )
    return [pair for _, pair in scored[:max_pairs]]


def _to_page_info(row: dict) -> DedupPageInfo:
    return DedupPageInfo(
        page_id=str(row["id"]),
        slug=row["slug"],
        title=row["title"],
        page_type=row["page_type"],
        parent_page_id=str(row["parent_page_id"]) if row.get("parent_page_id") else None,
    )
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `python -m pytest tests/test_wiki_dedup_repository.py -v`
Expected: 5 passed

- [ ] **Step 5: 커밋**

```bash
git add src/wiki/dedup_repository.py tests/test_wiki_dedup_repository.py
git commit -m "Feat: 위키 중복 후보 탐지(공유 근거 + 제목 유사도) 구현"
```

---

### Task 4: `reparent_children()` — 아카이빙되는 페이지의 자식 재연결

**Files:**
- Modify: `src/wiki/dedup_repository.py` (Task 3에서 만든 파일에 함수 추가)
- Test: `tests/test_wiki_dedup_repository.py` (Task 3 파일에 테스트 추가)

**Interfaces:**
- Consumes: 없음(순수 DB 업데이트)
- Produces: `reparent_children(old_page_id: str, new_page_id: str, *, workspace_id: str, supabase: Client | None = None) -> int` (재연결된 자식 수 반환) — Task 7(`_judge_and_merge`)이 사용.

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/test_wiki_dedup_repository.py` 맨 아래에 추가 (이번엔 `update`도 지원해야 하므로 `FakeTable`에
`update` 메서드를 추가한다 — `tests/test_wiki_generation_repository.py`의 `FakeTable.update` 패턴과 동일):

```python
class _UpdatableFakeTable(FakeTable):
    def __init__(self, rows):
        super().__init__(rows)
        self.update_payload = None

    def update(self, payload):
        self.update_payload = dict(payload)
        return self

    def execute(self):
        if self.update_payload is not None:
            matched = self._filtered_rows()
            for row in matched:
                row.update(self.update_payload)
            return FakeResult([dict(row) for row in matched])
        return super().execute()


class _UpdatableFakeSupabase(FakeSupabase):
    def table(self, name):
        return _UpdatableFakeTable(self.tables[name])


def test_reparent_children_updates_all_matching_rows():
    from src.wiki.dedup_repository import reparent_children

    rows = [
        _page("child-1", "c1", "이슈1", parent_page_id="page-old"),
        _page("child-2", "c2", "이슈2", parent_page_id="page-old"),
        _page("unrelated", "u", "무관", parent_page_id="page-other"),
    ]
    db = _UpdatableFakeSupabase({"wiki_pages": rows})

    count = reparent_children("page-old", "page-new", workspace_id=WORKSPACE_ID, supabase=db)

    assert count == 2
    assert rows[0]["parent_page_id"] == "page-new"
    assert rows[1]["parent_page_id"] == "page-new"
    assert rows[2]["parent_page_id"] == "page-other"  # 무관한 행은 안 바뀜


def test_reparent_children_returns_zero_when_no_children():
    from src.wiki.dedup_repository import reparent_children

    db = _UpdatableFakeSupabase({"wiki_pages": [_page("a", "a", "제목", parent_page_id=None)]})
    count = reparent_children("page-old", "page-new", workspace_id=WORKSPACE_ID, supabase=db)
    assert count == 0
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `python -m pytest tests/test_wiki_dedup_repository.py -k reparent -v`
Expected: FAIL — `ImportError: cannot import name 'reparent_children'`

- [ ] **Step 3: `reparent_children()` 추가**

`src/wiki/dedup_repository.py` 파일 맨 아래에 추가:

```python
def reparent_children(
    old_page_id: str,
    new_page_id: str,
    *,
    workspace_id: str,
    supabase: Client | None = None,
) -> int:
    """old_page_id를 parent_page_id로 참조하던 페이지들을 new_page_id로 재연결한다.

    아카이빙되는 페이지가 토픽 페이지라서 그 밑에 이슈 페이지들이 매달려 있었다면,
    이걸 안 하면 부모 없는 이슈 페이지가 남는다.
    """
    db = supabase or get_supabase()
    result = (
        db.table("wiki_pages")
        .update({"parent_page_id": new_page_id})
        .eq("workspace_id", workspace_id)
        .eq("parent_page_id", old_page_id)
        .execute()
    )
    return len(result.data or [])
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `python -m pytest tests/test_wiki_dedup_repository.py -v`
Expected: 7 passed

- [ ] **Step 5: 커밋**

```bash
git add src/wiki/dedup_repository.py tests/test_wiki_dedup_repository.py
git commit -m "Feat: 아카이빙 시 자식 페이지 재부모연결(reparent_children) 추가"
```

---

### Task 5: `dedup_prompts.py` — LLM 프롬프트

**Files:**
- Create: `src/wiki/dedup_prompts.py`
- Test: `tests/test_wiki_dedup_prompts.py` (신규)

**Interfaces:**
- Consumes: `WikiPageContent`, `WikiSource` (`src/wiki/interface.py`, 이미 존재)
- Produces: `WIKI_DEDUP_SYSTEM_PROMPT: str`, `build_wiki_dedup_user_prompt(content_a: WikiPageContent, content_b: WikiPageContent) -> str` — Task 6(`_judge_and_merge`)이 사용.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from __future__ import annotations

from src.wiki.dedup_prompts import WIKI_DEDUP_SYSTEM_PROMPT, build_wiki_dedup_user_prompt
from src.wiki.interface import WikiPageContent, WikiSource


def _content(page_id, title, markdown, sources):
    return WikiPageContent(
        page_id=page_id, slug=page_id, title=title, page_type="issue", published_at=None,
        version_id=f"v-{page_id}", version_no=1, markdown=markdown, change_summary=None,
        confidence_score=None, validation_status="passed", review_status="approved",
        generated_by="llm", generator_model=None, created_at="2026-08-04T00:00:00Z",
        sources=tuple(sources), versions=(),
    )


def test_system_prompt_requires_grounded_claims_and_allows_not_duplicate():
    assert "not_duplicate" in WIKI_DEDUP_SYSTEM_PROMPT
    assert "claims" in WIKI_DEDUP_SYSTEM_PROMPT


def test_user_prompt_includes_both_pages_titles_and_markdown():
    content_a = _content("page-a", "제목 A", "# 본문 A", [
        WikiSource(document_version_id="doc-1", citation_order=1, claim_text="근거 A",
                   support_type="supports", source_start_line=None, source_end_line=None),
    ])
    content_b = _content("page-b", "제목 B", "# 본문 B", [
        WikiSource(document_version_id="doc-2", citation_order=1, claim_text="근거 B",
                   support_type="supports", source_start_line=None, source_end_line=None),
    ])

    prompt = build_wiki_dedup_user_prompt(content_a, content_b)

    assert "page_id=page-a" in prompt
    assert "제목 A" in prompt
    assert "# 본문 A" in prompt
    assert "document_version_id=doc-1" in prompt
    assert "제목 B" in prompt
    assert "# 본문 B" in prompt
    assert "document_version_id=doc-2" in prompt


def test_user_prompt_handles_page_with_no_sources():
    content_a = _content("page-a", "제목 A", "# 본문", [])
    content_b = _content("page-b", "제목 B", "# 본문", [])
    prompt = build_wiki_dedup_user_prompt(content_a, content_b)
    assert "없음" in prompt
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `python -m pytest tests/test_wiki_dedup_prompts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.wiki.dedup_prompts'`

- [ ] **Step 3: `src/wiki/dedup_prompts.py` 작성**

```python
from __future__ import annotations

from .interface import WikiPageContent

WIKI_DEDUP_SYSTEM_PROMPT = """당신은 SK하이닉스 반도체 산업 위키를 관리하는 편집자입니다.

이미 발행된 위키 문서 두 개(문서 A, 문서 B)가 서로 중복(같은 사건·주제를 다뤄서 사실상
같은 내용)인지 판단하고, 맞다면 하나로 통합하십시오.

절대 규칙:
- claims에 없는 문장(document_version_id로 뒷받침되지 않는 주장)은 markdown에 쓰지 마십시오.
- 두 문서가 실제로는 다른 내용을 다룬다면(제목·근거가 일부 겹쳐도 실질적으로 별개
  주제·사건이면) 반드시 decision을 "not_duplicate"로 반환하고 markdown/claims를
  비우십시오. 의심스러우면 병합하지 말고 "not_duplicate"를 선택하십시오.
- 병합하기로 했다면 두 문서 중 더 대표성 있는(제목이 더 넓은 범위를 다루거나 본문이
  더 충실한) 쪽의 page_id를 representative_page_id로 반환하십시오. 반드시 두 문서
  중 하나의 page_id여야 합니다.
- markdown은 반드시 아래 섹션 순서를 따르십시오: 현재 상황 -> 수급 구조 -> 종합 판단
  -> 변경 이력 -> 관련 문서 -> 출처.
- "변경 이력" 섹션에는 두 문서의 기존 이력을 모두 보존하고, 이번 통합 사유를 한 줄
  추가하십시오. 기존 사실관계를 삭제하지 마십시오.
- claims는 문서 A 또는 문서 B의 근거 문서(document_version_id) 중에서만 인용하십시오.
  지어내지 마십시오.
- 마크다운 코드블록 없이 지정된 JSON 구조로만 응답하십시오.

JSON 출력 형식:
{
  "decision": "merge" | "not_duplicate",
  "representative_page_id": "병합 시 대표로 남길 페이지의 page_id",
  "markdown": "통합된 전체 본문(병합 시에만)",
  "change_summary": "변경 이력에 들어갈 한 줄(병합 시에만)",
  "claims": [{"document_version_id": "...", "claim_text": "...", "citation_order": 1}]
}"""


def _page_block(label: str, content: WikiPageContent) -> str:
    lines = [
        f"[{label}] page_id={content.page_id}",
        f"제목: {content.title}",
        f"유형: {content.page_type}",
        "본문:",
        content.markdown,
        "근거 문서:",
    ]
    if content.sources:
        for source in content.sources:
            lines.append(
                f"- document_version_id={source.document_version_id} "
                f"citation_order={source.citation_order}: {source.claim_text or ''}"
            )
    else:
        lines.append("없음")
    return "\n".join(lines)


def build_wiki_dedup_user_prompt(content_a: WikiPageContent, content_b: WikiPageContent) -> str:
    return "\n\n".join([_page_block("문서 A", content_a), _page_block("문서 B", content_b)])
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `python -m pytest tests/test_wiki_dedup_prompts.py -v`
Expected: 4 passed

- [ ] **Step 5: 커밋**

```bash
git add src/wiki/dedup_prompts.py tests/test_wiki_dedup_prompts.py
git commit -m "Feat: 위키 dedup LLM 프롬프트 추가"
```

---

### Task 6: `_judge_and_merge()` — 페어 하나 판단 + 병합 적용

**Files:**
- Create: `src/wiki/dedup.py`
- Test: `tests/test_wiki_dedup.py` (신규)

**Interfaces:**
- Consumes: `DedupCandidatePair`, `WikiDedupLLMResult`, `DedupResult` (Task 2), `WIKI_DEDUP_SYSTEM_PROMPT`/`build_wiki_dedup_user_prompt` (Task 5), `reparent_children` (Task 4), `WikiPageContent`/`WikiSourceInput`/`WikiDraftInput`/`create_wiki_version`/`record_wiki_validation`/`review_wiki_version`/`publish_wiki_version` (`src/wiki/interface.py`), `archive_wiki_page` (`src/wiki/generation_repository.py`), `create_json_completion`/`get_openrouter_settings`/`parse_json_response` (`src/analysis/classifier.py`)
- Produces: `_judge_and_merge(pair: DedupCandidatePair, content_a: WikiPageContent, content_b: WikiPageContent, *, workspace_id: str, requested_by: str | None = None, supabase=None, llm_client=None) -> DedupResult` — Task 7(`run_wiki_dedup_batch`)이 사용. `WikiDedupLLMClient = Callable[[str, str, str | None], str]` 타입도 이 파일에서 정의(`generation.py`의 `WikiTopicLLMClient`와 같은 패턴).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_wiki_dedup.py` — `generation.py`의 `llm_client` 주입 테스트 패턴(`test_generate_topic_page_uses_injected_llm_client` 등)과 동일하게, `create_json_completion`을 monkeypatch하거나 `llm_client`를 직접 주입한다:

```python
from __future__ import annotations

import json

from src.wiki import dedup
from src.wiki.dedup_models import DedupCandidatePair, DedupPageInfo
from src.wiki.interface import WikiPageContent, WikiSource

WORKSPACE_ID = "ws-1"


def _content(page_id, slug, title, page_type, markdown, sources, parent_page_id=None):
    return WikiPageContent(
        page_id=page_id, slug=slug, title=title, page_type=page_type, published_at=None,
        version_id=f"v-{page_id}", version_no=1, markdown=markdown, change_summary=None,
        confidence_score=None, validation_status="passed", review_status="approved",
        generated_by="llm", generator_model=None, created_at="2026-08-04T00:00:00Z",
        sources=tuple(sources), versions=(),
    )


def _pair(page_a_id="page-a", page_b_id="page-b", page_a_parent=None, page_b_parent=None):
    return DedupCandidatePair(
        page_a=DedupPageInfo(page_id=page_a_id, slug="a", title="제목 A", page_type="issue", parent_page_id=page_a_parent),
        page_b=DedupPageInfo(page_id=page_b_id, slug="b", title="제목 B", page_type="market", parent_page_id=page_b_parent),
        shared_source_count=1, title_similarity=0.9,
    )


def test_merge_creates_version_archives_other_and_reparents_children(monkeypatch):
    calls = []
    monkeypatch.setattr(
        dedup, "create_json_completion",
        lambda **kwargs: json.dumps({
            "decision": "merge",
            "representative_page_id": "page-b",
            "markdown": "# 통합 본문",
            "change_summary": "두 문서를 통합",
            "claims": [{"document_version_id": "doc-1", "claim_text": "근거", "citation_order": 1}],
        }),
    )
    monkeypatch.setattr(dedup, "create_wiki_version", lambda draft, **k: calls.append(("create", draft.slug, draft.page_type, draft.parent_page_id, [s.document_version_id for s in draft.sources])) or "version-new")
    monkeypatch.setattr(dedup, "record_wiki_validation", lambda *a, **k: calls.append(("validate", a)))
    monkeypatch.setattr(dedup, "review_wiki_version", lambda *a, **k: calls.append(("review", a)))
    monkeypatch.setattr(dedup, "publish_wiki_version", lambda *a, **k: calls.append(("publish", a)))
    monkeypatch.setattr(dedup, "archive_wiki_page", lambda page_id, **k: calls.append(("archive", page_id)))
    monkeypatch.setattr(dedup, "reparent_children", lambda old, new, **k: calls.append(("reparent", old, new)) or 0)

    pair = _pair(page_a_parent="page-parent")
    content_a = _content("page-a", "a", "제목 A", "issue", "# A", [
        WikiSource(document_version_id="doc-1", citation_order=1, claim_text="근거A", support_type="supports", source_start_line=None, source_end_line=None),
    ])
    content_b = _content("page-b", "b", "제목 B", "market", "# B", [])

    result = dedup._judge_and_merge(pair, content_a, content_b, workspace_id=WORKSPACE_ID, requested_by=None)

    assert result.decision == "merged"
    assert result.representative_page_id == "page-b"
    assert result.archived_page_id == "page-a"
    assert result.version_id == "version-new"
    create_call = next(c for c in calls if c[0] == "create")
    assert create_call[1:4] == ("b", "market", None)  # 대표(page-b)의 slug/page_type/parent_page_id 유지
    assert create_call[4] == ["doc-1"]
    assert ("publish", ("page-b", "version-new")) in calls
    assert ("archive", "page-a") in calls
    assert ("reparent", "page-a", "page-b") in calls


def test_not_duplicate_decision_does_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(
        dedup, "create_json_completion",
        lambda **kwargs: json.dumps({"decision": "not_duplicate", "claims": []}),
    )
    monkeypatch.setattr(dedup, "create_wiki_version", lambda draft, **k: calls.append(("create",)) or "should-not-run")
    monkeypatch.setattr(dedup, "archive_wiki_page", lambda page_id, **k: calls.append(("archive", page_id)))

    pair = _pair()
    content_a = _content("page-a", "a", "제목 A", "issue", "# A", [])
    content_b = _content("page-b", "b", "제목 B", "market", "# B", [])

    result = dedup._judge_and_merge(pair, content_a, content_b, workspace_id=WORKSPACE_ID, requested_by=None)

    assert result.decision == "not_duplicate"
    assert calls == []


def test_merge_skipped_when_representative_page_id_is_invalid(monkeypatch):
    """LLM이 두 후보 page_id 중 하나가 아닌 값을 반환하면(지어낸 값) 병합하지 않는다."""
    calls = []
    monkeypatch.setattr(
        dedup, "create_json_completion",
        lambda **kwargs: json.dumps({
            "decision": "merge", "representative_page_id": "page-not-in-pair",
            "markdown": "# 통합", "change_summary": "요약",
            "claims": [{"document_version_id": "doc-1", "claim_text": "근거", "citation_order": 1}],
        }),
    )
    monkeypatch.setattr(dedup, "create_wiki_version", lambda draft, **k: calls.append(("create",)) or "should-not-run")

    pair = _pair()
    content_a = _content("page-a", "a", "제목 A", "issue", "# A", [
        WikiSource(document_version_id="doc-1", citation_order=1, claim_text="근거", support_type="supports", source_start_line=None, source_end_line=None),
    ])
    content_b = _content("page-b", "b", "제목 B", "market", "# B", [])

    result = dedup._judge_and_merge(pair, content_a, content_b, workspace_id=WORKSPACE_ID, requested_by=None)

    assert result.decision == "not_duplicate"
    assert calls == []


def test_merge_skipped_when_no_valid_grounded_claims(monkeypatch):
    """claims가 두 문서 어느 근거에도 없는 document_version_id만 가리키면 병합하지 않는다."""
    calls = []
    monkeypatch.setattr(
        dedup, "create_json_completion",
        lambda **kwargs: json.dumps({
            "decision": "merge", "representative_page_id": "page-b",
            "markdown": "# 통합", "change_summary": "요약",
            "claims": [{"document_version_id": "doc-unknown", "claim_text": "근거", "citation_order": 1}],
        }),
    )
    monkeypatch.setattr(dedup, "create_wiki_version", lambda draft, **k: calls.append(("create",)) or "should-not-run")

    pair = _pair()
    content_a = _content("page-a", "a", "제목 A", "issue", "# A", [])
    content_b = _content("page-b", "b", "제목 B", "market", "# B", [])

    result = dedup._judge_and_merge(pair, content_a, content_b, workspace_id=WORKSPACE_ID, requested_by=None)

    assert result.decision == "not_duplicate"
    assert calls == []


def test_uses_injected_llm_client_instead_of_create_json_completion(monkeypatch):
    received = {}

    def fake_llm_client(system_prompt, user_prompt, model):
        received["system_prompt"] = system_prompt
        received["user_prompt"] = user_prompt
        return json.dumps({"decision": "not_duplicate", "claims": []})

    monkeypatch.setattr(
        dedup, "create_json_completion",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("llm_client가 있으면 이건 호출되면 안 됨")),
    )

    pair = _pair()
    content_a = _content("page-a", "a", "제목 A", "issue", "# A", [])
    content_b = _content("page-b", "b", "제목 B", "market", "# B", [])

    result = dedup._judge_and_merge(
        pair, content_a, content_b, workspace_id=WORKSPACE_ID, requested_by=None, llm_client=fake_llm_client,
    )

    assert result.decision == "not_duplicate"
    assert "문서 A" in received["user_prompt"]
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `python -m pytest tests/test_wiki_dedup.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.wiki.dedup'`

- [ ] **Step 3: `src/wiki/dedup.py` 작성 (Task 7의 `run_wiki_dedup_batch`는 다음 태스크에서 같은 파일에 추가)**

```python
from __future__ import annotations

import logging
from collections.abc import Callable

from supabase import Client

from ..analysis.classifier import create_json_completion, get_openrouter_settings, parse_json_response
from .dedup_models import DedupCandidatePair, DedupResult, WikiDedupLLMResult
from .dedup_prompts import WIKI_DEDUP_SYSTEM_PROMPT, build_wiki_dedup_user_prompt
from .dedup_repository import reparent_children
from .generation_repository import archive_wiki_page
from .interface import (
    WikiDraftInput,
    WikiPageContent,
    WikiSourceInput,
    create_wiki_version,
    publish_wiki_version,
    record_wiki_validation,
    review_wiki_version,
)

logger = logging.getLogger(__name__)

# (system_prompt, user_prompt, model) -> raw JSON 문자열. generation.py의
# WikiTopicLLMClient와 같은 형태의 호출 가능 객체다.
WikiDedupLLMClient = Callable[[str, str, str | None], str]


def _judge_and_merge(
    pair: DedupCandidatePair,
    content_a: WikiPageContent,
    content_b: WikiPageContent,
    *,
    workspace_id: str,
    requested_by: str | None = None,
    supabase: Client | None = None,
    llm_client: WikiDedupLLMClient | None = None,
) -> DedupResult:
    settings = get_openrouter_settings()
    user_prompt = build_wiki_dedup_user_prompt(content_a, content_b)

    if llm_client is not None:
        response_text = llm_client(WIKI_DEDUP_SYSTEM_PROMPT, user_prompt, settings.model)
    else:
        response_text = create_json_completion(
            system_prompt=WIKI_DEDUP_SYSTEM_PROMPT, user_prompt=user_prompt, model=settings.model,
        )
    payload = parse_json_response(response_text)
    result = WikiDedupLLMResult.model_validate(payload)

    not_duplicate = DedupResult(
        page_a_id=pair.page_a.page_id, page_b_id=pair.page_b.page_id, decision="not_duplicate",
    )

    if result.decision != "merge":
        return not_duplicate

    candidates_by_id = {content_a.page_id: (pair.page_a, content_a), content_b.page_id: (pair.page_b, content_b)}
    if result.representative_page_id not in candidates_by_id:
        return not_duplicate

    representative_info, _ = candidates_by_id[result.representative_page_id]
    other_page_id = pair.page_b.page_id if representative_info.page_id == pair.page_a.page_id else pair.page_a.page_id
    other_info, _ = candidates_by_id[other_page_id]

    allowed_document_version_ids = {s.document_version_id for s in content_a.sources} | {
        s.document_version_id for s in content_b.sources
    }
    valid_claims = [c for c in result.claims if c.document_version_id in allowed_document_version_ids]

    if not valid_claims or not (result.markdown or "").strip():
        return not_duplicate

    sources = [
        WikiSourceInput(
            document_version_id=claim.document_version_id,
            claim_text=claim.claim_text,
            citation_order=claim.citation_order,
        )
        for claim in valid_claims
    ]

    draft = WikiDraftInput(
        workspace_id=workspace_id,
        slug=representative_info.slug,
        title=representative_info.title,
        page_type=representative_info.page_type,
        parent_page_id=representative_info.parent_page_id,
        markdown=result.markdown or "",
        sources=sources,
        change_summary=result.change_summary,
        created_by=requested_by,
        generated_by="llm",
    )
    version_id = create_wiki_version(draft, supabase=supabase)
    record_wiki_validation(version_id, "passed", None, supabase=supabase)
    review_wiki_version(version_id, None, "approved", supabase=supabase)
    publish_wiki_version(representative_info.page_id, version_id, supabase=supabase)
    archive_wiki_page(other_info.page_id, supabase=supabase)
    reparent_children(other_info.page_id, representative_info.page_id, workspace_id=workspace_id, supabase=supabase)

    return DedupResult(
        page_a_id=pair.page_a.page_id,
        page_b_id=pair.page_b.page_id,
        decision="merged",
        representative_page_id=representative_info.page_id,
        archived_page_id=other_info.page_id,
        version_id=version_id,
    )
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `python -m pytest tests/test_wiki_dedup.py -v`
Expected: 5 passed

- [ ] **Step 5: 커밋**

```bash
git add src/wiki/dedup.py tests/test_wiki_dedup.py
git commit -m "Feat: 위키 dedup 페어 판단+병합 적용(_judge_and_merge) 구현"
```

---

### Task 7: `run_wiki_dedup_batch()` — 전체 오케스트레이션

**Files:**
- Modify: `src/wiki/dedup.py` (Task 6 파일에 추가)
- Test: `tests/test_wiki_dedup.py` (Task 6 파일에 테스트 추가)

**Interfaces:**
- Consumes: `find_duplicate_candidate_pairs` (Task 3), `get_published_wiki_page` (`src/wiki/query.py`, 이미 존재), `_judge_and_merge` (Task 6)
- Produces: `run_wiki_dedup_batch(workspace_id: str, *, max_pairs: int = 20, requested_by: str | None = None, supabase=None, llm_client=None) -> list[DedupResult]` — Task 8(`scripts/dedup_wiki_scheduled.py`)이 사용.

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/test_wiki_dedup.py` 맨 아래에 추가:

```python
def test_run_wiki_dedup_batch_processes_each_candidate_pair(monkeypatch):
    pair1 = _pair(page_a_id="page-1a", page_b_id="page-1b")
    pair2 = _pair(page_a_id="page-2a", page_b_id="page-2b")
    monkeypatch.setattr(dedup, "find_duplicate_candidate_pairs", lambda workspace_id, **k: [pair1, pair2])

    contents = {
        "a1": _content("page-1a", "a1", "제목", "issue", "# A", []),
        "b1": _content("page-1b", "b1", "제목", "market", "# B", []),
        "a2": _content("page-2a", "a2", "제목", "issue", "# A", []),
        "b2": _content("page-2b", "b2", "제목", "market", "# B", []),
    }
    slug_by_page_id = {"page-1a": "a1", "page-1b": "b1", "page-2a": "a2", "page-2b": "b2"}
    monkeypatch.setattr(
        dedup, "get_published_wiki_page",
        lambda workspace_id, slug: next((c for key, c in contents.items() if c.slug == slug), None),
    )

    judged_pairs = []
    monkeypatch.setattr(
        dedup, "_judge_and_merge",
        lambda pair, content_a, content_b, **k: judged_pairs.append((pair.page_a.page_id, pair.page_b.page_id))
        or DedupResult(page_a_id=pair.page_a.page_id, page_b_id=pair.page_b.page_id, decision="not_duplicate"),
    )

    results = dedup.run_wiki_dedup_batch(WORKSPACE_ID)

    assert len(results) == 2
    assert ("page-1a", "page-1b") in judged_pairs
    assert ("page-2a", "page-2b") in judged_pairs


def test_run_wiki_dedup_batch_skips_pair_when_a_page_already_archived(monkeypatch):
    """이번 배치에서 앞선 페어 처리로 이미 아카이빙된 페이지는 get_published_wiki_page가
    None을 반환하므로(status='published' 필터), 뒤 페어는 건너뛴다."""
    pair = _pair()
    monkeypatch.setattr(dedup, "find_duplicate_candidate_pairs", lambda workspace_id, **k: [pair])
    monkeypatch.setattr(dedup, "get_published_wiki_page", lambda workspace_id, slug: None)

    judge_calls = []
    monkeypatch.setattr(dedup, "_judge_and_merge", lambda *a, **k: judge_calls.append(1))

    results = dedup.run_wiki_dedup_batch(WORKSPACE_ID)

    assert results == []
    assert judge_calls == []


def test_run_wiki_dedup_batch_isolates_pair_failures(monkeypatch):
    """한 페어 처리 중 예외가 나도 다른 페어 처리를 막지 않는다."""
    pair1 = _pair(page_a_id="page-1a", page_b_id="page-1b")
    pair2 = _pair(page_a_id="page-2a", page_b_id="page-2b")
    monkeypatch.setattr(dedup, "find_duplicate_candidate_pairs", lambda workspace_id, **k: [pair1, pair2])
    monkeypatch.setattr(
        dedup, "get_published_wiki_page",
        lambda workspace_id, slug: _content(slug, slug, "제목", "issue", "# 본문", []),
    )

    def fake_judge(pair, content_a, content_b, **k):
        if pair.page_a.page_id == "page-1a":
            raise RuntimeError("boom")
        return DedupResult(page_a_id=pair.page_a.page_id, page_b_id=pair.page_b.page_id, decision="not_duplicate")

    monkeypatch.setattr(dedup, "_judge_and_merge", fake_judge)

    results = dedup.run_wiki_dedup_batch(WORKSPACE_ID)

    assert len(results) == 2
    failed = next(r for r in results if r.page_a_id == "page-1a")
    assert failed.decision == "failed"
    assert "boom" in failed.error_message
    succeeded = next(r for r in results if r.page_a_id == "page-2a")
    assert succeeded.decision == "not_duplicate"
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `python -m pytest tests/test_wiki_dedup.py -k run_wiki_dedup_batch -v`
Expected: FAIL — `AttributeError: module 'src.wiki.dedup' has no attribute 'run_wiki_dedup_batch'`

- [ ] **Step 3: `run_wiki_dedup_batch()` 추가**

`src/wiki/dedup.py`에 import 한 줄 추가(`from .dedup_repository import reparent_children` 바로 위 또는 아래):

```python
from .dedup_repository import find_duplicate_candidate_pairs, reparent_children
from .query import get_published_wiki_page
```

파일 맨 아래에 추가:

```python
def run_wiki_dedup_batch(
    workspace_id: str,
    *,
    max_pairs: int = 20,
    requested_by: str | None = None,
    supabase: Client | None = None,
    llm_client: WikiDedupLLMClient | None = None,
) -> list[DedupResult]:
    """중복 후보를 찾아 페어마다 LLM 판단+병합을 시도한다.

    한 배치 안에서 앞선 페어 처리로 이미 아카이빙된 페이지는 get_published_wiki_page가
    None을 반환하므로 자연스럽게 건너뛴다(다시 조회하지 않아도 최신 상태 반영).
    """
    pairs = find_duplicate_candidate_pairs(workspace_id, max_pairs=max_pairs, supabase=supabase)
    results: list[DedupResult] = []

    for pair in pairs:
        content_a = get_published_wiki_page(workspace_id, pair.page_a.slug)
        content_b = get_published_wiki_page(workspace_id, pair.page_b.slug)
        if content_a is None or content_b is None:
            continue

        try:
            result = _judge_and_merge(
                pair, content_a, content_b,
                workspace_id=workspace_id, requested_by=requested_by,
                supabase=supabase, llm_client=llm_client,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "wiki_dedup_pair_failed",
                extra={"page_a": pair.page_a.slug, "page_b": pair.page_b.slug},
            )
            result = DedupResult(
                page_a_id=pair.page_a.page_id, page_b_id=pair.page_b.page_id,
                decision="failed", error_message=str(exc),
            )
        results.append(result)

    return results
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `python -m pytest tests/test_wiki_dedup.py -v`
Expected: 8 passed

- [ ] **Step 5: 전체 wiki 테스트 회귀 확인**

Run: `python -m pytest tests/test_wiki_dedup.py tests/test_wiki_dedup_repository.py tests/test_wiki_dedup_prompts.py tests/test_wiki_text_similarity.py tests/test_wiki_generation.py tests/test_wiki_query_related_pages.py -v`
Expected: 전부 passed, 실패 없음

- [ ] **Step 6: 커밋**

```bash
git add src/wiki/dedup.py tests/test_wiki_dedup.py
git commit -m "Feat: 위키 dedup 배치 오케스트레이션(run_wiki_dedup_batch) 구현"
```

---

### Task 8: `scripts/dedup_wiki_scheduled.py` — 실행 스크립트

**Files:**
- Create: `scripts/dedup_wiki_scheduled.py`
- Test: 없음(스크립트, 수동/워크플로우로 실행) — `python -m py_compile`로 문법만 확인

**Interfaces:**
- Consumes: `run_wiki_dedup_batch` (Task 7), `get_workspace_id`/로그 패턴 (`scripts/refresh_wiki_scheduled.py`와 동일 관례)

- [ ] **Step 1: 스크립트 작성**

```python
"""위키 중복 정리(dedup) 배치 — 이미 발행된 중복 위키 페이지를 LLM이 찾아 병합한다.

scripts/refresh_wiki_scheduled.py와 달리 사용자 설정 주기가 없다 — GitHub Actions
cron이 매일 1회 도는 것 자체가 실행 주기다(급하지 않은 정리 작업이라 발행 배치의
30분 주기보다 훨씬 느슨하게 잡는다).

사용법:
    python scripts/dedup_wiki_scheduled.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.pipeline_common.db import get_client
from src.wiki.dedup import run_wiki_dedup_batch
from src.wiki.dedup_models import DedupResult


def log(msg: str) -> None:
    print(f"[dedup_wiki_scheduled] {msg}", flush=True)


def get_workspace_id() -> str:
    rows = get_client().table("workspaces").select("id, name").limit(2).execute().data
    if len(rows) != 1:
        raise SystemExit(f"workspace_id를 자동으로 하나로 못 정했다 (workspaces 행 {len(rows)}개).")
    return str(rows[0]["id"])


def report_results(results: list[DedupResult]) -> int:
    merged = [r for r in results if r.decision == "merged"]
    not_duplicate = [r for r in results if r.decision == "not_duplicate"]
    failed = [r for r in results if r.decision == "failed"]
    log(f"{len(results)}개 후보 처리: 병합 {len(merged)}건, 중복 아님 {len(not_duplicate)}건, 실패 {len(failed)}건")
    for r in merged:
        log(f"  - 병합: {r.page_a_id} + {r.page_b_id} -> 대표 {r.representative_page_id} (아카이빙: {r.archived_page_id})")
    for r in failed:
        log(f"  - 실패: {r.page_a_id} + {r.page_b_id}: {r.error_message}")
    if results and len(failed) == len(results):
        return 1
    return 0


if __name__ == "__main__":
    workspace_id = get_workspace_id()
    log("중복 위키 탐지·정리 시작")
    results = run_wiki_dedup_batch(workspace_id)
    exit_code = report_results(results)
    if exit_code != 0:
        raise SystemExit(exit_code)
```

- [ ] **Step 2: 문법 확인**

Run: `python -m py_compile scripts/dedup_wiki_scheduled.py`
Expected: 에러 없음(출력 없음)

- [ ] **Step 3: 커밋**

```bash
git add scripts/dedup_wiki_scheduled.py
git commit -m "Feat: 위키 dedup 배치 실행 스크립트 추가"
```

---

### Task 9: GitHub Actions 워크플로우

**Files:**
- Create: `.github/workflows/wiki-dedup-batch.yml`

**Interfaces:**
- Consumes: `scripts/dedup_wiki_scheduled.py` (Task 8)

- [ ] **Step 1: 워크플로우 작성**

`.github/workflows/wiki-refresh-gate.yml`과 동일한 패턴, cron만 매일 1회(한국시간 새벽
3시 = UTC 18시)로 변경:

```yaml
name: Wiki Dedup Batch

on:
  schedule:
    - cron: "0 18 * * *" # 매일 1회(한국시간 새벽 3시) — 급하지 않은 정리 작업
  workflow_dispatch: {}

jobs:
  dedup:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run wiki dedup batch
        run: python scripts/dedup_wiki_scheduled.py
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SECRET_KEY }}
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
```

- [ ] **Step 2: YAML 문법 확인**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/wiki-dedup-batch.yml', encoding='utf-8'))"`
Expected: 에러 없음

- [ ] **Step 3: 커밋**

```bash
git add .github/workflows/wiki-dedup-batch.yml
git commit -m "Feat: 위키 dedup 배치 GitHub Actions cron 등록(매일 1회)"
```

---

### Task 10: 전체 회귀 테스트 + 실제 프로덕션 데이터로 라이브 드라이런 검증

**Files:** 없음(검증 전용 태스크)

**Interfaces:** 없음

- [ ] **Step 1: 전체 백엔드 테스트 스위트 실행**

Run: `python -m pytest tests/ -q`
Expected: 이번 변경으로 추가된 테스트는 전부 통과. 기존에 확인된 7개 pre-existing/환경 전용
실패(`test_missing_api_key_*`, `tests/pipeline/test_pending_documents.py`)만 남고 새 실패 없음.

- [ ] **Step 2: 실제 프로덕션에서 발견한 중복 쌍으로 후보 탐지가 정확히 잡는지 확인(읽기 전용, 병합 실행 안 함)**

VM(hermes-server)에 `src/wiki/text_similarity.py`, `dedup_models.py`, `dedup_repository.py`,
`dedup_prompts.py`, `dedup.py`를 scp한 뒤:

```bash
ssh hermes-server "cd ~/projects/myWiki && /tmp/mywiki_venv/bin/python -c \"
from dotenv import load_dotenv
load_dotenv()
from src.wiki.dedup_repository import find_duplicate_candidate_pairs
pairs = find_duplicate_candidate_pairs('98359399-ae4d-4c5c-beb1-8a47dc6cf6fe', max_pairs=50)
for p in pairs:
    print(p.page_a.slug, '<->', p.page_b.slug, 'shared=', p.shared_source_count, 'title_sim=', round(p.title_similarity, 2))
\""
```

Expected: 이전 세션에서 SQL로 직접 확인했던 실제 중복 쌍
(`sk_hynix_moody_a3_upgrade_and_midterm_market_opportunities` ↔ `heuristic:시장·경영:945a469aeada9cb3`,
`china_semiconductor_design_protection_regulation` ↔ `..._2026` 등)이 출력에 나타나는지 확인.

- [ ] **Step 3: 실제 후보 하나로 LLM 판단까지 드라이런(병합은 실제로 실행됨 — 운영 데이터이므로
      실행 전 사용자에게 결과를 보여주고 진행 여부 확인)**

VM에서 `run_wiki_dedup_batch(workspace_id, max_pairs=1)`을 실행해 정말 `sk_hynix_moody_a3...`
쌍이 병합되는지, 병합 후 "연결된 문서" API가 더 이상 이 쌍을 관련 문서로 보여주지 않는지
(양쪽 다 published가 아니게 되므로) 확인한다.

- [ ] **Step 4: PR 생성**

```bash
git push -u origin feat/wiki-dedup-batch
gh pr create --base develop --title "Feat: 위키 중복 정리(Dedup) 배치 추가" --body "$(cat <<'EOF'
## 작업 내용
- text_similarity.py로 제목 유사도 로직 공용화(PR #59와 공유)
- 공유 근거 문서 OR 제목 유사도로 중복 후보 탐지(find_duplicate_candidate_pairs)
- LLM이 진짜 중복인지 판단하고, 맞으면 하나로 통합 + 다른 하나는 아카이빙(삭제 아님)
- 아카이빙되는 페이지의 자식 페이지 재부모연결(reparent_children)
- GitHub Actions cron으로 매일 1회 자동 실행

## 변경 이유
프로덕션에 이미 쌓인 중복 위키 페이지(토픽-이슈, 이슈-이슈)를 사용자가 발견 —
설계 문서: docs/superpowers/specs/2026-08-04-wiki-dedup-batch-design.md

## 테스트 결과
[여기에 Step 1~3 결과 채우기]

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review 체크리스트 (구현 시작 전 확인)

- [ ] 스펙의 "아키텍처" 섹션 → Task 1, 3, 6, 7, 8, 9로 커버됨
- [ ] 스펙의 "후보 탐지" 섹션 → Task 3으로 커버됨
- [ ] 스펙의 "LLM 판단 + 병합" 섹션 → Task 5, 6으로 커버됨
- [ ] 스펙의 "안전장치"(삭제 없음/재부모연결/비용 제어) → Task 4(재부모연결), Task 3(max_pairs 로그), Task 6(archive만 사용)로 커버됨
- [ ] 스펙의 "실행 방식"(cron) → Task 8, 9로 커버됨
- [ ] 스펙의 "테스트 계획" → 각 Task의 테스트로 커버됨

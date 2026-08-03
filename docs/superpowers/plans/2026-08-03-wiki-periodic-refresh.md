# 위키 주기 갱신(2시간) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 리포트 파이프라인과 별개로, 최근 2시간 내 분석 완료된 문서를 근거로 위키 이슈/주제 페이지만 주기적으로 갱신하는 배치를 추가한다.

**Architecture:** 기존 리포트 파이프라인의 candidate 선별→그룹핑→wiki_context 보강→섹션 작성 단계(`select_report_candidates`/`group_report_candidates`/`enrich_issue_groups`/`compose_report_sections`)를 그대로 재사용하되, candidate 조회만 "최근 분석 완료" 기준으로 바꾸고 report 저장 단계(`save_report_sections`/`create_and_save_markdown_artifact`/`mark_report_completed`)는 생략한다. `report/interface.py`는 수정하지 않는다.

**Tech Stack:** Python 3.12, Pydantic v2, Supabase Python client, pytest.

## Global Constraints

- `src/report/interface.py`는 수정하지 않는다 — 새 오케스트레이션은 `src/wiki/generation.py`(이 파트 소유 파일)에 둔다.
- report 저장 3종(`save_report_sections`/`create_and_save_markdown_artifact`/`mark_report_completed`/`create_report_version`)은 호출하지 않는다 — `reports`/`report_sections`에 흔적을 남기지 않는다.
- candidate 조회~섹션 작성 단계 실패는 예외를 그대로 전파한다(리포트처럼 감싸서 "failed" 상태로 기록하지 않음 — 외부 스케줄러가 다음 주기에 재시도).
- 이슈 단위 실패 격리는 이미 `generate_wiki_drafts_for_sections` 내부에 있으므로 재구현하지 않는다.
- 기존 프로젝트 컨벤션을 따른다: `from __future__ import annotations`, `*`-only 키워드 인자, `Client | None = None` 테스트 주입 지점.

---

## File Structure

```
src/report/
└── candidate_provider.py   # 수정 — get_recently_analyzed_candidates 추가 (기존 함수는 안 건드림)

src/wiki/
└── generation.py           # 수정 — refresh_wiki_from_recent_analysis 추가

scripts/
└── refresh_wiki.py         # 신규 — refresh_wiki_from_recent_analysis() CLI 진입점

tests/
├── test_report_candidate_provider.py   # 신규 — get_recently_analyzed_candidates 테스트
└── test_wiki_generation.py             # 기존 파일에 refresh_wiki_from_recent_analysis 테스트 추가
```

---

### Task 1: `get_recently_analyzed_candidates` — 최근 분석 완료 문서 조회

**Files:**
- Modify: `src/report/candidate_provider.py` (파일 끝에 함수 추가)
- Test: `tests/test_report_candidate_provider.py` (신규)

**Interfaces:**
- Consumes: 기존 `to_report_candidate(*, result, document_id)`, `build_report_candidates(candidates)`, `_row_is_report_candidate_ready(row)`(모두 `candidate_provider.py`에 이미 있음), `_select_analysis_row_for_ranking`(`analysis.repository`에 이미 있음), `AnalysisResultForReport`(`analysis.importance_models`에 이미 있음)
- Produces: `get_recently_analyzed_candidates(*, workspace_id: str, since: datetime, supabase: Client | None = None) -> list[ReportCandidate]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report_candidate_provider.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.report.candidate_provider import get_recently_analyzed_candidates


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, supabase, name):
        self.rows = supabase.tables.get(name, [])
        self.filters = []
        self.gte_filters = []
        self.in_filters = []

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def gte(self, field, value):
        self.gte_filters.append((field, value))
        return self

    def in_(self, field, values):
        self.in_filters.append((field, set(values)))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def execute(self):
        rows = self.rows
        for field, value in self.filters:
            rows = [row for row in rows if row.get(field) == value]
        for field, value in self.gte_filters:
            rows = [row for row in rows if (row.get(field) or "") >= value]
        for field, values in self.in_filters:
            rows = [row for row in rows if row.get(field) in values]
        return FakeResult([dict(row) for row in rows])


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return FakeTable(self, name)


def _completed_analysis_row(*, document_version_id: str, importance_evaluated_at: str, ranking_score: str = "80.00") -> dict:
    return {
        "id": f"analysis-{document_version_id}",
        "workspace_id": "ws-1",
        "document_version_id": document_version_id,
        "status": "completed",
        "reliability_status": "completed",
        "importance_status": "completed",
        "ranking_status": "completed",
        "ranking_score": ranking_score,
        "reliability_score": 80,
        "importance_score": 85,
        "importance_evaluated_at": importance_evaluated_at,
        "reliability_evaluated_at": importance_evaluated_at,
        "classified_at": importance_evaluated_at,
        "primary_category": "제품·기술",
        "secondary_categories": [],
        "core_summary": "요약",
        "impact_direction": "중립",
        "time_horizon": "단기",
    }


def _tables_for(analysis_rows: list[dict]) -> dict:
    document_version_ids = [row["document_version_id"] for row in analysis_rows]
    return {
        "document_analysis_results": analysis_rows,
        "document_versions": [
            {"id": dvid, "document_id": f"doc-{dvid}"} for dvid in document_version_ids
        ],
        "documents": [
            {"id": f"doc-{dvid}", "title": f"제목-{dvid}", "canonical_url": None, "published_at": None, "source_id": None}
            for dvid in document_version_ids
        ],
        "sources": [],
    }


def test_get_recently_analyzed_candidates_excludes_rows_before_since():
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(hours=1)).isoformat()
    old = (now - timedelta(hours=5)).isoformat()
    analysis_rows = [
        _completed_analysis_row(document_version_id="dv-recent", importance_evaluated_at=recent),
        _completed_analysis_row(document_version_id="dv-old", importance_evaluated_at=old),
    ]
    supabase = FakeSupabase(_tables_for(analysis_rows))

    candidates = get_recently_analyzed_candidates(
        workspace_id="ws-1", since=now - timedelta(hours=2), supabase=supabase,
    )

    assert [c.document_version_id for c in candidates] == ["dv-recent"]


def test_get_recently_analyzed_candidates_excludes_incomplete_status():
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(hours=1)).isoformat()
    incomplete_row = _completed_analysis_row(document_version_id="dv-incomplete", importance_evaluated_at=recent)
    incomplete_row["ranking_status"] = "pending"
    incomplete_row["ranking_score"] = None
    analysis_rows = [incomplete_row]
    supabase = FakeSupabase(_tables_for(analysis_rows))

    candidates = get_recently_analyzed_candidates(
        workspace_id="ws-1", since=now - timedelta(hours=2), supabase=supabase,
    )

    assert candidates == []


def test_get_recently_analyzed_candidates_returns_empty_when_no_rows():
    supabase = FakeSupabase({"document_analysis_results": []})
    candidates = get_recently_analyzed_candidates(
        workspace_id="ws-1", since=datetime.now(timezone.utc) - timedelta(hours=2), supabase=supabase,
    )
    assert candidates == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_report_candidate_provider.py -v`
Expected: FAIL with `ImportError: cannot import name 'get_recently_analyzed_candidates'`

- [ ] **Step 3: Write minimal implementation**

`src/report/candidate_provider.py` 파일 끝에 추가:

```python
def get_recently_analyzed_candidates(
    *,
    workspace_id: str,
    since: datetime,
    supabase: Client | None = None,
) -> list[ReportCandidate]:
    """report_date 하루 단위가 아니라 '최근 since 이후 분석 완료된 것' 기준으로
    candidate를 가져온다 — 2시간 주기 위키 갱신 배치 전용."""
    db = supabase or get_supabase()
    analysis_rows = (
        db.table(DOCUMENT_ANALYSIS_RESULTS_TABLE)
        .select("*")
        .eq("workspace_id", workspace_id)
        .eq("status", "completed")
        .eq("reliability_status", "completed")
        .eq("importance_status", "completed")
        .eq("ranking_status", "completed")
        .gte("importance_evaluated_at", since.isoformat())
        .order("importance_evaluated_at", desc=True)
        .execute()
        .data
    )
    if not analysis_rows:
        return []

    document_version_ids = list({row["document_version_id"] for row in analysis_rows if row.get("document_version_id")})
    version_rows = (
        db.table("document_versions")
        .select("id, document_id")
        .in_("id", document_version_ids)
        .execute()
        .data
    )
    if not version_rows:
        return []
    version_to_document = {row["id"]: row["document_id"] for row in version_rows}

    document_ids = list(set(version_to_document.values()))
    document_rows = (
        db.table("documents")
        .select("id, title, canonical_url, published_at, source_id")
        .in_("id", document_ids)
        .execute()
        .data
    )
    documents_by_id = {row["id"]: row for row in document_rows}

    source_ids = [row.get("source_id") for row in document_rows if row.get("source_id")]
    source_rows = (
        db.table("sources")
        .select("id, name")
        .in_("id", list(set(source_ids)) or [""])
        .execute()
        .data
    ) if source_ids else []
    sources_by_id = {row["id"]: row for row in source_rows}

    rows_by_document_version: dict[str, list[dict[str, Any]]] = {}
    for row in analysis_rows:
        document_version_id = row.get("document_version_id")
        if not document_version_id:
            continue
        rows_by_document_version.setdefault(document_version_id, []).append(row)

    selected_results: list[tuple[AnalysisResultForReport, str]] = []
    for document_version_id in document_version_ids:
        document_id = version_to_document.get(document_version_id)
        document = documents_by_id.get(document_id) if document_id else None
        if document_id is None or document is None:
            continue

        ready_rows = [
            row
            for row in rows_by_document_version.get(document_version_id, [])
            if _row_is_report_candidate_ready(row)
        ]
        selected_row = _select_analysis_row_for_ranking(
            rows=ready_rows,
            workspace_id=workspace_id,
            document_version_id=document_version_id,
        )
        if selected_row is None:
            continue

        source = sources_by_id.get(document.get("source_id"), {}) if document.get("source_id") else {}
        payload = dict(selected_row)
        payload["analysis_result_id"] = payload.get("id")
        payload["title"] = document.get("title") or ""
        payload["canonical_url"] = document.get("canonical_url")
        payload["published_at"] = document.get("published_at")
        payload["source_name"] = source.get("name")
        selected_results.append((AnalysisResultForReport.model_validate(payload), document_id))

    candidates = [
        to_report_candidate(result=result, document_id=document_id)
        for result, document_id in selected_results
    ]
    return build_report_candidates(candidates)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_report_candidate_provider.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/report/candidate_provider.py tests/test_report_candidate_provider.py
git commit -m "Feat: 최근 분석 완료 문서 기준 candidate 조회 함수 추가"
```

---

### Task 2: `refresh_wiki_from_recent_analysis` — 오케스트레이션

**Files:**
- Modify: `src/wiki/generation.py` (파일 끝에 함수 추가)
- Modify: `tests/test_wiki_generation.py` (테스트 추가)

**Interfaces:**
- Consumes: `get_recently_analyzed_candidates`(Task 1), `select_report_candidates`(`report/selector.py`, 이미 존재), `group_report_candidates`(`report/grouper.py`), `enrich_issue_groups`(`report/wiki_context.py`), `compose_report_sections`(`report/composer.py`), `search_wiki_contexts`(`wiki/interface.py`), `ReportGenerationConfig`(확인 완료 — `src/report/interface.py:58`에 정의됨. **import만 하고 파일은 수정하지 않는다** — Global Constraints의 "수정 금지"는 import 금지가 아니다), `generate_wiki_drafts_for_sections`(Task 7, 이미 `generation.py`에 있음)
- Produces: `refresh_wiki_from_recent_analysis(workspace_id: str, *, since_hours: int = 2, requested_by: str | None = None, supabase: Client | None = None) -> list[WikiDraftGenerationResult]`

- [ ] **Step 1: Write the failing test**

`tests/test_wiki_generation.py` 파일 최상단 import 블록(`from __future__ import annotations` 바로 아래, `import json` 위나 아래)에 `from decimal import Decimal`을 추가해라 — 현재 이 파일에 `Decimal`이 import돼 있지 않다(`ReportCandidate.ranking_score`가 `Decimal | None` 타입이라 필요).

```python
# tests/test_wiki_generation.py 에 이어서 추가
from datetime import datetime, timedelta, timezone


def test_refresh_wiki_from_recent_analysis_runs_pipeline_and_skips_report_persistence(monkeypatch):
    calls = []

    candidate = ReportCandidate(
        analysis_result_id="analysis-1",
        workspace_id="ws-1",
        document_id="doc-1",
        document_version_id="doc-ver-1",
        category=Category.PRODUCT_TECHNOLOGY,
        title="HBM4 공급 부족 심화",
        reliability_score=80,
        importance_score=85,
        ranking_score=Decimal("90"),
    )
    issue_group = IssueGroup(issue_key="issue-1", category=Category.PRODUCT_TECHNOLOGY, candidates=[candidate])
    enriched_group = EnrichedIssueGroup(issue_group=issue_group, wiki_contexts=[])
    section = _section("issue-1")

    monkeypatch.setattr(generation, "get_recently_analyzed_candidates", lambda *, workspace_id, since, supabase=None: calls.append(("candidates", workspace_id, since)) or [candidate])
    monkeypatch.setattr(generation, "select_report_candidates", lambda candidates, **kwargs: calls.append(("select", len(candidates))) or candidates)
    monkeypatch.setattr(generation, "group_report_candidates", lambda candidates, **kwargs: calls.append(("group", len(candidates))) or [issue_group])
    monkeypatch.setattr(generation, "enrich_issue_groups", lambda groups, **kwargs: calls.append(("enrich", len(groups))) or [enriched_group])
    monkeypatch.setattr(generation, "compose_report_sections", lambda groups, **kwargs: calls.append(("compose", len(groups))) or [section])
    monkeypatch.setattr(generation, "generate_wiki_drafts_for_sections", lambda sections, groups, **kwargs: calls.append(("wiki", len(sections), kwargs.get("workspace_id"))) or [])

    result = generation.refresh_wiki_from_recent_analysis("ws-1", since_hours=2)

    assert result == []
    call_names = [c[0] for c in calls]
    assert call_names == ["candidates", "select", "group", "enrich", "compose", "wiki"]
    assert calls[0][1] == "ws-1"
    assert calls[5][2] == "ws-1"


def test_refresh_wiki_from_recent_analysis_stops_early_when_no_candidates(monkeypatch):
    calls = []
    monkeypatch.setattr(generation, "get_recently_analyzed_candidates", lambda **kwargs: [])
    monkeypatch.setattr(generation, "select_report_candidates", lambda *a, **k: calls.append("select") or [])
    monkeypatch.setattr(generation, "group_report_candidates", lambda *a, **k: calls.append("group") or [])
    monkeypatch.setattr(generation, "enrich_issue_groups", lambda *a, **k: calls.append("enrich") or [])
    monkeypatch.setattr(generation, "compose_report_sections", lambda *a, **k: calls.append("compose") or [])
    monkeypatch.setattr(generation, "generate_wiki_drafts_for_sections", lambda *a, **k: calls.append("wiki") or [])

    result = generation.refresh_wiki_from_recent_analysis("ws-1")

    assert result == []
    # 후보가 없어도 나머지 단계는 그대로 빈 리스트를 흘려보낸다(에러 없이).
    assert calls == ["select", "group", "enrich", "compose", "wiki"]
```

`_section`, `ReportCandidate`, `IssueGroup`, `EnrichedIssueGroup`, `Category`, `Decimal`는 이미 `tests/test_wiki_generation.py` 상단에 import돼 있다(Task 7에서 추가됨) — 없으면 파일 상단 import를 확인해서 추가해라.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wiki_generation.py -v -k refresh_wiki_from_recent_analysis`
Expected: FAIL with `AttributeError: module 'src.wiki.generation' has no attribute 'refresh_wiki_from_recent_analysis'`

- [ ] **Step 3: Write minimal implementation**

`src/wiki/generation.py` 최상단에 `from __future__ import annotations`와 `import logging` 사이(또는 바로 아래)에 추가(현재 이 파일에 `datetime` import가 전혀 없다):

```python
from datetime import datetime, timedelta, timezone
```

import 블록에 추가로 다음도 넣어라:

```python
from ..report.candidate_provider import get_recently_analyzed_candidates
from ..report.composer import compose_report_sections
from ..report.grouper import group_report_candidates
from ..report.interface import ReportGenerationConfig  # import만, report/interface.py 파일 자체는 수정 안 함
from ..report.selector import select_report_candidates
from ..report.wiki_context import enrich_issue_groups
from .interface import search_wiki_contexts
```

파일 끝에 추가:

```python
def refresh_wiki_from_recent_analysis(
    workspace_id: str,
    *,
    since_hours: int = 2,
    requested_by: str | None = None,
    supabase: Client | None = None,
) -> list[WikiDraftGenerationResult]:
    """리포트 파이프라인과 별개로, 최근 since_hours 내 분석 완료된 문서를 근거로
    위키만 갱신한다. reports/report_sections에는 아무것도 남기지 않는다."""
    config = ReportGenerationConfig()
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)

    candidates = get_recently_analyzed_candidates(workspace_id=workspace_id, since=since, supabase=supabase)
    selected = select_report_candidates(
        candidates,
        max_candidates=config.selection.max_candidates or 15,
        min_reliability_score=config.selection.min_reliability_score,
        min_importance_score=config.selection.min_importance_score,
        min_ranking_score=config.selection.min_ranking_score,
        category_limits=config.selection.category_limits,
    )
    issue_groups = group_report_candidates(selected, config=config.grouping)
    enriched_groups = enrich_issue_groups(
        issue_groups,
        wiki_search=lambda wiki_request: search_wiki_contexts(wiki_request, supabase=supabase),
        limit_per_group=config.wiki.limit_per_group,
    )
    sections = compose_report_sections(enriched_groups, config=config.composer)

    return generate_wiki_drafts_for_sections(
        sections, enriched_groups, workspace_id=workspace_id, requested_by=requested_by,
    )
```

`datetime`/`timezone`/`timedelta`는 이미 파일 상단에 import돼 있을 수 있다(Task 3/6에서 `datetime`, `timezone` 사용) — `timedelta`가 빠져 있으면 추가해라.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_wiki_generation.py -v`
Expected: PASS (전체 — 기존 14개 + 신규 2개)

- [ ] **Step 5: Commit**

```bash
git add src/wiki/generation.py tests/test_wiki_generation.py
git commit -m "Feat: 리포트와 별개로 최근 분석 기반 위키 갱신 오케스트레이션 추가"
```

---

### Task 3: `scripts/refresh_wiki.py` — CLI 진입점

**Files:**
- Create: `scripts/refresh_wiki.py`

**Interfaces:**
- Consumes: `refresh_wiki_from_recent_analysis`(Task 2)
- Produces: 없음 (최종 진입점)

- [ ] **Step 1: Write the script**

```python
"""최근 2시간 내 분석 완료된 문서를 근거로 위키만 갱신하는 배치.

리포트 파이프라인과 완전히 독립된 스케줄로 돈다(로컬: Windows 작업
스케줄러/cron, 배포: EventBridge). reports/report_sections에는 아무것도
남기지 않는다.

사용법:
    python scripts/refresh_wiki.py
    python scripts/refresh_wiki.py --since-hours 3
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.pipeline_common.db import get_client
from src.wiki.generation import refresh_wiki_from_recent_analysis


def get_workspace_id() -> str:
    rows = get_client().table("workspaces").select("id, name").limit(2).execute().data
    if len(rows) != 1:
        raise SystemExit(f"workspace_id를 자동으로 하나로 못 정했다 (workspaces 행 {len(rows)}개).")
    return str(rows[0]["id"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since-hours", type=int, default=2)
    args = parser.parse_args()

    workspace_id = get_workspace_id()
    results = refresh_wiki_from_recent_analysis(workspace_id, since_hours=args.since_hours)
    print(f"[refresh_wiki] {len(results)}개 이슈 처리:")
    for r in results:
        print(f"  - {r.issue_key}: issue_page={r.issue_page_id} topic_action={r.topic_action}")
```

- [ ] **Step 2: Syntax check**

Run: `python -c "import ast; ast.parse(open('scripts/refresh_wiki.py', encoding='utf-8').read())"`
Expected: 에러 없이 종료

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest tests/ -q`
Expected: 기존 대비 신규 5개(Task1 3개 + Task2 2개) 추가 통과, 그 외 실패 없음(로컬 `.env` placeholder로 인한 기존 4건 `test_missing_api_key_*` 실패는 이 변경과 무관 — 무시)

- [ ] **Step 4: Commit**

```bash
git add scripts/refresh_wiki.py
git commit -m "Feat: 위키 주기 갱신 CLI 스크립트 추가"
```

---

## Post-Implementation Checklist

- [ ] `python -m pytest tests/ -q` 전체 통과 (알려진 4건 제외)
- [ ] `src/report/interface.py`가 이번 변경으로 수정되지 않았는지 `git diff --stat`로 확인
- [ ] 로컬에서 실제 credential로 `python scripts/refresh_wiki.py` 1회 실행해, `wiki_pages`에 변화가 생기는지(또는 최근 분석 건이 없으면 "0개 처리"로 조용히 끝나는지) 확인

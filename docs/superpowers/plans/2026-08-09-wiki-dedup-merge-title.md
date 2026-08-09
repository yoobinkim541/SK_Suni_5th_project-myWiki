# 위키 중복 병합 시 제목 갱신 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** dedup 배치가 두 위키 페이지를 병합할 때, 대표 페이지의 `wiki_pages.title`이 병합 전 원래 제목이 아니라 병합된 새 본문을 반영한 제목으로 갱신되게 한다.

**Architecture:** 병합 LLM(`WikiDedupLLMResult`)의 출력 스키마에 `title` 필드를 추가하고, `_judge_and_merge()`가 병합 성공 시 이미 존재하는 `update_wiki_page_title()`(`src/wiki/interface.py`, PR #225에서 추가됨)을 호출해 대표 페이지 title을 갱신한다. title이 비어 있으면(LLM이 못 만들었으면) 기존 markdown 빈값 검증과 같은 자리에서 함께 걸러 `not_duplicate`로 폴백한다.

**Tech Stack:** Python, pydantic v2, 기존 OpenRouter 설정(`get_openrouter_settings`/`create_json_completion`) 그대로 재사용 — 새 모델/설정 분기점 없음.

## Global Constraints

- 토픽 페이지(`generation.py`)의 `update_existing` 경로는 건드리지 않는다 — 그쪽은 제목이 회차마다 안 바뀌는 게 설계 의도(스펙 "범위 밖" 참고).
- `_build_issue_page_markdown`/dedup의 대표/아카이빙/재부모지정 로직 등 기존 병합 흐름은 변경하지 않는다 — title 처리만 추가한다.
- 새 모델 설정을 만들지 않는다 — 기존 `get_openrouter_settings()`/`create_json_completion()`을 그대로 쓴다.

---

### Task 1: dedup 병합 결과에 title 필드 추가 + 검증 + `update_wiki_page_title` 연결

**Files:**
- Modify: `src/wiki/dedup_models.py`
- Modify: `src/wiki/dedup_prompts.py`
- Modify: `src/wiki/dedup.py`
- Test: `tests/test_wiki_dedup.py`

**Interfaces:**
- Consumes: `update_wiki_page_title(page_id: str, title: str, *, supabase: Client | None = None) -> None` (`src/wiki/interface.py`, 이미 존재 — PR #225에서 추가됨, import만 하면 됨).
- Produces: `WikiDedupLLMResult.title: str | None = None` (새 필드).

- [ ] **Step 1: 실패 테스트 작성 — 병합 성공 시 update_wiki_page_title 호출**

`tests/test_wiki_dedup.py`의 `test_merge_creates_version_archives_other_and_reparents_children` 함수를 아래 내용으로 교체(기존 fake LLM 응답에 `"title": "통합 제목"` 추가, `update_wiki_page_title` 스텁 추가, 호출 검증 추가):

```python
def test_merge_creates_version_archives_other_and_reparents_children(monkeypatch):
    calls = []
    monkeypatch.setattr(
        dedup, "create_json_completion",
        lambda **kwargs: json.dumps({
            "decision": "merge",
            "representative_page_id": "page-b",
            "title": "통합 제목",
            "markdown": "# 통합 본문",
            "change_summary": "두 문서를 통합",
            "claims": [{"document_version_id": "doc-1", "claim_text": "근거", "citation_order": 1}],
        }),
    )
    monkeypatch.setattr(dedup, "create_wiki_version", lambda draft, **k: calls.append(("create", draft.slug, draft.page_type, draft.parent_page_id, [s.document_version_id for s in draft.sources])) or "version-new")
    monkeypatch.setattr(dedup, "record_wiki_validation", lambda *a, **k: calls.append(("validate", a)))
    monkeypatch.setattr(dedup, "review_wiki_version", lambda *a, **k: calls.append(("review", a)))
    monkeypatch.setattr(dedup, "publish_wiki_version", lambda *a, **k: calls.append(("publish", a)))
    monkeypatch.setattr(dedup, "update_wiki_page_title", lambda page_id, title, **k: calls.append(("update_title", page_id, title)))
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
    assert ("update_title", "page-b", "통합 제목") in calls
    assert ("archive", "page-a") in calls
    assert ("reparent", "page-a", "page-b") in calls
```

바로 다음(파일에서 `test_not_duplicate_decision_does_nothing` 함수 앞)에 새 테스트를 추가:

```python
def test_merge_skipped_when_title_is_blank(monkeypatch):
    """병합을 결정했는데 title을 못 만들면(빈 문자열/공백) 본문만 바뀌고 제목은 그대로인
    반쪽짜리 상태를 막기 위해 병합 자체를 취소한다."""
    calls = []
    monkeypatch.setattr(
        dedup, "create_json_completion",
        lambda **kwargs: json.dumps({
            "decision": "merge",
            "representative_page_id": "page-b",
            "title": "   ",
            "markdown": "# 통합 본문",
            "change_summary": "두 문서를 통합",
            "claims": [{"document_version_id": "doc-1", "claim_text": "근거", "citation_order": 1}],
        }),
    )
    monkeypatch.setattr(dedup, "create_wiki_version", lambda draft, **k: calls.append(("create",)) or "should-not-run")
    monkeypatch.setattr(dedup, "update_wiki_page_title", lambda page_id, title, **k: calls.append(("update_title",)))
    monkeypatch.setattr(dedup, "archive_wiki_page", lambda page_id, **k: calls.append(("archive", page_id)))

    pair = _pair()
    content_a = _content("page-a", "a", "제목 A", "issue", "# A", [
        WikiSource(document_version_id="doc-1", citation_order=1, claim_text="근거", support_type="supports", source_start_line=None, source_end_line=None),
    ])
    content_b = _content("page-b", "b", "제목 B", "market", "# B", [])

    result = dedup._judge_and_merge(pair, content_a, content_b, workspace_id=WORKSPACE_ID, requested_by=None)

    assert result.decision == "not_duplicate"
    assert calls == []
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_wiki_dedup.py -k "creates_version_archives_other_and_reparents_children or title_is_blank" -v`
Expected: FAIL — `test_merge_creates_version_archives_other_and_reparents_children`은 `json.dumps` 호출 자체는 통과하지만 `AttributeError: <module 'src.wiki.dedup'> does not have the attribute 'update_wiki_page_title'`로 실패(아직 import 안 함). `test_merge_skipped_when_title_is_blank`는 title 검증이 아직 없어 `create`가 실제로 호출돼(`calls == [("create",)]`) `assert calls == []`에서 실패.

- [ ] **Step 3: `WikiDedupLLMResult`에 title 필드 추가**

`src/wiki/dedup_models.py`의 `WikiDedupLLMResult` 클래스를:
```python
class WikiDedupLLMResult(BaseModel):
    decision: WikiDedupDecision
    representative_page_id: str | None = None
    markdown: str | None = None
    change_summary: str | None = None
    claims: list[WikiDedupClaim] = Field(default_factory=list)
```
다음으로 교체(마지막에 `title` 필드 하나 추가):
```python
class WikiDedupLLMResult(BaseModel):
    decision: WikiDedupDecision
    representative_page_id: str | None = None
    title: str | None = None
    markdown: str | None = None
    change_summary: str | None = None
    claims: list[WikiDedupClaim] = Field(default_factory=list)
```

- [ ] **Step 4: 프롬프트에 제목 지시 추가**

`src/wiki/dedup_prompts.py`의 `WIKI_DEDUP_SYSTEM_PROMPT`에서, 아래 절대 규칙 항목:
```
- 병합하기로 했다면 두 문서 중 더 대표성 있는(제목이 더 넓은 범위를 다루거나 본문이
  더 충실한) 쪽의 page_id를 representative_page_id로 반환하십시오. 반드시 두 문서
  중 하나의 page_id여야 합니다.
```
바로 다음 줄에 새 규칙을 추가:
```
- 병합하기로 했다면 title에 통합된 새 본문 전체를 대표하는 새 제목을 지으십시오.
  두 원본 문서의 제목을 그대로 재사용하지 말고, 합쳐진 내용을 한눈에 알 수 있는
  제목으로 새로 쓰십시오.
```

그리고 JSON 출력 형식 블록:
```
JSON 출력 형식:
{
  "decision": "merge" | "not_duplicate",
  "representative_page_id": "병합 시 대표로 남길 페이지의 page_id",
  "markdown": "통합된 전체 본문(병합 시에만)",
  "change_summary": "변경 이력에 들어갈 한 줄(병합 시에만)",
  "claims": [{"document_version_id": "...", "claim_text": "...", "citation_order": 1}]
}"""
```
를 아래로 교체(`title` 필드 추가):
```
JSON 출력 형식:
{
  "decision": "merge" | "not_duplicate",
  "representative_page_id": "병합 시 대표로 남길 페이지의 page_id",
  "title": "통합된 새 제목(병합 시에만)",
  "markdown": "통합된 전체 본문(병합 시에만)",
  "change_summary": "변경 이력에 들어갈 한 줄(병합 시에만)",
  "claims": [{"document_version_id": "...", "claim_text": "...", "citation_order": 1}]
}"""
```

- [ ] **Step 5: `_judge_and_merge`에 title 검증 + `update_wiki_page_title` 호출 배선**

`src/wiki/dedup.py` 상단 `from .interface import (...)` 블록을:
```python
from .interface import (
    WikiDraftInput,
    WikiPageContent,
    WikiSourceInput,
    create_wiki_version,
    publish_wiki_version,
    record_wiki_validation,
    review_wiki_version,
)
```
다음으로 교체(`update_wiki_page_title` 추가):
```python
from .interface import (
    WikiDraftInput,
    WikiPageContent,
    WikiSourceInput,
    create_wiki_version,
    publish_wiki_version,
    record_wiki_validation,
    review_wiki_version,
    update_wiki_page_title,
)
```

`_judge_and_merge` 안, 기존 markdown 빈값 검증:
```python
    if not valid_claims or not (result.markdown or "").strip():
        return not_duplicate
```
를 title 검증도 함께 걸도록 교체:
```python
    if not valid_claims or not (result.markdown or "").strip() or not (result.title or "").strip():
        return not_duplicate
```

그리고 `publish_wiki_version(representative_info.page_id, version_id, supabase=supabase)` 바로 다음 줄에 추가:
```python
    update_wiki_page_title(representative_info.page_id, result.title, supabase=supabase)
```

(전체 순서는: `create_wiki_version` → `record_wiki_validation` → `review_wiki_version` → `publish_wiki_version` → **`update_wiki_page_title`(신규)** → `archive_wiki_page` → `reparent_children`.)

- [ ] **Step 6: 테스트 통과 확인**

Run: `pytest tests/test_wiki_dedup.py -v`
Expected: PASS 전부(기존 테스트 포함 — `test_not_duplicate_decision_does_nothing`/`test_merge_skipped_when_representative_page_id_is_invalid`/`test_merge_skipped_when_no_valid_grounded_claims`/`test_uses_injected_llm_client_instead_of_create_json_completion`은 전부 `not_duplicate`로 끝나는 fake 응답이라 `update_wiki_page_title` 스텁 없이도 그대로 통과해야 함)

- [ ] **Step 7: 커밋**

```bash
git add src/wiki/dedup_models.py src/wiki/dedup_prompts.py src/wiki/dedup.py tests/test_wiki_dedup.py
git commit -m "Feat: 위키 중복 병합 시 대표 페이지 제목도 새로 갱신"
```

---

## PR 생성 체크리스트 (구현 완료 후)

- `gh pr list --state open`로 중복 PR 없는지 확인
- 브랜치명 `feature/wiki-dedup-merge-title`, 커밋 접두사 `Feat:` (collaboration_rule.md 준수)
- PR 본문에 작업내용/변경이유/테스트결과/참고사항 포함
- 스쿼시 머지 후 배포(develop push → deploy-backend.yml, `src/wiki/**` 경로 포함이라 트리거됨) 확인
- 라이브 검증: 다음 dedup 배치(`wiki-dedup-batch.yml`, 하루 2회) 실행 시 병합된 페이지의 title이 새 본문과 일치하는지 확인 — 필요하면 `gh workflow run wiki-dedup-batch.yml`로 수동 트리거해 확인

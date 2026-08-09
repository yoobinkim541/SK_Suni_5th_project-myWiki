# 이슈 페이지 LLM 재작성 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 리포트 파이프라인이 자동 생성하는 이슈 페이지의 본문(현재 상황/핵심 사실/시사점/주시할 지점)을, 지금처럼 리포트 필드를 그대로 이어붙이지 않고 LLM이 자연스러운 문장으로 다듬어 쓰게 한다.

**Architecture:** `src/wiki/generation.py`에 `_rewrite_issue_page_content()`를 추가해 `_generate_issue_page()`가 마크다운 조립 직전에 호출한다. LLM은 4개 필드만 재작성한 `IssuePageRewriteResult`를 반환하고, 이를 원본 `ReportSectionDraft`의 `model_copy(update=...)`로 반영한 새 섹션 객체를 만들어 기존 `_build_issue_page_markdown()`에 그대로 넘긴다 — 마크다운 조립 함수 자체는 건드리지 않는다. "## 출처" 섹션과 `sources`는 원본 `section`(재작성 이전 값)으로 그대로 조립해 인용 안전성에 영향이 없다. LLM 호출 실패(타임아웃/잘못된 JSON/스키마 검증 실패)는 전부 함수 내부에서 잡아 원본 섹션을 그대로 반환하는 폴백으로 처리한다.

**Tech Stack:** Python, pydantic v2, `src/analysis/classifier.py`의 `create_json_completion`/`get_openrouter_settings`(OpenRouter, 모델 v4-flash 기본/v4-pro 폴백 — 기존 설정 그대로 재사용), pytest + `monkeypatch`.

## Global Constraints

- 새 모델/타임아웃 설정을 만들지 않는다 — `classifier.get_openrouter_settings()`를 그대로 재사용한다 (스펙 목표 5).
- "## 출처" 섹션과 `WikiSourceInput` 리스트(`_build_issue_page_sources`)는 이 변경으로 절대 값이 달라지지 않는다 — 항상 원본 `section`으로 조립한다 (스펙 목표 3).
- LLM 호출이 실패해도 이슈 페이지 생성은 지금처럼 항상 성공한다 — 실패는 함수 내부에서 잡아 원본 필드로 폴백하고, 상위로 예외를 던지지 않는다 (스펙 목표 4).
- 이슈 페이지에 `update_existing`/`create_new`/`skip` 판단이나 신뢰도 게이트를 새로 추가하지 않는다 (스펙 비목표).
- `_build_issue_page_markdown`/`_build_issue_page_sources`의 함수 시그니처는 변경하지 않는다.

---

### Task 1: 데이터 모델 + 프롬프트 추가

**Files:**
- Modify: `src/wiki/generation_models.py`
- Modify: `src/wiki/generation_prompts.py`
- Test: `tests/test_wiki_generation_models.py`
- Test: `tests/test_wiki_generation_prompts.py`

**Interfaces:**
- Produces: `IssuePageRewriteResult(BaseModel)` — `current_summary: str`, `key_facts: list[str]`, `implications: list[str]`, `watch_points: list[str]` (모두 `Field(min_length=1)`, 즉 빈 문자열/빈 리스트는 검증 실패).
- Produces: `ISSUE_PAGE_REWRITE_SYSTEM_PROMPT: str`, `build_issue_page_rewrite_user_prompt(section: ReportSectionDraft, evidence_texts: dict[str, str] | None = None) -> str`.

- [ ] **Step 1: 모델 실패 테스트 작성**

`tests/test_wiki_generation_models.py`의 import 목록에 `IssuePageRewriteResult`를 추가하고, 파일 끝에 추가:

```python
def test_issue_page_rewrite_result_requires_nonempty_fields():
    with pytest.raises(ValidationError):
        IssuePageRewriteResult(current_summary="", key_facts=["a"], implications=["b"], watch_points=["c"])
    with pytest.raises(ValidationError):
        IssuePageRewriteResult(current_summary="요약", key_facts=[], implications=["b"], watch_points=["c"])


def test_issue_page_rewrite_result_accepts_valid_payload():
    result = IssuePageRewriteResult(
        current_summary="다듬어진 요약",
        key_facts=["사실 1"],
        implications=["시사점 1"],
        watch_points=["지점 1"],
    )
    assert result.current_summary == "다듬어진 요약"
    assert result.key_facts == ["사실 1"]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_wiki_generation_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'IssuePageRewriteResult'`

- [ ] **Step 3: 모델 구현**

`src/wiki/generation_models.py` 파일 끝에 추가:

```python
class IssuePageRewriteResult(BaseModel):
    current_summary: str = Field(min_length=1)
    key_facts: list[str] = Field(min_length=1)
    implications: list[str] = Field(min_length=1)
    watch_points: list[str] = Field(min_length=1)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_wiki_generation_models.py -v`
Expected: PASS (기존 테스트 포함 전부)

- [ ] **Step 5: 프롬프트 실패 테스트 작성**

`tests/test_wiki_generation_prompts.py`의 import에 `ISSUE_PAGE_REWRITE_SYSTEM_PROMPT`, `build_issue_page_rewrite_user_prompt`를 추가하고, 파일 끝에 추가(이 파일은 이미 `_section(evidence_text=...)` 헬퍼가 있으므로 재사용):

```python
def test_issue_rewrite_system_prompt_forbids_new_facts():
    assert "새로운 사실" in ISSUE_PAGE_REWRITE_SYSTEM_PROMPT
    assert "JSON" in ISSUE_PAGE_REWRITE_SYSTEM_PROMPT


def test_issue_rewrite_user_prompt_includes_section_fields():
    prompt = build_issue_page_rewrite_user_prompt(_section())
    assert "HBM4 공급 부족 심화" in prompt
    assert "HBM4 공급이 예상보다 더 타이트해지고 있다." in prompt
    assert "주요 고객사 수요 증가" in prompt
    assert "SK하이닉스 협상력 강화" in prompt
    assert "경쟁사 증설 발표 여부" in prompt


def test_issue_rewrite_user_prompt_uses_evidence_text_map():
    prompt = build_issue_page_rewrite_user_prompt(
        _section(evidence_text=None), {"doc-1": "HBM4 수요가 급증했다"},
    )
    assert "HBM4 수요가 급증했다" in prompt


def test_issue_rewrite_user_prompt_handles_no_citations():
    section = _section().model_copy(update={"news_citations": []})
    prompt = build_issue_page_rewrite_user_prompt(section)
    assert "없음" in prompt
```

- [ ] **Step 6: 테스트 실패 확인**

Run: `pytest tests/test_wiki_generation_prompts.py -v`
Expected: FAIL — `ImportError: cannot import name 'ISSUE_PAGE_REWRITE_SYSTEM_PROMPT'`

- [ ] **Step 7: 프롬프트 구현**

`src/wiki/generation_prompts.py` 파일 끝에 추가:

```python
ISSUE_PAGE_REWRITE_SYSTEM_PROMPT = """당신은 SK하이닉스 반도체 산업 위키를 관리하는 편집자입니다.

아래 리포트 섹션의 네 항목(현재 상황/핵심 사실/시사점/주시할 지점)을 더 자연스러운 문장으로
다듬어 위키 문서 본문에 쓸 수 있게 재작성하십시오.

절대 규칙:
- [현재 상황]/[핵심 사실]/[시사점]/[주시할 지점]과 [근거 문서 원문]에 없는 새로운 사실·수치·
  기업명·날짜·인용을 추가하지 마십시오. 문장을 다듬을 뿐 내용을 지어내면 안 됩니다.
- current_summary는 한 문단(3~5문장)으로 자연스럽게 이어 쓰십시오.
- key_facts/implications/watch_points는 각각 원본과 비슷한 개수의 리스트로, 항목마다
  한 문장 이내로 쓰십시오. 원본에 있던 사실을 누락하지 마십시오.
- 출처·인용 표기는 이 작업과 무관합니다 — 절대 언급하거나 만들어내지 마십시오.
- 마크다운 코드블록 없이 지정된 JSON 구조로만 응답하십시오.

JSON 출력 형식:
{
  "current_summary": "다듬어진 현재 상황 문단",
  "key_facts": ["핵심 사실 1", "핵심 사실 2"],
  "implications": ["시사점 1", "시사점 2"],
  "watch_points": ["주시할 지점 1", "주시할 지점 2"]
}"""


def build_issue_page_rewrite_user_prompt(
    section: ReportSectionDraft,
    evidence_texts: dict[str, str] | None = None,
) -> str:
    lines: list[str] = [
        "[이슈 정보]",
        f"제목: {section.title}",
        f"카테고리: {section.category.value}",
        "",
        "[현재 상황]",
        section.current_summary or "",
        "",
        "[핵심 사실]",
    ]
    lines.extend(f"- {fact}" for fact in section.key_facts)
    lines.append("")
    lines.append("[시사점]")
    lines.extend(f"- {implication}" for implication in section.implications)
    lines.append("")
    lines.append("[주시할 지점]")
    lines.extend(f"- {watch_point}" for watch_point in section.watch_points)
    lines.append("")
    lines.append("[근거 문서 원문] (문맥 이해용 — 여기 없는 사실을 새로 추가하지 마십시오)")
    if section.news_citations:
        for citation in section.news_citations:
            evidence = (evidence_texts or {}).get(citation.document_version_id) or citation.evidence_text or ""
            lines.append(f"- {evidence}")
    else:
        lines.append("없음")
    return "\n".join(lines)
```

`ReportSectionDraft`는 이 파일 상단에 이미 import돼 있으므로(`from ..report.models import ReportCandidate, ReportSectionDraft`) 추가 import는 필요 없다.

- [ ] **Step 8: 테스트 통과 확인**

Run: `pytest tests/test_wiki_generation_prompts.py -v`
Expected: PASS (기존 테스트 포함 전부)

- [ ] **Step 9: 커밋**

```bash
git add src/wiki/generation_models.py src/wiki/generation_prompts.py tests/test_wiki_generation_models.py tests/test_wiki_generation_prompts.py
git commit -m "Feat: 이슈 페이지 LLM 재작성용 모델·프롬프트 추가"
```

---

### Task 2: `_rewrite_issue_page_content` 구현 + `_generate_issue_page` 배선

**Files:**
- Modify: `src/wiki/generation.py`
- Test: `tests/test_wiki_generation.py`

**Interfaces:**
- Consumes (Task 1에서): `IssuePageRewriteResult` (`src/wiki/generation_models.py`), `ISSUE_PAGE_REWRITE_SYSTEM_PROMPT` / `build_issue_page_rewrite_user_prompt` (`src/wiki/generation_prompts.py`).
- Produces: `_rewrite_issue_page_content(section: ReportSectionDraft, evidence_texts: dict[str, str] | None = None, *, llm_client: WikiTopicLLMClient | None = None) -> ReportSectionDraft` — 성공하면 4개 필드가 교체된 새 `ReportSectionDraft`, 실패하면 원본 `section`을 그대로 반환(동일 객체가 아니라 값이 같은 경우도 있을 수 있으니 테스트는 `==` 비교로 값 동일성만 확인).
- `_generate_issue_page`에 `llm_client: WikiTopicLLMClient | None = None` 키워드 인자 추가.

- [ ] **Step 1: `_rewrite_issue_page_content` 실패 테스트 작성**

`tests/test_wiki_generation.py`의 `test_generate_issue_page_markdown_contains_all_sections` 함수 바로 아래(184번째 줄 부근)에 추가:

```python
def test_rewrite_issue_page_content_uses_llm_result():
    def fake_llm(system_prompt, user_prompt, model):
        return json.dumps({
            "current_summary": "다듬어진 요약",
            "key_facts": ["다듬어진 사실"],
            "implications": ["다듬어진 시사점"],
            "watch_points": ["다듬어진 지점"],
        })

    rewritten = generation._rewrite_issue_page_content(_section(), llm_client=fake_llm)

    assert rewritten.current_summary == "다듬어진 요약"
    assert rewritten.key_facts == ["다듬어진 사실"]
    assert rewritten.implications == ["다듬어진 시사점"]
    assert rewritten.watch_points == ["다듬어진 지점"]
    assert rewritten.title == _section().title  # 제목은 재작성 대상이 아니다


def test_rewrite_issue_page_content_falls_back_on_invalid_json(monkeypatch):
    monkeypatch.setattr(generation, "create_json_completion", lambda **kwargs: "not json")

    rewritten = generation._rewrite_issue_page_content(_section())

    assert rewritten == _section()


def test_rewrite_issue_page_content_falls_back_on_empty_fields(monkeypatch):
    monkeypatch.setattr(
        generation, "create_json_completion",
        lambda **kwargs: json.dumps(
            {"current_summary": "", "key_facts": [], "implications": [], "watch_points": []}
        ),
    )

    rewritten = generation._rewrite_issue_page_content(_section())

    assert rewritten == _section()


def test_rewrite_issue_page_content_falls_back_on_llm_exception(monkeypatch):
    def exploding_completion(**kwargs):
        raise generation.OpenRouterTimeoutError("타임아웃")

    monkeypatch.setattr(generation, "create_json_completion", exploding_completion)

    rewritten = generation._rewrite_issue_page_content(_section())

    assert rewritten == _section()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_wiki_generation.py -k rewrite_issue_page_content -v`
Expected: FAIL — `AttributeError: module 'src.wiki.generation' has no attribute '_rewrite_issue_page_content'`

- [ ] **Step 3: `_rewrite_issue_page_content` 구현**

`src/wiki/generation.py` 상단 import 블록을 수정한다.

`from .generation_models import ...` 줄을:
```python
from .generation_models import TopicPageCandidate, TopLevelTopicPage, WikiDraftGenerationResult, WikiPageIdentity, WikiTopicLLMResult
```
다음으로 교체:
```python
from .generation_models import (
    IssuePageRewriteResult,
    TopicPageCandidate,
    TopLevelTopicPage,
    WikiDraftGenerationResult,
    WikiPageIdentity,
    WikiTopicLLMResult,
)
```

`from .generation_prompts import WIKI_TOPIC_SYSTEM_PROMPT, build_wiki_topic_user_prompt` 줄을:
```python
from .generation_prompts import (
    ISSUE_PAGE_REWRITE_SYSTEM_PROMPT,
    WIKI_TOPIC_SYSTEM_PROMPT,
    build_issue_page_rewrite_user_prompt,
    build_wiki_topic_user_prompt,
)
```
로 교체.

`from ..analysis.classifier import create_json_completion, get_openrouter_settings, parse_json_response` 바로 아래에 추가:
```python
from ..analysis.exceptions import (
    InvalidJsonResponseError,
    MissingApiKeyError,
    OpenRouterApiError,
    OpenRouterTimeoutError,
)
```

`_build_issue_page_sources` 함수 바로 다음, `_generate_issue_page` 함수 바로 앞에 추가:

```python
def _rewrite_issue_page_content(
    section: ReportSectionDraft,
    evidence_texts: dict[str, str] | None = None,
    *,
    llm_client: WikiTopicLLMClient | None = None,
) -> ReportSectionDraft:
    """이슈 페이지 본문 4개 필드(현재상황/핵심사실/시사점/주시할지점)를 LLM으로 다듬는다.

    실패(LLM 오류·잘못된 JSON·빈 필드)하면 원본 section을 그대로 반환한다 — 이슈 페이지는
    지금까지 LLM 없이도 항상 생성에 성공했으므로, 이 재작성 단계가 그 신뢰성을 깨서는 안 된다.
    "## 출처" 섹션(_build_issue_page_sources)은 여기서 건드리는 4개 필드와 무관해 영향받지 않는다.
    """
    settings = get_openrouter_settings()
    user_prompt = build_issue_page_rewrite_user_prompt(section, evidence_texts)
    try:
        if llm_client is not None:
            response_text = llm_client(ISSUE_PAGE_REWRITE_SYSTEM_PROMPT, user_prompt, settings.model)
        else:
            response_text = create_json_completion(
                system_prompt=ISSUE_PAGE_REWRITE_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                model=settings.model,
            )
        payload = parse_json_response(response_text)
        result = IssuePageRewriteResult.model_validate(payload)
    except (
        MissingApiKeyError,
        OpenRouterApiError,
        OpenRouterTimeoutError,
        InvalidJsonResponseError,
        ValidationError,
    ) as exc:
        logger.warning(
            "issue_page_rewrite_llm_fallback",
            extra={"issue_key": section.issue_key, "error": str(exc)},
        )
        return section

    return section.model_copy(update={
        "current_summary": result.current_summary,
        "key_facts": result.key_facts,
        "implications": result.implications,
        "watch_points": result.watch_points,
    })
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_wiki_generation.py -k rewrite_issue_page_content -v`
Expected: PASS (4개 전부)

- [ ] **Step 5: `_generate_issue_page`/`generate_wiki_drafts_for_sections`에 배선**

`_generate_issue_page`의 시그니처(`src/wiki/generation.py`)를:
```python
def _generate_issue_page(
    section: ReportSectionDraft,
    *,
    workspace_id: str,
    requested_by: str | None,
    parent_page_id: str | None = None,
    evidence_texts: dict[str, str] | None = None,
    citation_attribution: dict[str, ReportCandidate] | None = None,
    supabase: Client | None = None,
) -> tuple[str, str]:
```
다음으로 교체(마지막에 `llm_client` 추가):
```python
def _generate_issue_page(
    section: ReportSectionDraft,
    *,
    workspace_id: str,
    requested_by: str | None,
    parent_page_id: str | None = None,
    evidence_texts: dict[str, str] | None = None,
    citation_attribution: dict[str, ReportCandidate] | None = None,
    supabase: Client | None = None,
    llm_client: WikiTopicLLMClient | None = None,
) -> tuple[str, str]:
```

같은 함수 안, `draft = WikiDraftInput(` 바로 앞에 추가:
```python
    rewritten_section = _rewrite_issue_page_content(section, evidence_texts, llm_client=llm_client)
```

그리고 `draft = WikiDraftInput(...)` 블록 안의
```python
        markdown=_build_issue_page_markdown(section, evidence_texts, citation_attribution),
```
를
```python
        markdown=_build_issue_page_markdown(rewritten_section, evidence_texts, citation_attribution),
```
로 교체한다. `sources=_build_issue_page_sources(section, evidence_texts)`는 **`section`(원본) 그대로 유지** — 출처는 재작성 대상이 아니므로 바꾸지 않는다.

`generate_wiki_drafts_for_sections` 안, `_generate_issue_page` 호출부:
```python
            issue_page_id, issue_version_id = _generate_issue_page(
                section,
                workspace_id=workspace_id,
                requested_by=requested_by,
                parent_page_id=topic_page_id,
                evidence_texts=evidence_texts,
                citation_attribution=citation_attribution,
                supabase=supabase,
            )
```
를
```python
            issue_page_id, issue_version_id = _generate_issue_page(
                section,
                workspace_id=workspace_id,
                requested_by=requested_by,
                parent_page_id=topic_page_id,
                evidence_texts=evidence_texts,
                citation_attribution=citation_attribution,
                supabase=supabase,
                llm_client=llm_client,
            )
```
로 교체.

`tests/test_wiki_generation.py`의 `test_generate_wiki_drafts_for_sections_threads_injected_clients`가 지금은 이슈 페이지 쪽 `llm_client`가 실제로 전달되는지 검증하지 않는다 — `fake_generate_issue_page`와 마지막 assert를 아래로 교체해 토픽과 동일하게 검증하게 한다:
```python
    def fake_generate_issue_page(section, **kwargs):
        seen["issue_supabase"] = kwargs["supabase"]
        seen["issue_llm_client"] = kwargs["llm_client"]
        return "page-1", "version-1"
```
```python
    assert seen["topic_supabase"] is supabase
    assert seen["topic_llm_client"] is llm_client
    assert seen["issue_supabase"] is supabase
    assert seen["issue_llm_client"] is llm_client
```

- [ ] **Step 6: 기존 테스트 6개가 실제 네트워크 호출을 시도하지 않도록 스텁 추가**

`_generate_issue_page`를 직접 호출하면서 `create_json_completion`을 스텁하지 않는 기존 테스트가 6개 있다. 이대로 두면 `_rewrite_issue_page_content`가 실제 OpenRouter를 호출하려고 시도한다(로컬에 `OPENROUTER_API_KEY`가 있으면 실제 API 호출, 없으면 `MissingApiKeyError` — 어느 쪽이든 이 테스트들의 검증 대상과 무관한 이유로 느려지거나 깨진다). 각 테스트 함수 맨 앞줄에 아래 한 줄을 추가한다(빈 JSON을 반환해 `IssuePageRewriteResult` 검증에 실패시켜 원본 필드로 조용히 폴백하게 만든다 — 이 6개 테스트는 마크다운 텍스트 내용을 검증하지 않으므로 폴백이어도 기존 assert는 그대로 통과한다):

```python
    monkeypatch.setattr(generation, "create_json_completion", lambda **kwargs: "{}")
```

대상 함수 6개(전부 `monkeypatch` 인자를 이미 받고 있다):
1. `test_generate_issue_page_creates_and_auto_publishes` (53번째 줄 함수 시작 바로 다음, `calls = []` 앞 또는 뒤 아무 곳)
2. `test_generate_issue_page_defaults_parent_to_none`
3. `test_generate_issue_page_reuses_matched_page_identity`
4. `test_generate_issue_page_adopts_new_parent_when_matched_page_has_none`
5. `test_generate_issue_page_creates_new_when_no_match`
6. `test_generate_issue_page_threads_supabase_into_writes`

예시(1번, `test_generate_issue_page_creates_and_auto_publishes`):
```python
def test_generate_issue_page_creates_and_auto_publishes(monkeypatch):
    calls = []
    monkeypatch.setattr(generation, "create_json_completion", lambda **kwargs: "{}")

    def fake_upsert_wiki_page(workspace_id, slug, title, page_type, parent_page_id=None, *, supabase=None):
        ...
```
(이후 함수 본문은 변경 없음 — 맨 위에 스텁 한 줄만 추가)

나머지 5개도 동일하게 함수 본문 첫 줄로 같은 스텁 한 줄을 추가한다.

- [ ] **Step 7: 전체 스위트 재확인 (아직 통과해야 함 — 회귀 없음 확인용)**

Run: `pytest tests/test_wiki_generation.py -v`
Expected: PASS 전부 (Step 6 이전에 실패하거나 느려지던 6개 포함)

- [ ] **Step 8: 통합 테스트 2개 추가 (재작성 반영 확인 + 출처 안전성 회귀)**

`tests/test_wiki_generation.py`에서 `test_generate_issue_page_threads_supabase_into_writes` 함수 바로 다음에 추가:

```python
def test_generate_issue_page_uses_rewritten_content_in_markdown(monkeypatch):
    monkeypatch.setattr(generation, "find_matching_issue_page", lambda *a, **k: None)
    monkeypatch.setattr(generation, "upsert_wiki_page", lambda *a, **k: "page-1")
    captured = {}

    def fake_create_wiki_version(draft, **k):
        captured["markdown"] = draft.markdown
        return "version-1"

    monkeypatch.setattr(generation, "create_wiki_version", fake_create_wiki_version)
    monkeypatch.setattr(generation, "record_wiki_validation", lambda *a, **k: None)
    monkeypatch.setattr(generation, "review_wiki_version", lambda *a, **k: None)
    monkeypatch.setattr(generation, "publish_wiki_version", lambda *a, **k: None)

    def fake_llm(system_prompt, user_prompt, model):
        return json.dumps({
            "current_summary": "다듬어진 요약 문단",
            "key_facts": ["다듬어진 사실"],
            "implications": ["다듬어진 시사점"],
            "watch_points": ["다듬어진 지점"],
        })

    generation._generate_issue_page(
        _section(), workspace_id="ws-1", requested_by=None, llm_client=fake_llm,
    )

    assert "다듬어진 요약 문단" in captured["markdown"]
    assert "다듬어진 사실" in captured["markdown"]
    # 원본 문장은 재작성 결과로 완전히 대체된다
    assert "HBM4 공급이 예상보다 더 타이트해지고 있다." not in captured["markdown"]


def test_generate_issue_page_sources_unaffected_by_rewrite(monkeypatch):
    """LLM 재작성이 성공해도 '## 출처' 섹션과 sources는 원본 section 기준 그대로다."""
    monkeypatch.setattr(generation, "find_matching_issue_page", lambda *a, **k: None)
    monkeypatch.setattr(generation, "upsert_wiki_page", lambda *a, **k: "page-1")
    captured = {}

    def fake_create_wiki_version(draft, **k):
        captured["markdown"] = draft.markdown
        captured["sources"] = draft.sources
        return "version-1"

    monkeypatch.setattr(generation, "create_wiki_version", fake_create_wiki_version)
    monkeypatch.setattr(generation, "record_wiki_validation", lambda *a, **k: None)
    monkeypatch.setattr(generation, "review_wiki_version", lambda *a, **k: None)
    monkeypatch.setattr(generation, "publish_wiki_version", lambda *a, **k: None)

    def fake_llm(system_prompt, user_prompt, model):
        return json.dumps({
            "current_summary": "다듬어진 요약",
            "key_facts": ["다듬어진 사실"],
            "implications": ["다듬어진 시사점"],
            "watch_points": ["다듬어진 지점"],
        })

    generation._generate_issue_page(
        _section(), workspace_id="ws-1", requested_by=None, llm_client=fake_llm,
    )

    assert "## 출처" in captured["markdown"]
    assert [s.document_version_id for s in captured["sources"]] == ["doc-1"]
    assert "document_version_id" not in captured["markdown"]
```

- [ ] **Step 9: 전체 스위트 최종 확인**

Run: `pytest tests/test_wiki_generation.py tests/test_wiki_generation_models.py tests/test_wiki_generation_prompts.py -v`
Expected: PASS 전부

- [ ] **Step 10: 커밋**

```bash
git add src/wiki/generation.py tests/test_wiki_generation.py
git commit -m "Feat: 이슈 페이지 생성 시 LLM으로 본문 재작성 + 출처 섹션 불변 보장"
```

---

## PR 생성 체크리스트 (구현 완료 후)

- `gh pr list --state open`로 중복 PR 없는지 확인
- 브랜치명 `feature/issue-page-llm-rewrite`, 커밋 접두사 `Feat:` (collaboration_rule.md 준수)
- PR 본문에 작업내용/변경이유/테스트결과(위 pytest 명령 결과)/참고사항 포함
- 스쿼시 머지 후 배포 파이프라인(Oracle VM, `develop` 브랜치 push 트리거) 확인, 다음 리포트 생성 배치 실행 시(또는 `refresh_wiki_from_recent_analysis`/`generate_wiki_drafts_for_sections` 수동 실행) 실제 이슈 페이지 마크다운이 재작성됐는지 라이브 확인

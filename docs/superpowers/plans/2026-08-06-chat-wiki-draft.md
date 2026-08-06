# 대화 기반 위키 저장(save-to-wiki) 본문 템플릿 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 에이전트 챗봇 답변을 "위키에 저장"할 때, 제목을 질문 앞 80자 자르기가 아니라 LLM이 만든 제목으로, 본문을 챗봇 답변 원문 그대로가 아니라 질문/답변 요약/핵심 근거/출처로 구조화된 마크다운으로 저장하게 만든다.

**Architecture:** 새 모듈 `src/wiki/chat_wiki.py`에 `compose_chat_wiki_draft(question, answer, citations)` 함수를 만든다. 내부에서 `src/wiki/generation.py`의 토픽 페이지 생성과 동일한 패턴(`analysis/classifier.py`의 `create_json_completion` → `parse_json_response` → pydantic `model_validate`)으로 LLM을 한 번 호출해 `{title, answer_summary, key_evidence}`를 받고, 그걸 고정 마크다운 템플릿에 꽂아 넣는다. LLM 호출이 실패하면(API 키 없음/타임아웃/검증 실패) 예외를 던지지 않고 코드 폴백(질문 앞 80자를 제목으로, 답변 원문과 citation 텍스트를 그대로 사용)으로 같은 템플릿 구조를 만든다. `src/api/main.py`의 `save_message_to_wiki`는 이 함수 하나만 호출하도록 바뀐다.

**Tech Stack:** Python, FastAPI, Pydantic v2, pytest, OpenRouter(via 기존 `analysis/classifier.py` 클라이언트) — 새 라이브러리 추가 없음.

## Global Constraints

- 새 OpenRouter 모델/설정을 추가하지 않는다 — `analysis/classifier.py`의 `get_openrouter_settings()`(기본 `deepseek/deepseek-v4-flash`, 폴백 `deepseek/deepseek-v4-pro`)를 그대로 재사용한다.
- LLM 호출 실패가 저장 실패로 이어지면 안 된다 — 항상 폴백으로 성공해야 한다.
- 기존 `is_llm_fallback`/citations 400 검증 로직(`src/api/main.py:284-294`)은 변경하지 않는다.
- 프론트엔드는 변경하지 않는다 — "위키에 저장" 버튼은 이미 이 엔드포인트를 정상 호출하고 있다.

## ⚠️ 시작 전 필수 확인

**이 작업은 반드시 `develop` 브랜치를 베이스로 진행한다.** `save-to-wiki` 엔드포인트, `src/wiki/generation.py`, `WikiDraftInput` 등은 전부 `develop`에만 있고 다른 로컬 브랜치(예: `feat/dashboard-kpi-real-data`)에는 없다. 시작하기 전에 아래를 실행해서 베이스를 맞춘다:

```bash
git fetch origin
git checkout develop
git pull origin develop
git checkout -b feat/chat-wiki-draft-template
```

각 Task 안의 파일 경로/라인 번호는 이 시점의 `develop` 기준이다 — 실제 실행 시 라인 번호가 약간 밀려 있을 수 있으니 함수 이름으로 다시 찾아서 확인할 것.

---

### Task 1: `ChatWikiLLMResult` 모델 + 프롬프트

**Files:**
- Create: `src/wiki/chat_wiki.py`
- Test: `tests/test_wiki_chat_draft.py`

**Interfaces:**
- Produces: `ChatWikiLLMResult(BaseModel)` — 필드 `title: str`, `answer_summary: str`, `key_evidence: list[str]`. `CHAT_WIKI_SYSTEM_PROMPT: str`. `_build_chat_wiki_user_prompt(question: str, answer: str, citations: list[dict]) -> str`.

- [ ] **Step 1: 실패하는 테스트 작성 — 프롬프트에 질문/답변/근거가 들어가는지**

```python
# tests/test_wiki_chat_draft.py
"""compose_chat_wiki_draft 및 관련 프롬프트/모델 테스트.

analysis/classifier.py의 create_json_completion을 monkeypatch로 대체해서
실제 OpenRouter 네트워크 호출이 절대 나가지 않게 한다(tests/test_wiki_generation.py와
동일한 패턴).
"""
from __future__ import annotations

import json

from src.analysis.exceptions import OpenRouterTimeoutError
from src.wiki import chat_wiki

SAMPLE_CITATION = {
    "id": "c1",
    "document_version_id": "dv-1",
    "quoted_text": "HBM4는 차세대 메모리다.",
    "citation_order": 1,
}


def test_user_prompt_includes_question_answer_and_evidence():
    prompt = chat_wiki._build_chat_wiki_user_prompt(
        question="HBM4가 뭐야?",
        answer="HBM4는 차세대 메모리다. [1]",
        citations=[SAMPLE_CITATION],
    )
    assert "HBM4가 뭐야?" in prompt
    assert "HBM4는 차세대 메모리다. [1]" in prompt
    assert "document_version_id=dv-1" in prompt
    assert "HBM4는 차세대 메모리다." in prompt


def test_user_prompt_handles_no_citations():
    prompt = chat_wiki._build_chat_wiki_user_prompt(
        question="HBM4가 뭐야?", answer="답변", citations=[],
    )
    assert "없음" in prompt
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `python -m pytest tests/test_wiki_chat_draft.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.wiki.chat_wiki'`

- [ ] **Step 3: `src/wiki/chat_wiki.py` 작성 (모델 + 프롬프트만)**

```python
from __future__ import annotations

import logging

from pydantic import BaseModel, Field, ValidationError

from ..analysis.classifier import create_json_completion, get_openrouter_settings, parse_json_response
from ..analysis.exceptions import (
    InvalidJsonResponseError,
    MissingApiKeyError,
    OpenRouterApiError,
    OpenRouterTimeoutError,
)

logger = logging.getLogger(__name__)

CHAT_WIKI_SYSTEM_PROMPT = """당신은 SK하이닉스 반도체 산업 위키를 관리하는 편집자입니다.

사용자가 에이전트에게 물어본 질문과 답변을 위키 문서로 저장하려 합니다. 아래 질문/답변/근거를
바탕으로 위키 문서의 제목과 답변 요약, 핵심 근거를 작성하십시오.

절대 규칙:
- title은 질문의 핵심 주제를 담아 80자 이내로 간결하게 쓰십시오. 질문 문장을 그대로 베끼지
  말고 문서 제목답게 다듬으십시오.
- answer_summary는 답변 원문을 그대로 베끼지 말고, 핵심 내용만 간결하게 요약하십시오.
- key_evidence는 [근거] 목록에 있는 내용만 근거로 1~5개의 짧은 문장으로 정리하십시오.
  [근거]에 없는 사실을 지어내지 마십시오.
- 마크다운 코드블록 없이 지정된 JSON 구조로만 응답하십시오.

JSON 출력 형식:
{
  "title": "위키 문서 제목",
  "answer_summary": "답변 요약",
  "key_evidence": ["핵심 근거 1", "핵심 근거 2"]
}"""


class ChatWikiLLMResult(BaseModel):
    title: str = Field(min_length=1)
    answer_summary: str = Field(min_length=1)
    key_evidence: list[str] = Field(min_length=1)


def _build_chat_wiki_user_prompt(question: str, answer: str, citations: list[dict]) -> str:
    lines = ["[질문]", question, "", "[답변]", answer, "", "[근거]"]
    if citations:
        for citation in citations:
            quoted = citation.get("quoted_text") or ""
            lines.append(f"- document_version_id={citation['document_version_id']}: {quoted}")
    else:
        lines.append("없음")
    return "\n".join(lines)
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `python -m pytest tests/test_wiki_chat_draft.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/wiki/chat_wiki.py tests/test_wiki_chat_draft.py
git commit -m "feat: 대화 기반 위키 저장용 LLM 응답 모델과 프롬프트 추가"
```

---

### Task 2: `compose_chat_wiki_draft()` — 정상 경로 + 마크다운 조립

**Files:**
- Modify: `src/wiki/chat_wiki.py`
- Test: `tests/test_wiki_chat_draft.py`

**Interfaces:**
- Consumes: Task 1의 `ChatWikiLLMResult`, `CHAT_WIKI_SYSTEM_PROMPT`, `_build_chat_wiki_user_prompt`.
- Produces: `ChatWikiDraft(BaseModel)` — 필드 `title: str`, `markdown: str`. `compose_chat_wiki_draft(question: str, answer: str, citations: list[dict], *, llm_client: Callable[[str, str, str | None], str] | None = None) -> ChatWikiDraft`.

- [ ] **Step 1: 실패하는 테스트 작성 — 정상 LLM 응답으로 5개 섹션 마크다운 생성**

```python
# tests/test_wiki_chat_draft.py에 이어서 추가

def test_compose_chat_wiki_draft_builds_structured_markdown(monkeypatch):
    monkeypatch.setattr(
        chat_wiki,
        "create_json_completion",
        lambda **kwargs: json.dumps(
            {
                "title": "HBM4 개요",
                "answer_summary": "HBM4는 차세대 고대역폭 메모리다.",
                "key_evidence": ["HBM4는 차세대 메모리다."],
            }
        ),
    )

    draft = chat_wiki.compose_chat_wiki_draft(
        question="HBM4가 뭐야?",
        answer="HBM4는 차세대 메모리다. [1]",
        citations=[SAMPLE_CITATION],
    )

    assert draft.title == "HBM4 개요"
    assert "# HBM4 개요" in draft.markdown
    assert "## 질문" in draft.markdown
    assert "HBM4가 뭐야?" in draft.markdown
    assert "## 답변 요약" in draft.markdown
    assert "HBM4는 차세대 고대역폭 메모리다." in draft.markdown
    assert "## 핵심 근거" in draft.markdown
    assert "- HBM4는 차세대 메모리다." in draft.markdown
    assert "## 출처" in draft.markdown
    assert "(document_version_id=dv-1)" in draft.markdown


def test_compose_chat_wiki_draft_uses_injected_llm_client(monkeypatch):
    """generation.py의 llm_client 주입 패턴과 동일 — 테스트에서 fake client를 직접 넘길 수 있어야 한다."""
    calls = []

    def fake_client(system_prompt, user_prompt, model):
        calls.append((system_prompt, user_prompt, model))
        return json.dumps({"title": "t", "answer_summary": "s", "key_evidence": ["e"]})

    draft = chat_wiki.compose_chat_wiki_draft(
        question="q", answer="a", citations=[SAMPLE_CITATION], llm_client=fake_client,
    )

    assert draft.title == "t"
    assert len(calls) == 1
    assert calls[0][0] == chat_wiki.CHAT_WIKI_SYSTEM_PROMPT
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `python -m pytest tests/test_wiki_chat_draft.py -v`
Expected: FAIL — `AttributeError: module 'src.wiki.chat_wiki' has no attribute 'compose_chat_wiki_draft'`

- [ ] **Step 3: `compose_chat_wiki_draft` 정상 경로 구현 (폴백은 Task 3에서 추가)**

`src/wiki/chat_wiki.py`에 이어서 추가:

```python
class ChatWikiDraft(BaseModel):
    title: str
    markdown: str


def _build_sources_lines(citations: list[dict]) -> list[str]:
    lines = ["## 출처"]
    for citation in citations:
        quoted = citation.get("quoted_text") or ""
        lines.append(f"- {quoted} (document_version_id={citation['document_version_id']})")
    return lines


def _build_markdown(
    title: str, question: str, answer_summary: str, key_evidence: list[str], citations: list[dict],
) -> str:
    lines = [
        f"# {title}", "",
        "## 질문", question, "",
        "## 답변 요약", answer_summary, "",
        "## 핵심 근거",
    ]
    lines.extend(f"- {item}" for item in key_evidence)
    lines.append("")
    lines.extend(_build_sources_lines(citations))
    return "\n".join(lines)


def compose_chat_wiki_draft(
    question: str,
    answer: str,
    citations: list[dict],
    *,
    llm_client=None,
) -> ChatWikiDraft:
    settings = get_openrouter_settings()
    user_prompt = _build_chat_wiki_user_prompt(question, answer, citations)

    if llm_client is not None:
        response_text = llm_client(CHAT_WIKI_SYSTEM_PROMPT, user_prompt, settings.model)
    else:
        response_text = create_json_completion(
            system_prompt=CHAT_WIKI_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=settings.model,
        )
    payload = parse_json_response(response_text)
    result = ChatWikiLLMResult.model_validate(payload)

    markdown = _build_markdown(result.title, question, result.answer_summary, result.key_evidence, citations)
    return ChatWikiDraft(title=result.title, markdown=markdown)
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `python -m pytest tests/test_wiki_chat_draft.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/wiki/chat_wiki.py tests/test_wiki_chat_draft.py
git commit -m "feat: compose_chat_wiki_draft 정상 경로 구현"
```

---

### Task 3: LLM 실패 시 코드 폴백

**Files:**
- Modify: `src/wiki/chat_wiki.py`
- Test: `tests/test_wiki_chat_draft.py`

**Interfaces:**
- Consumes: Task 2의 `compose_chat_wiki_draft`, `ChatWikiDraft`, `_build_markdown`.
- Produces: 변경 없음 — `compose_chat_wiki_draft`의 동작만 확장(예외 시에도 항상 `ChatWikiDraft` 반환).

- [ ] **Step 1: 실패하는 테스트 작성 — 검증 실패와 LLM 예외 각각 폴백으로 이어지는지**

```python
# tests/test_wiki_chat_draft.py에 이어서 추가

def test_compose_chat_wiki_draft_falls_back_on_invalid_json(monkeypatch):
    monkeypatch.setattr(chat_wiki, "create_json_completion", lambda **kwargs: "이건 JSON이 아님")

    draft = chat_wiki.compose_chat_wiki_draft(
        question="HBM4가 뭐야?", answer="HBM4는 차세대 메모리다.", citations=[SAMPLE_CITATION],
    )

    assert draft.title == "HBM4가 뭐야?"
    assert "## 답변 요약" in draft.markdown
    assert "HBM4는 차세대 메모리다." in draft.markdown
    assert "- HBM4는 차세대 메모리다." in draft.markdown  # key_evidence 폴백 = citation quoted_text


def test_compose_chat_wiki_draft_falls_back_on_schema_validation_error(monkeypatch):
    monkeypatch.setattr(
        chat_wiki, "create_json_completion", lambda **kwargs: json.dumps({"title": "제목만 있음"}),
    )

    draft = chat_wiki.compose_chat_wiki_draft(
        question="HBM4가 뭐야?", answer="답변 원문", citations=[SAMPLE_CITATION],
    )

    assert draft.title == "HBM4가 뭐야?"
    assert "답변 원문" in draft.markdown


def test_compose_chat_wiki_draft_falls_back_on_llm_exception(monkeypatch):
    def raise_timeout(**kwargs):
        raise OpenRouterTimeoutError("timeout")

    monkeypatch.setattr(chat_wiki, "create_json_completion", raise_timeout)

    draft = chat_wiki.compose_chat_wiki_draft(
        question="HBM4가 뭐야?", answer="답변 원문", citations=[SAMPLE_CITATION],
    )

    assert draft.title == "HBM4가 뭐야?"
    assert "답변 원문" in draft.markdown


def test_compose_chat_wiki_draft_truncates_long_question_for_fallback_title(monkeypatch):
    def raise_timeout(**kwargs):
        raise OpenRouterTimeoutError("timeout")

    monkeypatch.setattr(chat_wiki, "create_json_completion", raise_timeout)
    long_question = "가" * 100

    draft = chat_wiki.compose_chat_wiki_draft(question=long_question, answer="답변", citations=[SAMPLE_CITATION])

    assert draft.title == long_question[:80]
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `python -m pytest tests/test_wiki_chat_draft.py -v`
Expected: FAIL — 폴백 없이 `InvalidJsonResponseError`/`ValidationError`/`OpenRouterTimeoutError`가 그대로 올라와서 4개 테스트가 예외로 실패

- [ ] **Step 3: `compose_chat_wiki_draft`에 예외 처리 추가**

`src/wiki/chat_wiki.py`의 `compose_chat_wiki_draft` 본문을 아래로 교체(전체 함수):

```python
def _fallback_draft(question: str, answer: str, citations: list[dict]) -> ChatWikiDraft:
    title = question[:80]
    key_evidence = [citation.get("quoted_text") or "" for citation in citations]
    markdown = _build_markdown(title, question, answer, key_evidence, citations)
    return ChatWikiDraft(title=title, markdown=markdown)


def compose_chat_wiki_draft(
    question: str,
    answer: str,
    citations: list[dict],
    *,
    llm_client=None,
) -> ChatWikiDraft:
    settings = get_openrouter_settings()
    user_prompt = _build_chat_wiki_user_prompt(question, answer, citations)

    try:
        if llm_client is not None:
            response_text = llm_client(CHAT_WIKI_SYSTEM_PROMPT, user_prompt, settings.model)
        else:
            response_text = create_json_completion(
                system_prompt=CHAT_WIKI_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                model=settings.model,
            )
        payload = parse_json_response(response_text)
        result = ChatWikiLLMResult.model_validate(payload)
    except (
        MissingApiKeyError,
        OpenRouterApiError,
        OpenRouterTimeoutError,
        InvalidJsonResponseError,
        ValidationError,
    ) as exc:
        logger.warning("chat_wiki_draft_llm_fallback", extra={"error": str(exc)})
        return _fallback_draft(question, answer, citations)

    markdown = _build_markdown(result.title, question, result.answer_summary, result.key_evidence, citations)
    return ChatWikiDraft(title=result.title, markdown=markdown)
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `python -m pytest tests/test_wiki_chat_draft.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/wiki/chat_wiki.py tests/test_wiki_chat_draft.py
git commit -m "feat: compose_chat_wiki_draft LLM 실패 시 코드 폴백 추가"
```

---

### Task 4: `save_message_to_wiki` 통합

**Files:**
- Modify: `src/api/main.py` (import 추가, `save_message_to_wiki` 함수, 현재 라인 276-326 부근 — 함수명으로 다시 찾을 것)
- Modify: `tests/test_chat_sessions.py` (save-to-wiki 관련 테스트, 현재 686-790 부근)

**Interfaces:**
- Consumes: Task 3의 `src.wiki.chat_wiki.compose_chat_wiki_draft`, `src.wiki.chat_wiki.ChatWikiDraft`.

- [ ] **Step 1: 실패하는 테스트로 먼저 바꾸기 — 기존 테스트를 새 동작 기준으로 갱신**

`tests/test_chat_sessions.py` 상단 import에 추가:

```python
from src.wiki import chat_wiki
```

`test_save_to_wiki_with_citations_creates_wiki_version`을 아래로 교체:

```python
def test_save_to_wiki_with_citations_creates_wiki_version(make_client, monkeypatch):
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: PRIVATE_SESSION if uid == OWNER_ID else None)
    monkeypatch.setattr(db, "get_chat_message", lambda mid: ASSISTANT_MESSAGE if mid == ASSISTANT_MESSAGE["id"] else None)
    monkeypatch.setattr(db, "list_message_citations", lambda mid: [SAMPLE_CITATION])
    monkeypatch.setattr(db, "get_preceding_user_message", lambda sid, before: USER_QUESTION)

    compose_calls = []

    def fake_compose_chat_wiki_draft(question, answer, citations):
        compose_calls.append((question, answer, citations))
        return chat_wiki.ChatWikiDraft(title="HBM4 개요", markdown="# HBM4 개요\n\n본문")

    monkeypatch.setattr(main_module, "compose_chat_wiki_draft", fake_compose_chat_wiki_draft)

    captured = {}

    def fake_upsert_wiki_page(workspace_id, slug, title, page_type):
        captured["upsert_args"] = (workspace_id, slug, title, page_type)
        return "page-1"

    def fake_create_wiki_version(draft):
        captured["draft"] = draft
        return "version-1"

    monkeypatch.setattr(main_module, "upsert_wiki_page", fake_upsert_wiki_page)
    monkeypatch.setattr(main_module, "create_wiki_version", fake_create_wiki_version)
    monkeypatch.setattr(main_module, "record_wiki_validation", lambda *a, **kw: None)
    monkeypatch.setattr(main_module, "review_wiki_version", lambda *a, **kw: None)
    monkeypatch.setattr(main_module, "publish_wiki_version", lambda *a, **kw: None)

    res = make_client(OWNER_ID).post(
        f"/chat/sessions/{PRIVATE_SESSION['id']}/messages/{ASSISTANT_MESSAGE['id']}/save-to-wiki"
    )

    assert res.status_code == 200
    expected_slug = f"chat-{ASSISTANT_MESSAGE['id'][:8]}"
    assert res.json() == {"page_id": "page-1", "version_id": "version-1", "slug": expected_slug}

    assert compose_calls == [(USER_QUESTION["content"], ASSISTANT_MESSAGE["content"], [SAMPLE_CITATION])]

    assert captured["upsert_args"] == (WORKSPACE_ID, expected_slug, "HBM4 개요", "issue")

    draft = captured["draft"]
    assert draft.workspace_id == WORKSPACE_ID
    assert draft.slug == expected_slug
    assert draft.page_type == "issue"
    assert draft.markdown == "# HBM4 개요\n\n본문"
    assert len(draft.sources) == 1
    assert draft.sources[0].document_version_id == SAMPLE_CITATION["document_version_id"]
    assert draft.sources[0].claim_text == SAMPLE_CITATION["quoted_text"]
```

`test_save_to_wiki_auto_publishes_version`에는 다음 줄을 다른 `monkeypatch.setattr(main_module, ...)` 줄들 옆에 추가:

```python
    monkeypatch.setattr(
        main_module, "compose_chat_wiki_draft",
        lambda question, answer, citations: chat_wiki.ChatWikiDraft(title="t", markdown="m"),
    )
```

(`test_save_to_wiki_without_citations_returns_400`, `test_save_to_wiki_rejects_llm_fallback_answer`는 `compose_chat_wiki_draft` 호출 이전에 400으로 끝나므로 변경 불필요.)

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `python -m pytest tests/test_chat_sessions.py -v -k save_to_wiki`
Expected: FAIL — `AttributeError: <module 'src.api.main'> does not have the attribute 'compose_chat_wiki_draft'` (아직 import 안 됨) 및 기존 로직 기준 assertion 불일치

- [ ] **Step 3: `src/api/main.py` 수정**

import 블록(`from ..wiki.interface import (...)` 바로 아래)에 추가:

```python
from ..wiki.chat_wiki import compose_chat_wiki_draft
```

`save_message_to_wiki` 함수에서(정확한 현재 코드는 함수를 검색해서 확인):

```python
    user_message = db.get_preceding_user_message(session_id, message["created_at"])
    title = user_message["content"][:80] if user_message else "채팅에서 저장된 답변"
    slug = f"chat-{message_id[:8]}"

    page_id = upsert_wiki_page(workspace_id, slug, title, "issue")
    draft = WikiDraftInput(
        workspace_id=workspace_id,
        slug=slug,
        title=title,
        page_type="issue",
        markdown=message["content"],
        sources=[
```

를 아래로 교체:

```python
    user_message = db.get_preceding_user_message(session_id, message["created_at"])
    question = user_message["content"] if user_message else "채팅에서 저장된 답변"
    chat_draft = compose_chat_wiki_draft(question, message["content"], citations)
    title = chat_draft.title
    slug = f"chat-{message_id[:8]}"

    page_id = upsert_wiki_page(workspace_id, slug, title, "issue")
    draft = WikiDraftInput(
        workspace_id=workspace_id,
        slug=slug,
        title=title,
        page_type="issue",
        markdown=chat_draft.markdown,
        sources=[
```

(이후 `sources=[...]`, `created_by=...`, `generated_by="llm"`, `generator_model=...` 부분은 변경 없음.)

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `python -m pytest tests/test_chat_sessions.py -v -k save_to_wiki`
Expected: PASS (4 passed)

- [ ] **Step 5: 전체 관련 테스트 스위트 실행**

Run: `python -m pytest tests/test_chat_sessions.py tests/test_wiki_chat_draft.py -v`
Expected: 전부 PASS, 회귀 없음

- [ ] **Step 6: 커밋**

```bash
git add src/api/main.py tests/test_chat_sessions.py
git commit -m "feat: save-to-wiki가 compose_chat_wiki_draft로 구조화된 제목/본문을 저장하도록 연결"
```

---

## 최종 확인

- [ ] `python -m pytest tests/ -k "chat_draft or save_to_wiki"` 전체 통과
- [ ] `git log --oneline -4` — 4개 커밋(Task 1~4) 확인
- [ ] `docs/superpowers/specs/2026-08-06-chat-wiki-draft-design.md`의 목표 3가지(구조화된 본문, LLM 실패 시 안전한 폴백, 기존 모델 설정 재사용)가 전부 구현됐는지 스펙과 다시 대조

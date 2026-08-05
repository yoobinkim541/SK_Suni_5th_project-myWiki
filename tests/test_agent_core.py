"""
src/agent/core.py 유닛 테스트 — OpenRouter 호출은 _call_model을 monkeypatch로 대체한다.

실제 LLM/DB 호출 없이, tool-use 라운드 로직(도구 실행 → submit_answer/submit_no_answer
강제 → 최대 라운드 초과 처리)만 검증한다. WikiTools는 MagicMock으로 대체한다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from src.agent.core import MAX_TOOL_ROUNDS, AgentResult, WikiAgent, _strip_orphaned_citation_markers


# ---------------------------------------------------------------------------
# OpenAI 응답 형태를 흉내내는 최소 fake 객체
# ---------------------------------------------------------------------------

class FakeFunctionCall:
    def __init__(self, name: str, arguments: dict):
        self.name = name
        self.arguments = json.dumps(arguments, ensure_ascii=False)


class FakeToolCall:
    def __init__(self, call_id: str, name: str, arguments: dict):
        self.id = call_id
        self.function = FakeFunctionCall(name, arguments)


class FakeMessage:
    def __init__(self, tool_calls=None):
        self.tool_calls = tool_calls or None

    def model_dump(self, exclude_unset: bool = True) -> dict:
        return {"role": "assistant", "tool_calls": self.tool_calls}


class FakeChoice:
    def __init__(self, message: FakeMessage, finish_reason: str):
        self.message = message
        self.finish_reason = finish_reason


class FakeResponse:
    def __init__(self, choices: list[FakeChoice]):
        self.choices = choices


def tool_call_response(*calls: tuple[str, str, dict]) -> FakeResponse:
    """calls: (call_id, tool_name, arguments) 튜플들 — 한 라운드에 여러 도구 호출도 지원."""
    tool_calls = [FakeToolCall(cid, name, args) for cid, name, args in calls]
    return FakeResponse([FakeChoice(FakeMessage(tool_calls=tool_calls), "tool_calls")])


def text_only_response() -> FakeResponse:
    return FakeResponse([FakeChoice(FakeMessage(tool_calls=None), "stop")])


# ---------------------------------------------------------------------------
# WikiTools가 반환하는 DTO 흉내
# ---------------------------------------------------------------------------

@dataclass
class FakeTopic:
    id: str
    slug: str
    title: str
    page_type: str
    status: str


@dataclass
class FakeSource:
    document_version_id: str
    claim_text: str


@dataclass
class FakePage:
    title: str
    markdown: str
    sources: list


@pytest.fixture
def wiki_tools() -> MagicMock:
    return MagicMock()


@pytest.fixture
def agent(wiki_tools: MagicMock) -> WikiAgent:
    return WikiAgent(wiki_tools=wiki_tools, openrouter_client=MagicMock())


# ---------------------------------------------------------------------------
# 정상 흐름: list_wiki_topics → read_wiki_page → submit_answer
# ---------------------------------------------------------------------------

def test_answer_returns_result_with_citations_after_reading_page(agent, wiki_tools, monkeypatch):
    wiki_tools.list_wiki_topics.return_value = [
        FakeTopic(id="1", slug="hbm4", title="HBM4", page_type="technology", status="published")
    ]
    wiki_tools.read_wiki_page.return_value = FakePage(
        title="HBM4",
        markdown="# HBM4\nHBM4는 차세대 메모리다.",
        sources=[FakeSource(document_version_id="doc-1", claim_text="HBM4는 차세대 메모리다.")],
    )

    citation = {
        "document_version_id": "doc-1",
        "wiki_slug": "hbm4",
        "quote": "HBM4는 차세대 메모리다.",
        "relevance_score": 0.9,
    }
    responses = [
        tool_call_response(("call-1", "list_wiki_topics", {})),
        tool_call_response(("call-2", "read_wiki_page", {"slug": "hbm4"})),
        tool_call_response(("call-3", "submit_answer", {"answer": "HBM4는 차세대 메모리다. [1]", "citations": [citation]})),
    ]
    monkeypatch.setattr(agent, "_call_model", MagicMock(side_effect=responses))

    result = agent.answer("HBM4가 뭐야?")

    assert isinstance(result, AgentResult)
    assert result.has_answer is True
    assert result.answer == "HBM4는 차세대 메모리다. [1]"
    assert len(result.citations) == 1
    assert result.citations[0].document_version_id == "doc-1"
    assert result.citations[0].wiki_slug == "hbm4"
    assert result.citations[0].quote == "HBM4는 차세대 메모리다."
    assert result.citations[0].relevance_score == 0.9

    wiki_tools.list_wiki_topics.assert_called_once()
    wiki_tools.read_wiki_page.assert_called_once_with("hbm4")


def test_answer_strips_out_of_range_citation_markers_from_answer_text(agent, wiki_tools, monkeypatch):
    """LLM이 citations는 1건만 제출했는데 본문에는 [1]과 [4]까지 인용한 경우 —
    실사용 데이터에서 확인된 버그(본문 각주 개수와 citations 개수 불일치)의 회귀 테스트.
    citations 범위를 벗어난 번호는 저장 전에 제거해야 죽은 각주가 화면에 안 남는다."""
    wiki_tools.list_wiki_topics.return_value = [
        FakeTopic(id="1", slug="hbm4", title="HBM4", page_type="technology", status="published")
    ]
    wiki_tools.read_wiki_page.return_value = FakePage(
        title="HBM4",
        markdown="# HBM4\nHBM4는 차세대 메모리다.",
        sources=[FakeSource(document_version_id="doc-1", claim_text="HBM4는 차세대 메모리다.")],
    )
    citation = {
        "document_version_id": "doc-1",
        "wiki_slug": "hbm4",
        "quote": "HBM4는 차세대 메모리다.",
        "relevance_score": 0.9,
    }
    responses = [
        tool_call_response(("call-1", "list_wiki_topics", {})),
        tool_call_response(("call-2", "read_wiki_page", {"slug": "hbm4"})),
        tool_call_response(("call-3", "submit_answer", {
            "answer": "HBM4는 차세대 메모리다.[1] 추가로 이런 내용도 있다.[4]",
            "citations": [citation],
        })),
    ]
    monkeypatch.setattr(agent, "_call_model", MagicMock(side_effect=responses))

    result = agent.answer("HBM4가 뭐야?")

    assert result.answer == "HBM4는 차세대 메모리다.[1] 추가로 이런 내용도 있다."


def test_strip_orphaned_citation_markers_keeps_all_when_within_range():
    text = "A[1] B[2] C[3]"
    assert _strip_orphaned_citation_markers(text, citation_count=3) == text


def test_strip_orphaned_citation_markers_removes_out_of_range_numbers():
    text = "첫 문장[1]. 다음 문장[4]."
    assert _strip_orphaned_citation_markers(text, citation_count=1) == "첫 문장[1]. 다음 문장."


def test_strip_orphaned_citation_markers_removes_zero_like_numbers():
    text = "이상함[0]."
    assert _strip_orphaned_citation_markers(text, citation_count=3) == "이상함."


def test_strip_orphaned_citation_markers_handles_no_citations():
    text = "근거 없음[1]."
    assert _strip_orphaned_citation_markers(text, citation_count=0) == "근거 없음."


def test_answer_passes_question_and_history_to_first_call(agent, wiki_tools, monkeypatch):
    # messages는 answer() 내부에서 in-place로 계속 append되는 같은 리스트이므로,
    # 호출 시점 상태를 보려면 그때그때 복사해서 기록해야 한다.
    captured_calls: list[list[dict]] = []

    def fake_call_model(messages):
        captured_calls.append(list(messages))
        return tool_call_response(("call-1", "submit_no_answer", {"reason": "근거 없음"}))

    monkeypatch.setattr(agent, "_call_model", fake_call_model)

    history = [{"role": "user", "content": "이전 질문"}, {"role": "assistant", "content": "이전 답변"}]
    agent.answer("새 질문", history=history)

    sent_messages = captured_calls[0]
    assert sent_messages[0]["role"] == "system"
    assert sent_messages[1] == history[0]
    assert sent_messages[2] == history[1]
    assert sent_messages[-1] == {"role": "user", "content": "새 질문"}


# ---------------------------------------------------------------------------
# 근거 없음 경로
# ---------------------------------------------------------------------------

def test_answer_returns_no_answer_when_model_calls_submit_no_answer(agent, wiki_tools, monkeypatch):
    responses = [tool_call_response(("call-1", "submit_no_answer", {"reason": "위키에 관련 문서 없음"}))]
    monkeypatch.setattr(agent, "_call_model", MagicMock(side_effect=responses))

    result = agent.answer("존재하지 않는 주제에 대해 알려줘")

    assert result.has_answer is False
    assert result.answer is None
    assert result.citations == []
    assert result.no_answer_reason == "위키에 관련 문서 없음"


def test_answer_returns_no_answer_when_model_ends_without_tool_calls(agent, wiki_tools, monkeypatch):
    monkeypatch.setattr(agent, "_call_model", MagicMock(side_effect=[text_only_response()]))

    result = agent.answer("아무 질문")

    assert result.has_answer is False
    assert result.no_answer_reason == "모델이 근거 조회 없이 응답을 종료함"


def test_answer_returns_no_answer_when_read_wiki_page_not_found(agent, wiki_tools, monkeypatch):
    wiki_tools.read_wiki_page.return_value = None
    responses = [
        tool_call_response(("call-1", "read_wiki_page", {"slug": "does-not-exist"})),
        tool_call_response(("call-2", "submit_no_answer", {"reason": "문서를 찾을 수 없음"})),
    ]
    monkeypatch.setattr(agent, "_call_model", MagicMock(side_effect=responses))

    result = agent.answer("존재하지 않는 슬러그 질문")

    assert result.has_answer is False
    wiki_tools.read_wiki_page.assert_called_once_with("does-not-exist")


def test_answer_exhausts_max_rounds_without_submit(agent, wiki_tools, monkeypatch):
    wiki_tools.list_wiki_topics.return_value = []
    responses = [
        tool_call_response((f"call-{i}", "list_wiki_topics", {})) for i in range(MAX_TOOL_ROUNDS)
    ]
    call_mock = MagicMock(side_effect=responses)
    monkeypatch.setattr(agent, "_call_model", call_mock)

    result = agent.answer("계속 조회만 하는 모델")

    assert result.has_answer is False
    assert result.no_answer_reason == "최대 조회 횟수 초과 — 근거 확정 실패"
    assert call_mock.call_count == MAX_TOOL_ROUNDS


# ---------------------------------------------------------------------------
# 근거 검증 — 모델이 citations에 지어낸(또는 규칙 위반인) 값을 넣는 경우
# ---------------------------------------------------------------------------

def test_answer_accepts_citation_missing_optional_wiki_slug(agent, wiki_tools, monkeypatch):
    """submit_answer 도구 스키마는 wiki_slug를 required로 요구하지 않으므로,
    모델이 생략해도 Citation 파싱이 죽으면 안 된다."""
    wiki_tools.read_wiki_page.return_value = FakePage(
        title="HBM4",
        markdown="# HBM4",
        sources=[FakeSource(document_version_id="doc-1", claim_text="HBM4는 차세대 메모리다.")],
    )
    citation_without_wiki_slug = {
        "document_version_id": "doc-1",
        "quote": "HBM4는 차세대 메모리다.",
    }
    responses = [
        tool_call_response(("call-1", "read_wiki_page", {"slug": "hbm4"})),
        tool_call_response(("call-2", "submit_answer", {"answer": "HBM4는 차세대 메모리다.", "citations": [citation_without_wiki_slug]})),
    ]
    monkeypatch.setattr(agent, "_call_model", MagicMock(side_effect=responses))

    result = agent.answer("HBM4가 뭐야?")

    assert result.has_answer is True
    assert result.citations[0].wiki_slug is None


def test_answer_rejects_citation_not_grounded_in_read_page(agent, wiki_tools, monkeypatch):
    """read_wiki_page로 실제 조회한 문서에 없는 document_version_id를 인용하면
    (모델이 지어낸 근거) has_answer=False로 강등해야 한다 — 그대로 저장하면
    message_citations의 document_version_id FK 위반으로 API가 죽는다."""
    wiki_tools.read_wiki_page.return_value = FakePage(
        title="HBM4",
        markdown="# HBM4",
        sources=[FakeSource(document_version_id="doc-1", claim_text="HBM4는 차세대 메모리다.")],
    )
    hallucinated_citation = {
        "document_version_id": "doc-does-not-exist",
        "quote": "지어낸 인용",
    }
    responses = [
        tool_call_response(("call-1", "read_wiki_page", {"slug": "hbm4"})),
        tool_call_response(("call-2", "submit_answer", {"answer": "답변", "citations": [hallucinated_citation]})),
    ]
    monkeypatch.setattr(agent, "_call_model", MagicMock(side_effect=responses))

    result = agent.answer("HBM4가 뭐야?")

    assert result.has_answer is False
    assert "일치하지 않음" in result.no_answer_reason


def test_answer_rejects_empty_citations_list(agent, wiki_tools, monkeypatch):
    """citations가 빈 리스트인 submit_answer는 근거 없이 답한 것과 같으므로 거부한다."""
    responses = [
        tool_call_response(("call-1", "submit_answer", {"answer": "근거 없는 답변", "citations": []})),
    ]
    monkeypatch.setattr(agent, "_call_model", MagicMock(side_effect=responses))

    result = agent.answer("질문")

    assert result.has_answer is False


def test_answer_rejects_citation_with_out_of_range_relevance_score(agent, wiki_tools, monkeypatch):
    """relevance_score는 message_citations에 CHECK(0~1) 제약이 있다 — 범위 밖 값을
    그대로 저장하면 API가 500을 낸다."""
    wiki_tools.read_wiki_page.return_value = FakePage(
        title="HBM4",
        markdown="# HBM4",
        sources=[FakeSource(document_version_id="doc-1", claim_text="HBM4는 차세대 메모리다.")],
    )
    out_of_range_citation = {
        "document_version_id": "doc-1",
        "quote": "HBM4는 차세대 메모리다.",
        "relevance_score": 85,
    }
    responses = [
        tool_call_response(("call-1", "read_wiki_page", {"slug": "hbm4"})),
        tool_call_response(("call-2", "submit_answer", {"answer": "답변", "citations": [out_of_range_citation]})),
    ]
    monkeypatch.setattr(agent, "_call_model", MagicMock(side_effect=responses))

    result = agent.answer("HBM4가 뭐야?")

    assert result.has_answer is False


# ---------------------------------------------------------------------------
# 초기화
# ---------------------------------------------------------------------------

def test_init_uses_env_var_and_openrouter_base_url(monkeypatch, wiki_tools):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    captured = {}

    class FakeOpenAI:
        def __init__(self, base_url, api_key):
            captured["base_url"] = base_url
            captured["api_key"] = api_key

    monkeypatch.setattr("src.agent.core.OpenAI", FakeOpenAI)

    WikiAgent(wiki_tools=wiki_tools)

    assert captured["api_key"] == "test-key"
    assert captured["base_url"] == "https://openrouter.ai/api/v1"


def test_init_raises_when_api_key_missing(monkeypatch, wiki_tools):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(KeyError):
        WikiAgent(wiki_tools=wiki_tools)

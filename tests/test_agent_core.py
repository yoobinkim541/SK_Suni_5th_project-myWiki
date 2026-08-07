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

from src.agent.core import DOCUMENT_TOOLS, MAX_TOOL_ROUNDS, TOOLS, AgentResult, WikiAgent


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
    def __init__(self, tool_calls=None, content=None):
        self.tool_calls = tool_calls or None
        self.content = content

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


def plain_text_response(text: str) -> FakeResponse:
    """_llm_fallback_answer가 받는 형태 — tools 없이 호출하므로 tool_calls 없이 content만 있다."""
    return FakeResponse([FakeChoice(FakeMessage(tool_calls=None, content=text), "stop")])


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


@dataclass
class FakeSearchHit:
    slug: str
    title: str
    score: float


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


def test_answer_uses_search_wiki_pages_tool_to_find_and_read_page(agent, wiki_tools, monkeypatch):
    """제목만 훑는 list_wiki_topics 대신 search_wiki_pages(제목+본문 관련도 검색)로
    페이지를 찾아도 read_wiki_page -> submit_answer 흐름이 그대로 동작해야 한다."""
    wiki_tools.search_wiki_pages.return_value = [FakeSearchHit(slug="hbm4", title="HBM4", score=0.83)]
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
        tool_call_response(("call-1", "search_wiki_pages", {"query": "HBM4 수요"})),
        tool_call_response(("call-2", "read_wiki_page", {"slug": "hbm4"})),
        tool_call_response(("call-3", "submit_answer", {"answer": "HBM4는 차세대 메모리다. [1]", "citations": [citation]})),
    ]
    monkeypatch.setattr(agent, "_call_model", MagicMock(side_effect=responses))

    result = agent.answer("HBM4 수요는 어때?")

    assert result.has_answer is True
    wiki_tools.search_wiki_pages.assert_called_once_with("HBM4 수요")
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


def test_answer_passes_question_and_history_to_first_call(agent, wiki_tools, monkeypatch):
    # messages는 answer() 내부에서 in-place로 계속 append되는 같은 리스트이므로,
    # 호출 시점 상태를 보려면 그때그때 복사해서 기록해야 한다.
    captured_calls: list[list[dict]] = []

    def fake_call_model(messages, use_tools=True, tools=None):
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
    # 위키 단계가 근거 없음이면 원문 단계가 이어서 시도되므로(3단계 파이프라인),
    # 그 단계도 근거 없음으로 끝나는 응답을 준비해야 한다 — 최종 no_answer_reason은
    # 마지막으로 실제 실행된 단계(원문 단계)의 사유가 된다.
    responses = [
        tool_call_response(("call-1", "submit_no_answer", {"reason": "위키에 관련 문서 없음"})),
        tool_call_response(("call-2", "submit_no_answer", {"reason": "원문에도 관련 문서 없음"})),
    ]
    monkeypatch.setattr(agent, "_call_model", MagicMock(side_effect=responses))

    result = agent.answer("존재하지 않는 주제에 대해 알려줘")

    assert result.has_answer is False
    assert result.answer is None
    assert result.citations == []
    assert result.no_answer_reason == "원문에도 관련 문서 없음"


def test_answer_returns_no_answer_when_model_ends_without_tool_calls(agent, wiki_tools, monkeypatch):
    # 위키 단계가 이 사유로 끝나면 원문 단계도 실행되므로, 검증하려는 "도구 호출 없이
    # 텍스트로 종료" 동작이 최종 결과에도 그대로 남게 원문 단계도 같은 방식으로 끝낸다.
    monkeypatch.setattr(
        agent, "_call_model", MagicMock(side_effect=[text_only_response(), text_only_response()])
    )

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
    """MAX_TOOL_ROUNDS 초과 시 정확히 "최대 조회 횟수 초과 — 근거 확정 실패" 사유로
    끝나야 한다는 게 이 테스트의 핵심 신호다. 3단계 파이프라인에서 그 신호가 최종
    결과에도 그대로 남으려면(fix round 1에서 이 사유 문자열이 다른 테스트 어디에도
    안 남고 사라졌던 문제), 원문 단계도 위키 단계와 동일하게 라운드를 소진시켜
    같은 방식(같은 사유 문자열)으로 끝나게 해야 한다."""
    wiki_tools.list_wiki_topics.return_value = []
    wiki_tools.search_documents.return_value = []
    responses = [
        tool_call_response((f"call-{i}", "list_wiki_topics", {})) for i in range(MAX_TOOL_ROUNDS)
    ] + [
        # 위키 단계가 라운드 초과로 끝나면 원문 단계가 이어서 시도된다 — 원문 단계도
        # search_documents만 반복 호출하고 끝내 submit하지 않아 동일하게 라운드를
        # 소진시킨다(내용은 중요치 않음, 소진 자체가 목적).
        tool_call_response((f"call-doc-{i}", "search_documents", {"query": "x"}))
        for i in range(MAX_TOOL_ROUNDS)
    ]
    call_mock = MagicMock(side_effect=responses)
    monkeypatch.setattr(agent, "_call_model", call_mock)

    result = agent.answer("계속 조회만 하는 모델")

    assert result.has_answer is False
    assert result.no_answer_reason == "최대 조회 횟수 초과 — 근거 확정 실패"
    # MAX_TOOL_ROUNDS번은 _wiki_answer(라운드 초과), 다시 MAX_TOOL_ROUNDS번은
    # _document_answer(마찬가지로 라운드 초과), +1번은 answer()가 이어서 시도하는
    # _llm_fallback_answer의 호출 — side_effect 목록이 그만큼만 있어 마지막 호출은
    # StopIteration으로 실패하고(폴백 실패로 처리) 원문 단계의 no_answer 결과가
    # 그대로 반환된다.
    assert call_mock.call_count == (MAX_TOOL_ROUNDS * 2) + 1


# ---------------------------------------------------------------------------
# 실사용 크래시 — OpenRouter 응답 자체가 비정상인 경우
# ---------------------------------------------------------------------------

def test_answer_recovers_from_malformed_tool_call_json(agent, wiki_tools, monkeypatch):
    """실측 버그: 모델이 tool call 인자로 잘린(비정상 종료된) JSON을 주면 json.loads가
    JSONDecodeError를 던져 answer() 전체가 그대로 죽었다. 이 tool_call만 실패로 보고
    라운드를 이어가야 한다(모델이 다음 라운드에 다시 시도할 기회를 얻는다)."""
    bad_call = FakeToolCall("call-bad", "search_wiki_pages", {"query": "x"})
    bad_call.function.arguments = '{"query": "SK하'  # 잘린 JSON
    responses = [
        FakeResponse([FakeChoice(FakeMessage(tool_calls=[bad_call]), "tool_calls")]),
        tool_call_response(("call-2", "submit_no_answer", {"reason": "근거 없음"})),
    ]
    monkeypatch.setattr(agent, "_call_model", MagicMock(side_effect=responses))

    result = agent.answer("SK하이닉스 ADR 상장 공시가 뭐야?")

    assert result.has_answer is False
    wiki_tools.search_wiki_pages.assert_not_called()


def test_call_model_falls_back_when_primary_returns_no_choices(agent, wiki_tools):
    """실측 버그: OpenRouter가 200으로 choices=None인 응답을 줄 때가 있다(에러를
    본문에만 담고 예외를 안 던짐) — response.choices[0]에서 TypeError로 크래시했다.
    choices가 비어 있으면 실패로 취급해 기존 폴백 모델 재시도 경로를 타야 한다."""

    class EmptyChoicesResponse:
        choices = None

    agent.client.chat.completions.create = MagicMock(
        side_effect=[
            EmptyChoicesResponse(),
            tool_call_response(("call-1", "submit_no_answer", {"reason": "근거 없음"})),
        ]
    )

    result = agent.answer("질문")

    # _wiki_answer가 근거 없음으로 끝나면 _llm_fallback_answer가 이어서 시도되므로,
    # 여기서 확인할 건 "크래시 없이 폴백 모델 재시도 경로를 탔는가"이지 정확한 호출
    # 횟수가 아니다 — primary 실패 -> fallback 성공(submit_no_answer)까지 최소 2번은
    # 호출됐어야 한다.
    assert result.has_answer is False
    assert agent.client.chat.completions.create.call_count >= 2


def test_answer_falls_back_to_llm_when_wiki_answer_raises(agent, wiki_tools, monkeypatch):
    """_wiki_answer 도중 예외(OpenRouter 호출 실패 등)가 나도 500 성격의 크래시로 새지
    않고 근거 없음으로 강등한 뒤, 원문 그라운딩 단계도 정직하게 시도되고(마찬가지로
    근거 없음), 최종적으로 LLM 폴백을 시도해야 한다.

    fake_call_model이 tools 키워드 인자를 받지 않던 예전 버전은 _document_answer가
    tools=DOCUMENT_TOOLS로 호출할 때 TypeError를 던졌고, 그 예외는 _safe_run이 잡아서
    문서 단계를 조용히 "근거 없음"으로 강등시켰다 — 결과 assert는 우연히 여전히
    성립해서(폴백까지 이어지므로) 문서 단계가 한 번도 실행되지 못한 채로 그린이었다.
    이제 tools 인자를 받되(값은 안 씀, use_tools로만 분기) 문서 단계도 실제로
    use_tools=True로 호출되게 해서 그 단계도 정직하게 예외 -> 근거 없음을 거치게 한다."""

    def fake_call_model(messages, use_tools=True, tools=None):
        if use_tools:
            raise RuntimeError("OpenRouter returned no choices")
        return plain_text_response("일반 지식 답변")

    monkeypatch.setattr(agent, "_call_model", fake_call_model)

    result = agent.answer("질문")

    assert result.has_answer is True
    assert result.is_llm_fallback is True
    assert result.answer == "일반 지식 답변"


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


def test_document_answer_passes_document_tools_not_wiki_tools_to_model(agent, wiki_tools, monkeypatch):
    """_document_answer가 실수로 위키용 TOOLS를 모델에 넘기면(예: _run_grounded_answer의
    tools 인자 배선이 잘못 꼬이면) 모델이 search_wiki_pages/read_wiki_page 같은 위키
    도구를 호출하게 되는데, 이 브랜치 이전 테스트들은 전부 _call_model을 통째로
    monkeypatch해서 실제로 전달된 tools kwarg 값을 검증하지 않았다 — 이 테스트가
    그 공백을 메운다. 위키 단계(첫 라운드) 호출들의 tools는 TOOLS와 동일 객체여야
    하고, 원문 단계(위키가 근거 없음으로 끝난 뒤 이어지는 라운드) 호출들의 tools는
    DOCUMENT_TOOLS와 동일 객체여야 한다(위키용 TOOLS가 아니어야 한다)."""
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
    captured_tools: list[list[dict] | None] = []

    def capturing_call_model(messages, use_tools=True, tools=None):
        captured_tools.append(tools)
        return responses[len(captured_tools) - 1]

    monkeypatch.setattr(agent, "_call_model", capturing_call_model)

    result = agent.answer("SK하이닉스 ADR 상장 공시가 뭐야?")

    assert result.has_answer is True
    assert len(captured_tools) == 4
    # 라운드 1(call-1)은 위키 단계 — tools는 위키용 TOOLS와 동일 객체여야 한다.
    assert captured_tools[0] is TOOLS
    # 라운드 2~4(call-2, call-3, call-4)는 원문 단계 — tools는 DOCUMENT_TOOLS와 동일
    # 객체여야 하고, 위키용 TOOLS가 아니어야 한다.
    assert captured_tools[1] is DOCUMENT_TOOLS
    assert captured_tools[2] is DOCUMENT_TOOLS
    assert captured_tools[3] is DOCUMENT_TOOLS
    for tools_arg in captured_tools[1:]:
        assert tools_arg is not TOOLS


def test_document_answer_forces_wiki_slug_to_none_even_if_model_sends_one(agent, wiki_tools, monkeypatch):
    """원문 문서 단계는 위키 페이지에서 나온 근거가 아니므로 citations[].wiki_slug는
    항상 None이어야 한다. DOCUMENT_TOOLS의 submit_answer 스키마는 위키 단계와
    공유(재사용)하느라 wiki_slug 필드 자체를 막지 못하므로, 모델이 실수로 wiki_slug를
    채워 보내도 코드가 강제로 지워야 한다 — 프롬프트만으로는 강제되지 않는다."""
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
    citation_with_wiki_slug = {
        "document_version_id": "doc-ver-1",
        "wiki_slug": "hbm4",  # 모델이 실수로 채워 보낸 위키 슬러그 — 원문 단계엔 있으면 안 됨
        "quote": "SK하이닉스가 나스닥에 ADR을 상장했다.",
        "relevance_score": 0.9,
    }
    responses = [
        tool_call_response(("call-1", "submit_no_answer", {"reason": "위키에 관련 문서 없음"})),
        tool_call_response(("call-2", "search_documents", {"query": "SK하이닉스 ADR 상장"})),
        tool_call_response(("call-3", "read_document", {"document_version_id": "doc-ver-1"})),
        tool_call_response(("call-4", "submit_answer", {
            "answer": "SK하이닉스가 나스닥에 ADR을 상장했다. [1]",
            "citations": [citation_with_wiki_slug],
        })),
    ]
    monkeypatch.setattr(agent, "_call_model", MagicMock(side_effect=responses))

    result = agent.answer("SK하이닉스 ADR 상장 공시가 뭐야?")

    assert result.has_answer is True
    assert len(result.citations) == 1
    assert result.citations[0].wiki_slug is None


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


# ---------------------------------------------------------------------------
# LLM 폴백 — 위키 근거를 못 찾으면(has_answer=False) 일반 지식으로 한 번 더 시도한다.
# 위키 citations와 절대 헷갈리면 안 되므로 is_llm_fallback=True로 명확히 구분한다.
# ---------------------------------------------------------------------------

def test_answer_falls_back_to_llm_when_no_wiki_answer(agent, wiki_tools, monkeypatch):
    responses = [
        tool_call_response(("call-1", "submit_no_answer", {"reason": "위키에 관련 문서 없음"})),
        # 위키 다음 원문 단계도 근거 없음으로 끝나야 그 뒤에 llm 폴백이 시도된다.
        tool_call_response(("call-2", "submit_no_answer", {"reason": "원문에도 관련 문서 없음"})),
        plain_text_response("HBM은 여러 D램을 수직으로 쌓아 대역폭을 늘린 고대역폭 메모리다."),
    ]
    monkeypatch.setattr(agent, "_call_model", MagicMock(side_effect=responses))

    result = agent.answer("HBM이 뭐야?")

    assert result.has_answer is True
    assert result.is_llm_fallback is True
    assert result.citations == []
    assert result.answer == "HBM은 여러 D램을 수직으로 쌓아 대역폭을 늘린 고대역폭 메모리다."
    assert result.no_answer_reason is None


def test_answer_does_not_fall_back_when_wiki_answer_found(agent, wiki_tools, monkeypatch):
    """근거를 이미 찾았으면 _llm_fallback_answer는 아예 호출되지 않아야 한다."""
    wiki_tools.read_wiki_page.return_value = FakePage(
        title="HBM4",
        markdown="# HBM4",
        sources=[FakeSource(document_version_id="doc-1", claim_text="HBM4는 차세대 메모리다.")],
    )
    citation = {"document_version_id": "doc-1", "quote": "HBM4는 차세대 메모리다."}
    responses = [
        tool_call_response(("call-1", "read_wiki_page", {"slug": "hbm4"})),
        tool_call_response(("call-2", "submit_answer", {"answer": "답변 [1]", "citations": [citation]})),
    ]
    call_mock = MagicMock(side_effect=responses)
    monkeypatch.setattr(agent, "_call_model", call_mock)

    result = agent.answer("HBM4가 뭐야?")

    assert result.has_answer is True
    assert result.is_llm_fallback is False
    assert call_mock.call_count == 2  # 폴백 호출이 추가로 없었다


def test_llm_fallback_answer_calls_model_without_tools(agent, wiki_tools, monkeypatch):
    """_llm_fallback_answer는 WikiTools/citations를 아예 안 주려는 것이므로
    use_tools=False로 호출해야 한다."""
    responses = [
        tool_call_response(("call-1", "submit_no_answer", {"reason": "근거 없음"})),
        plain_text_response("일반 지식 답변"),
    ]
    call_mock = MagicMock(side_effect=responses)
    monkeypatch.setattr(agent, "_call_model", call_mock)

    agent.answer("아무 질문")

    fallback_call = call_mock.call_args_list[-1]
    assert fallback_call.kwargs.get("use_tools") is False


def test_answer_keeps_no_answer_when_llm_fallback_raises(agent, wiki_tools, monkeypatch):
    """폴백 호출 자체가 실패하면(예외) 폴백 실패를 감추지 않고 원래의 근거 없음
    결과를 그대로 낸다 — 거짓 답을 주면 안 된다.

    fake_call_model의 시그니처에 tools 키워드를 추가한 건 순수 호환성 수정이다 —
    _document_answer는 tools=DOCUMENT_TOOLS를 명시적으로 넘기므로 이 kwarg를 받아야
    한다. 값 자체는 안 쓰므로(use_tools만으로 분기) 원문 단계도 위키 단계와 동일하게
    submit_no_answer("근거 없음")로 끝나 최종 사유 문자열은 바뀌지 않는다."""
    def fake_call_model(messages, use_tools=True, tools=None):
        if use_tools:
            return tool_call_response(("call-1", "submit_no_answer", {"reason": "근거 없음"}))
        raise RuntimeError("OpenRouter 호출 실패")

    monkeypatch.setattr(agent, "_call_model", fake_call_model)

    result = agent.answer("아무 질문")

    assert result.has_answer is False
    assert result.is_llm_fallback is False
    assert result.no_answer_reason == "근거 없음"


def test_answer_keeps_no_answer_when_llm_fallback_returns_empty_text(agent, wiki_tools, monkeypatch):
    """폴백 모델이 빈 응답을 주면 근거 없음으로 취급하고, 있지도 않은 답을 만들지 않는다."""
    responses = [
        tool_call_response(("call-1", "submit_no_answer", {"reason": "근거 없음"})),
        # 원문 단계도 근거 없음으로 끝나야 llm 폴백이 시도된다. 폴백이 빈 텍스트를
        # 주면 최종 결과는 마지막으로 실행된 단계(원문 단계)의 사유로 남는다.
        tool_call_response(("call-2", "submit_no_answer", {"reason": "원문에도 관련 문서 없음"})),
        plain_text_response("   "),
    ]
    monkeypatch.setattr(agent, "_call_model", MagicMock(side_effect=responses))

    result = agent.answer("아무 질문")

    assert result.has_answer is False
    assert result.is_llm_fallback is False
    assert result.no_answer_reason == "원문에도 관련 문서 없음"


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
        # 위키 단계가 지어낸 근거로 거부되면 원문 단계가 이어서 시도된다 — 검증하려는
        # "그라운딩 안 된 citation은 거부된다"는 동작 자체가 최종 결과에도 남게, 원문
        # 단계도 동일하게 그라운딩 안 된 citation을 제출해 같은 사유로 거부시킨다.
        tool_call_response(("call-3", "submit_answer", {"answer": "답변", "citations": [hallucinated_citation]})),
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


def test_answer_does_not_crash_when_citation_missing_required_quote(agent, wiki_tools, monkeypatch):
    """실측 버그: 폴백 모델이 citations 항목에 필수 필드 quote를 빼먹고 응답하면
    Citation(**c)가 TypeError를 던져 answer() 전체가 그대로 죽었다(위키 dedup 이후
    라운드 수가 줄면서 실사용 중 재현됨). 지어낸/형식이 어긋난 근거로 보고 근거 없음으로
    강등해야 한다 — 예외가 새 나가면 안 된다."""
    wiki_tools.read_wiki_page.return_value = FakePage(
        title="HBM4",
        markdown="# HBM4",
        sources=[FakeSource(document_version_id="doc-1", claim_text="HBM4는 차세대 메모리다.")],
    )
    citation_missing_quote = {"document_version_id": "doc-1"}
    responses = [
        tool_call_response(("call-1", "read_wiki_page", {"slug": "hbm4"})),
        tool_call_response(("call-2", "submit_answer", {"answer": "답변", "citations": [citation_missing_quote]})),
        # 위키 단계가 필수 필드 누락으로 거부되면 원문 단계가 이어서 시도된다 — 검증
        # 하려는 "크래시 없이 근거 없음으로 강등된다"는 동작이 최종 결과에도 남게,
        # 원문 단계도 동일하게 필수 필드 누락 citation을 제출해 같은 사유로 거부시킨다.
        tool_call_response(("call-3", "submit_answer", {"answer": "답변", "citations": [citation_missing_quote]})),
    ]
    monkeypatch.setattr(agent, "_call_model", MagicMock(side_effect=responses))

    result = agent.answer("HBM4가 뭐야?")

    assert result.has_answer is False
    assert "일치하지 않음" in result.no_answer_reason


def test_answer_does_not_crash_when_relevance_score_is_not_numeric(agent, wiki_tools, monkeypatch):
    """relevance_score가 숫자가 아니면 _is_grounded의 범위 비교(0.0 <= score <= 1.0)에서
    TypeError가 난다 — 이 경우도 크래시 없이 근거 없음으로 처리돼야 한다."""
    wiki_tools.read_wiki_page.return_value = FakePage(
        title="HBM4",
        markdown="# HBM4",
        sources=[FakeSource(document_version_id="doc-1", claim_text="HBM4는 차세대 메모리다.")],
    )
    citation_with_non_numeric_score = {
        "document_version_id": "doc-1",
        "quote": "HBM4는 차세대 메모리다.",
        "relevance_score": "높음",
    }
    responses = [
        tool_call_response(("call-1", "read_wiki_page", {"slug": "hbm4"})),
        tool_call_response(("call-2", "submit_answer", {"answer": "답변", "citations": [citation_with_non_numeric_score]})),
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

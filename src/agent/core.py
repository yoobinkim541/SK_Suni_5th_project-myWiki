"""
Agent 핵심 로직 — Claude tool-use로 위키를 "직접 읽게" 만든다 (Karpathy LLM Wiki 패턴).

동작 순서:
1. 모델에게 list_wiki_topics / read_wiki_page 두 개의 조회 도구만 준다.
2. 모델이 필요한 만큼 위키 페이지를 읽어보게 하고 (여러 번 호출 가능),
3. 답을 낼 수 있으면 submit_answer(근거 포함)를, 근거가 없으면 submit_no_answer를
   호출하게 강제한다 — 이게 "근거 없으면 답을 만들지 않는다"를 코드로 강제하는 부분이다.

이 파일은 LLM provider에 의존하는 부분(_call_model)만 anthropic SDK를 쓰고,
나머지 로직(도구 실행, 반복, 결과 조립)은 provider와 무관하게 짜여 있어서
나중에 OpenRouter 등으로 바꿔도 _call_model만 교체하면 된다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

import anthropic

from .wiki_tools import WikiTools

MODEL_NAME = "claude-haiku-4-5-20251001"  # 비용 우선. 품질 필요하면 sonnet으로 교체
MAX_TOOL_ROUNDS = 6  # 무한루프 방지

SYSTEM_PROMPT = """\
너는 myWiki의 답변 Agent다. 규칙:
1. 반드시 read_wiki_page로 실제 읽은 위키 문서 내용만 근거로 답변해라.
   너의 사전 지식이나 추측으로 빈틈을 채우지 마라.
2. list_wiki_topics로 먼저 관련 있어 보이는 문서를 찾고, read_wiki_page로 내용을 확인해라.
   필요하면 여러 문서를 읽어도 된다.
3. 답을 뒷받침할 근거를 찾았으면 submit_answer를 호출해라. 문장마다 어떤 근거(citations)를
   썼는지 반드시 포함하고, citations의 document_version_id는 read_wiki_page 결과에서
   본 sources 중에서만 골라라 (지어내지 마라).
4. 근거를 찾지 못했거나, 질문에 답하기에 근거가 불충분하거나 상호 확인이 안 되면
   submit_answer 대신 반드시 submit_no_answer를 호출해라. 애매하게 답하지 말고 이 상태로
   명시적으로 전환해라.
5. 톤은 직접적이고 전문적으로, 가벼운 대화체는 쓰지 마라.
"""

TOOLS = [
    {
        "name": "list_wiki_topics",
        "description": "현재 workspace에 축적된 위키 문서 목록(슬러그·제목·유형)을 반환한다.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_wiki_page",
        "description": "특정 슬러그의 위키 문서 본문과, 그 안의 각 주장을 뒷받침하는 원문 근거 목록을 반환한다.",
        "input_schema": {
            "type": "object",
            "properties": {"slug": {"type": "string", "description": "wiki_pages.slug"}},
            "required": ["slug"],
        },
    },
    {
        "name": "submit_answer",
        "description": "충분한 근거를 찾았을 때 최종 답변과 근거 목록을 제출한다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "answer": {"type": "string", "description": "근거 번호 표기(예: [1])를 포함한 답변 본문"},
                "citations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "document_version_id": {"type": "string"},
                            "wiki_slug": {"type": "string"},
                            "quote": {"type": "string"},
                            "relevance_score": {"type": "number"},
                        },
                        "required": ["document_version_id", "quote"],
                    },
                },
            },
            "required": ["answer", "citations"],
        },
    },
    {
        "name": "submit_no_answer",
        "description": "축적된 위키에서 답을 뒷받침할 근거를 찾지 못했을 때 호출한다.",
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
        },
    },
]


@dataclass
class Citation:
    document_version_id: str
    wiki_slug: Optional[str]
    quote: str
    relevance_score: Optional[float] = None


@dataclass
class AgentResult:
    has_answer: bool
    answer: Optional[str] = None
    citations: list[Citation] = field(default_factory=list)
    no_answer_reason: Optional[str] = None
    model_name: str = MODEL_NAME


class WikiAgent:
    def __init__(self, wiki_tools: WikiTools, anthropic_client: Optional[anthropic.Anthropic] = None):
        self.wiki_tools = wiki_tools
        self.client = anthropic_client or anthropic.Anthropic()

    def answer(self, question: str, history: Optional[list[dict]] = None) -> AgentResult:
        messages: list[dict] = list(history or [])
        messages.append({"role": "user", "content": question})

        for _ in range(MAX_TOOL_ROUNDS):
            response = self._call_model(messages)

            if response.stop_reason != "tool_use":
                # 모델이 도구 없이 텍스트로만 끝냈다면, 규칙 위반이므로 근거 없음으로 처리
                return AgentResult(has_answer=False, no_answer_reason="모델이 근거 조회 없이 응답을 종료함")

            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            terminal_result: Optional[AgentResult] = None

            for block in response.content:
                if block.type != "tool_use":
                    continue

                if block.name == "list_wiki_topics":
                    topics = self.wiki_tools.list_wiki_topics()
                    output = [t.__dict__ for t in topics]
                    tool_results.append(self._tool_result(block.id, output))

                elif block.name == "read_wiki_page":
                    page = self.wiki_tools.read_wiki_page(block.input["slug"])
                    if page is None:
                        tool_results.append(self._tool_result(block.id, {"error": "문서를 찾을 수 없음"}))
                    else:
                        tool_results.append(self._tool_result(block.id, {
                            "title": page.title,
                            "markdown": page.markdown,
                            "sources": [s.__dict__ for s in page.sources],
                        }))

                elif block.name == "submit_answer":
                    citations = [Citation(**c) for c in block.input.get("citations", [])]
                    terminal_result = AgentResult(
                        has_answer=True, answer=block.input["answer"], citations=citations,
                    )
                    tool_results.append(self._tool_result(block.id, {"status": "recorded"}))

                elif block.name == "submit_no_answer":
                    terminal_result = AgentResult(
                        has_answer=False, no_answer_reason=block.input["reason"],
                    )
                    tool_results.append(self._tool_result(block.id, {"status": "recorded"}))

            if terminal_result is not None:
                return terminal_result

            messages.append({"role": "user", "content": tool_results})

        return AgentResult(has_answer=False, no_answer_reason="최대 조회 횟수 초과 — 근거 확정 실패")

    def _call_model(self, messages: list[dict]):
        return self.client.messages.create(
            model=MODEL_NAME,
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

    @staticmethod
    def _tool_result(tool_use_id: str, output: object) -> dict:
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": json.dumps(output, ensure_ascii=False, default=str),
        }

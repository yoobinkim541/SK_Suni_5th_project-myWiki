"""
Agent 핵심 로직 — LLM tool-use로 위키를 "직접 읽게" 만든다 (Karpathy LLM Wiki 패턴).

동작 순서:
1. 모델에게 list_wiki_topics / read_wiki_page 두 개의 조회 도구만 준다.
2. 모델이 필요한 만큼 위키 페이지를 읽어보게 하고 (여러 번 호출 가능),
3. 답을 낼 수 있으면 submit_answer(근거 포함)를, 근거가 없으면 submit_no_answer를
   호출하게 강제한다 — 이게 "근거 없으면 답을 만들지 않는다"를 코드로 강제하는 부분이다.

이 파일은 LLM provider에 의존하는 부분(_call_model)만 OpenRouter(OpenAI 호환 API)를 쓰고,
나머지 로직(도구 실행, 반복, 결과 조립)은 provider와 무관하게 짜여 있다.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

from openai import OpenAI

from ..wiki.citation_text import strip_orphaned_citation_markers
from .wiki_tools import WikiTools

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# 팀 확정 모델(analysis/classifier.py, report/composer.py와 통일)
MODEL_NAME = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-v4-flash")
# 기본 모델 호출이 실패하면 이 모델로 한 번 더 시도한다.
FALLBACK_MODEL_NAME = os.getenv("OPENROUTER_FALLBACK_MODEL", "").strip() or "deepseek/deepseek-v4-pro"
MAX_TOOL_ROUNDS = 10  # 무한루프 방지 — 실사용 로그에서 6일 때 답변의 17%가 라운드 초과로
# 근거 없음 처리됐다(2026-08-05, chat_messages 66건 중 11건). search_wiki_pages 도입으로
# 첫 라운드부터 관련도 순 후보를 받게 됐지만, 복합 질문의 교차검증(여러 페이지 읽기)엔
# 여전히 여유가 필요해 상한을 올린다.

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
너는 myWiki의 답변 Agent다. 규칙:
1. 반드시 read_wiki_page로 실제 읽은 위키 문서 내용만 근거로 답변해라.
   너의 사전 지식이나 추측으로 빈틈을 채우지 마라.
2. 관련 문서를 찾을 때는 search_wiki_pages를 먼저 써라 — 질문의 핵심 키워드로 제목뿐
   아니라 본문까지 훑어 관련도 순으로 찾아준다. list_wiki_topics(전체 목록)는 검색어로
   뭘 넣어야 할지 모를 때 훑어보는 용도로만 보조적으로 써라. 찾은 slug는 read_wiki_page로
   내용을 확인해라. 필요하면 여러 문서를 읽어도 된다.
3. 답을 뒷받침할 근거를 찾았으면 submit_answer를 호출해라. 문장마다 어떤 근거(citations)를
   썼는지 반드시 포함하고, citations의 document_version_id는 read_wiki_page 결과에서
   본 sources 중에서만 골라라 (지어내지 마라). 답변 본문에 쓰는 근거 번호 [N]은 반드시
   citations 배열의 N번째(1부터 시작) 항목과 정확히 대응해야 한다 — citations에 없는
   번호는 절대 쓰지 마라.
4. 근거를 찾지 못했거나, 질문에 답하기에 근거가 불충분하거나 상호 확인이 안 되면
   submit_answer 대신 반드시 submit_no_answer를 호출해라. 애매하게 답하지 말고 이 상태로
   명시적으로 전환해라.
5. 톤은 직접적이고 전문적으로, 가벼운 대화체는 쓰지 마라.
6. 이전 대화 히스토리에 관련 내용이 있어 보여도, 그 텍스트 자체를 근거로 쓰지 마라.
   짧은 후속 질문("그러면~", "그건 뭐야?" 등)이라도 이번 턴에 read_wiki_page로 다시
   조회해서 확인한 내용만 근거로 인정된다.
"""

# 위키 근거로 답을 못 찾았을 때(has_answer=False)만 쓰는 별도 시스템 프롬프트.
# WikiTools/citations를 아예 안 주는 일반 지식 답변이라, 절대 위키 출처처럼 보이면
# 안 된다 — AgentResult.is_llm_fallback으로 프론트가 명확히 다른 라벨을 붙인다.
LLM_FALLBACK_SYSTEM_PROMPT = """\
너는 반도체/AI 산업 일반 지식으로 간결하게 답하는 보조 도우미다. 위키 근거 없이
네 일반 지식으로만 답하고, 확실하지 않으면 그렇다고 말해라.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_wiki_topics",
            "description": "현재 workspace에 축적된 위키 문서 목록(슬러그·제목·유형)을 반환한다.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_wiki_pages",
            "description": (
                "질문 키워드로 위키 문서를 제목+본문 관련도 순으로 찾는다. "
                "list_wiki_topics보다 이 도구를 먼저 써라 — 제목 문자열이 질문과 "
                "겹치지 않아도 본문 내용으로 찾아준다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "질문에서 뽑은 검색 키워드"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_wiki_page",
            "description": "특정 슬러그의 위키 문서 본문과, 그 안의 각 주장을 뒷받침하는 원문 근거 목록을 반환한다.",
            "parameters": {
                "type": "object",
                "properties": {"slug": {"type": "string", "description": "wiki_pages.slug"}},
                "required": ["slug"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_answer",
            "description": "충분한 근거를 찾았을 때 최종 답변과 근거 목록을 제출한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "answer": {
                        "type": "string",
                        "description": (
                            "근거 번호 표기(예: [1])를 포함한 답변 본문 — [N]은 citations 배열의"
                            " N번째(1부터) 항목과 정확히 일치해야 하며, citations에 없는 번호는"
                            " 쓰지 말 것"
                        ),
                    },
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
    },
    {
        "type": "function",
        "function": {
            "name": "submit_no_answer",
            "description": "축적된 위키에서 답을 뒷받침할 근거를 찾지 못했을 때 호출한다.",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        },
    },
]


@dataclass
class Citation:
    document_version_id: str
    quote: str
    wiki_slug: Optional[str] = None
    relevance_score: Optional[float] = None


@dataclass
class AgentResult:
    has_answer: bool
    answer: Optional[str] = None
    citations: list[Citation] = field(default_factory=list)
    no_answer_reason: Optional[str] = None
    model_name: str = MODEL_NAME
    # True면 위키 근거 없이 일반 LLM 지식으로 답한 것 — 위키 citations가 있는 답변과
    # 절대 헷갈리면 안 돼서(citations는 항상 빈 리스트), 프론트가 이 값으로 별도 라벨을 붙인다.
    is_llm_fallback: bool = False


class WikiAgent:
    def __init__(self, wiki_tools: WikiTools, openrouter_client: Optional[OpenAI] = None):
        self.wiki_tools = wiki_tools
        self.client = openrouter_client or OpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=os.environ["OPENROUTER_API_KEY"],
        )

    def answer(self, question: str, history: Optional[list[dict]] = None) -> AgentResult:
        """위키 근거로 먼저 답을 찾고(_wiki_answer), 못 찾으면 일반 LLM 지식으로
        한 번 더 시도한다(_llm_fallback_answer) — 이때는 반드시 is_llm_fallback=True로
        표시해서 위키 근거 답변과 구분되게 한다. 폴백마저 실패하면(예외) 원래의
        has_answer=False 결과를 그대로 낸다 — 폴백 실패를 감추고 거짓 답을 주면 안 된다."""
        result = self._wiki_answer(question, history)
        if result.has_answer:
            return result
        fallback = self._llm_fallback_answer(question, history)
        return fallback if fallback is not None else result

    def _llm_fallback_answer(
        self, question: str, history: Optional[list[dict]] = None
    ) -> Optional[AgentResult]:
        messages: list[dict] = [{"role": "system", "content": LLM_FALLBACK_SYSTEM_PROMPT}]
        messages.extend(history or [])
        messages.append({"role": "user", "content": question})
        try:
            response = self._call_model(messages, use_tools=False)
            text = (response.choices[0].message.content or "").strip()
        except Exception:  # noqa: BLE001 - 폴백은 실패해도 원래 no_answer 결과로 조용히 넘어간다
            return None
        if not text:
            return None
        return AgentResult(
            has_answer=True, answer=text, citations=[], is_llm_fallback=True, model_name=MODEL_NAME,
        )

    def _wiki_answer(self, question: str, history: Optional[list[dict]] = None) -> AgentResult:
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(history or [])
        messages.append({"role": "user", "content": question})
        seen_document_version_ids: set[str] = set()

        for _ in range(MAX_TOOL_ROUNDS):
            response = self._call_model(messages)
            choice = response.choices[0]
            message = choice.message

            if choice.finish_reason != "tool_calls" or not message.tool_calls:
                # 모델이 도구 없이 텍스트로만 끝냈다면, 규칙 위반이므로 근거 없음으로 처리
                return AgentResult(has_answer=False, no_answer_reason="모델이 근거 조회 없이 응답을 종료함")

            messages.append(message.model_dump(exclude_unset=True))
            terminal_result: Optional[AgentResult] = None

            for tool_call in message.tool_calls:
                name = tool_call.function.name
                args = json.loads(tool_call.function.arguments or "{}")

                if name == "list_wiki_topics":
                    topics = self.wiki_tools.list_wiki_topics()
                    output = [t.__dict__ for t in topics]
                    messages.append(self._tool_result(tool_call.id, output))

                elif name == "search_wiki_pages":
                    hits = self.wiki_tools.search_wiki_pages(args["query"])
                    output = [h.__dict__ for h in hits]
                    messages.append(self._tool_result(tool_call.id, output))

                elif name == "read_wiki_page":
                    page = self.wiki_tools.read_wiki_page(args["slug"])
                    if page is None:
                        messages.append(self._tool_result(tool_call.id, {"error": "문서를 찾을 수 없음"}))
                    else:
                        seen_document_version_ids.update(s.document_version_id for s in page.sources)
                        messages.append(self._tool_result(tool_call.id, {
                            "title": page.title,
                            "markdown": page.markdown,
                            "sources": [s.__dict__ for s in page.sources],
                        }))

                elif name == "submit_answer":
                    try:
                        citations = [Citation(**c) for c in args.get("citations", [])]
                        is_grounded = self._is_grounded(citations, seen_document_version_ids)
                    except (TypeError, ValueError):
                        # 모델이 citations 항목에 필수 필드(quote 등)를 빼먹거나
                        # relevance_score에 숫자가 아닌 값을 넣는 등 도구 스키마를 어겼을 때 —
                        # 그대로 두면 Citation(**c) 생성이나 _is_grounded의 점수 비교에서
                        # TypeError가 나서 요청 전체가 죽는다(실측: 폴백 모델 응답에서 발생).
                        # 지어낸/형식이 어긋난 근거이므로 근거 없음으로 강등한다.
                        citations = []
                        is_grounded = False
                    if is_grounded:
                        terminal_result = AgentResult(
                            has_answer=True,
                            answer=strip_orphaned_citation_markers(args["answer"], len(citations)),
                            citations=citations,
                        )
                    else:
                        # citations가 비었거나, read_wiki_page로 실제 조회한 문서에 없는
                        # document_version_id를 인용했거나(모델의 지어낸 근거), relevance_score가
                        # CHECK 제약(0~1) 범위를 벗어남 — 이런 답변을 그대로 저장하면 message_citations
                        # FK/CHECK 위반으로 API가 500을 내거나, 근거 없는 답이 저장된다.
                        terminal_result = AgentResult(
                            has_answer=False,
                            no_answer_reason="인용 근거가 실제로 조회한 문서와 일치하지 않음",
                        )
                    messages.append(self._tool_result(tool_call.id, {"status": "recorded"}))

                elif name == "submit_no_answer":
                    terminal_result = AgentResult(
                        has_answer=False, no_answer_reason=args["reason"],
                    )
                    messages.append(self._tool_result(tool_call.id, {"status": "recorded"}))

            if terminal_result is not None:
                return terminal_result

        return AgentResult(has_answer=False, no_answer_reason="최대 조회 횟수 초과 — 근거 확정 실패")

    @staticmethod
    def _is_grounded(citations: list[Citation], seen_document_version_ids: set[str]) -> bool:
        """citations가 비어있지 않고, 전부 실제로 read_wiki_page로 조회한 문서를
        인용하며, relevance_score가 있다면 message_citations의 CHECK 제약(0~1) 범위 안인지."""
        if not citations:
            return False
        for citation in citations:
            if citation.document_version_id not in seen_document_version_ids:
                return False
            if citation.relevance_score is not None and not (0.0 <= citation.relevance_score <= 1.0):
                return False
        return True

    def _call_model(self, messages: list[dict], *, use_tools: bool = True):
        try:
            return self._complete(MODEL_NAME, messages, use_tools=use_tools)
        except Exception:
            if FALLBACK_MODEL_NAME == MODEL_NAME:
                raise
            logger.warning(
                "openrouter_primary_model_failed_using_fallback",
                extra={"primary_model": MODEL_NAME, "fallback_model": FALLBACK_MODEL_NAME},
            )
            return self._complete(FALLBACK_MODEL_NAME, messages, use_tools=use_tools)

    def _complete(self, model: str, messages: list[dict], *, use_tools: bool = True):
        # _llm_fallback_answer(위키 근거 없는 일반 지식 답변)는 tools 없이 호출한다 —
        # WikiTools/citations를 아예 안 주려는 것이므로 도구 자체를 노출하면 안 된다.
        if not use_tools:
            return self.client.chat.completions.create(
                model=model, max_tokens=1500, messages=messages,
            )
        return self.client.chat.completions.create(
            model=model,
            max_tokens=1500,
            tools=TOOLS,
            # 매 라운드는 4개 도구 중 하나로 끝나야 한다는 게 아래 로직 전체의 전제다.
            # tool_choice="auto"(기본값)로 두면 모델이 도구 없이 텍스트로 답을 끝낼 수
            # 있는데, 특히 대화 히스토리가 있는 짧은 후속 질문("그러면~")에서 모델이
            # 직전 턴 답변 텍스트를 근거로 오인해 이번 턴 조회를 건너뛰는 경우가 있었다
            # ("모델이 근거 조회 없이 응답을 종료함"). "required"로 강제해 그 경로를 막는다.
            tool_choice="required",
            messages=messages,
        )

    @staticmethod
    def _tool_result(tool_call_id: str, output: object) -> dict:
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": json.dumps(output, ensure_ascii=False, default=str),
        }

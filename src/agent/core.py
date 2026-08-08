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
from dataclasses import dataclass, field, replace
from typing import Callable, Optional

from openai import OpenAI

from ..wiki.citation_text import strip_orphaned_citation_markers
from .wiki_tools import WikiTools
from ..pipeline_common import dart_lookup

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


class OpenRouterEmptyResponseError(RuntimeError):
    """OpenRouter가 예외 없이 choices가 비어 있는 응답을 줬을 때(실측 사례)."""

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

# 위키에는 없지만 수집된 원문(뉴스+DART)에는 있을 수 있는 경우에 쓰는 시스템 프롬프트.
# _wiki_answer가 실패했을 때만 시도하는 2차 그라운딩 단계.
DOCUMENT_ANSWER_SYSTEM_PROMPT = """\
너는 myWiki의 답변 Agent다. 위키에는 정리된 문서가 없지만, 수집된 원문(뉴스 기사·
DART 공시) 중에 관련 있는 게 있는지 찾는 단계다. 규칙:
1. 반드시 read_document로 실제 읽은 원문 내용만 근거로 답변해라. 사전 지식이나
   추측으로 빈틈을 채우지 마라.
2. search_documents로 질문의 핵심 키워드와 관련된 원문을 먼저 찾고, read_document로
   내용을 확인해라. 필요하면 여러 문서를 읽어도 된다.
3. 답을 뒷받침할 근거를 찾았으면 submit_answer를 호출해라. 문장마다 어떤 근거
   (citations)를 썼는지 반드시 포함하고, citations의 document_version_id는
   read_document 결과에서 실제로 읽은 것 중에서만 골라라 (지어내지 마라). 답변
   본문에 쓰는 근거 번호 [N]은 반드시 citations 배열의 N번째(1부터 시작) 항목과
   정확히 대응해야 한다 — citations에 없는 번호는 절대 쓰지 마라.
4. 근거를 찾지 못했거나 근거가 불충분하면 submit_answer 대신 반드시
   submit_no_answer를 호출해라.
5. 톤은 직접적이고 전문적으로, 가벼운 대화체는 쓰지 마라.
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
                                "source_url": {"type": "string"},
                                "quote": {"type": "string"},
                                "relevance_score": {"type": "number"},
                            },
                            "required": ["quote"],
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

_SUBMIT_ANSWER_TOOL = next(t for t in TOOLS if t["function"]["name"] == "submit_answer")
_SUBMIT_NO_ANSWER_TOOL = next(t for t in TOOLS if t["function"]["name"] == "submit_no_answer")

DOCUMENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": (
                "질문 키워드로 수집된 원문(뉴스 기사·DART 공시, 위키 발행 여부 무관)을 "
                "제목+본문 관련도 순으로 찾는다."
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
            "name": "read_document",
            "description": "특정 원문 문서의 전체 내용과 출처(매체명·게시일·원문 링크)를 반환한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "document_version_id": {
                        "type": "string",
                        "description": "search_documents 결과의 document_version_id",
                    },
                },
                "required": ["document_version_id"],
            },
        },
    },
    _SUBMIT_ANSWER_TOOL,
    _SUBMIT_NO_ANSWER_TOOL,
]


# 위키에도, 수집된 원문에도 근거가 없어서 사용자가 명시적으로 "웹에서 찾아줘"를
# 요청했을 때만(WikiAgent.answer(allow_web_search=True)) 쓰는 3차 그라운딩 단계.
WEB_SEARCH_ANSWER_SYSTEM_PROMPT = """\
너는 myWiki의 답변 Agent다. 위키에도, 수집된 원문(뉴스+DART)에도 근거가 없어서
실시간 웹 검색으로 마지막으로 근거를 찾는 단계다. 규칙:
1. search_web으로 뉴스를 찾아라. 질문이 실적·지분·계약·투자 등 공시성 내용이면
   search_recent_disclosures로 최근 DART 공시 목록도 같이 확인하고, 관련 있어
   보이는 제목이 있으면 read_disclosure로 본문을 읽어라.
2. 찾은 결과(뉴스 요약 또는 공시 본문)에 실제로 있는 내용만 근거로 답변해라.
   사전 지식이나 추측으로 빈틈을 채우지 마라.
3. 답을 뒷받침할 근거를 찾았으면 submit_answer를 호출해라. 문장마다 어떤 근거
   (citations)를 썼는지 반드시 포함하고, citations의 source_url은 실제로 본
   결과(search_web의 url 또는 read_disclosure로 읽은 공시)에서만 골라라(지어내지
   마라). document_version_id는 비워둬라 — DB 문서가 아니다. 답변 본문에 쓰는 근거
   번호 [N]은 반드시 citations 배열의 N번째(1부터 시작) 항목과 정확히 대응해야 한다
   — citations에 없는 번호는 절대 쓰지 마라.
4. 근거를 찾지 못했거나 근거가 불충분하면 submit_answer 대신 반드시
   submit_no_answer를 호출해라.
5. 톤은 직접적이고 전문적으로, 가벼운 대화체는 쓰지 마라.
"""

WEB_SEARCH_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": (
                "질문 키워드로 실시간 웹(네이버 검색)을 찾는다. 위키·수집된 원문 어디에도 "
                "근거가 없을 때만 쓰는 최후 수단 — 검색 결과의 제목·요약·링크·게시일을 반환한다."
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
            "name": "search_recent_disclosures",
            "description": (
                "이 워크스페이스에 등록된 회사들의 최근 공시 목록(제목·접수번호·게시일)을 "
                "찾는다. 질문이 실적·지분·계약·투자 등 공시성 내용일 때 시도해라. 자유 "
                "검색어는 지원 안 됨 — 최근 공시 전체 목록만 준다, 관련 있어 보이는 제목을 "
                "read_disclosure로 읽어서 확인해라."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "최근 며칠치 공시를 볼지(기본 14일)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_disclosure",
            "description": "search_recent_disclosures 결과에서 접수번호(rcept_no)로 공시 원문 전체를 읽는다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "rcept_no": {
                        "type": "string",
                        "description": "search_recent_disclosures 결과의 rcept_no",
                    },
                },
                "required": ["rcept_no"],
            },
        },
    },
    _SUBMIT_ANSWER_TOOL,
    _SUBMIT_NO_ANSWER_TOOL,
]


@dataclass
class Citation:
    quote: str
    document_version_id: Optional[str] = None
    wiki_slug: Optional[str] = None
    relevance_score: Optional[float] = None
    source_url: Optional[str] = None
    source_title: Optional[str] = None
    source_published_at: Optional[str] = None


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

    def answer(
        self, question: str, history: Optional[list[dict]] = None, *, allow_web_search: bool = False
    ) -> AgentResult:
        """4단계로 근거를 찾는다: 위키(_wiki_answer) -> 수집된 원문(_document_answer) ->
        (allow_web_search일 때만) 실시간 웹 검색(_web_search_answer) -> 위키 근거 없이
        일반 지식(_llm_fallback_answer). 앞 세 그라운딩 단계는 예외가 나도(OpenRouter
        응답 이상 등) 그대로 새 나가지 않고 다음 단계로 넘어간다 — 500으로 죽는 대신
        최소한 다음 단계 결과(또는 일반 지식 폴백)라도 낸다.

        allow_web_search=False(기본값)면 원문 그라운딩 실패 시 그 자리에서 근거 없음을
        반환한다 — 웹 검색도 일반 지식 폴백도 시도하지 않는다(2턴 흐름의 1턴). 사용자가
        명시적으로 "웹에서 찾아줘"를 요청했을 때만(allow_web_search=True, 2턴) 웹 검색을
        시도하고, 그것도 실패하면 자동으로 일반 지식 폴백까지 이어간다 — 한 번 요청한
        뒤라 추가 확인 없이 진행한다."""
        result = self._safe_run(
            self._wiki_answer, question, history, no_answer_reason="위키 근거 조회 중 오류 발생"
        )
        if result.has_answer:
            return result
        result = self._safe_run(
            self._document_answer, question, history, no_answer_reason="원문 문서 조회 중 오류 발생"
        )
        if result.has_answer or not allow_web_search:
            return result
        result = self._safe_run(
            self._web_search_answer, question, history, no_answer_reason="웹 검색 중 오류 발생"
        )
        if result.has_answer:
            return result
        fallback = self._llm_fallback_answer(question, history)
        return fallback if fallback is not None else result

    def _safe_run(
        self,
        method: Callable[[str, Optional[list[dict]]], AgentResult],
        question: str,
        history: Optional[list[dict]],
        *,
        no_answer_reason: str,
    ) -> AgentResult:
        try:
            return method(question, history)
        except Exception:  # noqa: BLE001 - OpenRouter 응답 이상 등, 다음 단계로 넘긴다
            logger.warning("grounded_answer_step_failed", exc_info=True, extra={"step": method.__name__})
            return AgentResult(has_answer=False, no_answer_reason=no_answer_reason)

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
        def handle_list_wiki_topics(args: dict, seen: set[str]) -> object:
            topics = self.wiki_tools.list_wiki_topics()
            return [t.__dict__ for t in topics]

        def handle_search_wiki_pages(args: dict, seen: set[str]) -> object:
            hits = self.wiki_tools.search_wiki_pages(args["query"])
            return [h.__dict__ for h in hits]

        def handle_read_wiki_page(args: dict, seen: set[str]) -> object:
            page = self.wiki_tools.read_wiki_page(args["slug"])
            if page is None:
                return {"error": "문서를 찾을 수 없음"}
            seen.update(s.document_version_id for s in page.sources)
            return {
                "title": page.title,
                "markdown": page.markdown,
                "sources": [s.__dict__ for s in page.sources],
            }

        return self._run_grounded_answer(
            question,
            history,
            system_prompt=SYSTEM_PROMPT,
            tools=TOOLS,
            tool_handlers={
                "list_wiki_topics": handle_list_wiki_topics,
                "search_wiki_pages": handle_search_wiki_pages,
                "read_wiki_page": handle_read_wiki_page,
            },
        )

    def _document_answer(self, question: str, history: Optional[list[dict]] = None) -> AgentResult:
        def handle_search_documents(args: dict, seen: set[str]) -> object:
            hits = self.wiki_tools.search_documents(args["query"])
            return [h.__dict__ for h in hits]

        def handle_read_document(args: dict, seen: set[str]) -> object:
            document = self.wiki_tools.read_document(args["document_version_id"])
            if document is None:
                return {"error": "문서를 찾을 수 없음"}
            seen.add(document.document_version_id)
            return {
                "title": document.title,
                "markdown": document.markdown,
                "canonical_url": document.canonical_url,
                "source_name": document.source_name,
                "published_at": document.published_at,
            }

        result = self._run_grounded_answer(
            question,
            history,
            system_prompt=DOCUMENT_ANSWER_SYSTEM_PROMPT,
            tools=DOCUMENT_TOOLS,
            tool_handlers={
                "search_documents": handle_search_documents,
                "read_document": handle_read_document,
            },
        )
        # DOCUMENT_TOOLS는 submit_answer 스키마를 위키 단계와 재사용하므로 wiki_slug
        # 필드 자체를 막지 못한다 — 프롬프트로만 "원문 단계엔 wiki_slug 없음"을 바라는
        # 대신, 모델이 실수로(또는 이전 위키 조회 결과를 착각해) wiki_slug를 채워 보내도
        # 여기서 강제로 지운다. Citation은 non-frozen dataclass이지만 원본 객체를
        # 그대로 변형하지 않고 새로 만든다.
        if result.has_answer and result.citations:
            result.citations = [replace(c, wiki_slug=None) for c in result.citations]
        return result

    def _web_search_answer(self, question: str, history: Optional[list[dict]] = None) -> AgentResult:
        # search_web 결과의 (title, published_at)을 url로 찾아올 수 있게 기억해둔다 —
        # 모델은 citations에 source_url만 채우고 title/published_at은 안 채우므로
        # (submit_answer 스키마에 그 두 필드가 없다), 저장할 값은 여기서 직접 채운다.
        hit_by_url: dict[str, tuple[str, Optional[str]]] = {}
        # DART는 목록(search_recent_disclosures)에 본문이 없어 read_disclosure로 실제로
        # 읽어야만 인용 가능하다 — 목록만 보고 안 읽은 공시는 hit_by_url에 안 들어간다.
        disclosure_hits: dict[str, dart_lookup.DisclosureHit] = {}

        def handle_search_web(args: dict, seen: set[str]) -> object:
            hits = self.wiki_tools.search_web(args["query"])
            # 원문 단계와 다르게 read 단계가 따로 없다 — search_web 결과 자체가 그라운딩에
            # 쓸 내용(title/snippet) 전부라, 검색 시점에 바로 seen에 URL을 채운다.
            seen.update(h.url for h in hits)
            hit_by_url.update({h.url: (h.title, h.published_at) for h in hits})
            return [h.__dict__ for h in hits]

        def handle_search_recent_disclosures(args: dict, seen: set[str]) -> object:
            days = args.get("days") or dart_lookup.DEFAULT_LOOKBACK_DAYS
            hits = self.wiki_tools.search_recent_disclosures(days)
            disclosure_hits.update({h.rcept_no: h for h in hits})
            return [h.__dict__ for h in hits]

        def handle_read_disclosure(args: dict, seen: set[str]) -> object:
            rcept_no = args["rcept_no"]
            markdown = self.wiki_tools.read_disclosure(rcept_no)
            if markdown is None:
                return {"error": "공시를 찾을 수 없음"}
            url = dart_lookup.viewer_url(rcept_no)
            hit = disclosure_hits.get(rcept_no)
            seen.add(url)
            hit_by_url[url] = (hit.report_name if hit else None, hit.published_at if hit else None)
            return {
                "markdown": markdown,
                "canonical_url": url,
                "report_name": hit.report_name if hit else None,
                "corp_name": hit.corp_name if hit else None,
            }

        result = self._run_grounded_answer(
            question,
            history,
            system_prompt=WEB_SEARCH_ANSWER_SYSTEM_PROMPT,
            tools=WEB_SEARCH_TOOLS,
            tool_handlers={
                "search_web": handle_search_web,
                "search_recent_disclosures": handle_search_recent_disclosures,
                "read_disclosure": handle_read_disclosure,
            },
        )
        # submit_answer 스키마를 다른 단계와 공유하므로 document_version_id/wiki_slug
        # 필드 자체를 막지 못한다 — 모델이 실수로(또는 검색 결과 URL을) document_version_id
        # 칸에 채워 보내도 그 값이 이번 검색에서 실제로 본 URL(hit_by_url의 키)이면
        # source_url로 승격시킨다. source_url도 비어 있고 document_version_id도 이번
        # 검색 결과에 없는 값이면(식별자가 통째로 없는 것과 같다) 그 citation은 근거
        # 없음으로 취급해 답변 전체를 has_answer=False로 강등한다 — 지어낸/형식이
        # 어긋난 근거를 저장하면 안 된다는 이 파일의 기존 원칙과 동일하다.
        if result.has_answer and result.citations:
            def _enrich(c: Citation) -> Citation:
                url = c.source_url or (c.document_version_id if c.document_version_id in hit_by_url else None)
                title, published_at = hit_by_url.get(url, (None, None))
                return replace(
                    c,
                    document_version_id=None,
                    wiki_slug=None,
                    source_url=url,
                    source_title=title,
                    source_published_at=published_at,
                )

            enriched = [_enrich(c) for c in result.citations]
            if any(c.source_url is None for c in enriched):
                return AgentResult(
                    has_answer=False,
                    no_answer_reason="인용 근거가 실제로 조회한 검색 결과와 일치하지 않음",
                )
            result.citations = enriched
        return result

    def _run_grounded_answer(
        self,
        question: str,
        history: Optional[list[dict]],
        *,
        system_prompt: str,
        tools: list[dict],
        tool_handlers: dict[str, Callable[[dict, set[str]], object]],
    ) -> AgentResult:
        """라운드 루프 본체 — _wiki_answer/_document_answer가 공유한다.

        tool_handlers는 {tool 이름: handler}. handler(args, seen_document_version_ids)는
        JSON 직렬화 가능한 tool 결과를 반환하고, "읽기" 성격의 도구라면
        seen(식별자 집합, document_version_id 또는 URL)을 in-place로 갱신해야 한다(뒤이은
        submit_answer의 grounding 검증이 이 집합을 기준으로 판정한다). submit_answer/
        submit_no_answer는 두 그라운딩 단계에서 동일하므로 여기서 직접 처리하고
        tool_handlers에 넣지 않는다.
        """
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        messages.extend(history or [])
        messages.append({"role": "user", "content": question})
        seen_identifiers: set[str] = set()

        for _ in range(MAX_TOOL_ROUNDS):
            response = self._call_model(messages, tools=tools)
            choice = response.choices[0]
            message = choice.message

            if choice.finish_reason != "tool_calls" or not message.tool_calls:
                # 모델이 도구 없이 텍스트로만 끝냈다면, 규칙 위반이므로 근거 없음으로 처리
                return AgentResult(has_answer=False, no_answer_reason="모델이 근거 조회 없이 응답을 종료함")

            messages.append(message.model_dump(exclude_unset=True))
            terminal_result: Optional[AgentResult] = None

            for tool_call in message.tool_calls:
                name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments or "{}")
                except json.JSONDecodeError:
                    # 실측 버그: 모델이 tool call 인자로 잘린(비정상 종료된) JSON을 줄 때가
                    # 있다 — 그대로 두면 answer() 전체가 크래시한다. 이 호출만 실패로
                    # 알리고 다음 라운드에서 모델이 다시 시도하게 둔다.
                    messages.append(
                        self._tool_result(tool_call.id, {"error": "잘못된 인자(JSON 파싱 실패)"})
                    )
                    continue

                if name in tool_handlers:
                    output = tool_handlers[name](args, seen_identifiers)
                    messages.append(self._tool_result(tool_call.id, output))

                elif name == "submit_answer":
                    try:
                        citations = [Citation(**c) for c in args.get("citations", [])]
                        is_grounded = self._is_grounded(citations, seen_identifiers)
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
                        # citations가 비었거나, 실제로 조회한 문서에 없는 document_version_id를
                        # 인용했거나(모델의 지어낸 근거), relevance_score가 CHECK 제약(0~1)
                        # 범위를 벗어남 — 이런 답변을 그대로 저장하면 message_citations
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
    def _is_grounded(citations: list[Citation], seen_identifiers: set[str]) -> bool:
        """citations가 비어있지 않고, 전부 실제로 조회한 문서/검색 결과를 인용하며
        (document_version_id 또는 source_url 중 있는 쪽으로 seen_identifiers를 검증),
        relevance_score가 있다면 message_citations의 CHECK 제약(0~1) 범위 안인지."""
        if not citations:
            return False
        for citation in citations:
            identifier = citation.document_version_id or citation.source_url
            if identifier is None or identifier not in seen_identifiers:
                return False
            if citation.relevance_score is not None and not (0.0 <= citation.relevance_score <= 1.0):
                return False
        return True

    def _call_model(self, messages: list[dict], *, use_tools: bool = True, tools: list[dict] | None = None):
        try:
            return self._complete(MODEL_NAME, messages, use_tools=use_tools, tools=tools)
        except Exception:
            if FALLBACK_MODEL_NAME == MODEL_NAME:
                raise
            logger.warning(
                "openrouter_primary_model_failed_using_fallback",
                extra={"primary_model": MODEL_NAME, "fallback_model": FALLBACK_MODEL_NAME},
            )
            return self._complete(FALLBACK_MODEL_NAME, messages, use_tools=use_tools, tools=tools)

    def _complete(
        self, model: str, messages: list[dict], *, use_tools: bool = True, tools: list[dict] | None = None
    ):
        # _llm_fallback_answer(위키 근거 없는 일반 지식 답변)는 tools 없이 호출한다 —
        # WikiTools/citations를 아예 안 주려는 것이므로 도구 자체를 노출하면 안 된다.
        if not use_tools:
            response = self.client.chat.completions.create(
                model=model, max_tokens=1500, messages=messages,
            )
        else:
            response = self.client.chat.completions.create(
                model=model,
                max_tokens=1500,
                tools=tools if tools is not None else TOOLS,
                # 매 라운드는 4개 도구 중 하나로 끝나야 한다는 게 아래 로직 전체의 전제다.
                # tool_choice="auto"(기본값)로 두면 모델이 도구 없이 텍스트로 답을 끝낼 수
                # 있는데, 특히 대화 히스토리가 있는 짧은 후속 질문("그러면~")에서 모델이
                # 직전 턴 답변 텍스트를 근거로 오인해 이번 턴 조회를 건너뛰는 경우가 있었다
                # ("모델이 근거 조회 없이 응답을 종료함"). "required"로 강제해 그 경로를 막는다.
                tool_choice="required",
                messages=messages,
            )
        # 실측 버그: OpenRouter가 HTTP 200에 choices=None(또는 빈 배열)인 응답을 줄 때가
        # 있다 — 예외를 안 던져서 그대로 두면 호출부의 response.choices[0]에서
        # TypeError로 크래시한다. 여기서 실패로 취급해야 _call_model의 기존 폴백 모델
        # 재시도 경로(원인이 primary 모델 자체가 아니어도)를 그대로 탄다.
        if not response.choices:
            raise OpenRouterEmptyResponseError(f"OpenRouter returned no choices (model={model})")
        return response

    @staticmethod
    def _tool_result(tool_call_id: str, output: object) -> dict:
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": json.dumps(output, ensure_ascii=False, default=str),
        }

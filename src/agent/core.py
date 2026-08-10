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

from ..analysis.classifier import get_openrouter_settings
from ..pipeline_common import dart_lookup
from ..wiki.citation_text import strip_orphaned_citation_markers
from .wiki_tools import WikiTools

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# 모델 기본값을 여기서 다시 os.getenv로 읽지 않고 analysis/classifier.py의
# OpenRouterSettings에서 그대로 가져온다 — 두 곳에 각자 하드코딩된 기본값이 어긋난 적이
# 실제로 있었다(2026-08-04, 한쪽에만 잘못된 기본 모델이 남아있던 사고). 단일 출처로 통일.
_settings = get_openrouter_settings()
MODEL_NAME = _settings.model
# 기본 모델 호출이 실패하면 이 모델로 한 번 더 시도한다.
FALLBACK_MODEL_NAME = _settings.fallback_model
# OpenAI SDK 기본 read timeout(600초)을 그대로 두면, primary 모델이 막혔을 때 폴백으로
# 넘어가기까지 라운드 하나가 몇 분씩 걸릴 수 있다(실측: 2026-08-09, primary 반복 실패로
# 답변 하나에 190~200초+ 소요 — 프론트가 기다릴 수 있는 시간을 훨씬 넘겨 "완전 무응답"
# 처럼 보였다). 이 값을 짧게 잡으면 실제로 느릴 뿐인 정상 응답도 폴백으로 넘어갈 수
# 있다는 트레이드오프가 있다 — 배포 후 폴백 전환 빈도·답변 품질 체감을 지켜봐야 한다.
OPENROUTER_TIMEOUT_SECONDS = float(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "25"))
MAX_TOOL_ROUNDS = 10  # 위키 단계 전용 — 무한루프 방지. 실사용 로그에서 6일 때 답변의
# 17%가 라운드 초과로 근거 없음 처리됐다(2026-08-05, chat_messages 66건 중 11건).
# search_wiki_pages 도입으로 첫 라운드부터 관련도 순 후보를 받게 됐지만, 복합 질문의
# 교차검증(여러 페이지 읽기)엔 여전히 여유가 필요해 상한을 올린다.
MAX_TOOL_ROUNDS_SEARCH = 4  # 원문/웹검색+DART 단계 전용 — 검색 후 읽기 위주의 단순
# 작업이라 위키만큼 여유가 필요 없다. 이 두 단계가 위키 단계와 같은 상한(10)을 쓰면
# 위키에 없는 질문 하나가 최악의 경우 최대 30라운드(10+10+10)를 순차 호출해 응답이
# 지연되고 매 요청마다 DART·네이버 API까지 자동으로 붙어 비용이 과도해진다.

# 실측 버그(2026-08-09): 두 경로가 max_tokens=1500 하나를 공유해서, 5개 섹션짜리
# 종합 답변이 "실적은 AI 메"처럼 문장 중간에 잘렸다 — finish_reason을 안 봐서 정상
# 완료로 오인하고 그대로 저장·전송됐다. 경로별로 분리해 독립적으로 조정 가능하게 한다.
LLM_FALLBACK_MAX_TOKENS = 2200  # _llm_fallback_answer — 도구 호출 없이 answer 텍스트만.
GROUNDED_ANSWER_MAX_TOKENS = 2200  # 그라운딩 라운드 — submit_answer의 citations JSON도
# 같은 응답 안에 담아야 해서 answer 텍스트만 있는 폴백 경로와 필요량이 비슷하다.

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
   명시적으로 전환해라. 그래도 read_wiki_page로 실제 읽어본 문서 중 참고할 만한 게
   있으면 citations로 같이 제출해라(실제로 읽은 것만 — 지어내지 마라) — reason
   안에서 그 문서를 언급할 땐 citations 배열의 N번째(1부터) 항목과 정확히 대응하는
   [N] 표기를 써라; citations에 없는 번호는 절대 쓰지 마라. 참고할 문서가 없으면
   citations는 생략해라.
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

질문이 여러 주제를 한 번에 묻더라도(예: 동향+실적+공시+주가를 한꺼번에 요청)
장황하게 전부 나열하지 말고, 각 항목을 핵심 한두 문장으로만 간결하게 요약해라.
답변이 길어질수록 문장 중간에 잘릴 위험이 커진다 — 분량을 스스로 조절해서
반드시 완결된 문장으로 끝내라.

이 답변에는 실제 출처(citations)가 전혀 붙지 않는다 — 답변 본문에 [1], [2] 같은
대괄호 각주 표기를 절대 쓰지 마라. 위키 근거로 답한 것처럼 보이면 사용자가
오해한다.

질문이 특정 제품의 양산 시점·세부 로드맵처럼 구체적인 계획을 묻는데 앞선
공시(DART)·뉴스 검색 단계에서도 못 찾았을 가능성이 높은 내용이면, 왜 못 찾았을
수 있는지 이유도 같이 알려줘라 — DART 공시는 실적·지분·계약·시설투자 등 법정
의무 공시 항목 위주라, 제품 로드맵·세부 사양처럼 공시 의무가 아닌 내용은 애초에
공시 대상이 아닐 수 있다.
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
   submit_no_answer를 호출해라. 그래도 read_document로 실제 읽어본 문서 중 참고할
   만한 게 있으면 citations로 같이 제출해라(실제로 읽은 것만 — 지어내지 마라) —
   reason 안에서 언급할 땐 citations 배열의 N번째(1부터) 항목과 정확히 대응하는
   [N] 표기를 써라; citations에 없는 번호는 절대 쓰지 마라. 참고할 문서가 없으면
   citations는 생략해라.
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
            "description": (
                "충분한 근거를 찾지 못해 답을 낼 수 없을 때 호출한다. 완전한 답은 못 내도"
                " 실제로 읽어본 문서 중 참고할 만한 게 있으면 citations로 같이 제출할 수"
                " 있다(선택 사항)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                    "citations": {
                        "type": "array",
                        "description": (
                            "선택 사항 — reason에서 [N]으로 언급한 문서가 있으면, 실제로 조회한"
                            " 것만 여기에 채워라. 없으면 생략해라."
                        ),
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
1. search_web을 반드시 먼저 호출해라 — 이 단계에서 도구 호출 없이 텍스트로만
   답하면 "근거 조회 없이 종료"로 간주돼 곧장 근거 없음 처리된다. 질문이 특정
   회사와 관련된 사실관계를 묻는 것이면(실적·지분·계약·투자·상장·증권발행·
   제품·기술 등 어떤 종류든 — 공시 유형을 미리 짐작해서 거르지 마라)
   search_recent_disclosures로 최근 DART 공시 목록도 같이 확인하고, 관련 있어
   보이는 제목이 있으면 read_disclosure로 본문을 읽어라. 회사와 무관한 일반
   산업 동향 질문일 때만 DART 조회를 생략해도 된다. 처음엔 유형 필터 없이
   전체로 조회해라 — 상장·증권발행처럼 유형이 뚜렷이 짐작되는 질문에서 결과가
   너무 많아 훑기 부담스러울 때만 search_recent_disclosures의 pblntf_ty로
   좁혀서 다시 불러라(예: 상장 관련이면 B, 그다음 C로 한 번씩 더).
2. 찾은 결과(뉴스 요약 또는 공시 본문)에 실제로 있는 내용만 근거로 답변해라.
   사전 지식이나 추측으로 빈틈을 채우지 마라. 검색 결과 요약이 짧아 구체적인 내용이
   부족하면, 그 부족한 부분은 답변에 넣지 마라.
3. 답을 뒷받침할 근거를 찾았으면 submit_answer를 호출해라. 문장마다 어떤 근거
   (citations)를 썼는지 반드시 포함하고, citations의 source_url은 실제로 본
   결과(search_web의 url 또는 read_disclosure로 읽은 공시)에서만 골라라(지어내지
   마라). document_version_id는 비워둬라 — DB 문서가 아니다. 답변 본문에 쓰는 근거
   번호 [N]은 반드시 citations 배열의 N번째(1부터 시작) 항목과 정확히 대응해야 한다
   — citations에 없는 번호는 절대 쓰지 마라.
4. 근거를 찾지 못했거나 근거가 불충분하면 submit_answer 대신 반드시
   submit_no_answer를 호출해라. 그래도 실제로 읽어본 결과(뉴스 요약 또는 공시
   본문) 중 참고할 만한 게 있으면 citations로 같이 제출해라(실제로 본 것만 —
   지어내지 마라). document_version_id는 비워둬라. reason 안에서 언급할 땐
   citations 배열의 N번째(1부터) 항목과 정확히 대응하는 [N] 표기를 써라;
   citations에 없는 번호는 절대 쓰지 마라. 참고할 결과가 없으면 citations는
   생략해라.
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
                "찾는다. 질문이 특정 회사의 사실관계를 묻는 것이면 공시 유형(실적/지분/"
                "계약/투자/상장/증권발행 등)을 미리 짐작해서 거르지 말고 일단 시도해라 — "
                "제목만 봐서는 관련 여부를 알 수 없는 경우가 많다. 자유 검색어는 지원 안 "
                "됨 — 최근 공시 전체 목록만 준다, 관련 있어 보이는 제목을 read_disclosure로 "
                "읽어서 확인해라. pblntf_ty를 비워두면(기본) 전체 유형을 준다 — 결과가 너무 "
                "많아 훑어보기 부담스러울 때만 유형을 좁혀라."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "최근 며칠치 공시를 볼지(기본 14일)",
                    },
                    "pblntf_ty": {
                        "type": "string",
                        "description": (
                            "공시유형 한 글자로 좁혀서 조회(선택, 기본은 전체 유형). "
                            "A=정기공시(실적 등) B=주요사항보고(상장·유상증자·합병 등) "
                            "C=발행공시(증권신고·투자설명서 등) D=지분공시 E=기타공시. "
                            "DART API는 한 번에 유형 하나만 받는다 — 'B,C'처럼 콤마로 "
                            "여러 개를 넣으면 오류가 난다. 여러 유형을 다 보고 싶으면 이 "
                            "도구를 유형별로 따로 호출해라(예: 상장·증권 관련 질문이면 "
                            "B로 한 번, C로 한 번). 확실하지 않으면 비워두고 전체를 봐라 "
                            "— 잘못 좁히면 오히려 정작 필요한 공시를 놓친다."
                        ),
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
            timeout=OPENROUTER_TIMEOUT_SECONDS,
        )

    def answer(
        self, question: str, history: Optional[list[dict]] = None, *, allow_web_search: bool = False
    ) -> AgentResult:
        """4단계로 근거를 찾는다: 위키(_wiki_answer) -> 수집된 원문(_document_answer) ->
        (allow_web_search일 때만) 실시간 웹 검색(_web_search_answer) -> 위키 근거 없이
        일반 지식(_llm_fallback_answer). 앞 세 그라운딩 단계는 예외가 나도(OpenRouter
        응답 이상 등) 그대로 새 나가지 않고 다음 단계로 넘어간다 — 500으로 죽는 대신
        최소한 다음 단계 결과(또는 일반 지식 폴백)라도 낸다.

        위키·원문 두 단계는 DB 조회 위주라 빠르고 저렴해 항상 자동으로 이어간다.
        웹 검색+DART 실시간 조회(_web_search_answer)만 옵트인이다 — 실제 외부 API를
        호출하고 라운드마다 컨텍스트도 커져 비용·시간이 크기 때문에, 사용자가 명시적으로
        "웹에서 찾아줘"를 요청했을 때만(allow_web_search=True) 시도한다. 일반 지식
        폴백(_llm_fallback_answer)은 도구 호출 없는 1회성 호출이라 빠르고 저렴하므로,
        allow_web_search 여부와 무관하게 그 앞 단계들이 전부 실패하면 항상 마지막으로
        시도한다 — 첫 응답에서 새로고침 없이 답이 오게 하려면 이 단계는 옵트인으로 두면
        안 된다."""
        result = self._safe_run(
            self._wiki_answer, question, history, no_answer_reason="위키 근거 조회 중 오류 발생"
        )
        if result.has_answer:
            return result
        result = self._safe_run(
            self._document_answer, question, history, no_answer_reason="원문 문서 조회 중 오류 발생"
        )
        if result.has_answer:
            return result
        if allow_web_search:
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
        except Exception as exc:  # noqa: BLE001 - OpenRouter 응답 이상 등, 다음 단계로 넘긴다
            # exception_type/exception_message를 extra에 남긴다 — 이게 없으면 "진짜 에러라
            # 조용히 삼켜진 것"과 "정상 호출인데 근거 0건"을 로그만 보고 구분할 수 없다
            # (실측: DART_API_KEY/NAVER 키 누락 같은 설정 오류도 이 경로로 삼켜진다).
            logger.warning(
                "grounded_answer_step_failed",
                exc_info=True,
                extra={
                    "step": method.__name__,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
            )
            return AgentResult(has_answer=False, no_answer_reason=no_answer_reason)

    def _llm_fallback_answer(
        self, question: str, history: Optional[list[dict]] = None
    ) -> Optional[AgentResult]:
        messages: list[dict] = [{"role": "system", "content": LLM_FALLBACK_SYSTEM_PROMPT}]
        messages.extend(history or [])
        messages.append({"role": "user", "content": question})
        try:
            response = self._call_model(messages, use_tools=False)
            choice = response.choices[0]
            text = (choice.message.content or "").strip()
        except Exception:  # noqa: BLE001 - 폴백은 실패해도 원래 no_answer 결과로 조용히 넘어간다
            return None
        if not text:
            return None
        # 프롬프트로 각주 표기를 쓰지 말라고 지시해도(위) 모델이 그래도 [N]을 흉내 낼
        # 수 있다 — citations가 항상 빈 배열이라 citation_count=0을 넘기면 모든 [N]이
        # 범위 밖으로 걸러진다(submit_answer/submit_no_answer 경로와 같은 안전장치).
        text = strip_orphaned_citation_markers(text, citation_count=0)
        if choice.finish_reason == "length":
            # LLM_FALLBACK_MAX_TOKENS를 늘리고 프롬프트로 간결하게 답하라고 지시해도,
            # 모델이 그래도 그 안에 못 끝낼 수 있다 — 잘린 문장을 정상 완료처럼 그대로
            # 보여주면 사용자가 못 알아챈다(실측 2026-08-09). 로그로 남기고 안내를 붙인다.
            logger.warning("llm_fallback_answer_truncated", extra={"model": MODEL_NAME})
            text = f"{text}\n\n(응답이 길어 일부 내용이 생략됐습니다.)"
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
            max_rounds=MAX_TOOL_ROUNDS_SEARCH,
        )
        # DOCUMENT_TOOLS는 submit_answer 스키마를 위키 단계와 재사용하므로 wiki_slug
        # 필드 자체를 막지 못한다 — 프롬프트로만 "원문 단계엔 wiki_slug 없음"을 바라는
        # 대신, 모델이 실수로(또는 이전 위키 조회 결과를 착각해) wiki_slug를 채워 보내도
        # 여기서 강제로 지운다. Citation은 non-frozen dataclass이지만 원본 객체를
        # 그대로 변형하지 않고 새로 만든다. has_answer 여부와 무관하게 적용한다 —
        # submit_no_answer도 이제 citations를 선택적으로 실어 보낼 수 있다.
        if result.citations:
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
            try:
                days = int(args.get("days") or dart_lookup.DEFAULT_LOOKBACK_DAYS)
            except (TypeError, ValueError):
                # 모델이 스키마를 어기고 숫자로 변환 안 되는 값(예: "not-a-number")을
                # 보내면 timedelta(days=...)가 TypeError를 던져 웹 검색 단계 전체가
                # 유실된다 — 이 파일의 다른 곳(JSON 파싱 실패, Citation(**c) TypeError)과
                # 같은 원칙으로 기본값으로 방어한다.
                days = dart_lookup.DEFAULT_LOOKBACK_DAYS
            days = max(1, min(days, 90))
            pblntf_ty = (args.get("pblntf_ty") or "").strip() or None
            hits = self.wiki_tools.search_recent_disclosures(days, pblntf_ty)
            disclosure_hits.update({h.rcept_no: h for h in hits})
            return [h.__dict__ for h in hits]

        def handle_read_disclosure(args: dict, seen: set[str]) -> object:
            rcept_no = args["rcept_no"]
            text = self.wiki_tools.read_disclosure(rcept_no)
            if text is None:
                return {"error": "공시를 찾을 수 없음"}
            url = dart_lookup.viewer_url(rcept_no)
            hit = disclosure_hits.get(rcept_no)
            seen.add(url)
            hit_by_url[url] = (hit.report_name if hit else None, hit.published_at if hit else None)
            return {
                "text": text,
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
            max_rounds=MAX_TOOL_ROUNDS_SEARCH,
        )
        # submit_answer 스키마를 다른 단계와 공유하므로 document_version_id/wiki_slug
        # 필드 자체를 막지 못한다 — 모델이 실수로(또는 검색 결과 URL을) document_version_id
        # 칸에 채워 보내도 그 값이 이번 검색에서 실제로 본 URL(hit_by_url의 키)이면
        # source_url로 승격시킨다.
        if result.citations:
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
            if result.has_answer:
                # source_url도 비어 있고 document_version_id도 이번 검색 결과에 없는
                # 값이면(식별자가 통째로 없는 것과 같다) 그 citation은 근거 없음으로
                # 취급해 답변 전체를 has_answer=False로 강등한다 — 지어낸/형식이 어긋난
                # 근거를 저장하면 안 된다는 이 파일의 기존 원칙과 동일하다.
                if any(c.source_url is None for c in enriched):
                    return AgentResult(
                        has_answer=False,
                        no_answer_reason="인용 근거가 실제로 조회한 검색 결과와 일치하지 않음",
                    )
                result.citations = enriched
            else:
                # submit_no_answer 경로 — 강등할 "정상 답변"이 없으므로, 식별이 안 되는
                # (지어낸) citation만 조용히 버리고 검증된 것만 남긴다. _run_grounded_answer의
                # _filter_grounded_citations가 이미 seen_identifiers로 한 번 걸렀지만,
                # hit_by_url에 없는(예: document_version_id로 잘못 채워 보낸) 케이스가
                # 남아있을 수 있어 enrich 이후 한 번 더 확인한다.
                result.citations = [c for c in enriched if c.source_url is not None]
        return result

    def _run_grounded_answer(
        self,
        question: str,
        history: Optional[list[dict]],
        *,
        system_prompt: str,
        tools: list[dict],
        tool_handlers: dict[str, Callable[[dict, set[str]], object]],
        max_rounds: int = MAX_TOOL_ROUNDS,
    ) -> AgentResult:
        """라운드 루프 본체 — _wiki_answer/_document_answer/_web_search_answer가 공유한다.

        tool_handlers는 {tool 이름: handler}. handler(args, seen_document_version_ids)는
        JSON 직렬화 가능한 tool 결과를 반환하고, "읽기" 성격의 도구라면
        seen(식별자 집합, document_version_id 또는 URL)을 in-place로 갱신해야 한다(뒤이은
        submit_answer의 grounding 검증이 이 집합을 기준으로 판정한다). submit_answer/
        submit_no_answer는 두 그라운딩 단계에서 동일하므로 여기서 직접 처리하고
        tool_handlers에 넣지 않는다.

        max_rounds는 단계별로 다르다 — 위키는 다중 페이지 교차검증이 필요해 여유가
        크고(MAX_TOOL_ROUNDS), 원문/웹검색+DART는 검색 후 읽기 위주라 낮다
        (MAX_TOOL_ROUNDS_SEARCH). 호출부(_wiki_answer/_document_answer/_web_search_answer)가
        각자 맞는 값을 넘긴다.
        """
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        messages.extend(history or [])
        messages.append({"role": "user", "content": question})
        seen_identifiers: set[str] = set()

        for _ in range(max_rounds):
            response = self._call_model(messages, tools=tools)
            choice = response.choices[0]
            message = choice.message

            if choice.finish_reason == "length":
                # submit_answer의 citations JSON이 GROUNDED_ANSWER_MAX_TOKENS 안에 못 끝나면
                # tool_call.function.arguments가 잘린 채로 온다 — 아래 json.loads가
                # JSONDecodeError로 잡아서 이 라운드만 실패로 처리하고 다음 라운드에서
                # 모델이 다시 시도하게 두지만(원인 파악 불가), 여기서 미리 로그를 남겨야
                # "모델이 지어낸 근거"와 "그냥 길이 초과로 잘림"을 구분할 수 있다.
                logger.warning("grounded_answer_response_truncated", extra={"step": "tool_call_round"})
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
                    # citations는 선택 사항이다 — 완전한 답은 못 내도(has_answer=False는
                    # 그대로) 실제로 읽어본 문서 중 참고할 만한 게 있으면 reason의 [N]과
                    # 연결해서 보여준다. submit_answer와 달리 citations가 비어있거나
                    # 일부가 무효해도 전체를 거부하지 않는다 — 여기는 애초에 "정상 답변"이
                    # 아니라 강등할 대상이 없으므로, 검증을 통과한 것만 조용히 남긴다.
                    try:
                        raw_citations = [Citation(**c) for c in args.get("citations", [])]
                    except (TypeError, ValueError):
                        raw_citations = []
                    citations = self._filter_grounded_citations(raw_citations, seen_identifiers)
                    terminal_result = AgentResult(
                        has_answer=False,
                        no_answer_reason=strip_orphaned_citation_markers(args["reason"], len(citations)),
                        citations=citations,
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

    @staticmethod
    def _filter_grounded_citations(
        citations: list[Citation], seen_identifiers: set[str]
    ) -> list[Citation]:
        """_is_grounded와 같은 기준(seen_identifiers에 있는 식별자, 0~1 범위의
        relevance_score)으로 각 citation을 개별 검증하되, submit_no_answer처럼
        "일부가 무효하면 통째로 거부"가 아니라 "무효한 것만 조용히 버리고 유효한 것만
        남기는" 관대한 필터가 필요한 경로에서 쓴다."""
        valid = []
        for citation in citations:
            identifier = citation.document_version_id or citation.source_url
            if identifier is None or identifier not in seen_identifiers:
                continue
            if citation.relevance_score is not None and not (0.0 <= citation.relevance_score <= 1.0):
                continue
            valid.append(citation)
        return valid

    def _call_model(self, messages: list[dict], *, use_tools: bool = True, tools: list[dict] | None = None):
        try:
            return self._complete(MODEL_NAME, messages, use_tools=use_tools, tools=tools)
        except Exception:
            if FALLBACK_MODEL_NAME == MODEL_NAME:
                raise
            # exc_info=True — 이 경고만 보고는 원인(타임아웃/429/5xx 등)을 알 수 없어서
            # 실제 장애 조사 때 추측만 하게 됐다(2026-08-09). 예외 스택을 같이 남긴다.
            logger.warning(
                "openrouter_primary_model_failed_using_fallback",
                extra={"primary_model": MODEL_NAME, "fallback_model": FALLBACK_MODEL_NAME},
                exc_info=True,
            )
            return self._complete(FALLBACK_MODEL_NAME, messages, use_tools=use_tools, tools=tools)

    def _complete(
        self, model: str, messages: list[dict], *, use_tools: bool = True, tools: list[dict] | None = None
    ):
        # _llm_fallback_answer(위키 근거 없는 일반 지식 답변)는 tools 없이 호출한다 —
        # WikiTools/citations를 아예 안 주려는 것이므로 도구 자체를 노출하면 안 된다.
        if not use_tools:
            response = self.client.chat.completions.create(
                model=model, max_tokens=LLM_FALLBACK_MAX_TOKENS, messages=messages,
            )
        else:
            response = self.client.chat.completions.create(
                model=model,
                max_tokens=GROUNDED_ANSWER_MAX_TOKENS,
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

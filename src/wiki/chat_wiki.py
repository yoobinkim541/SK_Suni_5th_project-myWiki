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

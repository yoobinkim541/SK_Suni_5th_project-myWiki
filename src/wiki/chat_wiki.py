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
            doc_id = citation.get("document_version_id") or ""
            lines.append(f"- document_version_id={doc_id}: {quoted}")
    else:
        lines.append("없음")
    return "\n".join(lines)


class ChatWikiDraft(BaseModel):
    title: str
    markdown: str


def _build_sources_lines(citations: list[dict]) -> list[str]:
    lines = ["## 출처"]
    for citation in citations:
        quoted = citation.get("quoted_text") or ""
        doc_id = citation.get("document_version_id") or ""
        lines.append(f"- {quoted} (document_version_id={doc_id})")
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
                # 기본 30초 타임아웃 * 최대 2회 시도(기본 모델 + 폴백 모델) = 최악의 경우 약 60초까지
                # 걸릴 수 있어, 리버스 프록시/게이트웨이가 이 엔드포인트 자체를 504로 먼저 끊어버릴
                # 수 있다. 15초로 줄여 두 번 시도해도 최악의 경우 약 30초 안에 끝나도록 한다.
                timeout=15,
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

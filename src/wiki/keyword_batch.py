from __future__ import annotations

import logging

from pydantic import BaseModel

from ..analysis.classifier import create_json_completion, get_openrouter_settings, parse_json_response
from ..categories.keywords import CATEGORY_KEYWORDS
from .keyword_prompts import WIKI_KEYWORD_SYSTEM_PROMPT, build_wiki_keyword_user_prompt

logger = logging.getLogger(__name__)

MAX_KEYWORDS_PER_PAGE = 8

_ALLOWED_KEYWORDS = frozenset(
    keyword for keywords in CATEGORY_KEYWORDS.values() for keyword in keywords
)


class WikiKeywordLLMResult(BaseModel):
    keywords: list[str]


def extract_keywords_for_page(markdown: str, *, llm_client=None) -> list[str]:
    """위키 본문에서 122개 사전 안의 키워드만 추출한다.

    LLM 호출/파싱/스키마 검증이 실패하면 예외를 그대로 던진다(여기서 폴백하지 않음) —
    호출부(run_wiki_keyword_batch)가 페이지 단위로 잡아서 그 페이지만 건너뛰고
    배치를 계속 진행하는 게 이 함수의 책임 밖이기 때문이다.
    """
    settings = get_openrouter_settings()
    user_prompt = build_wiki_keyword_user_prompt(markdown)

    if llm_client is not None:
        response_text = llm_client(WIKI_KEYWORD_SYSTEM_PROMPT, user_prompt, settings.model)
    else:
        response_text = create_json_completion(
            system_prompt=WIKI_KEYWORD_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=settings.model,
        )
    payload = parse_json_response(response_text)
    result = WikiKeywordLLMResult.model_validate(payload)

    in_dictionary = [kw for kw in result.keywords if kw in _ALLOWED_KEYWORDS]
    return in_dictionary[:MAX_KEYWORDS_PER_PAGE]

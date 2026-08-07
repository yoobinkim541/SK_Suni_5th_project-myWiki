from __future__ import annotations

import logging
from typing import Literal, Optional

from pydantic import BaseModel, ValidationError
from supabase import Client

from ..analysis.classifier import create_json_completion, get_openrouter_settings, parse_json_response
from ..analysis.exceptions import (
    InvalidJsonResponseError,
    MissingApiKeyError,
    OpenRouterApiError,
    OpenRouterTimeoutError,
)
from ..analysis.repository import get_supabase
from ..categories.keywords import CATEGORY_KEYWORDS
from .keyword_prompts import WIKI_KEYWORD_SYSTEM_PROMPT, build_wiki_keyword_user_prompt
from .query import get_published_wiki_page

logger = logging.getLogger(__name__)

MAX_KEYWORDS_PER_PAGE = 8
MAX_CANDIDATES_PER_RUN = 100

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

    in_dictionary = [kw for kw in dict.fromkeys(result.keywords) if kw in _ALLOWED_KEYWORDS]
    return in_dictionary[:MAX_KEYWORDS_PER_PAGE]


class WikiKeywordPageResult(BaseModel):
    page_id: str
    slug: str
    status: Literal["tagged", "no_match", "failed"]
    keywords: list[str] = []
    error_message: Optional[str] = None


def find_pages_missing_keywords(workspace_id: str, *, supabase: Client | None = None) -> list[dict]:
    """published 페이지 중 wiki_page_keywords에 행이 하나도 없는 페이지를 찾는다.

    embedded join 대신 순차 조회(이 코드베이스의 기존 관례) — 전체 published 페이지와
    이미 키워드가 있는 page_id 집합을 각각 조회해 파이썬에서 차집합을 구한다.
    """
    db = supabase or get_supabase()

    pages = (
        db.table("wiki_pages")
        .select("id, slug")
        .eq("workspace_id", workspace_id)
        .eq("status", "published")
        .execute()
        .data
    )
    if not pages:
        return []

    page_ids = [row["id"] for row in pages]
    tagged_res = (
        db.table("wiki_page_keywords")
        .select("page_id")
        .in_("page_id", page_ids)
        .execute()
    )
    tagged_page_ids = {row["page_id"] for row in tagged_res.data}

    missing = [{"id": row["id"], "slug": row["slug"]} for row in pages if row["id"] not in tagged_page_ids]
    return missing[:MAX_CANDIDATES_PER_RUN]


def _insert_page_keywords(page_id: str, keywords: list[str], *, supabase: Client) -> None:
    if not keywords:
        return
    supabase.table("wiki_page_keywords").insert(
        [{"page_id": page_id, "keyword": keyword} for keyword in keywords]
    ).execute()


def run_wiki_keyword_batch(workspace_id: str, *, supabase: Client | None = None) -> list[WikiKeywordPageResult]:
    """키워드 없는 published 페이지를 찾아 채운다.

    한 페이지의 LLM 호출/파싱이 실패해도 그 페이지만 'failed'로 기록하고 다음
    페이지로 계속 진행한다 — 다음 배치 실행 때 여전히 '키워드 없음' 상태라 자동
    재시도된다.
    """
    db = supabase or get_supabase()
    candidates = find_pages_missing_keywords(workspace_id, supabase=db)

    results: list[WikiKeywordPageResult] = []
    for candidate in candidates:
        content = get_published_wiki_page(workspace_id, candidate["slug"])
        if content is None:
            continue

        try:
            keywords = extract_keywords_for_page(content.markdown)
        except (
            MissingApiKeyError,
            OpenRouterApiError,
            OpenRouterTimeoutError,
            InvalidJsonResponseError,
            ValidationError,
        ) as exc:
            logger.warning(
                "wiki_keyword_extraction_failed",
                extra={"page_id": candidate["id"], "slug": candidate["slug"], "error": str(exc)},
            )
            results.append(
                WikiKeywordPageResult(
                    page_id=candidate["id"], slug=candidate["slug"],
                    status="failed", error_message=str(exc),
                )
            )
            continue

        if keywords:
            _insert_page_keywords(candidate["id"], keywords, supabase=db)
            results.append(
                WikiKeywordPageResult(page_id=candidate["id"], slug=candidate["slug"], status="tagged", keywords=keywords)
            )
        else:
            results.append(WikiKeywordPageResult(page_id=candidate["id"], slug=candidate["slug"], status="no_match"))

    return results

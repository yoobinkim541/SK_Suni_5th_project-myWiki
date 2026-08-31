from __future__ import annotations

import json
import logging
import os
import threading
import time
from functools import lru_cache
from typing import Any

from dotenv import load_dotenv
from pydantic import ValidationError

from .exceptions import (
    InvalidCategoryError,
    InvalidJsonResponseError,
    MissingApiKeyError,
    OpenRouterApiError,
    OpenRouterTimeoutError,
)
from .models import ALLOWED_CATEGORIES, ClassificationResult
from .prompts import SYSTEM_PROMPT, build_user_prompt

DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# OpenRouter 모델 목록에 등록된 버전 고정 ID를 기본값으로 사용한다.
# 짧은 별칭(deepseek/deepseek-v4-flash, ...-pro)은 최신 라우팅 대상과 달라질 수 있어
# 스케줄러에서 기본·fallback 호출이 함께 실패하는 문제가 있었다.
DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-v4-flash-0731"
# 기본 모델 호출이 API/타임아웃 오류로 실패하면 이 모델로 한 번 더 시도한다.
# 유료 모델이 잔액/한도에 걸리면 OpenRouter가 JSON을 지원하는 무료 모델을 고른다.
DEFAULT_FALLBACK_MODEL = "openrouter/free"
DEFAULT_TEMPERATURE = 0
DEFAULT_TIMEOUT = 30
DEFAULT_MAX_RETRIES = 1
# OpenRouter는 max_tokens를 생략하면 모델 상한(현재 131,072)을 예약한다.
# 키 잔액이 작은 환경에서도 분류·평가 JSON이 처리되도록 출력 상한을 명시한다.
DEFAULT_MAX_TOKENS = 1024

logger = logging.getLogger(__name__)

# OpenRouter 무료 라우터는 키당 요청 빈도가 제한될 수 있다. 병렬 분석에서
# 429가 연쇄적으로 발생하지 않도록 무료 폴백 호출을 프로세스 전역에서 직렬화한다.
FREE_MODEL_MIN_INTERVAL_SECONDS = 3.2
_free_model_gate = threading.Lock()
_free_model_last_started = 0.0


def _wait_for_free_model_slot() -> None:
    global _free_model_last_started
    with _free_model_gate:
        now = time.monotonic()
        delay = FREE_MODEL_MIN_INTERVAL_SECONDS - (now - _free_model_last_started)
        if delay > 0:
            time.sleep(delay)
        _free_model_last_started = time.monotonic()


class OpenRouterSettings:
    def __init__(self) -> None:
        load_dotenv()
        self.api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        self.model = os.getenv("OPENROUTER_MODEL", "").strip() or DEFAULT_OPENROUTER_MODEL
        self.fallback_model = os.getenv("OPENROUTER_FALLBACK_MODEL", "").strip() or DEFAULT_FALLBACK_MODEL
        self.base_url = os.getenv("OPENROUTER_BASE_URL", "").strip() or DEFAULT_OPENROUTER_BASE_URL


def get_openrouter_settings() -> OpenRouterSettings:
    return OpenRouterSettings()


def classify_document(
    *,
    title: str,
    markdown: str,
    source_name: str | None = None,
    published_at: str | None = None,
) -> ClassificationResult:
    settings = get_openrouter_settings()
    if not settings.api_key:
        raise MissingApiKeyError("OPENROUTER_API_KEY 환경변수가 설정되지 않았습니다.")

    response = create_json_completion(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=build_user_prompt(
            title=title,
            markdown=markdown,
            source_name=source_name,
            published_at=published_at,
        ),
        model=settings.model,
    )
    return parse_classification_response(response)


def create_json_completion(
    *,
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """기본 모델로 호출하고, API/타임아웃 오류면 fallback_model로 한 번만 더 시도한다.
    (검증 실패 등 응답 자체의 문제는 호출부의 재시도 루프가 처리하므로 여기서 재시도하지 않는다.)"""
    settings = get_openrouter_settings()
    if not settings.api_key:
        raise MissingApiKeyError("OPENROUTER_API_KEY 환경변수가 설정되지 않았습니다.")

    primary_model = model or settings.model
    try:
        return _complete(
            system_prompt=system_prompt, user_prompt=user_prompt,
            model=primary_model, temperature=temperature, timeout=timeout,
        )
    except (OpenRouterApiError, OpenRouterTimeoutError):
        if settings.fallback_model == primary_model:
            raise
        logger.warning(
            "openrouter_primary_model_failed_using_fallback",
            extra={"primary_model": primary_model, "fallback_model": settings.fallback_model},
        )
        return _complete(
            system_prompt=system_prompt, user_prompt=user_prompt,
            model=settings.fallback_model, temperature=temperature, timeout=timeout,
        )


def _complete(
    *, system_prompt: str, user_prompt: str, model: str, temperature: float, timeout: int,
) -> str:
    if model == "openrouter/free":
        _wait_for_free_model_slot()
    client = get_openrouter_client()
    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=DEFAULT_MAX_TOKENS,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            # DeepSeek V4 Flash의 추론 토큰을 끄면 작은 잔액에서도 구조화 응답을 안정적으로 받는다.
            extra_body={"reasoning": {"enabled": False}},
            timeout=timeout,
        )
    except Exception as exc:  # pragma: no cover
        timeout_error = _get_openai_exception("APITimeoutError")
        api_error = _get_openai_exception("APIError")
        if timeout_error is not None and isinstance(exc, timeout_error):
            raise OpenRouterTimeoutError("OpenRouter API 요청이 제한 시간 내에 완료되지 않았습니다.") from exc
        if api_error is not None and isinstance(exc, api_error):
            raise OpenRouterApiError("OpenRouter API 호출 중 오류가 발생했습니다.") from exc
        raise OpenRouterApiError("OpenRouter API 호출에 실패했습니다.") from exc

    return extract_message_content(response)


def parse_classification_response(raw_content: str) -> ClassificationResult:
    payload = parse_json_response(raw_content)

    try:
        result = ClassificationResult.model_validate(payload)
    except ValidationError as exc:
        invalid_categories = [
            value for value in payload.get("secondary_categories", [])
            if value not in ALLOWED_CATEGORIES
        ]
        primary_category = payload.get("primary_category")
        if primary_category not in ALLOWED_CATEGORIES or invalid_categories:
            raise InvalidCategoryError("허용되지 않은 카테고리가 응답에 포함되었습니다.") from exc
        raise ValueError(str(exc)) from exc

    return result


def parse_json_response(raw_content: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise InvalidJsonResponseError("OpenRouter 응답이 유효한 JSON이 아닙니다.") from exc
    if not isinstance(payload, dict):
        raise InvalidJsonResponseError("OpenRouter 응답 JSON 구조가 올바르지 않습니다.")
    return payload


def extract_message_content(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise InvalidJsonResponseError("OpenRouter 응답에 선택지가 없습니다.")

    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None)
    if not content or not isinstance(content, str):
        raise InvalidJsonResponseError("OpenRouter 응답 본문이 비어 있습니다.")
    return content


@lru_cache(maxsize=1)
def _get_openai_constructor():
    from openai import OpenAI

    return OpenAI


@lru_cache(maxsize=1)
def get_openrouter_client():
    settings = get_openrouter_settings()
    constructor = _get_openai_constructor()
    return constructor(
        base_url=settings.base_url,
        api_key=settings.api_key,
        max_retries=DEFAULT_MAX_RETRIES,
    )


@lru_cache(maxsize=8)
def _get_openai_exception(name: str):
    try:
        module = __import__("openai", fromlist=[name])
    except ImportError:
        return None
    return getattr(module, name, None)


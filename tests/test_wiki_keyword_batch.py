from __future__ import annotations

import json

from pydantic import ValidationError

from src.analysis.exceptions import OpenRouterTimeoutError
from src.wiki import keyword_batch


def test_extract_keywords_filters_out_of_dictionary_values(monkeypatch):
    monkeypatch.setattr(
        keyword_batch,
        "create_json_completion",
        lambda **kwargs: json.dumps({"keywords": ["HBM", "지어낸키워드", "삼성전자"]}),
    )

    keywords = keyword_batch.extract_keywords_for_page("HBM 관련 문서, 삼성전자 언급")

    assert keywords == ["HBM", "삼성전자"]


def test_extract_keywords_truncates_to_max_eight(monkeypatch):
    from src.categories.keywords import CATEGORY_KEYWORDS

    nine_real_keywords = list(CATEGORY_KEYWORDS["제품·기술"]) + list(CATEGORY_KEYWORDS["경쟁사"])
    nine_real_keywords = nine_real_keywords[:9]
    assert len(nine_real_keywords) == 9

    monkeypatch.setattr(
        keyword_batch, "create_json_completion",
        lambda **kwargs: json.dumps({"keywords": nine_real_keywords}),
    )

    keywords = keyword_batch.extract_keywords_for_page("본문")

    assert len(keywords) == keyword_batch.MAX_KEYWORDS_PER_PAGE
    assert keywords == nine_real_keywords[:8]


def test_extract_keywords_returns_empty_list_when_no_match(monkeypatch):
    monkeypatch.setattr(
        keyword_batch, "create_json_completion", lambda **kwargs: json.dumps({"keywords": []}),
    )

    assert keyword_batch.extract_keywords_for_page("아무 관련 없는 본문") == []


def test_extract_keywords_uses_injected_llm_client():
    calls = []

    def fake_client(system_prompt, user_prompt, model):
        calls.append((system_prompt, user_prompt, model))
        return json.dumps({"keywords": ["HBM"]})

    keywords = keyword_batch.extract_keywords_for_page("본문", llm_client=fake_client)

    assert keywords == ["HBM"]
    assert len(calls) == 1
    assert calls[0][0] == keyword_batch.WIKI_KEYWORD_SYSTEM_PROMPT


def test_extract_keywords_raises_on_llm_exception(monkeypatch):
    def raise_timeout(**kwargs):
        raise OpenRouterTimeoutError("timeout")

    monkeypatch.setattr(keyword_batch, "create_json_completion", raise_timeout)

    try:
        keyword_batch.extract_keywords_for_page("본문")
        assert False, "OpenRouterTimeoutError가 그대로 올라와야 한다"
    except OpenRouterTimeoutError:
        pass


def test_extract_keywords_raises_on_invalid_schema(monkeypatch):
    monkeypatch.setattr(
        keyword_batch, "create_json_completion", lambda **kwargs: json.dumps({"not_keywords": []}),
    )

    try:
        keyword_batch.extract_keywords_for_page("본문")
        assert False, "ValidationError가 그대로 올라와야 한다"
    except ValidationError:
        pass

from __future__ import annotations

from src.categories.keywords import CATEGORY_KEYWORDS
from src.wiki import keyword_prompts


def test_system_prompt_includes_every_dictionary_keyword():
    for keywords in CATEGORY_KEYWORDS.values():
        for keyword in keywords:
            assert keyword in keyword_prompts.WIKI_KEYWORD_SYSTEM_PROMPT


def test_user_prompt_includes_markdown_body():
    prompt = keyword_prompts.build_wiki_keyword_user_prompt("# HBM4\n\nHBM4는 차세대 메모리다.")
    assert "HBM4는 차세대 메모리다." in prompt

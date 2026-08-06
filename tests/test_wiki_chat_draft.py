"""compose_chat_wiki_draft 및 관련 프롬프트/모델 테스트.

analysis/classifier.py의 create_json_completion을 monkeypatch로 대체해서
실제 OpenRouter 네트워크 호출이 절대 나가지 않게 한다(tests/test_wiki_generation.py와
동일한 패턴).
"""
from __future__ import annotations

import json

from src.analysis.exceptions import OpenRouterTimeoutError
from src.wiki import chat_wiki

SAMPLE_CITATION = {
    "id": "c1",
    "document_version_id": "dv-1",
    "quoted_text": "HBM4는 차세대 메모리다.",
    "citation_order": 1,
}


def test_user_prompt_includes_question_answer_and_evidence():
    prompt = chat_wiki._build_chat_wiki_user_prompt(
        question="HBM4가 뭐야?",
        answer="HBM4는 차세대 메모리다. [1]",
        citations=[SAMPLE_CITATION],
    )
    assert "HBM4가 뭐야?" in prompt
    assert "HBM4는 차세대 메모리다. [1]" in prompt
    assert "document_version_id=dv-1" in prompt
    assert "HBM4는 차세대 메모리다." in prompt


def test_user_prompt_handles_no_citations():
    prompt = chat_wiki._build_chat_wiki_user_prompt(
        question="HBM4가 뭐야?", answer="답변", citations=[],
    )
    assert "없음" in prompt

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
    "document_title": "SK하이닉스 HBM4 발표",
    "source_name": "전자신문",
    "published_at": "2026-08-01",
}


def test_user_prompt_includes_question_answer_and_evidence():
    prompt = chat_wiki._build_chat_wiki_user_prompt(
        question="HBM4가 뭐야?",
        answer="HBM4는 차세대 메모리다. [1]",
        citations=[SAMPLE_CITATION],
    )
    assert "HBM4가 뭐야?" in prompt
    assert "HBM4는 차세대 메모리다. [1]" in prompt
    assert "SK하이닉스 HBM4 발표 · 전자신문 · 2026-08-01" in prompt
    assert "HBM4는 차세대 메모리다." in prompt
    assert "document_version_id" not in prompt


def test_user_prompt_handles_no_citations():
    prompt = chat_wiki._build_chat_wiki_user_prompt(
        question="HBM4가 뭐야?", answer="답변", citations=[],
    )
    assert "없음" in prompt


def test_compose_chat_wiki_draft_builds_structured_markdown(monkeypatch):
    monkeypatch.setattr(
        chat_wiki,
        "create_json_completion",
        lambda **kwargs: json.dumps(
            {
                "title": "HBM4 개요",
                "answer_summary": "HBM4는 차세대 고대역폭 메모리다.",
                "key_evidence": ["HBM4는 차세대 메모리다."],
            }
        ),
    )

    draft = chat_wiki.compose_chat_wiki_draft(
        question="HBM4가 뭐야?",
        answer="HBM4는 차세대 메모리다. [1]",
        citations=[SAMPLE_CITATION],
    )

    assert draft.title == "HBM4 개요"
    assert "# HBM4 개요" in draft.markdown
    assert "## 질문" in draft.markdown
    assert "HBM4가 뭐야?" in draft.markdown
    assert "## 답변 요약" in draft.markdown
    assert "HBM4는 차세대 고대역폭 메모리다." in draft.markdown
    assert "## 핵심 근거" in draft.markdown
    assert "- HBM4는 차세대 메모리다." in draft.markdown
    assert "## 출처" in draft.markdown
    assert "(SK하이닉스 HBM4 발표 · 전자신문 · 2026-08-01)" in draft.markdown
    assert "document_version_id" not in draft.markdown


def test_compose_chat_wiki_draft_uses_injected_llm_client(monkeypatch):
    """generation.py의 llm_client 주입 패턴과 동일 — 테스트에서 fake client를 직접 넘길 수 있어야 한다."""
    calls = []

    def fake_client(system_prompt, user_prompt, model):
        calls.append((system_prompt, user_prompt, model))
        return json.dumps({"title": "t", "answer_summary": "s", "key_evidence": ["e"]})

    draft = chat_wiki.compose_chat_wiki_draft(
        question="q", answer="a", citations=[SAMPLE_CITATION], llm_client=fake_client,
    )

    assert draft.title == "t"
    assert len(calls) == 1
    assert calls[0][0] == chat_wiki.CHAT_WIKI_SYSTEM_PROMPT


def test_compose_chat_wiki_draft_falls_back_on_invalid_json(monkeypatch):
    monkeypatch.setattr(chat_wiki, "create_json_completion", lambda **kwargs: "이건 JSON이 아님")

    draft = chat_wiki.compose_chat_wiki_draft(
        question="HBM4가 뭐야?", answer="HBM4는 차세대 메모리다.", citations=[SAMPLE_CITATION],
    )

    assert draft.title == "HBM4가 뭐야?"
    assert "## 답변 요약" in draft.markdown
    assert "HBM4는 차세대 메모리다." in draft.markdown
    assert "- HBM4는 차세대 메모리다." in draft.markdown  # key_evidence 폴백 = citation quoted_text


def test_compose_chat_wiki_draft_falls_back_on_schema_validation_error(monkeypatch):
    monkeypatch.setattr(
        chat_wiki, "create_json_completion", lambda **kwargs: json.dumps({"title": "제목만 있음"}),
    )

    draft = chat_wiki.compose_chat_wiki_draft(
        question="HBM4가 뭐야?", answer="답변 원문", citations=[SAMPLE_CITATION],
    )

    assert draft.title == "HBM4가 뭐야?"
    assert "답변 원문" in draft.markdown


def test_compose_chat_wiki_draft_falls_back_on_llm_exception(monkeypatch):
    def raise_timeout(**kwargs):
        raise OpenRouterTimeoutError("timeout")

    monkeypatch.setattr(chat_wiki, "create_json_completion", raise_timeout)

    draft = chat_wiki.compose_chat_wiki_draft(
        question="HBM4가 뭐야?", answer="답변 원문", citations=[SAMPLE_CITATION],
    )

    assert draft.title == "HBM4가 뭐야?"
    assert "답변 원문" in draft.markdown


def test_compose_chat_wiki_draft_truncates_long_question_for_fallback_title(monkeypatch):
    def raise_timeout(**kwargs):
        raise OpenRouterTimeoutError("timeout")

    monkeypatch.setattr(chat_wiki, "create_json_completion", raise_timeout)
    long_question = "가" * 100

    draft = chat_wiki.compose_chat_wiki_draft(question=long_question, answer="답변", citations=[SAMPLE_CITATION])

    assert draft.title == long_question[:80]


def test_compose_chat_wiki_draft_handles_missing_document_version_id_in_fallback(monkeypatch):
    """Regression test: fallback should handle citations missing document_version_id without raising KeyError."""
    def raise_timeout(**kwargs):
        raise OpenRouterTimeoutError("timeout")

    monkeypatch.setattr(chat_wiki, "create_json_completion", raise_timeout)

    # Citation missing document_version_id
    incomplete_citation = {
        "id": "c1",
        "quoted_text": "HBM4는 차세대 메모리다.",
        "citation_order": 1,
        # document_version_id intentionally omitted
    }

    # Should not raise KeyError; should return fallback draft
    draft = chat_wiki.compose_chat_wiki_draft(
        question="HBM4가 뭐야?",
        answer="HBM4는 차세대 메모리다.",
        citations=[incomplete_citation],
    )

    assert draft.title == "HBM4가 뭐야?"
    assert "## 답변 요약" in draft.markdown
    assert "HBM4는 차세대 메모리다." in draft.markdown

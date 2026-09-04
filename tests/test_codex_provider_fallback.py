from __future__ import annotations

from types import SimpleNamespace

from src.report import composer
from src.wiki import generation


def test_report_uses_codex_when_openrouter_is_unavailable(monkeypatch) -> None:
    expected = '{"title":"ok"}'
    monkeypatch.setattr(composer, "get_openrouter_settings", lambda: SimpleNamespace(api_key=""))
    monkeypatch.setattr(composer, "get_codex_cli_settings", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(
        composer,
        "create_json_completion_with_codex",
        lambda **_kwargs: expected,
    )

    result = composer._create_report_json_completion(
        system_prompt="system",
        user_prompt="user",
        config=composer.ReportComposerConfig(),
    )

    assert result == expected


def test_wiki_uses_codex_after_openrouter_failure(monkeypatch) -> None:
    expected = '{"action":"skip","claims":[]}'
    monkeypatch.setattr(
        generation,
        "create_json_completion",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("402")),
    )
    monkeypatch.setattr(generation, "get_codex_cli_settings", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(
        generation,
        "create_json_completion_with_codex",
        lambda **_kwargs: expected,
    )

    assert generation._create_topic_json_completion("system", "user", "model") == expected


def test_wiki_uses_codex_when_openrouter_returns_non_json(monkeypatch) -> None:
    expected = '{"action":"skip","claims":[]}'
    monkeypatch.setattr(generation, "create_json_completion", lambda **_kwargs: "not-json")
    monkeypatch.setattr(generation, "get_codex_cli_settings", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(
        generation,
        "create_json_completion_with_codex",
        lambda **_kwargs: expected,
    )

    assert generation._create_topic_json_completion("system", "user", "model") == expected

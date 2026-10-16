import subprocess
from types import SimpleNamespace

import pytest

from src.llm import agy_cli

MESSAGES = [{"role": "system", "content": "시스템"}, {"role": "user", "content": "질문"}]


def fake_runner(calls, rc=0, out='{"a": 1}\n', err=""):
    def runner(cmd, **kw):
        calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, rc, out, err)
    return runner


class FakeFallback:
    def __init__(self):
        self.calls = []
        completions = SimpleNamespace(create=self._create)
        self.chat = SimpleNamespace(completions=completions)

    def _create(self, **kw):
        self.calls.append(kw)
        return "openrouter-response"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(agy_cli, "load_dotenv", lambda *a, **k: None)
    for name in ("AGY_CLI_ENABLED", "AGY_CLI_PATH", "AGY_CLI_HOME", "AGY_MODEL"):
        monkeypatch.delenv(name, raising=False)


def test_wrap_client_is_noop_unless_enabled(monkeypatch):
    real = object()
    assert agy_cli.wrap_client(real) is real
    monkeypatch.setenv("AGY_CLI_ENABLED", "true")
    assert isinstance(agy_cli.wrap_client(real), agy_cli.AgyChatClient)


def test_json_completion_uses_agy_and_returns_openai_shape(monkeypatch):
    monkeypatch.setenv("AGY_CLI_HOME", "/opt/agy-home")
    calls = []
    client = agy_cli.AgyChatClient(runner=fake_runner(calls, out='noise {"a": 1} tail'))
    resp = client.chat.completions.create(
        model="deepseek/x", messages=MESSAGES, response_format={"type": "json_object"}, timeout=40)
    assert resp.choices[0].message.content == '{"a": 1}'
    cmd, kw = calls[0]
    assert cmd[0] == "agy" and cmd[1] == "--print"
    assert "Return exactly one valid JSON object" in cmd[2] and "시스템" in cmd[2] and "질문" in cmd[2]
    assert cmd[cmd.index("--model") + 1] == "gemini-3.8-flash-medium"
    assert kw["env"]["HOME"] == "/opt/agy-home" and kw["stdin"] == subprocess.DEVNULL
    assert "mywiki-agy-" in kw["cwd"]


def test_plain_text_completion_is_not_json_normalized():
    client = agy_cli.AgyChatClient(runner=fake_runner([], out=" 제목 \n"))
    resp = client.chat.completions.create(model="m", messages=[{"role": "user", "content": "q"}])
    assert resp.choices[0].message.content == "제목"


@pytest.mark.parametrize("kwargs", [
    {"rc": 1, "err": "boom"},
    {"out": "  "},
    {"out": "not json at all"},
])
def test_failure_falls_back_to_openrouter(kwargs):
    fallback = FakeFallback()
    client = agy_cli.AgyChatClient(fallback=fallback, runner=fake_runner([], **kwargs))
    out = client.chat.completions.create(
        model="m", messages=MESSAGES, response_format={"type": "json_object"})
    assert out == "openrouter-response" and fallback.calls[0]["model"] == "m"


def test_failure_without_fallback_raises():
    client = agy_cli.AgyChatClient(runner=fake_runner([], rc=1))
    with pytest.raises(agy_cli.AgyCliError):
        client.chat.completions.create(model="m", messages=MESSAGES)


def test_oversized_prompt_skips_agy():
    calls, fallback = [], FakeFallback()
    client = agy_cli.AgyChatClient(fallback=fallback, runner=fake_runner(calls))
    big = [{"role": "user", "content": "가" * 50_000}]
    assert client.chat.completions.create(model="m", messages=big) == "openrouter-response"
    assert calls == []

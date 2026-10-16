"""OpenAI-client-compatible bridge to the Antigravity CLI (``agy``).

``classifier``/``composer``/``titling`` only call ``client.chat.completions.create(...)`` and read
``response.choices[0].message.content``.  ``wrap_client`` returns an object with that shape that runs
``agy --print`` (Gemini, on the signed-in Antigravity subscription) instead, and falls back to the
wrapped OpenRouter client when agy is off, missing, or fails.  Opt-in: ``AGY_CLI_ENABLED=true``.

agy is an agent, so every call runs in an empty temp directory (no repo access) and the prompt goes
on the command line (agy has no stdin prompt); oversized prompts skip agy and use the fallback.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import threading
from types import SimpleNamespace
from typing import Any

from dotenv import load_dotenv

from .codex_cli import CodexCliError, normalize_json_output

logger = logging.getLogger(__name__)

DEFAULT_AGY_MODEL = "gemini-3.8-flash-medium"
DEFAULT_AGY_TIMEOUT_SECONDS = 90
DEFAULT_AGY_MAX_CONCURRENCY = 2
# Linux caps one argv string at 128 KiB; stay below it.
MAX_PROMPT_BYTES = 120_000

JSON_INSTRUCTION = (
    "Return exactly one valid JSON object and no Markdown fences, commentary, or headings."
)

_gate_lock = threading.Lock()
_gate: threading.BoundedSemaphore | None = None


class AgyCliError(RuntimeError):
    """Raised when agy cannot produce a usable response."""


def agy_enabled() -> bool:
    load_dotenv()
    return os.getenv("AGY_CLI_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def _concurrency_gate() -> threading.BoundedSemaphore:
    # Each agy run boots a ~400 MB process; analysis runs in parallel, so bound it.
    global _gate
    with _gate_lock:
        if _gate is None:
            try:
                limit = max(1, int(os.getenv("AGY_CLI_MAX_CONCURRENCY", "")))
            except ValueError:
                limit = DEFAULT_AGY_MAX_CONCURRENCY
            _gate = threading.BoundedSemaphore(limit)
        return _gate


def build_prompt(messages: list[dict[str, Any]], *, json_mode: bool) -> str:
    parts: list[str] = []
    for message in messages:
        role = str(message.get("role") or "user")
        content = message.get("content")
        if not isinstance(content, str):
            raise AgyCliError("agy bridge only supports plain-text messages.")
        if role == "system":
            parts.append(f"=== SYSTEM INSTRUCTIONS ===\n{content.strip()}")
        else:
            parts.append(f"=== {role.upper()} ===\n{content.strip()}")
    if json_mode:
        parts.insert(0, JSON_INSTRUCTION)
    return "\n\n".join(parts) + "\n"


def run_agy(prompt: str, *, timeout: int, runner: Any | None = None) -> str:
    if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise AgyCliError("prompt too large for agy command line.")
    secs = max(30, int(timeout))
    command = [
        os.getenv("AGY_CLI_PATH", "").strip() or "agy",
        "--print", prompt,
        "--model", os.getenv("AGY_MODEL", "").strip() or DEFAULT_AGY_MODEL,
        "--print-timeout", f"{secs}s",
    ]
    env = dict(os.environ)
    # Container deployments keep agy's login state in a dedicated home (see docker-compose.yml).
    agy_home = os.getenv("AGY_CLI_HOME", "").strip()
    if agy_home:
        env["HOME"] = agy_home
    with _concurrency_gate(), tempfile.TemporaryDirectory(prefix="mywiki-agy-") as scratch:
        try:
            result = (runner or subprocess.run)(
                command, cwd=scratch, env=env, stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=secs + 30, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AgyCliError("agy request timed out.") from exc
        except OSError as exc:
            raise AgyCliError(f"agy could not be started: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or "").strip()[-300:] or f"exit code {result.returncode}"
        raise AgyCliError(f"agy failed: {detail}")
    text = (result.stdout or "").strip()
    if not text:
        raise AgyCliError("agy returned an empty response.")
    return text


class _Completions:
    def __init__(self, fallback: Any | None, runner: Any | None) -> None:
        self._fallback, self._runner = fallback, runner

    def create(self, **kwargs: Any) -> Any:
        json_mode = (kwargs.get("response_format") or {}).get("type") == "json_object"
        try:
            prompt = build_prompt(kwargs["messages"], json_mode=json_mode)
            text = run_agy(prompt, timeout=int(kwargs.get("timeout") or DEFAULT_AGY_TIMEOUT_SECONDS),
                           runner=self._runner)
            if json_mode:
                text = normalize_json_output(text)
        except (AgyCliError, CodexCliError) as exc:
            if self._fallback is None:
                raise
            logger.warning("agy_failed_using_openrouter: %s", str(exc)[:200])
            return self._fallback.chat.completions.create(**kwargs)
        message = SimpleNamespace(content=text, role="assistant")
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])


class AgyChatClient:
    """Duck-typed stand-in for ``openai.OpenAI`` covering ``chat.completions.create``."""

    def __init__(self, fallback: Any | None = None, runner: Any | None = None) -> None:
        self.chat = SimpleNamespace(completions=_Completions(fallback, runner))


def wrap_client(client: Any) -> Any:
    """Return an agy-backed client (falling back to ``client``) when enabled, else ``client``."""
    return AgyChatClient(fallback=client) if agy_enabled() else client

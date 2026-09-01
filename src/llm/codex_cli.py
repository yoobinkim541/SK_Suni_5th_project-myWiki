"""Small, non-interactive bridge to the Codex CLI.

This follows the same process boundary as stock-report: ``codex exec`` is
started with an explicit read-only sandbox, an ephemeral session, and a
file-backed final response.  The bridge is intentionally opt-in so GitHub
Actions and local development keep the existing OpenRouter behaviour until a
Hermes host has Codex CLI installed and authenticated.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

DEFAULT_CODEX_MODEL = "gpt-5.5"
DEFAULT_CODEX_REASONING = "low"
DEFAULT_CODEX_SANDBOX = "read-only"
DEFAULT_CODEX_TIMEOUT_SECONDS = 180


class CodexCliError(RuntimeError):
    """Raised when Codex CLI cannot produce a JSON response."""


@dataclass(frozen=True)
class CodexCliSettings:
    enabled: bool
    command: str
    workspace: Path
    model: str
    reasoning: str
    sandbox: str
    timeout_seconds: int


def get_codex_cli_settings() -> CodexCliSettings:
    """Read opt-in settings for the Hermes/stock-report style bridge."""
    load_dotenv()
    workspace = os.getenv("CODEX_CLI_WORKSPACE", "").strip()
    workspace_path = (
        Path(workspace).expanduser().resolve()
        if workspace
        else Path(__file__).resolve().parents[2]
    )
    timeout_raw = os.getenv("CODEX_CLI_TIMEOUT_SECONDS", "").strip()
    try:
        timeout_seconds = max(30, min(900, int(timeout_raw))) if timeout_raw else DEFAULT_CODEX_TIMEOUT_SECONDS
    except ValueError:
        timeout_seconds = DEFAULT_CODEX_TIMEOUT_SECONDS
    return CodexCliSettings(
        enabled=os.getenv("CODEX_CLI_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"},
        command=os.getenv("CODEX_CLI_PATH", "").strip() or "codex",
        workspace=workspace_path,
        model=os.getenv("CODEX_MODEL", "").strip() or DEFAULT_CODEX_MODEL,
        reasoning=os.getenv("CODEX_REASONING", "").strip() or DEFAULT_CODEX_REASONING,
        sandbox=os.getenv("CODEX_SANDBOX", "").strip() or DEFAULT_CODEX_SANDBOX,
        timeout_seconds=timeout_seconds,
    )


def build_codex_exec_args(
    *,
    command: str,
    workspace: str | Path,
    output_path: str | Path,
    model: str,
    reasoning: str,
    sandbox: str = DEFAULT_CODEX_SANDBOX,
) -> list[str]:
    """Build safe, current Codex CLI arguments.

    The final ``-`` makes Codex read the prompt from stdin, avoiding shell or
    command-line length issues when article context is large.  The command is
    returned as an argv list and is never passed through a shell.
    """
    return [
        command,
        "exec",
        "--skip-git-repo-check",
        "--ephemeral",
        "-C",
        str(workspace),
        "-s",
        sandbox,
        "-m",
        model,
        "-c",
        f'model_reasoning_effort="{reasoning}"',
        "--color",
        "never",
        "-o",
        str(output_path),
        "-",
    ]


def codex_cli_available(settings: CodexCliSettings | None = None) -> bool:
    settings = settings or get_codex_cli_settings()
    command = Path(settings.command)
    if command.is_absolute() or "/" in settings.command or "\\" in settings.command:
        return command.is_file()
    return shutil.which(settings.command) is not None


def _prompt_for_json(system_prompt: str, user_prompt: str) -> str:
    return (
        "You are a backend JSON generation worker.\n"
        "Return exactly one valid JSON object and no Markdown fences, commentary, or headings.\n"
        "Follow the output schema implied by the system instructions.\n\n"
        "=== SYSTEM INSTRUCTIONS ===\n"
        f"{system_prompt.strip()}\n\n"
        "=== USER DATA ===\n"
        f"{user_prompt.strip()}\n"
    )


def normalize_json_output(raw_output: str) -> str:
    """Normalize a Codex final answer to a compact JSON object string."""
    text = str(raw_output or "").strip()
    if not text:
        raise CodexCliError("Codex CLI returned an empty response.")

    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError:
        payload = None

    if payload is None:
        decoder = json.JSONDecoder()
        for index, char in enumerate(text):
            if char != "{":
                continue
            try:
                candidate, _end = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                payload = candidate
                break

    if not isinstance(payload, dict):
        raise CodexCliError("Codex CLI response was not a JSON object.")
    return json.dumps(payload, ensure_ascii=False)


def create_json_completion_with_codex(
    *,
    system_prompt: str,
    user_prompt: str,
    settings: CodexCliSettings | None = None,
    runner: Any | None = None,
) -> str:
    """Run one bounded Codex CLI request and return normalized JSON.

    ``runner`` is an injectable subprocess-compatible callable used by tests;
    production calls use :func:`subprocess.run`.
    """
    resolved = settings or get_codex_cli_settings()
    if not resolved.enabled:
        raise CodexCliError("Codex CLI provider is disabled.")
    if not codex_cli_available(resolved):
        raise CodexCliError(f"Codex CLI command not found: {resolved.command}")
    if not resolved.workspace.is_dir():
        raise CodexCliError(f"Codex CLI workspace does not exist: {resolved.workspace}")

    run = runner or subprocess.run
    prompt = _prompt_for_json(system_prompt, user_prompt)
    with tempfile.TemporaryDirectory(prefix="mywiki-codex-") as temp_dir:
        output_path = Path(temp_dir) / "last-message.json"
        args = build_codex_exec_args(
            command=resolved.command,
            workspace=resolved.workspace,
            output_path=output_path,
            model=resolved.model,
            reasoning=resolved.reasoning,
            sandbox=resolved.sandbox,
        )
        try:
            result = run(
                args,
                cwd=str(resolved.workspace),
                input=prompt,
                text=True,
                capture_output=True,
                timeout=resolved.timeout_seconds,
                check=False,
                env={**os.environ, "NO_COLOR": "1"},
            )
        except subprocess.TimeoutExpired as exc:
            raise CodexCliError("Codex CLI request timed out.") from exc
        except OSError as exc:
            raise CodexCliError(f"Codex CLI could not be started: {exc}") from exc

        response_text = output_path.read_text(encoding="utf-8") if output_path.is_file() else ""
        if not response_text.strip():
            response_text = str(getattr(result, "stdout", "") or "")
        if getattr(result, "returncode", 1) != 0:
            stderr = str(getattr(result, "stderr", "") or "").strip()
            detail = stderr[-1000:] if stderr else f"exit code {result.returncode}"
            raise CodexCliError(f"Codex CLI failed: {detail}")
        return normalize_json_output(response_text)


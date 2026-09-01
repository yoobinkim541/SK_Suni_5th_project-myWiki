from __future__ import annotations

import json

from src.llm.codex_cli import build_codex_exec_args, normalize_json_output


def test_build_codex_exec_args_matches_stock_report_safe_mode() -> None:
    args = build_codex_exec_args(
        command="codex",
        workspace="/srv/myWiki",
        output_path="/tmp/codex-output.json",
        model="gpt-5.5",
        reasoning="low",
        sandbox="read-only",
    )

    assert args == [
        "codex",
        "exec",
        "--skip-git-repo-check",
        "--ephemeral",
        "-C",
        "/srv/myWiki",
        "-s",
        "read-only",
        "-m",
        "gpt-5.5",
        "-c",
        'model_reasoning_effort="low"',
        "--color",
        "never",
        "-o",
        "/tmp/codex-output.json",
        "-",
    ]


def test_normalize_json_output_accepts_codex_markdown_fence() -> None:
    payload = {"action": "skip", "claims": []}

    assert json.loads(normalize_json_output(f"```json\n{json.dumps(payload)}\n```")) == payload



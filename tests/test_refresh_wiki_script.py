from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from src.wiki.generation_models import WikiDraftGenerationResult

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "refresh_wiki.py"


def _load_script_module():
    """scripts/refresh_wiki.py를 모듈로 로드한다.

    scripts/ 는 패키지가 아니라 일반 import가 안 되므로 파일 경로 기반으로 로드한다.
    모듈 최상단은 클라이언트를 실제로 만들지 않으므로(get_client는 호출 시점에만 접속)
    임포트만으로는 부작용이 없다.
    """
    spec = importlib.util.spec_from_file_location("refresh_wiki_script", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def refresh_wiki_script():
    return _load_script_module()


def _result(issue_key: str, error_message: str | None = None) -> WikiDraftGenerationResult:
    return WikiDraftGenerationResult(
        issue_key=issue_key,
        issue_page_id="" if error_message else "page-1",
        issue_version_id="" if error_message else "version-1",
        topic_action="skip",
        error_message=error_message,
    )


def test_report_results_returns_zero_when_no_results(refresh_wiki_script, capsys):
    exit_code = refresh_wiki_script.report_results([])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "0개 이슈 처리" in out


def test_report_results_returns_zero_when_all_succeed(refresh_wiki_script, capsys):
    results = [_result("issue-1"), _result("issue-2")]

    exit_code = refresh_wiki_script.report_results(results)

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "issue-1" in out
    assert "issue-2" in out


def test_report_results_returns_zero_and_prints_error_on_partial_failure(refresh_wiki_script, capsys):
    results = [_result("issue-ok"), _result("issue-fail", error_message="Storage 업로드 실패")]

    exit_code = refresh_wiki_script.report_results(results)

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "issue-ok" in out
    assert "error: Storage 업로드 실패" in out


def test_report_results_returns_nonzero_when_every_result_failed(refresh_wiki_script, capsys):
    results = [
        _result("issue-1", error_message="LLM 오류"),
        _result("issue-2", error_message="DB 오류"),
    ]

    exit_code = refresh_wiki_script.report_results(results)

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "error: LLM 오류" in out
    assert "error: DB 오류" in out

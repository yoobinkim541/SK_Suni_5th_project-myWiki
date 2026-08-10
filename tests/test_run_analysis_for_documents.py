from __future__ import annotations

from pathlib import Path

import pytest

from scripts.run_analysis_for_documents import collect_document_version_ids, main


def test_collect_document_version_ids_from_positional_only():
    assert collect_document_version_ids(positional=["a", "b"], file_path=None) == ["a", "b"]


def test_collect_document_version_ids_merges_file_and_dedupes(tmp_path):
    file_path = tmp_path / "ids.txt"
    file_path.write_text("b\nc\n\na\n", encoding="utf-8")

    result = collect_document_version_ids(positional=["a", "b"], file_path=str(file_path))

    assert result == ["a", "b", "c"]  # 순서 보존, 중복(b, a) 제거


def test_collect_document_version_ids_strips_blank_lines(tmp_path):
    file_path = tmp_path / "ids.txt"
    file_path.write_text("a\n   \nb\n", encoding="utf-8")

    assert collect_document_version_ids(positional=[], file_path=str(file_path)) == ["a", "b"]


def test_main_returns_1_when_no_ids_given(capsys):
    assert main([]) == 1
    assert "대상 id가 없습니다" in capsys.readouterr().out


def test_main_returns_1_when_over_max_candidates(monkeypatch, capsys):
    monkeypatch.setattr("scripts.run_analysis_for_documents.MAX_ANALYSIS_CANDIDATES", 2)

    assert main(["id-1", "id-2", "id-3"]) == 1
    assert "최대 2건" in capsys.readouterr().out


def test_main_calls_run_analysis_pipeline_with_explicit_ids_and_matching_limit(monkeypatch):
    calls = []
    monkeypatch.setattr("scripts.run_analysis_for_documents.get_workspace_id", lambda: "ws-1")
    monkeypatch.setattr(
        "scripts.run_analysis_for_documents.run_analysis_pipeline",
        lambda workspace_id, *, limit, document_version_ids: calls.append((workspace_id, limit, document_version_ids)) or ["id-1", "id-2"],
    )

    exit_code = main(["id-1", "id-2"])

    assert exit_code == 0
    assert calls == [("ws-1", 2, ["id-1", "id-2"])]


def test_main_returns_1_when_pipeline_reports_failure(monkeypatch):
    monkeypatch.setattr("scripts.run_analysis_for_documents.get_workspace_id", lambda: "ws-1")
    monkeypatch.setattr(
        "scripts.run_analysis_for_documents.run_analysis_pipeline",
        lambda workspace_id, *, limit, document_version_ids: None,
    )

    assert main(["id-1"]) == 1


def test_main_uses_explicit_workspace_id_when_given(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "scripts.run_analysis_for_documents.get_workspace_id",
        lambda: (_ for _ in ()).throw(AssertionError("get_workspace_id should not be called when --workspace-id is given")),
    )
    monkeypatch.setattr(
        "scripts.run_analysis_for_documents.run_analysis_pipeline",
        lambda workspace_id, *, limit, document_version_ids: calls.append(workspace_id) or ["id-1"],
    )

    assert main(["--workspace-id", "ws-explicit", "id-1"]) == 0
    assert calls == ["ws-explicit"]

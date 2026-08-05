from __future__ import annotations

from src.wiki.citation_text import strip_orphaned_citation_markers


def test_strip_orphaned_citation_markers_keeps_all_when_within_range():
    text = "A[1] B[2] C[3]"
    assert strip_orphaned_citation_markers(text, citation_count=3) == text


def test_strip_orphaned_citation_markers_removes_out_of_range_numbers():
    text = "첫 문장[1]. 다음 문장[4]."
    assert strip_orphaned_citation_markers(text, citation_count=1) == "첫 문장[1]. 다음 문장."


def test_strip_orphaned_citation_markers_removes_zero_like_numbers():
    text = "이상함[0]."
    assert strip_orphaned_citation_markers(text, citation_count=3) == "이상함."


def test_strip_orphaned_citation_markers_handles_no_citations():
    text = "근거 없음[1]."
    assert strip_orphaned_citation_markers(text, citation_count=0) == "근거 없음."

from __future__ import annotations

from src.wiki.text_similarity import is_duplicate_title, title_similarity


def test_title_similarity_exact_match_is_one():
    assert title_similarity("HBM4 공급 부족 심화", "HBM4 공급 부족 심화") == 1.0


def test_title_similarity_unrelated_titles_is_low():
    assert title_similarity("SK하이닉스", "HBM4 공급 부족 심화") < 0.2


def test_is_duplicate_title_true_for_exact_match():
    assert is_duplicate_title("SK하이닉스, 무디스 신용등급 'A3' 상향과 중기 시장 기회",
                               "SK하이닉스, 무디스 신용등급 'A3' 상향과 중기 시장 기회") is True


def test_is_duplicate_title_false_for_meaningfully_different_titles():
    assert is_duplicate_title("HBM4_수급현황", "HBM4 공급 부족 심화") is False


def test_is_duplicate_title_false_when_either_title_is_empty():
    assert is_duplicate_title("", "HBM4 공급 부족 심화") is False
    assert is_duplicate_title("HBM4 공급 부족 심화", "") is False


def test_is_duplicate_title_respects_custom_threshold():
    # "HBM4 공급"과 "HBM4 공급 부족 심화"는 토큰 일부만 겹침 — 낮은 threshold면 True.
    assert is_duplicate_title("HBM4 공급", "HBM4 공급 부족 심화", threshold=0.3) is True
    assert is_duplicate_title("HBM4 공급", "HBM4 공급 부족 심화", threshold=0.9) is False

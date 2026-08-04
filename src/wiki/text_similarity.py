from __future__ import annotations

import re
import unicodedata

# 두 제목이 이 이상 겹치면 "사실상 같은 제목"으로 본다(토큰 자카드 유사도).
DEFAULT_DUPLICATE_TITLE_THRESHOLD = 0.8
_TOKEN_SPLIT_PATTERN = re.compile(r"[\s\W_]+", re.UNICODE)


def _title_tokens(title: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", title or "").strip().lower()
    return {token for token in _TOKEN_SPLIT_PATTERN.split(normalized) if token}


def title_similarity(a: str, b: str) -> float:
    """두 제목의 토큰 자카드 유사도(0.0~1.0). 둘 중 하나라도 비어있으면 0.0."""
    tokens_a = _title_tokens(a)
    tokens_b = _title_tokens(b)
    if not tokens_a or not tokens_b:
        return 0.0
    union = tokens_a | tokens_b
    return len(tokens_a & tokens_b) / len(union)


def is_duplicate_title(
    candidate_title: str,
    issue_title: str,
    *,
    threshold: float = DEFAULT_DUPLICATE_TITLE_THRESHOLD,
) -> bool:
    """두 제목이 사실상 같은 제목인지 판단한다.

    위키 토픽 페이지가 이슈 페이지를 그대로 복제하는 문제(실사용 데이터에서 확인된
    버그)를 막기 위해, LLM 판단에만 맡기지 않고 코드에서 결정적으로 검사한다.
    """
    return title_similarity(candidate_title, issue_title) >= threshold

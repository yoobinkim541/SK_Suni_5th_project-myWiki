"""
documents.title 정규화 — 매체명 꼬리표 제거.

구글 뉴스 RSS는 <title>을 "기사제목 - 매체명" 형식으로 준다. collect는 이 값을
가공 없이 documents.title에 넣으므로(collectors/interface.py _resolve_title) 꼬리표가
그대로 DB에 남고, 위키·보고서·채팅의 근거 표시에까지 노출된다.

원문 <title>이 이미 매체명으로 끝나는 경우 RSS가 한 번 더 붙여서 두 겹이 된다.
    "... 목표가 400만원 유지" - 머니투데이 - 머니투데이
    SK하이닉스, 샌디스크와 HBF 첫 표준 규격 공개 - 조선비즈 - Chosunbiz
    "SK하이닉스 저평가, 2배 더 간다"...월가 분석에 ADR 8% 급등 - 머니투데이 - mt.co.kr
그래서 반복해서 벗기되 상한(_MAX_STRIPS)을 둔다.

제목 본문에 " - "가 들어간 기사를 훼손하면 안 된다. 실제로 수집분에 이런 게 있다.
    Uttar Pradesh Semiconductor Policy, 2024 - Driving with the Times
그래서 매체명 화이트리스트가 아니라 **형태**로 판정한다 — 짧고(_MAX_SUFFIX_LEN),
단어 수가 적고(_MAX_SUFFIX_WORDS), 문장부호가 없어야 매체명으로 본다.
위 예시는 22자·4단어라 두 조건 모두에서 걸러진다.

collect(수집 시점 힌트)와 preprocess(원문 <title>) 양쪽이 쓰므로 공용 모듈에 둔다.
"""
from __future__ import annotations

import re

# documents.title VARCHAR(500)
TITLE_MAX_LEN = 500

# 매체명으로 인정할 꼬리 토큰의 상한. 관측된 최장 매체명은 'MTN 머니투데이방송'(12자)이고,
# 오탐 사례 'Driving with the Times'는 22자다. 그 사이에서 보수적으로 잡는다.
_MAX_SUFFIX_LEN = 20
_MAX_SUFFIX_WORDS = 3

# 두 겹까지만 벗긴다. 세 겹은 관측된 적이 없고, 상한이 없으면 제목을 계속 갉아먹는다.
_MAX_STRIPS = 2

# 이만큼도 안 남으면 꼬리표가 아니라 제목 본체를 자른 것으로 본다.
_MIN_REMAINDER_LEN = 10

# 매체명에는 안 나오고 문장에는 나오는 문자. 하나라도 있으면 꼬리표로 보지 않는다.
# 마침표는 제외 — 'mt.co.kr', 'v.daum.net' 같은 도메인 형태가 실제 꼬리표로 쓰인다.
_SENTENCE_CHARS = set(',"\'“”‘’…?!·:;()[]{}<>')

# 구분자 앞뒤 공백은 반드시 있어야 한다. 'e-커머스' 같은 하이픈 합성어를 건드리지 않기 위해서다.
# head를 greedy로 둬서 **마지막** 구분자에서 자른다. 꼬리에서 하이픈을 배제하면
# 'g-enews.com' 같은 매체명을 못 잡는다 — 두 겹은 어차피 루프가 처리한다.
_TAIL = re.compile(r"^(?P<head>.*\S)\s+[-–—]\s+(?P<tail>.+)$")

_WHITESPACE = re.compile(r"\s+")


def _looks_like_publisher(token: str) -> bool:
    """꼬리 토큰이 매체명 형태인가. 화이트리스트가 아니라 형태로만 판정한다."""
    token = token.strip()
    if not token or len(token) > _MAX_SUFFIX_LEN:
        return False
    if len(token.split()) > _MAX_SUFFIX_WORDS:
        return False
    return not any(ch in _SENTENCE_CHARS for ch in token)


def strip_publisher_suffix(title: str) -> str:
    """
    제목 끝의 ' - 매체명' 꼬리표를 최대 _MAX_STRIPS번 제거한다.

    판정 실패(= 매체명 형태가 아님)면 그 지점에서 멈춘다. 확신이 없으면 그냥 둔다 —
    잘못 자르는 쪽이 꼬리표를 남겨두는 쪽보다 손해가 크다.
    """
    result = (title or "").strip()
    for _ in range(_MAX_STRIPS):
        m = _TAIL.match(result)
        if m is None:
            break
        head, tail = m.group("head").strip(), m.group("tail").strip()
        if len(head) < _MIN_REMAINDER_LEN or not _looks_like_publisher(tail):
            break
        result = head
    return result


def normalize_title(title: str, *, fallback: str = "") -> str:
    """
    documents.title에 넣을 최종 형태. 꼬리표 제거 + 공백 정리 + 길이 상한.

    전부 벗겨져 빈 문자열이 되면 fallback을 쓴다. documents.title은 NOT NULL이다.
    """
    text = _WHITESPACE.sub(" ", strip_publisher_suffix(title)).strip()
    if not text:
        text = _WHITESPACE.sub(" ", (fallback or "").strip())
    return text[:TITLE_MAX_LEN]

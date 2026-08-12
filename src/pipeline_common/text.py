"""
Markdown 조각에 사람이 읽을 텍스트가 있는지 판정한다.

왜 필요한가: 언론사가 봇을 막을 때 HTTP 403을 주지 않고 "차단 안내 이미지 한 장"을
200으로 돌려주는 경우가 있다. 2026-08-12 대시보드 '최신 뉴스'에 뜬 se-cu.com 기사가
그랬다 — 리다이렉트 끝이 http://se-cu.com/ndsoft/error.html 였고, 정제된 본문은
통째로 아래 한 줄이었다.

    ![](403.jpg)

이 값이 document_versions에 남으면 분석이 그걸 근거로 삼고, 인용문 자리에 그대로
올라와 카드에 "![](403.jpg)"가 노출된다. 빈 문자열이 아니라서 기존의 `if not markdown`
·`.strip()` 검사는 전부 통과한다.

이미지 문법에서 URL만 버리고 alt는 남기는 이유는 preprocessing/boilerplate.py의
replace_images_with_alt와 같다 — URL은 정보가 아니지만 alt는 사진 설명이라 뜻이 있다.
그래서 alt가 있는 사진 한 장짜리 문서는 여기서 살아남고, alt조차 없는 차단 이미지만
걸린다.
"""
from __future__ import annotations

import re

__all__ = ["has_readable_text", "strip_image_urls"]

# ![alt](url) -> alt. 그림 URL은 버리고 설명만 남긴다.
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")

# 한글·영문·숫자를 포함한 모든 문자 체계의 글자. 밑줄은 글자로 치지 않는다
# (\w는 '_'를 포함해서, '___' 같은 구분선만 있는 본문을 텍스트로 오판한다).
_WORD_CHAR = re.compile(r"[^\W_]", re.UNICODE)


def strip_image_urls(markdown: str) -> str:
    """`![alt](url)`을 alt로 바꾼다. alt가 없으면 빈 문자열이 된다."""
    return _MD_IMAGE.sub(r"\1", markdown or "")


def has_readable_text(markdown: str) -> bool:
    """이미지 URL을 걷어낸 뒤 글자가 하나라도 남으면 True.

    문턱을 '글자 1자 이상'으로 잡은 이유: 이건 본문 품질 검사가 아니라 "읽을 것이
    아예 없는가"만 보는 최소 방어선이다. 길이 하한(예: 50자)을 두면 짧지만 멀쩡한
    속보·단신까지 버리게 되는데, 그건 이 문제와 무관한 손실이다.
    """
    return bool(_WORD_CHAR.search(strip_image_urls(markdown)))

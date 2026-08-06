"""
canonical_url 정규화 (pipeline_common/urls.py).

이 모듈의 위험은 "덜 지우는 것"이 아니라 "더 지우는 것"이다. 기존 문서와 다른
값을 만들면 uq_documents_workspace_url이 안 걸려 같은 기사가 하나 더 생긴다.
그래서 보존 케이스를 지우기 케이스보다 두껍게 깐다.
"""
from __future__ import annotations

import pytest

from src.pipeline_common.urls import normalize_url

GOOGLE_ARTICLE = "https://news.google.com/rss/articles/CBMiaEFVX3lxTFBk"


# ------------------------------------------------------------
# 지우는 것 — 구글 표시 파라미터
# ------------------------------------------------------------


def test_removes_google_display_params() -> None:
    url = f"{GOOGLE_ARTICLE}?oc=5&hl=en-US&gl=US&ceid=US:en"

    assert normalize_url(url) == GOOGLE_ARTICLE


def test_removes_google_params_from_publisher_url_and_keeps_the_rest() -> None:
    """피드가 원문 주소에 표시 파라미터를 붙여 주는 경우."""
    url = "https://www.mt.co.kr/article/2026080312?hl=ko&idxno=167505"

    assert normalize_url(url) == "https://www.mt.co.kr/article/2026080312?idxno=167505"


def test_removes_tracking_params() -> None:
    """실데이터에는 없지만 방어용으로 막아둔 값들."""
    url = "https://example.com/a?utm_source=x&utm_medium=y&fbclid=z&gclid=w&id=7"

    assert normalize_url(url) == "https://example.com/a?id=7"


def test_param_name_match_is_case_insensitive() -> None:
    assert normalize_url("https://example.com/a?OC=5&Hl=ko") == "https://example.com/a"


def test_lowercases_scheme_and_host() -> None:
    assert normalize_url("HTTPS://News.Google.COM/rss") == "https://news.google.com/rss"


# ------------------------------------------------------------
# 보존해야 하는 것 — 지우면 기사가 목록 페이지가 된다
# ------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://www.iminju.net/news/articleView.html?idxno=167505",
        "https://www.edaily.co.kr/News/Read?newsId=03663766645543712&mediaCodeNo=257",
        "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260729800013",
        "http://www.newstomato.com/ReadNews.aspx?no=1309031&inflow=N",
        "https://example.co.kr/view?num=123",
        "https://example.co.kr/view?ncd=456",
        "https://example.co.kr/view?key=abc&command=read",
    ],
)
def test_preserves_cms_article_identifiers(url: str) -> None:
    """국내 CMS 식별자. 화이트리스트 방식이면 여기서 다 날아간다."""
    assert normalize_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        # www.을 지우면 209건의 기존 문서와 값이 어긋난다
        "https://www.yna.co.kr/view/AKR20260802",
        # 끝 슬래시를 지우면 20건이 어긋난다
        "https://www.hankyung.com/article/",
        # 경로 대소문자는 서버가 구분할 수 있다
        "https://example.com/News/Read",
        # 프래그먼트도 건드리지 않는다
        "https://example.com/a#section2",
        # 그 밖의 유입 표시 파라미터는 지우는 목록에 없다
        "https://www.dt.co.kr/article/12076221?ref=naver",
        "https://www.segye.com/newsView/20260803511351?OutUrl=naver",
        "https://v.daum.net/v/20260805225107667?f=m",
    ],
)
def test_leaves_untargeted_forms_untouched(url: str) -> None:
    assert normalize_url(url) == url


def test_preserves_remaining_param_order() -> None:
    """순서가 바뀌어도 기존 문서와 값이 어긋난다. 정렬하지 않는다."""
    url = "https://example.com/a?z=1&a=2&m=3"

    assert normalize_url(url) == url


def test_does_not_reencode_kept_param_values() -> None:
    """
    parse_qsl -> urlencode로 다시 묶으면 값이 재인코딩돼 지운 게 없어도 URL이
    달라진다. 실데이터(moneycontrol)에 값으로 URL을 담은 주소가 있다.
    """
    url = "https://www.moneycontrol.com/europe/?url=https://www.moneycontrol.com/news/a-1234.html"

    assert normalize_url(url) == url


def test_does_not_reencode_when_dropping_a_param() -> None:
    url = "https://example.com/a?hl=ko&url=https://example.com/b?x=1&title=한 글"

    assert normalize_url(url) == "https://example.com/a?url=https://example.com/b?x=1&title=한 글"


def test_drops_param_without_value() -> None:
    assert normalize_url("https://example.com/a?oc&idxno=7") == "https://example.com/a?idxno=7"


# ------------------------------------------------------------
# 망가진 입력 — 예외를 던지지 않는다
# ------------------------------------------------------------


@pytest.mark.parametrize("value", [None, ""])
def test_returns_falsy_input_as_is(value) -> None:
    assert normalize_url(value) == value


def test_whitespace_only_becomes_empty() -> None:
    """
    호출부(collectors/interface.py)가 빈 문자열을 no_canonical_url로 세므로
    공백뿐인 값은 빈 문자열로 접어준다.
    """
    assert normalize_url("   ") == ""


@pytest.mark.parametrize(
    "url",
    [
        "not a url",
        "/news/articleView.html?idxno=1",
        "mailto:someone@example.com",
        "https://example.com:포트/a",
    ],
)
def test_does_not_raise_on_unparseable_input(url: str) -> None:
    """여기서 죽으면 수집 1건이 통째로 날아간다. 원본을 그대로 돌려준다."""
    assert normalize_url(url) == url


def test_strips_surrounding_whitespace() -> None:
    assert normalize_url("  https://example.com/a  ") == "https://example.com/a"


def test_is_idempotent() -> None:
    """두 번 적용해도 같은 값이어야 한다 — 아니면 수집할 때마다 값이 흔들린다."""
    url = f"{GOOGLE_ARTICLE}?oc=5&hl=en-US&idxno=99"
    once = normalize_url(url)

    assert normalize_url(once) == once

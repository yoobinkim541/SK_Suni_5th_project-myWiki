"""
HTML 본문 추출 테스트.

케이스는 2026-08-05에 실패한 parse_document job 13건을 raw 파일까지 받아 분석한 결과에서 왔다.
    조선일보 계열 8 / news.google.com 3 / biz.sbs.co.kr 1  -> 전부 JS 렌더링, 정적 수집 불가
    businesspost.co.kr 1                                   -> 빈 #content가 body 폴백을 가로막던 버그
"""
from __future__ import annotations

import pytest

from src.preprocessing.parsers import ParseError, parse

# businesspost.co.kr 구조 축약 — 빈 <div id="content">가 있고 본문은 그 밖에 있다.
EMPTY_SELECTOR_HTML = """<!doctype html>
<html lang="ko">
  <head><title>CXMT LPDDR6 D램 양산</title></head>
  <body>
    <div id="content"></div>
    <div class="detail">
      <h2>CXMT LPDDR6 D램 이르면 하반기 양산</h2>
      <p>중국 창신메모리테크놀로지가 LPDDR6 D램을 이르면 올해 하반기 양산한다.
         삼성전자·SK하이닉스와의 기술 격차가 거의 사라졌다는 분석이 나온다.</p>
    </div>
  </body>
</html>
""".encode("utf-8")

# 본문이 있는 셀렉터가 정상적으로 매칭되는 경우
NORMAL_HTML = """<!doctype html>
<html lang="ko">
  <head><title>SK하이닉스 HBM4</title></head>
  <body>
    <article>
      <p>SK하이닉스가 HBM4 양산을 시작했다고 밝혔다. 업계는 이를 기술 우위 확보로 평가한다.</p>
    </article>
    <div class="footer-junk">푸터 광고 영역</div>
  </body>
</html>
""".encode("utf-8")


def test_빈_셀렉터를_건너뛰고_본문을_찾는다() -> None:
    """#content가 매칭되지만 비어 있다. 매칭만 보면 여기서 멈춰 정제가 실패한다."""
    parsed = parse(EMPTY_SELECTOR_HTML, "text/html")

    assert "CXMT LPDDR6" in parsed.markdown
    assert "기술 격차" in parsed.markdown


def test_내용이_있는_셀렉터는_그대로_쓴다() -> None:
    """폴백이 body로 넘어가면 푸터·광고까지 섞인다. 정상 매칭은 유지돼야 한다."""
    parsed = parse(NORMAL_HTML, "text/html")

    assert "HBM4 양산" in parsed.markdown
    assert "푸터 광고" not in parsed.markdown


def test_JS_렌더링_페이지는_사유를_구분해_남긴다() -> None:
    """
    고칠 수 있는 실패와 원리상 불가능한 실패가 한 문자열로 뭉치면
    실패율을 봐도 손댈 곳이 있는지 판단할 수 없다.
    """
    spa = b"<html><body><div id='root'></div>" + b"<!--" + b"x" * 6000 + b"-->" + b"</body></html>"

    with pytest.raises(ParseError) as exc:
        parse(spa, "text/html")

    assert "정제 결과가 비어 있다" in str(exc.value)
    assert "JS로 렌더링" in str(exc.value)


def test_작은_빈_문서는_JS_힌트를_붙이지_않는다() -> None:
    """원문 자체가 짧으면 JS 렌더링이라 단정할 근거가 없다."""
    with pytest.raises(ParseError) as exc:
        parse(b"<html><body><script>var a=1;</script></body></html>", "text/html")

    assert "정제 결과가 비어 있다" in str(exc.value)
    assert "JS로 렌더링" not in str(exc.value)

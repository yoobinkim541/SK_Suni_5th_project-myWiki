"""
상용구 제거 판정 테스트.

이 판정기의 실패 비용은 비대칭이다.
    덜 지움 -> 버전 churn이 남는다 (되돌릴 수 있다)
    더 지움 -> 본문·인용 근거가 사라진다 (되돌릴 수 없다)
그래서 '지운다' 케이스보다 '안 지운다' 케이스를 더 촘촘히 둔다.

HTML은 2026-08-07 관측된 실제 노이즈 형태를 축약한 것이다. 버전이 가장 많던 문서 4건의
v1<->v2 diff는 전부 아래 관련기사 목록 형태였고 본문 문단 변경은 0개였다.
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from src.preprocessing.boilerplate import strip_boilerplate

BODY = (
    "SK하이닉스가 HBM4 양산을 시작했다고 밝혔다. 회사는 이번 양산으로 고대역폭 메모리 "
    "시장에서 기술 우위를 확보했다고 설명했다. 업계는 내년 상반기까지 공급이 빠듯할 "
    "것으로 본다."
)


def _node(html: str):
    return BeautifulSoup(html, "html.parser")


def test_관련기사_목록을_제거한다() -> None:
    """v1<->v2 diff에서 실제로 관측된 형태. 본문은 그대로 남아야 한다."""
    node = _node(
        f"""
        <div>
          <p>{BODY}</p>
          <div class="related">
            <a href="/1">12년 잠든 비트코인 깨어났다…무슨 일?</a>
            <a href="/2">콩국수 '소금파 vs 설탕파' 그만 싸워라…</a>
            <a href="/3">주말 날씨, 전국에 비</a>
          </div>
        </div>
        """
    )

    stripped, report = strip_boilerplate(node)
    text = stripped.get_text(" ", strip=True)

    assert "HBM4 양산" in text
    assert "비트코인" not in text
    assert "콩국수" not in text
    assert report.removed_blocks == 1
    assert report.reverted is False
    assert report.removed[0].rule == "link_density"


def test_ul_형태의_추천기사_목록을_제거한다() -> None:
    node = _node(
        f"""
        <div>
          <p>{BODY}</p>
          <ul class="recommend">
            <li><a href="/1">많이 본 뉴스 1</a></li>
            <li><a href="/2">많이 본 뉴스 2</a></li>
            <li><a href="/3">많이 본 뉴스 3</a></li>
            <li><a href="/4">많이 본 뉴스 4</a></li>
          </ul>
        </div>
        """
    )

    stripped, report = strip_boilerplate(node)
    text = stripped.get_text(" ", strip=True)

    assert "HBM4 양산" in text
    assert "많이 본 뉴스" not in text
    assert report.removed[0].rule == "list"


def test_인라인_링크가_섞인_본문_문단은_보존한다() -> None:
    """
    과다 제거 방지의 핵심 케이스.

    본문 문단에도 링크가 3개 이상 들어갈 수 있다. 앵커 개수만 보면 걸리므로
    '앵커 밖 텍스트가 충분한가'를 먼저 본다.
    """
    node = _node(
        f"""
        <div>
          <p>{BODY} 자세한 내용은 <a href="/a">공시</a>와 <a href="/b">보도자료</a>,
             <a href="/c">실적발표</a>에서 확인할 수 있다.</p>
        </div>
        """
    )

    stripped, report = strip_boilerplate(node)

    assert "HBM4 양산" in stripped.get_text(" ", strip=True)
    assert report.removed_blocks == 0
    assert report.reverted is False


def test_본문_속_링크_2개는_앵커_하한에_걸리지_않는다() -> None:
    """짧은 문단이라 앵커 밖 텍스트 보호에는 못 걸려도, 앵커가 3개 미만이면 남는다."""
    node = _node('<div><p>관련 <a href="/a">공시</a>와 <a href="/b">자료</a>.</p></div>')

    _, report = strip_boilerplate(node)

    assert report.removed_blocks == 0


def test_상용구가_본문보다_많아도_본문만_남긴다() -> None:
    """
    _MAIN_SELECTORS가 안 맞아 <body>로 폴백하는 사이트(dailian.co.kr 등)는
    본문보다 관련기사 레일이 길다. 실측으로 10,307자 중 기사는 절반이 안 됐다.

    제거 비율을 상한으로 걸면 이런 페이지에서 전량 되돌려져 아무것도 못 지운다.
    실제로 그래서 버전 14개가 14개 해시로 남아 있었다 (2026-08-07 게이트 3).
    """
    links = "".join(f'<div class="l"><a href="/{i}">추천 기사 제목 {i}</a>'
                    f'<a href="/{i}b">추천 기사 제목 {i}b</a>'
                    f'<a href="/{i}c">추천 기사 제목 {i}c</a></div>' for i in range(12))
    node = _node(f"<div><p>{BODY}</p>{links}</div>")

    stripped, report = strip_boilerplate(node)
    text = stripped.get_text(" ", strip=True)

    assert report.reverted is False
    assert report.removed_blocks == 12
    assert "HBM4 양산" in text  # 본문은 남는다
    assert "추천 기사 제목" not in text  # 상용구는 사라진다
    assert report.shrink_ratio > 0.5  # 절반 넘게 지워도 정상이다


def test_본문_덩어리가_줄어들면_되돌린다() -> None:
    """
    본문 보존의 실제 지표 — 가장 긴 '앵커 밖' 텍스트 덩어리.

    본문이 짧아서 앵커 밖 텍스트 보호선(150자)에 못 미치는 기사가 링크에 둘러싸여
    있으면, 블록 규칙만으로는 본문째 지워진다. 이 경우 최장 덩어리가 줄어드는 것으로
    잡아내 되돌린다.
    """
    short_body = "짧은 기사 본문이다. 백 자에 조금 못 미치게 적어 둔 문장이며 보호선에는 걸리지 않는다."
    long_links = "".join(
        f'<a href="/{i}">아주 긴 관련기사 제목을 가진 링크 {i}번 항목이며 길이를 늘리려고 덧붙인다</a>'
        for i in range(3)
    )
    node = _node(f'<div><div class="mix"><p>{short_body}</p>{long_links}</div></div>')

    stripped, report = strip_boilerplate(node)

    assert report.reverted is True
    assert "덩어리" in (report.revert_reason or "")
    assert short_body in stripped.get_text(" ", strip=True)


def test_본문이_거의_없으면_되돌린다() -> None:
    """
    제거 비율은 상한 안이지만 남는 텍스트가 하한 미만인 경우.

    본문이 짧은 문서는 상용구를 조금만 지워도 빈 문서가 된다. 빈 정제 결과는
    parse()에서 ParseError가 되어 문서가 통째로 실패하므로, 지우지 않는 쪽을 택한다.
    """
    node = _node(
        """
        <div>
          <p>짧은 본문 문장이다. 이 문장은 마흔 자 남짓으로 짧게 적었다.</p>
          <div><a href="/1">가나다라</a><a href="/2">마바사아</a><a href="/3">자차카타</a></div>
        </div>
        """
    )

    stripped, report = strip_boilerplate(node)

    assert report.reverted is True
    assert "하한" in (report.revert_reason or "")
    assert "가나다라" in stripped.get_text(" ", strip=True)


def test_루트_노드_자신은_판정하지_않는다() -> None:
    """
    루트는 _parse_html이 이미 '본문'으로 고른 노드다. 후보에 넣으면 링크가 많은
    페이지에서 본문 전체가 한 블록으로 걸려, 안쪽의 진짜 상용구를 못 지운다.
    """
    node = _node(
        '<div><a href="/1">링크 하나</a><a href="/2">링크 둘</a><a href="/3">링크 셋</a>'
        f"<p>{BODY}</p></div>"
    )

    _, report = strip_boilerplate(node)

    # 루트를 판정했다면 removed[0].tag가 루트 div이고 본문까지 통째로 걸린다.
    assert all(block.excerpt.find("HBM4") == -1 for block in report.removed)


def test_원본_노드를_변형하지_않는다() -> None:
    """되돌리기가 '원본 반환' 한 줄로 끝나려면 원본이 온전해야 한다."""
    node = _node(
        f"""
        <div>
          <p>{BODY}</p>
          <div><a href="/1">관련기사 하나</a><a href="/2">관련기사 둘</a>
               <a href="/3">관련기사 셋</a></div>
        </div>
        """
    )
    before = str(node)

    strip_boilerplate(node)

    assert str(node) == before


def test_링크가_없는_문서는_손대지_않는다() -> None:
    node = _node(f"<div><p>{BODY}</p></div>")

    stripped, report = strip_boilerplate(node)

    assert report.removed_blocks == 0
    assert report.kept_chars > 0
    assert stripped is node


def test_리포트가_제거량과_잔존량을_기록한다() -> None:
    """오탐 측정(계획 게이트 2)이 이 값들을 읽는다."""
    node = _node(
        f"""
        <div>
          <p>{BODY}</p>
          <div><a href="/1">관련기사 하나</a><a href="/2">관련기사 둘</a>
               <a href="/3">관련기사 셋</a></div>
        </div>
        """
    )

    _, report = strip_boilerplate(node)

    assert report.removed_chars > 0
    assert report.kept_chars >= len(BODY)
    assert 0.0 < report.shrink_ratio < 0.4
    assert report.removed[0].excerpt.startswith("관련기사 하나")

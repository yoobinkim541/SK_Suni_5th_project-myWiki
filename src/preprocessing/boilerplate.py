"""
상용구(관련기사·추천기사 블록) 제거 (명세 §2-1 '노이즈 제거').

왜 필요한가
    content_hash가 정제된 Markdown 전체 기준이라, 본문이 그대로여도 관련기사 목록만
    바뀌면 새 document_versions 행이 쌓인다. 2026-08-07 실측으로 1,445행 중 452행이
    이 노이즈였고, 버전이 가장 많은 문서 4건의 v1<->v2 diff는 본문 문단 변경이 0개였다.
    즉 지금의 '정정 반영'은 정정과 노이즈를 구분하지 못한 채 재분석을 돌리고 있다.

왜 링크 밀도인가
    관측된 노이즈 라인('+12년 잠든 비트코인 깨어났다…무슨 일?')은 전부 <a> 텍스트다.
    parsers._parse_html이 markdownify(..., strip=["a"])로 앵커 '태그'만 벗기고 텍스트는
    남기기 때문에 Markdown에서는 평범한 줄로 보이지만, DOM에서는 앵커가 빽빽한 블록이다.
    본문 문단은 앵커 텍스트 비율이 0에 가까워서 이 지표 하나로 두 부류가 갈린다.

    사이트별 CSS 셀렉터를 쓰지 않는 이유: 관측 도메인이 120종이라 유지가 안 된다.
    도메인별 반복 블록 마이닝을 쓰지 않는 이유: 코퍼스 상태를 저장할 스키마가 없고
    롱테일 도메인은 문서가 1~2건뿐이라 '반복' 자체가 잡히지 않는다.

    **판정은 markdownify 이전, soup 위에서 해야 한다.** Markdown에는 링크 정보가 없다.

과하게 지우면 본문이 날아간다
    그래서 이 모듈은 '지운다'보다 '안 지운다'에 무게를 둔다. 아래 안전장치 3개 중
    하나라도 걸리면 원본 노드를 그대로 돌려준다. 덜 지워서 남는 버전 churn이
    본문·인용 근거 손실보다 싸다는 판단이다 (계획 §3 게이트 1 우선 규칙).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 무거운 import는 런타임에 하지 않는다 (지침 §3)
    from bs4.element import Tag


# --- 제거 판정 임계값 ---------------------------------------------------------

# 본문 속 인용 링크 1~2개가 걸리지 않도록 하는 하한.
_MIN_ANCHORS = 3

# 블록 텍스트 중 앵커 텍스트가 차지하는 비율.
_LINK_DENSITY_DROP = 0.6

# 목록 규칙은 <li> 형태라는 추가 근거가 있으므로 밀도 기준을 조금 낮춘다.
_LIST_MIN_ITEMS = 3
_LIST_LINK_DENSITY_DROP = 0.5
_LIST_MAX_ITEM_LEN = 100

# --- 안전장치 ---------------------------------------------------------------

# 앵커 밖 텍스트가 이만큼 있는 블록은 어떤 규칙에도 걸리지 않는다.
# 관련기사 목록은 거의 전부가 앵커 텍스트라 이 값을 넘지 못하고,
# 인라인 링크가 섞인 본문 문단은 넘는다.
_PROTECT_TEXT_LEN = 150

# 최후의 백스톱. 이 비율을 넘게 지우게 되면 아무것도 지우지 않는다.
#
# 처음에는 0.4로 잡았는데 그게 틀렸다. _MAIN_SELECTORS가 하나도 안 맞는 사이트는
# 메인 노드가 <body> 전체로 폴백하고(dailian.co.kr 등), 그런 페이지는 본문보다
# 관련기사 레일이 더 길다 — 실측으로 10,307자 중 5,000자 남짓만 기사였다.
# 0.4는 그 페이지에서 "52% 제거"를 보고 전량 되돌렸고, 결과적으로 버전 14개가
# 14개 해시로 남았다(2026-08-07 게이트 3 측정).
#
# 제거 비율은 애초에 본문 보존의 지표가 아니다. 본문을 지키는 건 아래 두 가지다.
#   1) _PROTECT_TEXT_LEN — 앵커 밖 텍스트가 긴 블록은 규칙에 걸리지 않는다.
#      집계값이라 자식에 실린 본문 문단까지 같이 보호된다.
#   2) _MIN_TEXT_RUN_KEPT — 가장 긴 텍스트 덩어리가 줄어들면 본문을 건드린 것이다.
# 비율은 병리적인 경우를 막는 백스톱으로만 남긴다.
_MAX_STRIP_RATIO = 0.9

# 제거 후 남은 텍스트 하한. parsers._MIN_MAIN_TEXT_LEN과 같은 값이지만
# parsers -> boilerplate 방향 import라 순환을 피하려고 여기에 따로 둔다.
_MIN_KEPT_TEXT_LEN = 50


@dataclass(frozen=True)
class RemovedBlock:
    """제거된 블록 1개의 근거. 오탐 조사와 dry-run 리포트가 이걸 읽는다."""

    rule: str  # 'link_density' | 'list'
    tag: str
    chars: int
    excerpt: str


@dataclass(frozen=True)
class StripReport:
    """
    제거 결과. 오탐률 측정(계획 §3 게이트 1·2)의 유일한 근거다.

    reverted=True면 blocks/chars는 '지웠을 뻔한 양'이고 실제로는 지우지 않았다.
    """

    removed_blocks: int = 0
    removed_chars: int = 0
    kept_chars: int = 0
    reverted: bool = False
    revert_reason: str | None = None
    removed: tuple[RemovedBlock, ...] = field(default_factory=tuple)

    @property
    def shrink_ratio(self) -> float:
        """제거 비율. 되돌린 경우 0.0."""
        total = self.kept_chars + self.removed_chars
        if self.reverted or total == 0:
            return 0.0
        return self.removed_chars / total


def replace_images_with_alt(node: "Tag") -> int:
    """
    <img>를 alt 텍스트로 바꾼다(alt가 없으면 지운다). 바꾼 개수를 돌려준다.

    왜 필요한가: markdownify가 이미지를 `![alt](url)`로 남기는데, 언론사 CDN은
    같은 사진에도 매번 다른 URL을 준다(썸네일 크기·캐시 파라미터·배너 로테이션).
    2026-08-07 접힘 측정에서 안 접힌 108건의 잔여 diff 중 가장 흔한 패턴이 이거였다.
        ![](https://img2.daumcdn.net/thumb/R658x0.q70/?fname=...)   v.daum.net 24건
        ![](https://img.newspim.com//mynews/mynews_banner1.jpg)     newspim 6건
    본문은 한 글자도 안 바뀌었는데 URL만 달라져 새 버전이 생긴다.

    URL을 버리고 alt를 남기는 이유: 분석 LLM에게 이미지 URL은 아무 정보도 아니지만
    alt는 사진 설명이라 뜻이 있다. 이미지를 통째로 지우면 그것까지 잃는다.
    이 단계는 되돌리지 않는다 — 상용구 판정과 달리 본문을 지울 위험이 없다.
    """
    from bs4.element import NavigableString

    replaced = 0
    for image in node.find_all("img"):
        alt = (image.get("alt") or "").strip()
        if alt:
            image.replace_with(NavigableString(alt))
        else:
            image.decompose()
        replaced += 1
    return replaced


def strip_boilerplate(node: "Tag") -> tuple["Tag", StripReport]:
    """
    본문 노드에서 상용구 블록을 제거한 사본과 그 근거를 돌려준다.

    원본 node는 변형하지 않는다 — 재파싱한 사본에서 지우므로 되돌리기가
    '원본을 그대로 반환'으로 끝난다.
    """
    from bs4 import BeautifulSoup

    original_len = len(_text(node))
    if original_len == 0:
        return node, StripReport()

    working = BeautifulSoup(str(node), "html.parser")
    removed: list[RemovedBlock] = []
    # 루트 자신은 판정하지 않고 자식부터 본다. 루트는 호출자(_parse_html)가 이미
    # '본문'으로 고른 노드라서, 이걸 후보에 넣으면 링크가 많은 페이지에서 본문 전체가
    # 한 블록으로 걸린다. 안전장치가 되돌려주기는 하지만 그러면 안쪽의 진짜 상용구도
    # 같이 살아남아 아무것도 못 지운다.
    for root in working.find_all(True, recursive=False):
        _strip_children(root, removed)

    if not removed:
        return node, StripReport(kept_chars=original_len)

    kept_len = len(_text(working))
    removed_len = original_len - kept_len
    counts = {
        "removed_blocks": len(removed),
        "removed_chars": removed_len,
        "kept_chars": kept_len,
        "removed": tuple(removed),
    }

    # 본문 보존의 실제 지표. 가장 긴 텍스트 덩어리가 짧아졌다면 본문을 지운 것이다.
    kept_run = _longest_text_run(working)
    original_run = _longest_text_run(node)
    if kept_run < original_run:
        reason = f"최장 텍스트 덩어리가 {original_run}자에서 {kept_run}자로 줄어듦"
        return node, StripReport(reverted=True, revert_reason=reason, **counts)

    shrink = removed_len / original_len
    if shrink > _MAX_STRIP_RATIO:
        reason = f"제거 비율 {shrink:.0%}가 상한 {_MAX_STRIP_RATIO:.0%}를 넘음"
        return node, StripReport(reverted=True, revert_reason=reason, **counts)
    if kept_len < _MIN_KEPT_TEXT_LEN:
        reason = f"제거 후 남은 텍스트 {kept_len}자가 하한 {_MIN_KEPT_TEXT_LEN}자 미만"
        return node, StripReport(reverted=True, revert_reason=reason, **counts)

    return working, StripReport(**counts)


# ------------------------------------------------------------
# 내부
# ------------------------------------------------------------


def _strip_children(parent: "Tag", removed: list[RemovedBlock]) -> None:
    """자식 블록을 훑어 제거 대상이면 지우고, 아니면 그 안으로 내려간다."""
    for child in list(parent.find_all(True, recursive=False)):
        rule = _drop_rule(child)
        if rule is None:
            _strip_children(child, removed)
            continue
        text = _text(child)
        removed.append(
            RemovedBlock(rule=rule, tag=child.name, chars=len(text), excerpt=text[:80])
        )
        child.decompose()


def _drop_rule(block: "Tag") -> str | None:
    """제거 대상이면 규칙 이름, 아니면 None."""
    text_len = len(_text(block))
    if text_len == 0:
        return None  # 빈 태그는 markdownify가 알아서 흘린다. 지울 이유가 없다

    anchors = [a for a in block.find_all("a") if _text(a)]
    if not anchors:
        return None

    link_len = sum(len(_text(a)) for a in anchors)
    # 앵커 밖 텍스트가 충분하면 본문이다. 다른 조건을 보기 전에 빠져나간다.
    if text_len - link_len >= _PROTECT_TEXT_LEN:
        return None

    density = link_len / text_len

    if block.name in ("ul", "ol"):
        items = block.find_all("li", recursive=False)
        if (
            len(items) >= _LIST_MIN_ITEMS
            and density >= _LIST_LINK_DENSITY_DROP
            and all(len(_text(li)) <= _LIST_MAX_ITEM_LEN for li in items)
        ):
            return "list"

    if len(anchors) >= _MIN_ANCHORS and density >= _LINK_DENSITY_DROP:
        return "link_density"
    return None


def _longest_text_run(node: "Tag") -> int:
    """
    한 요소에 직접 붙어 있는 텍스트 중 가장 긴 것의 길이.

    '본문이 남아 있는가'를 구조에 기대지 않고 재는 방법이다. 기사 문단은 수백 자짜리
    덩어리가 되지만 관련기사 헤드라인은 한 줄짜리 조각들이라, 이 값이 줄었다면
    상용구가 아니라 본문을 건드린 것이다.

    자식 요소를 타고 내려가 합치지 않는다 — 합치면 컨테이너가 전부 커져서
    "가장 긴 덩어리"가 아니라 "가장 큰 컨테이너"를 재게 된다.

    앵커 안의 텍스트는 세지 않는다. dailian.co.kr에는 301자짜리 <a> 텍스트가 있어서
    (요약이 딸린 관련기사 카드), 이걸 세면 상용구가 '본문'으로 잡혀 되돌림이 걸린다.
    """
    from bs4.element import NavigableString

    longest = 0
    for element in node.find_all(True):
        if element.name == "a" or element.find_parent("a") is not None:
            continue
        run = sum(
            len(child.strip())
            for child in element.children
            if isinstance(child, NavigableString)
        )
        if run > longest:
            longest = run
    return longest


def _text(node: "Tag") -> str:
    return node.get_text(" ", strip=True)

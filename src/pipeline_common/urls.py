"""
documents.canonical_url 정규화.

canonical_url은 uq_documents_workspace_url이 걸린 문서 식별자다. 같은 기사가
표기만 다른 주소로 들어오면 별개 문서가 되므로, 수집 시점에 표기를 하나로 맞춘다.

**대상을 좁게 잡는다.** 2026-08-06 수집분 373건을 실제로 재보고 정한 범위다.
정규화는 문서를 합쳐주기도 하지만, 기존 문서와 다른 값을 만들면 오히려 같은
기사를 하나 더 만든다. 그래서 "합쳐지는 게 있어서 넣는 규칙"만 넣고,
효과가 확인 안 된 규칙은 넣지 않는다.

    규칙                    현재 데이터에서 값이 바뀌는 문서
    호스트 소문자화          0건 (대문자 호스트 없음)
    구글 파라미터 제거        33건 — 전부 news.google.com 주소
    utm·fbclid·gclid 제거    0건 (실데이터에 없음. 방어용으로만 둔다)

일부러 **하지 않는** 것

    www. 제거      209건의 canonical_url이 바뀌는데 합쳐지는 문서는 0건이다.
                   기존 문서와 값이 어긋나 다음 수집에서 209건이 중복으로
                   재생성된다. 이득 0 / 비용 209라 넣지 않는다
    끝 슬래시 제거   같은 이유로 20건이 바뀌고 합쳐지는 건 0건
    쿼리 파라미터 정렬·전면 제거
                   idxno·newsId·rcpNo·no·num·ncd·key·command는 국내 CMS의
                   기사 식별자다. 지우면 URL이 기사가 아니라 목록 페이지가 된다.
                   그래서 블랙리스트 방식만 쓰고 화이트리스트를 쓰지 않는다

구글 파라미터 제거가 남아 있는 이유: fetchers가 디코딩 실패한 구글 주소를 이미
버리므로(UnresolvedURLError) 새 데이터에는 구글 주소가 안 들어온다. 그래도
피드가 원문 주소에 oc·hl을 붙여 주는 경우를 대비한 방어층으로 남긴다.
"""
from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

# 구글 뉴스가 링크에 붙이는 표시 파라미터. 기사 식별과 무관하다.
# oc=출력형식 / hl=UI언어 / gl=국가 / ceid=국가:언어
_GOOGLE_PARAMS = frozenset({"oc", "hl", "gl", "ceid"})

# 유입 경로 추적용. 2026-08-06 수집분에는 한 건도 없지만, 소스가 늘면 들어올 수
# 있어 미리 막아둔다. 지워도 기사 식별에 영향이 없는 값들이다.
_TRACKING_PARAMS = frozenset(
    {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid"}
)

DROP_PARAMS = _GOOGLE_PARAMS | _TRACKING_PARAMS


def normalize_url(url: str | None) -> str | None:
    """
    canonical_url로 쓸 표기를 통일한다. 값이 없거나 파싱이 안 되면 원본을 그대로 돌려준다.

    - 스킴·호스트를 소문자로
    - DROP_PARAMS에 있는 쿼리 파라미터만 제거 (나머지는 순서까지 보존)
    - 그 밖의 것(www., 끝 슬래시, 경로 대소문자, 프래그먼트)은 건드리지 않는다

    정규화 실패를 예외로 만들지 않는다. 여기서 죽으면 수집 1건이 통째로 날아가는데,
    표기를 못 다듬는 것보다 문서를 놓치는 쪽이 손해가 크다.
    """
    if not url:
        return url
    stripped = url.strip()
    if not stripped:
        return stripped

    # urlsplit은 지연 파싱이라 urlsplit() 자체는 통과하고 .hostname·.port를 읽을 때
    # ValueError가 난다(포트가 숫자가 아닌 경우 등). 그래서 파싱만이 아니라
    # 속성 접근까지 통째로 감싼다.
    try:
        parts = urlsplit(stripped)
        # 스킴이나 호스트가 없으면 절대 URL이 아니다. 손대지 않는다.
        if not parts.scheme or not parts.netloc:
            return stripped
        netloc = _lower_host(parts)
        query = _drop_params(parts.query)
    except ValueError:
        return stripped

    return urlunsplit((parts.scheme.lower(), netloc, parts.path, query, parts.fragment))


def _lower_host(parts) -> str:
    """호스트만 소문자로 낮춘다. userinfo·포트는 원형을 지킨다."""
    host = parts.hostname
    if not host:
        return parts.netloc
    netloc = host.lower()
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    if parts.username:
        credential = parts.username
        if parts.password:
            credential = f"{credential}:{parts.password}"
        netloc = f"{credential}@{netloc}"
    return netloc


def _drop_params(query: str) -> str:
    """
    DROP_PARAMS만 걷어낸다. 남는 파라미터는 순서·값·**인코딩까지** 그대로 둔다.

    parse_qsl로 풀었다가 urlencode로 다시 묶으면 안 된다. 남겨둔 값이 재인코딩돼서
    지운 파라미터가 하나도 없어도 URL 문자열이 달라진다. 실제로 수집분에
    ?url=https://... 처럼 값에 URL이 들어간 주소가 있고, 이게 ?url=https%3A%2F%2F...
    로 바뀌면 기존 문서와 값이 어긋나 같은 기사가 하나 더 생긴다.
    그래서 원본 문자열을 & 단위로만 자른다.
    """
    if not query:
        return query
    kept = [
        fragment
        for fragment in query.split("&")
        if fragment.split("=", 1)[0].lower() not in DROP_PARAMS
    ]
    return "&".join(kept)

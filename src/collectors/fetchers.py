"""
source_type별 원문 수집기.

collect()는 어느 소스를 어떻게 긁는지 몰라도 되게, 이 모듈이 source_type ->
수집 함수 매핑만 제공한다. 새 소스를 붙일 때는 register_fetcher()로 등록한다.

sources.config(JSONB)에서 읽는 키
    feed_url          RSS 피드 주소 (없으면 sources.base_url)
    provider          news 소스의 제공자 'naver' | 'gnews' (기본 naver)
    api_variant       naver 소스의 호출 경로 'apihub' | 'legacy' (기본 apihub)
    query             검색어 (news 소스)
    lang              gnews 검색 언어 (기본 en)
    country           gnews 매체 국가 (선택)
    corp_code         DART 고유번호 8자리 (disclosure 소스 필수) — corpCode.xml에서 1회 조회
    pblntf_ty         DART 공시유형 필터 (disclosure 소스, 선택 — 없으면 전체)
    lookback_days     disclosure 소스가 since 없이 처음 돌 때 조회할 기간 (기본 30일)
    max_items         1회 최대 항목 수 (CollectRequest.limit이 우선)
    request_delay_sec 외부 요청 간격 (기본 1.0초)
    timeout_sec       요청 타임아웃 (기본 15초)
    user_agent        요청 User-Agent

필요한 환경변수
    NAVER_CLIENT_ID / NAVER_CLIENT_SECRET   provider='naver'
    GNEWS_API_KEY                           provider='gnews'
    DART_API_KEY                            disclosure 소스 (https://opendart.fss.or.kr/api)

TODO(미확정): config 스키마·수집 주기·요청 간격은 지침 §9-A-3, 수집 키워드 셋은 §9-A-2.
확정되면 config/sources.yaml로 옮기고 이 표를 갱신한다.
"""
from __future__ import annotations

import html
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from ..pipeline_common import timeutil
from ..pipeline_common.models import CollectRequest, RawFetchResult

DEFAULT_USER_AGENT = "myWiki-collector/1.0 (+SK SUNI Team5)"
DEFAULT_TIMEOUT_SEC = 15.0
DEFAULT_REQUEST_DELAY_SEC = 1.0
DEFAULT_MAX_ITEMS = 30

# 응답이 이 코드면 수집 대상이 아니라고 보고 건너뛴다 (robots·저작권·차단).
_BLOCKED_STATUS = {401, 403, 429, 451}

# 네이버 검색 API 호출 경로. 응답 바디 구조는 두 경로가 같고, 호스트·경로·헤더
# 이름만 다르다. 그래서 items 파싱 로직은 공유하고 여기서 차이만 갈라둔다.
#
#   apihub  NAVER API HUB(NCP). 지금 발급되는 키는 이쪽으로만 인증된다
#   legacy  구 개발자센터. 2026-07-31 신규 발급 중단, 2027-06-30 서비스 종료
NAVER_API_VARIANTS: dict[str, dict[str, str]] = {
    "apihub": {
        "url": "https://naverapihub.apigw.ntruss.com/search/v1/news",
        "id_header": "X-NCP-APIGW-API-KEY-ID",
        "secret_header": "X-NCP-APIGW-API-KEY",
    },
    "legacy": {
        "url": "https://openapi.naver.com/v1/search/news.json",
        "id_header": "X-Naver-Client-Id",
        "secret_header": "X-Naver-Client-Secret",
    },
}
DEFAULT_NAVER_API_VARIANT = "apihub"

# 검색 API 문서상 display 허용 범위. 벗어나면 SE02로 거절된다.
NAVER_DISPLAY_MIN = 1
NAVER_DISPLAY_MAX = 100

# 검색 API는 검색어와 일치하는 부분을 <b> 태그로 감싸 돌려준다.
_HTML_TAG = re.compile(r"<[^>]+>")


class FetchError(Exception):
    """소스 전체를 읽을 수 없는 실패. collect()가 소스 job을 failed로 남긴다."""


@dataclass
class FetchOutcome:
    """수집 결과와, 문서를 만들지 않고 건너뛴 사유 집계."""

    items: list[RawFetchResult] = field(default_factory=list)
    skip_reasons: dict[str, int] = field(default_factory=dict)
    # 소스가 스스로 알려주는 제약 안내. 요금제 한도 때문에 결과가 조용히 0건이
    # 되는 상황을 놓치지 않으려고 job의 result에 그대로 남긴다.
    notices: list[str] = field(default_factory=list)

    def skip(self, reason: str) -> None:
        self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + 1

    def notice(self, message: str) -> None:
        if message and message not in self.notices:
            self.notices.append(message)


Fetcher = Callable[[dict, CollectRequest], FetchOutcome]

_REGISTRY: dict[str, Fetcher] = {}


def register_fetcher(source_type: str, fetcher: Fetcher) -> None:
    _REGISTRY[source_type] = fetcher


def get_fetcher(source_type: str) -> Fetcher:
    fetcher = _REGISTRY.get(source_type)
    if fetcher is None:
        raise FetchError(f"수집기가 없는 source_type: {source_type!r}")
    return fetcher


# ------------------------------------------------------------
# HTTP
# ------------------------------------------------------------


def _config(source: dict) -> dict:
    return source.get("config") or {}


def _conf_number(source: dict, key: str, default: float) -> float:
    """
    설정값을 숫자로 읽는다. 키가 없거나 None일 때만 기본값을 쓴다.

    `conf.get(key) or default`로 쓰면 0을 넣었을 때도 기본값이 적용된다.
    0은 "간격 없이 즉시"처럼 의미 있는 값이라 그대로 살려야 한다.
    """
    value = _config(source).get(key)
    if value is None:
        return default
    return float(value)


def _http_get(url: str, source: dict) -> tuple[bytes, str, int, str]:
    """
    (body, content_type, status_code, final_url). 네트워크 실패는 FetchError.

    final_url은 리다이렉트를 다 따라간 뒤의 주소다. 구글 뉴스 RSS가 주는 링크는
    news.google.com 경유 주소여서, 요청에 쓴 주소를 그대로 canonical_url에
    저장하면 같은 기사가 검색어마다 다른 문서로 쌓인다. 언론사 원문 주소를
    문서 식별 기준으로 쓰려고 최종 주소를 함께 돌려준다.
    """
    import httpx

    conf = _config(source)
    headers = {"User-Agent": conf.get("user_agent") or DEFAULT_USER_AGENT}
    timeout = _conf_number(source, "timeout_sec", DEFAULT_TIMEOUT_SEC)
    try:
        response = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
    except Exception as exc:  # noqa: BLE001 - httpx 예외 계층이 넓다
        raise FetchError(f"{url} 요청 실패: {exc}") from exc
    content_type = response.headers.get("content-type", "text/html")
    final_url = str(response.url) or url
    return response.content, content_type, response.status_code, final_url


def _sleep_between_requests(source: dict) -> None:
    """외부 요청은 간격을 지킨다 (프로젝트 지침 §7)."""
    delay = _conf_number(source, "request_delay_sec", DEFAULT_REQUEST_DELAY_SEC)
    if delay > 0:
        time.sleep(delay)


def _max_items(source: dict, request: CollectRequest) -> int:
    if request.limit is not None:
        return max(0, int(request.limit))
    return int(_conf_number(source, "max_items", DEFAULT_MAX_ITEMS))


def _resolve_google_news_url(url: str) -> str:
    """
    구글 뉴스 RSS 링크(news.google.com/rss/articles/...)는 서버 3xx 리다이렉트가
    아니라 JS 기반 리다이렉트라서 httpx(follow_redirects=True)가 못 따라간다 —
    그대로 요청하면 언론사 원문이 아니라 구글의 빈 중계 페이지를 받아서
    전처리 단계에서 "정제 결과가 비어 있다"로 매번 실패한다.

    google뉴스 링크가 아니면 원래 url을 그대로 돌려준다. 디코딩 실패 시에도
    예외를 던지지 않고 원래 url로 폴백한다 — 이후 흐름(전처리 실패)은 지금과
    동일하게 처리되므로 수집 자체가 죽는 것보단 낫다.
    """
    if "news.google.com" not in url:
        return url
    try:
        from googlenewsdecoder import gnewsdecoder

        result = gnewsdecoder(url, interval=1)
    except Exception:  # noqa: BLE001 - 디코더 내부 예외 종류가 다양하다
        return url
    if isinstance(result, dict) and result.get("status") and result.get("decoded_url"):
        return result["decoded_url"]
    return url


def _fetch_article(
    source: dict, url: str, title_hint: str | None, published_at: datetime | None
) -> RawFetchResult | None:
    """
    기사 1건의 원문을 가져온다. 차단 응답이면 None.

    문서 식별에 쓰는 url은 요청한 주소가 아니라 리다이렉트 최종 주소다.
    경유 주소를 그대로 쓰면 같은 기사가 중복 문서로 쌓인다.
    """
    url = _resolve_google_news_url(url)
    body, content_type, status, final_url = _http_get(url, source)
    if status in _BLOCKED_STATUS or status >= 400 or not body:
        return None
    return RawFetchResult(
        source_name=source["name"],
        url=final_url,
        fetched_at=datetime.now(timezone.utc),
        content_type=content_type,
        body=body,
        title_hint=title_hint,
        published_at_hint=published_at,
    )


def _entry_datetime(entry: Any) -> datetime | None:
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if parsed is None:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc)


# ------------------------------------------------------------
# 기본 수집기
# ------------------------------------------------------------


def fetch_rss(source: dict, request: CollectRequest) -> FetchOutcome:
    """RSS/Atom 피드 -> 각 항목의 원문 페이지. GeekNews·구글 RSS가 여기에 해당한다."""
    import feedparser

    feed_url = _config(source).get("feed_url") or source.get("base_url")
    if not feed_url:
        raise FetchError("RSS 소스에 base_url(또는 config.feed_url)이 없다")

    body, _, status, _final = _http_get(feed_url, source)
    if status >= 400:
        raise FetchError(f"피드 응답 코드 {status}: {feed_url}")

    feed = feedparser.parse(body)
    outcome = FetchOutcome()
    limit = _max_items(source, request)

    for entry in feed.entries:
        if len(outcome.items) >= limit:
            break
        url = (getattr(entry, "link", "") or "").strip()
        if not url:
            outcome.skip("no_canonical_url")
            continue
        published_at = _entry_datetime(entry)
        if request.since and published_at and published_at < request.since:
            outcome.skip("older_than_since")
            continue
        _sleep_between_requests(source)
        try:
            item = _fetch_article(source, url, getattr(entry, "title", None), published_at)
        except FetchError:
            outcome.skip("fetch_failed")
            continue
        if item is None:
            outcome.skip("blocked_or_empty")
            continue
        outcome.items.append(item)
    return outcome


def fetch_website(source: dict, request: CollectRequest) -> FetchOutcome:
    """단일 페이지 소스. base_url 하나를 그대로 가져온다."""
    url = _config(source).get("page_url") or source.get("base_url")
    if not url:
        raise FetchError("website 소스에 base_url이 없다")
    outcome = FetchOutcome()
    item = _fetch_article(source, url, source.get("name"), None)
    if item is None:
        outcome.skip("blocked_or_empty")
    else:
        outcome.items.append(item)
    return outcome


def strip_html(text: str | None) -> str | None:
    """
    검색 API가 돌려주는 <b> 강조 태그와 HTML 엔티티를 걷어낸다.

    문서상 "검색어와 일치하는 부분은 <b> 태그로 감쌈"이라 title·description에
    태그가 섞여 온다. 그대로 두면 documents.title에 마크업이 들어간다.

    태그 제거 -> 엔티티 해제 순서다. 반대로 하면 원문에 있던 &lt;b&gt; 같은
    "escape된 글자로서의 꺾쇠"까지 태그로 오인해 지운다.
    """
    if not text:
        return text
    return html.unescape(_HTML_TAG.sub("", text)).strip()


def _naver_display(limit: int) -> int:
    """
    display는 문서상 1~100이다.

    클램프하지 않으면 --limit 0으로 돌릴 때 display=0이 나가 SE02로 거절된다.
    수집 건수 자체는 호출부의 limit 루프가 따로 막으므로 여기서 1로 올려도
    0건 수집이라는 의도는 그대로 지켜진다.
    """
    return max(NAVER_DISPLAY_MIN, min(NAVER_DISPLAY_MAX, int(limit)))


def _naver_error_reason(payload: Any) -> str:
    """
    오류 사유를 뽑는다. 계층에 따라 응답 구조가 달라 둘 다 봐야 한다.

    게이트웨이 계층 (인증·라우팅 실패) — error 객체로 감싸져 온다
        {"error": {"errorCode": "200", "message": "Authentication Failed",
                   "details": "Authentication information are missing."}}
        여기 errorCode는 HTTP 상태 코드가 아니라 게이트웨이 자체 코드다.
    검색 API 계층 (파라미터 검증) — 평면 구조
        {"errorCode": "SE02", "errorMessage": "Invalid display value (...)"}

    payload.get("errorCode")만 보면 게이트웨이 오류는 중첩돼 있어 사유가 비고,
    FetchError 메시지에 상태 코드만 남아 원인을 못 찾는다.
    """
    if not isinstance(payload, dict):
        return ""
    nested = payload.get("error")
    if isinstance(nested, dict):
        source_dict, keys = nested, ("errorCode", "message", "details")
    else:
        source_dict, keys = payload, ("errorCode", "errorMessage")
    return " / ".join(str(source_dict[key]) for key in keys if source_dict.get(key))


def _naver_status_hint(status_code: int, variant_name: str) -> str:
    """상태 코드별 조치 힌트. 재시도로 풀릴 실패인지 아닌지를 여기서 가른다."""
    if status_code == 429:
        return "하루 호출 한도 초과 (검색 API 한도 25,000회/일) — 다음 날 재시도하면 된다"
    if status_code == 401:
        return (
            "인증 실패 — ① 키 값이 틀렸거나 ② 인증 헤더가 빠졌거나 "
            "③ 애플리케이션에 검색 API 이용 권한이 없다. "
            f"현재 api_variant={variant_name!r}이므로 키도 같은 쪽에서 발급한 값이어야 한다"
        )
    if status_code == 403:
        return "HTTPS가 아닌 HTTP로 호출했거나 필수 변수가 누락됐다"
    if status_code == 404:
        return "요청 URL이 틀렸다 (SE05)"
    return ""


def _raise_for_naver_error(status_code: int, payload: Any, variant_name: str) -> None:
    """
    오류면 FetchError로 올린다.

    status_code를 확인 안 하면 인증 실패(401) 같은 에러 응답도 payload.get("items", [])가
    빈 리스트를 돌려줘서 "정상 호출인데 0건 수집"으로 조용히 넘어간다 (명세 §1-3).
    """
    reason = _naver_error_reason(payload)
    if status_code < 400 and not reason:
        return
    message = f"네이버 검색 API 응답 오류 {status_code}"
    if reason:
        message += f": {reason}"
    hint = _naver_status_hint(status_code, variant_name)
    if hint:
        message += f" — {hint}"
    raise FetchError(message)


def fetch_naver_news(source: dict, request: CollectRequest) -> FetchOutcome:
    """
    네이버 검색 API(뉴스) -> 각 기사 원문 페이지.

    자격증명은 환경변수 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET에서 읽는다.
    NCP 콘솔 > All Services > Application Services > NAVER API HUB > Application >
    「인증 정보」에서 발급받는 Client ID / Client Secret이다.
    NCP 계정의 Access Key ID / Secret Key와는 다른 값이다 — 혼동해서 넣으면
    똑같이 401이 난다. 값을 코드·설정 파일에 적지 않는다 (프로젝트 지침 §2-7).

    config.api_variant로 호출 경로를 고른다 (기본 'apihub').
    응답 바디 구조는 두 경로가 같으므로 items 파싱은 아래 한 벌만 쓴다.
    """
    import httpx

    client_id = os.environ.get("NAVER_CLIENT_ID")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise FetchError("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수가 없다")

    conf = _config(source)
    query = conf.get("query")
    if not query:
        # TODO(미확정): 수집 키워드 셋 확정 전까지 소스별 config.query를 필수로 둔다 (지침 §9-A-2)
        raise FetchError("news 소스에 config.query가 없다")

    variant_name = (conf.get("api_variant") or DEFAULT_NAVER_API_VARIANT).lower()
    variant = NAVER_API_VARIANTS.get(variant_name)
    if variant is None:
        raise FetchError(
            f"알 수 없는 naver api_variant: {variant_name!r} "
            f"(가능: {sorted(NAVER_API_VARIANTS)})"
        )

    limit = _max_items(source, request)
    try:
        response = httpx.get(
            variant["url"],
            # GET 검색 API에는 Content-Type을 쓰지 않는다.
            params={"query": query, "display": _naver_display(limit), "sort": "date"},
            headers={
                variant["id_header"]: client_id,
                variant["secret_header"]: client_secret,
            },
            timeout=_conf_number(source, "timeout_sec", DEFAULT_TIMEOUT_SEC),
        )
    except Exception as exc:  # noqa: BLE001
        raise FetchError(f"네이버 검색 API 호출 실패: {exc}") from exc

    try:
        payload = response.json()
    except Exception as exc:  # noqa: BLE001 - 게이트웨이가 JSON 아닌 오류 페이지를 줄 수 있다
        raise FetchError(
            f"네이버 검색 API 응답을 JSON으로 읽을 수 없다 (HTTP {response.status_code}): {exc}"
        ) from exc

    _raise_for_naver_error(response.status_code, payload, variant_name)

    outcome = FetchOutcome()
    for entry in payload.get("items", []):
        if len(outcome.items) >= limit:
            break
        # originallink가 기사 원문, link는 네이버 뉴스 주소다. 원문을 우선한다.
        url = (entry.get("originallink") or entry.get("link") or "").strip()
        if not url:
            outcome.skip("no_canonical_url")
            continue
        published_at = timeutil.parse_datetime(entry.get("pubDate"))  # RFC 822
        if request.since and published_at and published_at < request.since:
            outcome.skip("older_than_since")
            continue
        _sleep_between_requests(source)
        try:
            # description은 RawFetchResult로 넘기지 않아 정제 대상이 아니다.
            # 넘기게 되면 title과 같이 strip_html()을 거쳐야 한다.
            item = _fetch_article(source, url, strip_html(entry.get("title")), published_at)
        except FetchError:
            outcome.skip("fetch_failed")
            continue
        if item is None:
            outcome.skip("blocked_or_empty")
            continue
        outcome.items.append(item)
    return outcome


def fetch_gnews(source: dict, request: CollectRequest) -> FetchOutcome:
    """
    GNews API(https://gnews.io) -> 각 기사 원문 페이지. 해외 영문 기사용이다.

    한국어 색인이 사실상 비어 있어(광범위한 검색어로도 결과 1건) 국내 기사는
    네이버로 받는다. 영문은 검색어 하나에 만 단위 결과가 나와 해외 동향 보조로 쓴다.

    자격증명은 환경변수 GNEWS_API_KEY에서 읽는다.

    무료 요금제 제약 두 가지가 결과를 조용히 0건으로 만든다.
      - 최근 12시간 기사 제외
      - 30일 이전 기사 제외
    응답의 information / articlesRemovedFromResponse에 그 사유가 담겨 오므로
    notices에 옮겨 job의 result에 남긴다.
    """
    import httpx

    api_key = os.environ.get("GNEWS_API_KEY")
    if not api_key:
        raise FetchError("GNEWS_API_KEY 환경변수가 없다")

    conf = _config(source)
    query = conf.get("query")
    if not query:
        raise FetchError("gnews 소스에 config.query가 없다")

    limit = _max_items(source, request)
    params: dict[str, Any] = {
        "q": query,
        "lang": conf.get("lang") or "en",
        "max": min(limit, 100),
        "apikey": api_key,
    }
    if conf.get("country"):
        params["country"] = conf["country"]
    if request.since:
        params["from"] = request.since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        response = httpx.get(
            "https://gnews.io/api/v4/search",
            params=params,
            timeout=_conf_number(source, "timeout_sec", DEFAULT_TIMEOUT_SEC),
        )
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        raise FetchError(f"GNews API 호출 실패: {exc}") from exc

    outcome = FetchOutcome()
    _collect_gnews_notices(payload, outcome)

    if response.status_code >= 400 or payload.get("errors"):
        raise FetchError(f"GNews 응답 오류 {response.status_code}: {payload.get('errors')}")

    for entry in payload.get("articles", []):
        if len(outcome.items) >= limit:
            break
        url = (entry.get("url") or "").strip()
        if not url:
            outcome.skip("no_canonical_url")
            continue
        published_at = timeutil.parse_datetime(entry.get("publishedAt"))
        if request.since and published_at and published_at < request.since:
            outcome.skip("older_than_since")
            continue
        _sleep_between_requests(source)
        try:
            item = _fetch_article(source, url, entry.get("title"), published_at)
        except FetchError:
            outcome.skip("fetch_failed")
            continue
        if item is None:
            outcome.skip("blocked_or_empty")
            continue
        outcome.items.append(item)

    # 전체 건수는 있는데 한 건도 못 받았으면 요금제 제약에 걸린 것이다.
    if payload.get("totalArticles") and not payload.get("articles"):
        outcome.skip("removed_by_plan_limit")
    return outcome


def _collect_gnews_notices(payload: dict, outcome: FetchOutcome) -> None:
    """information / articlesRemovedFromResponse 안내 문구를 notices로 옮긴다."""
    for section in ("information", "articlesRemovedFromResponse"):
        block = payload.get(section)
        if not isinstance(block, dict):
            continue
        for key, value in block.items():
            message = value.get("message") if isinstance(value, dict) else None
            if message:
                outcome.notice(f"{section}.{key}: {message}")


# ------------------------------------------------------------
# DART 공시 (source_type='disclosure')
# ------------------------------------------------------------

DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DART_DOCUMENT_URL = "https://opendart.fss.or.kr/api/document.xml"
DART_VIEWER_URL = "https://dart.fss.or.kr/dsaf001/main.do"

# list.json의 status. "000"만 정상이고, "013"은 에러가 아니라 "조회된 데이타가
# 없음"이라 빈 결과로 처리해야 한다(FetchError로 올리면 매번 job이 failed로 남는다).
_DART_STATUS_OK = "000"
_DART_STATUS_NO_DATA = "013"

DEFAULT_DART_LOOKBACK_DAYS = 30


def _dart_date(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def _parse_dart_date(value: str | None) -> datetime | None:
    """
    DART rcept_dt('YYYYMMDD')를 UTC datetime으로.

    timeutil.parse_datetime()을 안 쓰는 이유 — Python 3.11+의 datetime.fromisoformat은
    'YYYYMMDD'도 파싱하지만 naive datetime을 돌려준다. published_at_hint를
    request.since(항상 tz-aware)와 비교하면 naive/aware 비교로 TypeError가 난다.
    """
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _extract_disclosure_html(zip_bytes: bytes) -> bytes:
    """
    document.xml(zip) 안의 원문을 꺼낸다.

    파일명은 .xml이지만 내용은 실제로 HTML이다(DART 자체 포맷) — 그대로
    content_type='text/html'로 넘기면 기존 _parse_html이 처리한다.
    첨부문서가 여러 개면 zip 안에 항목이 여러 개일 수 있어 이어 붙인다.
    """
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        if not names:
            return b""
        return b"\n".join(zf.read(name) for name in names)


def _fetch_disclosure_document(
    source: dict, api_key: str, rcept_no: str, report_name: str | None, published_at: datetime | None
) -> RawFetchResult | None:
    """공시 1건의 원문(document.xml)을 가져와 RawFetchResult로 만든다. 실패/빈 응답이면 None."""
    import httpx

    timeout = _conf_number(source, "timeout_sec", DEFAULT_TIMEOUT_SEC)
    try:
        response = httpx.get(
            DART_DOCUMENT_URL,
            params={"crtfc_key": api_key, "rcept_no": rcept_no},
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001
        raise FetchError(f"DART document.xml 요청 실패({rcept_no}): {exc}") from exc
    if response.status_code >= 400 or not response.content:
        return None

    try:
        html_body = _extract_disclosure_html(response.content)
    except Exception:  # noqa: BLE001 - 손상된 zip 등
        return None
    if not html_body:
        return None

    # 본문은 document.xml에서 가져오지만, canonical_url은 사람이 실제로 클릭해서
    # 보는 뷰어 주소를 쓴다 — "원문 열기" 링크로 열었을 때 실제 화면과 일치해야 한다.
    # main.do 자체는 JS로 본문을 늦게 채우는 frameset이라 body로는 못 쓴다
    # (구글 뉴스 리다이렉트와 같은 문제, _resolve_google_news_url 참조).
    return RawFetchResult(
        source_name=source["name"],
        url=f"{DART_VIEWER_URL}?rcpNo={rcept_no}",
        fetched_at=datetime.now(timezone.utc),
        content_type="text/html",
        body=html_body,
        title_hint=(report_name or "").strip() or None,
        published_at_hint=published_at,
    )


def fetch_disclosure(source: dict, request: CollectRequest) -> FetchOutcome:
    """
    DART Open API(공시검색) -> 각 공시의 원문(document.xml).

    자격증명은 환경변수 DART_API_KEY에서 읽는다(https://opendart.fss.or.kr/api/document.xml 발급).
    config.corp_code(DART 고유번호 8자리)가 필수다 — corpCode.xml 벌크 파일에서
    회사명으로 찾아야 하는 값인데, 그 조회는 소스를 등록할 때 1회만 하면 되므로
    수집기가 매번 3MB대 파일을 받지 않도록 config에 직접 박아 둔다.

    한 페이지(page_count, 최대 100건)만 가져온다 — naver/gnews도 단일 호출 범위
    안에서만 수집하는 것과 같은 단순화다.
    """
    import httpx

    api_key = os.environ.get("DART_API_KEY")
    if not api_key:
        raise FetchError("DART_API_KEY 환경변수가 없다")

    conf = _config(source)
    corp_code = conf.get("corp_code")
    if not corp_code:
        raise FetchError("disclosure 소스에 config.corp_code가 없다")

    now = datetime.now(timezone.utc)
    since = request.since
    lookback_days = int(_conf_number(source, "lookback_days", DEFAULT_DART_LOOKBACK_DAYS))
    bgn_de = _dart_date(since) if since else _dart_date(now - timedelta(days=lookback_days))
    end_de = _dart_date(now)

    limit = _max_items(source, request)
    params: dict[str, Any] = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bgn_de": bgn_de,
        "end_de": end_de,
        "page_count": max(1, min(limit, 100)),
    }
    if conf.get("pblntf_ty"):
        params["pblntf_ty"] = conf["pblntf_ty"]

    try:
        response = httpx.get(
            DART_LIST_URL, params=params, timeout=_conf_number(source, "timeout_sec", DEFAULT_TIMEOUT_SEC)
        )
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        raise FetchError(f"DART 공시검색 API 호출 실패: {exc}") from exc

    status = payload.get("status")
    if status == _DART_STATUS_NO_DATA:
        return FetchOutcome()
    if status != _DART_STATUS_OK:
        raise FetchError(f"DART 공시검색 API 응답 오류 {status}: {payload.get('message')}")

    outcome = FetchOutcome()
    for entry in payload.get("list", []):
        if len(outcome.items) >= limit:
            break
        rcept_no = (entry.get("rcept_no") or "").strip()
        if not rcept_no:
            outcome.skip("no_canonical_url")
            continue
        published_at = _parse_dart_date(entry.get("rcept_dt"))
        if since and published_at and published_at < since:
            outcome.skip("older_than_since")
            continue
        _sleep_between_requests(source)
        try:
            item = _fetch_disclosure_document(source, api_key, rcept_no, entry.get("report_nm"), published_at)
        except FetchError:
            outcome.skip("fetch_failed")
            continue
        if item is None:
            outcome.skip("blocked_or_empty")
            continue
        outcome.items.append(item)
    return outcome


# source_type='news' 안에서 제공자를 나눈다. sources.source_type은 DB CHECK로
# 6개 값만 허용돼 gnews용 값을 새로 만들 수 없다. config.provider로 가른다.
_NEWS_PROVIDERS: dict[str, Fetcher] = {
    "naver": fetch_naver_news,
    "gnews": fetch_gnews,
}
DEFAULT_NEWS_PROVIDER = "naver"


def fetch_news(source: dict, request: CollectRequest) -> FetchOutcome:
    """config.provider로 뉴스 제공자를 골라 넘긴다. 없으면 네이버."""
    provider = (_config(source).get("provider") or DEFAULT_NEWS_PROVIDER).lower()
    fetcher = _NEWS_PROVIDERS.get(provider)
    if fetcher is None:
        raise FetchError(
            f"알 수 없는 news provider: {provider!r} (가능: {sorted(_NEWS_PROVIDERS)})"
        )
    return fetcher(source, request)


register_fetcher("rss", fetch_rss)
register_fetcher("news", fetch_news)
register_fetcher("website", fetch_website)
register_fetcher("disclosure", fetch_disclosure)
# report·manual_upload는 MVP 범위 밖이다. manual_upload는 명세 §4-2 참조.

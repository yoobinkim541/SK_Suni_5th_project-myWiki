"""
source_type별 원문 수집기.

collect()는 어느 소스를 어떻게 긁는지 몰라도 되게, 이 모듈이 source_type ->
수집 함수 매핑만 제공한다. 새 소스를 붙일 때는 register_fetcher()로 등록한다.

sources.config(JSONB)에서 읽는 키
    feed_url          RSS 피드 주소 (없으면 sources.base_url)
    query             검색어 (news 소스)
    max_items         1회 최대 항목 수 (CollectRequest.limit이 우선)
    request_delay_sec 외부 요청 간격 (기본 1.0초)
    timeout_sec       요청 타임아웃 (기본 15초)
    user_agent        요청 User-Agent

TODO(미확정): config 스키마·수집 주기·요청 간격은 지침 §9-A-3, 수집 키워드 셋은 §9-A-2.
확정되면 config/sources.yaml로 옮기고 이 표를 갱신한다.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from ..pipeline_common.models import CollectRequest, RawFetchResult

DEFAULT_USER_AGENT = "myWiki-collector/1.0 (+SK SUNI Team5)"
DEFAULT_TIMEOUT_SEC = 15.0
DEFAULT_REQUEST_DELAY_SEC = 1.0
DEFAULT_MAX_ITEMS = 30

# 응답이 이 코드면 수집 대상이 아니라고 보고 건너뛴다 (robots·저작권·차단).
_BLOCKED_STATUS = {401, 403, 429, 451}


class FetchError(Exception):
    """소스 전체를 읽을 수 없는 실패. collect()가 소스 job을 failed로 남긴다."""


@dataclass
class FetchOutcome:
    """수집 결과와, 문서를 만들지 않고 건너뛴 사유 집계."""

    items: list[RawFetchResult] = field(default_factory=list)
    skip_reasons: dict[str, int] = field(default_factory=dict)

    def skip(self, reason: str) -> None:
        self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + 1


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


def _http_get(url: str, source: dict) -> tuple[bytes, str, int]:
    """(body, content_type, status_code). 네트워크 실패는 FetchError."""
    import httpx

    conf = _config(source)
    headers = {"User-Agent": conf.get("user_agent") or DEFAULT_USER_AGENT}
    timeout = float(conf.get("timeout_sec") or DEFAULT_TIMEOUT_SEC)
    try:
        response = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
    except Exception as exc:  # noqa: BLE001 - httpx 예외 계층이 넓다
        raise FetchError(f"{url} 요청 실패: {exc}") from exc
    content_type = response.headers.get("content-type", "text/html")
    return response.content, content_type, response.status_code


def _sleep_between_requests(source: dict) -> None:
    """외부 요청은 간격을 지킨다 (프로젝트 지침 §7)."""
    delay = float(_config(source).get("request_delay_sec") or DEFAULT_REQUEST_DELAY_SEC)
    if delay > 0:
        time.sleep(delay)


def _max_items(source: dict, request: CollectRequest) -> int:
    if request.limit is not None:
        return max(0, int(request.limit))
    return int(_config(source).get("max_items") or DEFAULT_MAX_ITEMS)


def _fetch_article(
    source: dict, url: str, title_hint: str | None, published_at: datetime | None
) -> RawFetchResult | None:
    """기사 1건의 원문을 가져온다. 차단 응답이면 None."""
    body, content_type, status = _http_get(url, source)
    if status in _BLOCKED_STATUS or status >= 400 or not body:
        return None
    return RawFetchResult(
        source_name=source["name"],
        url=url,
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

    body, _, status = _http_get(feed_url, source)
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


def fetch_naver_news(source: dict, request: CollectRequest) -> FetchOutcome:
    """
    네이버 검색 API(뉴스) -> 각 기사 원문 페이지.

    자격증명은 환경변수 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET에서 읽는다.
    값을 코드·설정 파일에 적지 않는다 (프로젝트 지침 §2-7).
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

    limit = _max_items(source, request)
    try:
        response = httpx.get(
            "https://openapi.naver.com/v1/search/news.json",
            params={"query": query, "display": min(limit, 100), "sort": "date"},
            headers={
                "X-Naver-Client-Id": client_id,
                "X-Naver-Client-Secret": client_secret,
            },
            timeout=float(conf.get("timeout_sec") or DEFAULT_TIMEOUT_SEC),
        )
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        raise FetchError(f"네이버 검색 API 호출 실패: {exc}") from exc

    outcome = FetchOutcome()
    for entry in payload.get("items", []):
        if len(outcome.items) >= limit:
            break
        url = (entry.get("originallink") or entry.get("link") or "").strip()
        if not url:
            outcome.skip("no_canonical_url")
            continue
        from ..preprocessing.parsers import parse_datetime

        published_at = parse_datetime(entry.get("pubDate"))
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
    return outcome


register_fetcher("rss", fetch_rss)
register_fetcher("news", fetch_naver_news)
register_fetcher("website", fetch_website)
# disclosure·report·manual_upload는 MVP 범위 밖이다.
# disclosure(DART) 추가 여부는 지침 §9-C-4, manual_upload는 명세 §4-2 참조.

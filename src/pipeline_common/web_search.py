"""
네이버 검색 API(뉴스) 실시간 검색 — Agent가 위키·원문 모두 근거가 없을 때(_web_search_answer)
쓰는 3차 그라운딩 도구다.

src/collectors/fetchers.py::fetch_naver_news와 같은 API를 호출하지만, 파이프라인 수집용
무거운 처리(원문 페이지 GET, 소스별 config, 요청 간 sleep, 중복 검사)는 전부 뺀다 — 채팅
응답 시간 안에 끝나야 하므로 검색 결과의 title/originallink/description/pubDate만 그대로
반환한다. src/collectors(수집 파이프라인)를 참조하지 않는다 — pipeline_common(Agent 런타임이
참조)이 collectors를 참조하면 레이어 역행이다(document_search.py가 wiki/repository.py를
참조하지 않는 것과 같은 원칙). strip_html도 그래서 여기서 자체 구현한다.
"""
from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass

import httpx

from . import timeutil

_NAVER_SEARCH_URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"
_NAVER_DISPLAY_MIN = 1
_NAVER_DISPLAY_MAX = 100
_TIMEOUT_SEC = 10.0
_HTML_TAG = re.compile(r"<[^>]+>")


class WebSearchError(RuntimeError):
    """네이버 검색 API 호출 실패(자격증명 없음/HTTP 오류/네트워크 오류) 시."""


@dataclass
class WebSearchHit:
    title: str
    url: str
    snippet: str
    published_at: str | None


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    return html.unescape(_HTML_TAG.sub("", text)).strip()


def _clamp_display(limit: int) -> int:
    return max(_NAVER_DISPLAY_MIN, min(_NAVER_DISPLAY_MAX, int(limit)))


def search_web(query: str, limit: int = 5) -> list[WebSearchHit]:
    client_id = os.environ.get("NAVER_CLIENT_ID")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise WebSearchError("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수가 없다")

    try:
        response = httpx.get(
            _NAVER_SEARCH_URL,
            params={"query": query, "display": _clamp_display(limit), "sort": "date"},
            headers={
                "X-NCP-APIGW-API-KEY-ID": client_id,
                "X-NCP-APIGW-API-KEY": client_secret,
            },
            timeout=_TIMEOUT_SEC,
        )
    except Exception as exc:  # noqa: BLE001 - httpx 예외 계층이 넓다
        raise WebSearchError(f"네이버 검색 API 호출 실패: {exc}") from exc

    try:
        payload = response.json()
    except Exception as exc:  # noqa: BLE001 - 게이트웨이가 JSON 아닌 오류 페이지를 줄 수 있다
        raise WebSearchError(
            f"네이버 검색 API 응답을 JSON으로 읽을 수 없다 (HTTP {response.status_code}): {exc}"
        ) from exc

    # status_code를 확인 안 하면 인증 실패(401) 같은 오류 응답도 items가 빈 리스트라
    # "정상 호출인데 0건"으로 조용히 넘어간다 — fetchers.py의 같은 교훈을 그대로 적용.
    if response.status_code >= 400:
        reason = payload.get("errorMessage") or payload.get("error", {}).get("message", "")
        raise WebSearchError(f"네이버 검색 API 응답 오류 {response.status_code}: {reason}")

    hits: list[WebSearchHit] = []
    for entry in payload.get("items", [])[:limit]:
        url = (entry.get("originallink") or entry.get("link") or "").strip()
        if not url:
            continue
        published = timeutil.parse_datetime(entry.get("pubDate"))
        hits.append(
            WebSearchHit(
                title=_strip_html(entry.get("title")),
                url=url,
                snippet=_strip_html(entry.get("description")),
                published_at=published.isoformat() if published else None,
            )
        )
    return hits

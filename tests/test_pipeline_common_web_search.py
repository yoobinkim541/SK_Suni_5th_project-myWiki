"""src/pipeline_common/web_search.py 단위 테스트 — 네이버 검색 API 호출은 httpx.get을 monkeypatch한다."""
from __future__ import annotations

import httpx
import pytest

from src.pipeline_common import web_search


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def test_search_web_returns_parsed_hits(monkeypatch):
    captured = {}

    def fake_get(url, *, params, headers, timeout):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        return FakeResponse(200, {
            "items": [
                {
                    "title": "SK하이닉스 <b>ADR</b> 나스닥 상장",
                    "originallink": "https://example.com/article-1",
                    "link": "https://news.naver.com/article-1",
                    "description": "SK하이닉스가 <b>ADR</b>을 상장했다.",
                    "pubDate": "Fri, 07 Aug 2026 09:00:00 +0900",
                },
            ]
        })

    monkeypatch.setattr(web_search.httpx, "get", fake_get)
    monkeypatch.setenv("NAVER_CLIENT_ID", "test-id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "test-secret")

    hits = web_search.search_web("SK하이닉스 ADR", limit=5)

    assert len(hits) == 1
    assert hits[0].title == "SK하이닉스 ADR 나스닥 상장"  # <b> 태그 제거됨
    assert hits[0].url == "https://example.com/article-1"  # originallink 우선
    assert hits[0].snippet == "SK하이닉스가 ADR을 상장했다."
    assert hits[0].published_at == "2026-08-07T09:00:00+09:00"
    assert captured["params"]["query"] == "SK하이닉스 ADR"
    assert captured["params"]["display"] == 5
    assert captured["headers"]["X-NCP-APIGW-API-KEY-ID"] == "test-id"


def test_search_web_falls_back_to_link_when_no_originallink(monkeypatch):
    def fake_get(url, *, params, headers, timeout):
        return FakeResponse(200, {
            "items": [{
                "title": "제목", "originallink": "", "link": "https://news.naver.com/x",
                "description": "설명", "pubDate": "",
            }]
        })

    monkeypatch.setattr(web_search.httpx, "get", fake_get)
    monkeypatch.setenv("NAVER_CLIENT_ID", "test-id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "test-secret")

    hits = web_search.search_web("q")

    assert hits[0].url == "https://news.naver.com/x"
    assert hits[0].published_at is None


def test_search_web_clamps_limit_to_naver_display_range(monkeypatch):
    """네이버 검색 API의 display는 1~100 범위만 허용한다 — 범위 밖 limit을 클램프해야 한다."""
    captured = {}

    def fake_get(url, *, params, headers, timeout):
        captured["display"] = params["display"]
        return FakeResponse(200, {"items": []})

    monkeypatch.setattr(web_search.httpx, "get", fake_get)
    monkeypatch.setenv("NAVER_CLIENT_ID", "test-id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "test-secret")

    web_search.search_web("q", limit=0)
    assert captured["display"] == 1

    web_search.search_web("q", limit=999)
    assert captured["display"] == 100


def test_search_web_raises_when_credentials_missing(monkeypatch):
    monkeypatch.delenv("NAVER_CLIENT_ID", raising=False)
    monkeypatch.delenv("NAVER_CLIENT_SECRET", raising=False)

    with pytest.raises(web_search.WebSearchError):
        web_search.search_web("q")


def test_search_web_raises_on_error_status(monkeypatch):
    def fake_get(url, *, params, headers, timeout):
        return FakeResponse(401, {"errorMessage": "Invalid auth"})

    monkeypatch.setattr(web_search.httpx, "get", fake_get)
    monkeypatch.setenv("NAVER_CLIENT_ID", "test-id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "test-secret")

    with pytest.raises(web_search.WebSearchError):
        web_search.search_web("q")

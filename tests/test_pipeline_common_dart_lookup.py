"""src/pipeline_common/dart_lookup.py 단위 테스트 — DB 조회는 FakeSupabase, DART API 호출은 httpx.get monkeypatch로 대체한다."""
from __future__ import annotations

import zipfile
import io

import pytest

from src.pipeline_common import dart_lookup

WORKSPACE_ID = "ws-1"


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, rows):
        self.rows = rows
        self.eq_filters = []

    def select(self, _fields):
        return self

    def eq(self, field, value):
        self.eq_filters.append((field, value))
        return self

    def execute(self):
        rows = self.rows
        for field, value in self.eq_filters:
            rows = [r for r in rows if r.get(field) == value]
        return FakeResult(rows)


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return FakeTable(self.tables.get(name, []))


def _source_row(corp_code: str, enabled: bool = True) -> dict:
    return {
        "workspace_id": WORKSPACE_ID,
        "source_type": "disclosure",
        "enabled": enabled,
        "config": {"corp_code": corp_code},
    }


class FakeListResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _zip_bytes(inner_name: str, content: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(inner_name, content)
    return buf.getvalue()


class FakeDocResponse:
    def __init__(self, status_code, content):
        self.status_code = status_code
        self.content = content


def test_search_recent_disclosures_returns_hits_for_registered_corp_codes(monkeypatch):
    supabase = FakeSupabase(tables={"sources": [_source_row("00164779")]})

    def fake_get(url, *, params, timeout):
        assert params["corp_code"] == "00164779"
        return FakeListResponse({
            "status": "000",
            "list": [
                {"rcept_no": "20260805000123", "report_nm": "주식등의대량보유상황보고서", "corp_name": "SK하이닉스", "rcept_dt": "20260805"},
            ],
        })

    monkeypatch.setattr(dart_lookup.httpx, "get", fake_get)
    monkeypatch.setenv("DART_API_KEY", "test-key")

    hits = dart_lookup.search_recent_disclosures(WORKSPACE_ID, days=14, supabase=supabase)

    assert len(hits) == 1
    assert hits[0].rcept_no == "20260805000123"
    assert hits[0].report_name == "주식등의대량보유상황보고서"
    assert hits[0].corp_name == "SK하이닉스"
    assert hits[0].published_at == "2026-08-05T00:00:00+00:00"


def test_search_recent_disclosures_returns_empty_when_no_disclosure_sources_registered(monkeypatch):
    supabase = FakeSupabase(tables={"sources": []})
    monkeypatch.setenv("DART_API_KEY", "test-key")

    hits = dart_lookup.search_recent_disclosures(WORKSPACE_ID, supabase=supabase)

    assert hits == []


def test_search_recent_disclosures_skips_disabled_sources(monkeypatch):
    supabase = FakeSupabase(tables={"sources": [_source_row("00164779", enabled=False)]})
    monkeypatch.setenv("DART_API_KEY", "test-key")
    called = {"n": 0}

    def fake_get(url, *, params, timeout):
        called["n"] += 1
        return FakeListResponse({"status": "000", "list": []})

    monkeypatch.setattr(dart_lookup.httpx, "get", fake_get)

    hits = dart_lookup.search_recent_disclosures(WORKSPACE_ID, supabase=supabase)

    assert hits == []
    assert called["n"] == 0


def test_search_recent_disclosures_treats_no_data_status_as_empty_not_error(monkeypatch):
    supabase = FakeSupabase(tables={"sources": [_source_row("00164779")]})
    monkeypatch.setenv("DART_API_KEY", "test-key")

    def fake_get(url, *, params, timeout):
        return FakeListResponse({"status": "013", "message": "조회된 데이타가 없습니다"})

    monkeypatch.setattr(dart_lookup.httpx, "get", fake_get)

    hits = dart_lookup.search_recent_disclosures(WORKSPACE_ID, supabase=supabase)

    assert hits == []


def test_search_recent_disclosures_skips_corp_code_on_error_status(monkeypatch):
    supabase = FakeSupabase(tables={"sources": [_source_row("00164779")]})
    monkeypatch.setenv("DART_API_KEY", "test-key")

    def fake_get(url, *, params, timeout):
        return FakeListResponse({"status": "020", "message": "일일 요청 한도 초과"})

    monkeypatch.setattr(dart_lookup.httpx, "get", fake_get)

    hits = dart_lookup.search_recent_disclosures(WORKSPACE_ID, supabase=supabase)

    assert hits == []  # 예외 대신 그 회사만 건너뛰고 빈 결과


def test_search_recent_disclosures_raises_when_credentials_missing(monkeypatch):
    supabase = FakeSupabase(tables={"sources": [_source_row("00164779")]})
    monkeypatch.delenv("DART_API_KEY", raising=False)

    with pytest.raises(dart_lookup.DartLookupError):
        dart_lookup.search_recent_disclosures(WORKSPACE_ID, supabase=supabase)


def test_read_disclosure_extracts_html_from_zip(monkeypatch):
    zip_content = _zip_bytes("0001.xml", "<p>본문 내용</p>".encode("utf-8"))

    def fake_get(url, *, params, timeout):
        assert params["rcept_no"] == "20260805000123"
        return FakeDocResponse(200, zip_content)

    monkeypatch.setattr(dart_lookup.httpx, "get", fake_get)
    monkeypatch.setenv("DART_API_KEY", "test-key")

    markdown = dart_lookup.read_disclosure("20260805000123")

    assert markdown == "<p>본문 내용</p>"


def test_read_disclosure_returns_none_when_not_found(monkeypatch):
    def fake_get(url, *, params, timeout):
        return FakeDocResponse(404, b"")

    monkeypatch.setattr(dart_lookup.httpx, "get", fake_get)
    monkeypatch.setenv("DART_API_KEY", "test-key")

    assert dart_lookup.read_disclosure("missing") is None


def test_read_disclosure_returns_none_when_zip_corrupted(monkeypatch):
    def fake_get(url, *, params, timeout):
        return FakeDocResponse(200, b"not-a-zip")

    monkeypatch.setattr(dart_lookup.httpx, "get", fake_get)
    monkeypatch.setenv("DART_API_KEY", "test-key")

    assert dart_lookup.read_disclosure("bad-zip") is None


def test_viewer_url_format():
    assert dart_lookup.viewer_url("20260805000123") == "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260805000123"


def test_search_recent_disclosures_merges_hits_from_multiple_corp_codes(monkeypatch):
    supabase = FakeSupabase(tables={"sources": [_source_row("00164779"), _source_row("00126380")]})
    monkeypatch.setenv("DART_API_KEY", "test-key")

    def fake_get(url, *, params, timeout):
        if params["corp_code"] == "00164779":
            return FakeListResponse({
                "status": "000",
                "list": [{"rcept_no": "A", "report_nm": "SK하이닉스 공시", "corp_name": "SK하이닉스", "rcept_dt": "20260805"}],
            })
        return FakeListResponse({
            "status": "000",
            "list": [{"rcept_no": "B", "report_nm": "삼성전자 공시", "corp_name": "삼성전자", "rcept_dt": "20260806"}],
        })

    monkeypatch.setattr(dart_lookup.httpx, "get", fake_get)

    hits = dart_lookup.search_recent_disclosures(WORKSPACE_ID, supabase=supabase)

    assert {h.rcept_no for h in hits} == {"A", "B"}

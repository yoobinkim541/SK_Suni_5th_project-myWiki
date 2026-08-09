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


def test_search_recent_disclosures_skips_corp_code_on_error_status_when_others_succeed(monkeypatch):
    """부분 실패는 여전히 허용된다 — 등록된 회사 중 일부만 오류 상태를 반환하면 그
    회사만 건너뛰고 나머지 회사의 결과는 정상 반환해야 한다(전부 실패일 때만 예외)."""
    supabase = FakeSupabase(tables={"sources": [_source_row("00164779"), _source_row("00126380")]})
    monkeypatch.setenv("DART_API_KEY", "test-key")

    def fake_get(url, *, params, timeout):
        if params["corp_code"] == "00164779":
            return FakeListResponse({"status": "020", "message": "일일 요청 한도 초과"})
        return FakeListResponse({
            "status": "000",
            "list": [{"rcept_no": "B", "report_nm": "삼성전자 공시", "corp_name": "삼성전자", "rcept_dt": "20260806"}],
        })

    monkeypatch.setattr(dart_lookup.httpx, "get", fake_get)

    hits = dart_lookup.search_recent_disclosures(WORKSPACE_ID, supabase=supabase)

    assert {h.rcept_no for h in hits} == {"B"}


def test_search_recent_disclosures_raises_when_only_registered_corp_code_fails(monkeypatch):
    """등록된 corp_code가 1개뿐이고 그게 실패하면(=등록된 소스 전부 실패) 인증 만료/
    한도 초과 같은 오류가 "공시 0건"으로 조용히 둔갑하면 안 되므로 예외를 올려야 한다."""
    supabase = FakeSupabase(tables={"sources": [_source_row("00164779")]})
    monkeypatch.setenv("DART_API_KEY", "test-key")

    def fake_get(url, *, params, timeout):
        return FakeListResponse({"status": "020", "message": "일일 요청 한도 초과"})

    monkeypatch.setattr(dart_lookup.httpx, "get", fake_get)

    with pytest.raises(dart_lookup.DartLookupError):
        dart_lookup.search_recent_disclosures(WORKSPACE_ID, supabase=supabase)


def test_search_recent_disclosures_keeps_hits_from_succeeding_corp_code_when_another_fails(monkeypatch):
    supabase = FakeSupabase(tables={"sources": [_source_row("00164779"), _source_row("00126380")]})
    monkeypatch.setenv("DART_API_KEY", "test-key")

    def fake_get(url, *, params, timeout):
        if params["corp_code"] == "00164779":
            raise RuntimeError("network error")
        return FakeListResponse({
            "status": "000",
            "list": [{"rcept_no": "B", "report_nm": "삼성전자 공시", "corp_name": "삼성전자", "rcept_dt": "20260806"}],
        })

    monkeypatch.setattr(dart_lookup.httpx, "get", fake_get)

    hits = dart_lookup.search_recent_disclosures(WORKSPACE_ID, supabase=supabase)

    assert {h.rcept_no for h in hits} == {"B"}


def test_search_recent_disclosures_raises_when_credentials_missing(monkeypatch):
    supabase = FakeSupabase(tables={"sources": [_source_row("00164779")]})
    monkeypatch.delenv("DART_API_KEY", raising=False)

    with pytest.raises(dart_lookup.DartLookupError):
        dart_lookup.search_recent_disclosures(WORKSPACE_ID, supabase=supabase)


def test_read_disclosure_strips_html_tags_from_zip(monkeypatch):
    zip_content = _zip_bytes("0001.xml", "<p>본문 <b>내용</b></p>".encode("utf-8"))

    def fake_get(url, *, params, timeout):
        assert params["rcept_no"] == "20260805000123"
        return FakeDocResponse(200, zip_content)

    monkeypatch.setattr(dart_lookup.httpx, "get", fake_get)
    monkeypatch.setenv("DART_API_KEY", "test-key")

    text = dart_lookup.read_disclosure("20260805000123")

    assert text == "본문 내용"


def test_read_disclosure_truncates_text_over_max_chars(monkeypatch):
    long_body = "가" * (dart_lookup._MAX_TEXT_CHARS + 5_000)
    zip_content = _zip_bytes("0001.xml", f"<p>{long_body}</p>".encode("utf-8"))

    def fake_get(url, *, params, timeout):
        return FakeDocResponse(200, zip_content)

    monkeypatch.setattr(dart_lookup.httpx, "get", fake_get)
    monkeypatch.setenv("DART_API_KEY", "test-key")

    text = dart_lookup.read_disclosure("20260805000123")

    assert len(text) == dart_lookup._MAX_TEXT_CHARS
    assert text == long_body[: dart_lookup._MAX_TEXT_CHARS]


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


def test_search_recent_disclosures_passes_pblntf_ty_when_given(monkeypatch):
    """실측 확인(2026-08-09): DART API는 pblntf_ty에 콤마로 여러 유형을 넣으면
    '공시유형(pblntf_ty) 필드의 부적절한 값'으로 거절한다 — 한 번에 하나만 보낸다."""
    supabase = FakeSupabase(tables={"sources": [_source_row("00164779")]})
    captured = {}

    def fake_get(url, *, params, timeout):
        captured["pblntf_ty"] = params.get("pblntf_ty")
        return FakeListResponse({"status": "000", "list": []})

    monkeypatch.setattr(dart_lookup.httpx, "get", fake_get)
    monkeypatch.setenv("DART_API_KEY", "test-key")

    dart_lookup.search_recent_disclosures(WORKSPACE_ID, days=90, pblntf_ty="B", supabase=supabase)

    assert captured["pblntf_ty"] == "B"


def test_search_recent_disclosures_omits_pblntf_ty_param_when_not_given(monkeypatch):
    supabase = FakeSupabase(tables={"sources": [_source_row("00164779")]})
    captured = {}

    def fake_get(url, *, params, timeout):
        captured["has_pblntf_ty"] = "pblntf_ty" in params
        return FakeListResponse({"status": "000", "list": []})

    monkeypatch.setattr(dart_lookup.httpx, "get", fake_get)
    monkeypatch.setenv("DART_API_KEY", "test-key")

    dart_lookup.search_recent_disclosures(WORKSPACE_ID, days=90, supabase=supabase)

    assert captured["has_pblntf_ty"] is False


def test_search_recent_disclosures_follows_total_page_pagination(monkeypatch):
    """실측 버그(2026-08-09): page_count(100)를 넘는 공시가 있는 회사(나스닥 상장
    직후 등)는 1페이지만 보면 최신 공시가 누락된다 — total_page를 보고 이어 받아야
    한다."""
    supabase = FakeSupabase(tables={"sources": [_source_row("00164779")]})
    monkeypatch.setenv("DART_API_KEY", "test-key")
    seen_page_nos = []

    def fake_get(url, *, params, timeout):
        seen_page_nos.append(params["page_no"])
        if params["page_no"] == 1:
            return FakeListResponse({
                "status": "000",
                "total_page": 2,
                "list": [{"rcept_no": "PAGE1", "report_nm": "1페이지 공시", "corp_name": "SK하이닉스", "rcept_dt": "20260805"}],
            })
        return FakeListResponse({
            "status": "000",
            "total_page": 2,
            "list": [{"rcept_no": "PAGE2", "report_nm": "2페이지 공시", "corp_name": "SK하이닉스", "rcept_dt": "20260804"}],
        })

    monkeypatch.setattr(dart_lookup.httpx, "get", fake_get)

    hits = dart_lookup.search_recent_disclosures(WORKSPACE_ID, supabase=supabase)

    assert seen_page_nos == [1, 2]
    assert {h.rcept_no for h in hits} == {"PAGE1", "PAGE2"}


def test_search_recent_disclosures_stops_at_max_pages_safety_cap(monkeypatch):
    """total_page가 비정상적으로 크게 와도(혹은 API가 계속 total_page를 부풀려도)
    무한정 페이지를 이어 받지 않고 _MAX_PAGES에서 멈춰야 한다."""
    supabase = FakeSupabase(tables={"sources": [_source_row("00164779")]})
    monkeypatch.setenv("DART_API_KEY", "test-key")
    call_count = {"n": 0}

    def fake_get(url, *, params, timeout):
        call_count["n"] += 1
        return FakeListResponse({
            "status": "000",
            "total_page": 999,
            "list": [{"rcept_no": f"P{params['page_no']}", "report_nm": "공시", "corp_name": "SK하이닉스", "rcept_dt": "20260805"}],
        })

    monkeypatch.setattr(dart_lookup.httpx, "get", fake_get)

    hits = dart_lookup.search_recent_disclosures(WORKSPACE_ID, supabase=supabase)

    assert call_count["n"] == dart_lookup._MAX_PAGES
    assert len(hits) == dart_lookup._MAX_PAGES

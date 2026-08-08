# DART 공시 실시간 조회 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 3단계 웹 검색 그라운딩("웹에서 찾아줘")에 DART 공시를 실시간으로 찾는 도구 2개를 추가한다 — 예약 수집 파이프라인이 아직 못 가져온 최신 공시도 답변 근거로 쓸 수 있게 한다.

**Architecture:** `WEB_SEARCH_TOOLS`에 `search_recent_disclosures`(최근 N일 공시 목록)/`read_disclosure`(본문 조회) 2단계 도구를 추가한다. 인용은 이미 있는 `Citation.source_url`을 그대로 재사용한다(DART 뷰어 URL을 넣음) — 스키마 변경 없음. `search_web`이 검색 시점에 바로 `hit_by_url`을 채우는 것과 다르게, DART는 목록에 본문이 없으므로 `read_disclosure`가 실제로 읽었을 때만 `hit_by_url`에 채운다(목록만 보고 안 읽은 공시는 인용 못 함).

**Tech Stack:** Python, httpx(DART Open API 직접 호출), pytest.

**Spec:** `docs/superpowers/specs/2026-08-09-dart-live-lookup-design.md`.

## Global Constraints

- DART Open API는 자유 검색어를 지원하지 않는다 — `corp_code`(회사 고유번호) + 날짜 범위로만 공시 **목록**(제목·접수번호·날짜)을 얻고, 본문은 접수번호(`rcept_no`)로 별도 조회한다.
- `corp_code`는 하드코딩하지 않는다 — 워크스페이스의 `sources` 테이블에서 `source_type='disclosure'` AND `enabled=true`인 행 전부의 `config.corp_code`를 쓴다.
- 인용 스키마 변경 없음 — `Citation.source_url`/`source_title`/`source_published_at`(이미 웹 검색 그라운딩에서 씀)을 그대로 재사용한다. `message_citations`/`_is_grounded`/프론트 배지 전부 손대지 않는다.
- lookback 기본값 14일(파이프라인 수집기의 30일보다 짧게 — "아직 파이프라인이 못 커버한 최신분"만 메꾸는 용도).
- `DART_API_KEY` 환경변수는 이미 있다(새 자격증명 불필요).
- `src/collectors`를 참조하지 않는다(`web_search.py`/`document_search.py`와 같은 레이어 원칙 — `pipeline_common`이 `collectors`를 참조하면 역행).
- 각 태스크는 독립적으로 테스트 가능해야 하고, 태스크 완료마다 커밋한다(TDD).

---

### Task 1: `src/pipeline_common/dart_lookup.py` — DART Open API 실시간 조회

**Files:**
- Create: `src/pipeline_common/dart_lookup.py`
- Test: `tests/test_pipeline_common_dart_lookup.py`

**Interfaces:**
- Produces: `search_recent_disclosures(workspace_id: str, days: int = DEFAULT_LOOKBACK_DAYS, *, supabase=None) -> list[DisclosureHit]`, `read_disclosure(rcept_no: str) -> str | None`(마크다운/HTML 텍스트만), `viewer_url(rcept_no: str) -> str`, `DisclosureHit(rcept_no, report_name, corp_name, published_at)`, `class DartLookupError(RuntimeError)`. Task 2가 이 함수들을 가져다 쓴다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
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


def test_search_recent_disclosures_raises_on_error_status(monkeypatch):
    supabase = FakeSupabase(tables={"sources": [_source_row("00164779")]})
    monkeypatch.setenv("DART_API_KEY", "test-key")

    def fake_get(url, *, params, timeout):
        return FakeListResponse({"status": "020", "message": "일일 요청 한도 초과"})

    monkeypatch.setattr(dart_lookup.httpx, "get", fake_get)

    with pytest.raises(dart_lookup.DartLookupError):
        dart_lookup.search_recent_disclosures(WORKSPACE_ID, supabase=supabase)


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
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `pytest tests/test_pipeline_common_dart_lookup.py -v`
Expected: FAIL — `src.pipeline_common.dart_lookup` 모듈이 없음

- [ ] **Step 3: 구현**

```python
"""
DART(전자공시시스템) 공시 실시간 조회 — Agent가 위키·원문·네이버 검색 어디에도
근거가 없을 때(_web_search_answer) 쓰는 3차 그라운딩 도구다.

src/collectors/fetchers.py::fetch_disclosure/_fetch_disclosure_document와 같은
DART Open API(list.json/document.xml)를 호출하지만, 파이프라인 수집용 무거운
처리(RawFetchResult, source dict config, CollectRequest, 요청 간 sleep)는 뺀다 —
채팅 응답 시간 안에 끝나야 한다. src/collectors를 참조하지 않는다(레이어 역행 방지,
web_search.py/document_search.py와 같은 원칙 — 의도적으로 로직 일부를 중복한다).

DART Open API는 자유 검색어를 지원하지 않는다 — corp_code(회사 고유번호)와 날짜
범위로만 그 회사의 공시 목록(제목·접수번호·날짜)을 얻을 수 있고, 본문은 접수번호로
따로 조회해야 한다(2단계: search_recent_disclosures -> read_disclosure).
"""
from __future__ import annotations

import io
import os
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from ..analysis.repository import get_supabase

_DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
_DART_DOCUMENT_URL = "https://opendart.fss.or.kr/api/document.xml"
_DART_VIEWER_URL = "https://dart.fss.or.kr/dsaf001/main.do"
_TIMEOUT_SEC = 10.0

_STATUS_OK = "000"
_STATUS_NO_DATA = "013"

DEFAULT_LOOKBACK_DAYS = 14
"""
파이프라인 수집기(DEFAULT_DART_LOOKBACK_DAYS=30, fetchers.py)보다 짧다 — 이 모듈은
"아직 파이프라인이 못 커버한 최신 공시"만 메꾸는 용도라 30일 전체를 매번 다시 볼
필요가 없다.
"""


class DartLookupError(RuntimeError):
    """DART API 호출 실패(자격증명 없음/HTTP 오류/네트워크 오류) 시."""


@dataclass
class DisclosureHit:
    rcept_no: str
    report_name: str
    corp_name: str
    published_at: str | None


def viewer_url(rcept_no: str) -> str:
    return f"{_DART_VIEWER_URL}?rcpNo={rcept_no}"


def _parse_dart_date(value: str | None) -> datetime | None:
    """DART rcept_dt('YYYYMMDD')를 UTC datetime으로. fetchers.py::_parse_dart_date와
    같은 이유로 datetime.fromisoformat을 안 쓴다(naive datetime이 나옴)."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _registered_corp_codes(workspace_id: str, db) -> list[str]:
    rows = (
        db.table("sources")
        .select("config")
        .eq("workspace_id", workspace_id)
        .eq("source_type", "disclosure")
        .eq("enabled", True)
        .execute()
        .data
    )
    codes = []
    for row in rows:
        corp_code = (row.get("config") or {}).get("corp_code")
        if corp_code:
            codes.append(corp_code)
    return codes


def search_recent_disclosures(
    workspace_id: str, days: int = DEFAULT_LOOKBACK_DAYS, *, supabase=None
) -> list[DisclosureHit]:
    db = supabase or get_supabase()
    corp_codes = _registered_corp_codes(workspace_id, db)
    if not corp_codes:
        return []

    api_key = os.environ.get("DART_API_KEY")
    if not api_key:
        raise DartLookupError("DART_API_KEY 환경변수가 없다")

    now = datetime.now(timezone.utc)
    bgn_de = (now - timedelta(days=days)).strftime("%Y%m%d")
    end_de = now.strftime("%Y%m%d")

    hits: list[DisclosureHit] = []
    for corp_code in corp_codes:
        try:
            response = httpx.get(
                _DART_LIST_URL,
                params={
                    "crtfc_key": api_key,
                    "corp_code": corp_code,
                    "bgn_de": bgn_de,
                    "end_de": end_de,
                    "page_count": 100,
                },
                timeout=_TIMEOUT_SEC,
            )
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 - httpx 예외 계층이 넓다
            raise DartLookupError(f"DART 공시검색 API 호출 실패(corp_code={corp_code}): {exc}") from exc

        status = payload.get("status")
        if status == _STATUS_NO_DATA:
            continue
        if status != _STATUS_OK:
            raise DartLookupError(f"DART 공시검색 API 응답 오류 {status}: {payload.get('message')}")

        for entry in payload.get("list", []):
            rcept_no = (entry.get("rcept_no") or "").strip()
            if not rcept_no:
                continue
            published = _parse_dart_date(entry.get("rcept_dt"))
            hits.append(
                DisclosureHit(
                    rcept_no=rcept_no,
                    report_name=(entry.get("report_nm") or "").strip(),
                    corp_name=(entry.get("corp_name") or "").strip(),
                    published_at=published.isoformat() if published else None,
                )
            )
    return hits


def _extract_html(zip_bytes: bytes) -> bytes:
    """document.xml(zip) 안의 원문을 꺼낸다 — 파일명은 .xml이지만 내용은 HTML이다
    (DART 자체 포맷). 첨부문서가 여러 개면 이어 붙인다."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        if not names:
            return b""
        return b"\n".join(zf.read(name) for name in names)


def read_disclosure(rcept_no: str) -> str | None:
    api_key = os.environ.get("DART_API_KEY")
    if not api_key:
        raise DartLookupError("DART_API_KEY 환경변수가 없다")

    try:
        response = httpx.get(
            _DART_DOCUMENT_URL,
            params={"crtfc_key": api_key, "rcept_no": rcept_no},
            timeout=_TIMEOUT_SEC,
        )
    except Exception as exc:  # noqa: BLE001
        raise DartLookupError(f"DART document.xml 요청 실패({rcept_no}): {exc}") from exc
    if response.status_code >= 400 or not response.content:
        return None

    try:
        html_body = _extract_html(response.content)
    except Exception:  # noqa: BLE001 - 손상된 zip 등
        return None
    if not html_body:
        return None
    return html_body.decode("utf-8", errors="replace")
```

**주의:** `test_read_disclosure_returns_none_when_zip_corrupted`에서 `b"not-a-zip"`을 주면 `zipfile.ZipFile()`이 `zipfile.BadZipFile`을 던진다 — `except Exception`으로 잡으므로 그대로 통과한다.

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `pytest tests/test_pipeline_common_dart_lookup.py -v`
Expected: PASS (10개 테스트 전부)

- [ ] **Step 5: 커밋**

```bash
git add src/pipeline_common/dart_lookup.py tests/test_pipeline_common_dart_lookup.py
git commit -m "Feat: DART Open API 실시간 공시 조회 모듈 추가"
```

---

### Task 2: `WikiTools` 위임 메서드

**Files:**
- Modify: `src/agent/wiki_tools.py`
- Test: `tests/test_agent_wiki_tools.py`

**Interfaces:**
- Consumes: Task 1의 `dart_lookup.search_recent_disclosures(workspace_id, days)`, `dart_lookup.read_disclosure(rcept_no)`.
- Produces: `WikiTools.search_recent_disclosures(days=DEFAULT_LOOKBACK_DAYS) -> list[dart_lookup.DisclosureHit]`, `WikiTools.read_disclosure(rcept_no) -> Optional[str]`. Task 3이 이 메서드들을 쓴다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_agent_wiki_tools.py`에 기존 `test_search_web_delegates_to_web_search_module`과 같은 패턴으로 추가(이 파일이 `web_search`를 monkeypatch하는 것과 같은 import 별칭을 그대로 따라라):

```python
def test_search_recent_disclosures_delegates_to_dart_lookup_module(monkeypatch):
    tools = WikiTools(workspace_id="ws-1")
    called = {}

    def fake_search(workspace_id, days):
        called["workspace_id"] = workspace_id
        called["days"] = days
        return ["fake-hit"]

    monkeypatch.setattr(wiki_tools_module.dart_lookup, "search_recent_disclosures", fake_search)

    result = tools.search_recent_disclosures(days=7)

    assert result == ["fake-hit"]
    assert called == {"workspace_id": "ws-1", "days": 7}


def test_read_disclosure_delegates_to_dart_lookup_module(monkeypatch):
    tools = WikiTools(workspace_id="ws-1")
    called = {}

    def fake_read(rcept_no):
        called["rcept_no"] = rcept_no
        return "fake-markdown"

    monkeypatch.setattr(wiki_tools_module.dart_lookup, "read_disclosure", fake_read)

    result = tools.read_disclosure("20260805000123")

    assert result == "fake-markdown"
    assert called == {"rcept_no": "20260805000123"}
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `pytest tests/test_agent_wiki_tools.py -k disclosure -v`
Expected: FAIL — `WikiTools`에 해당 메서드 없음, `dart_lookup` import 없음

- [ ] **Step 3: 구현**

`src/agent/wiki_tools.py` 상단 import 교체:
```python
from ..pipeline_common import dart_lookup, document_search, web_search
```

`WikiTools` 클래스에 `search_web` 메서드 바로 뒤에 추가:
```python
    def search_recent_disclosures(
        self, days: int = dart_lookup.DEFAULT_LOOKBACK_DAYS
    ) -> list[dart_lookup.DisclosureHit]:
        """이 워크스페이스에 등록된 회사들의 최근 N일 DART 공시 목록. 위키·원문·웹
        검색 어디에도 없을 때(_web_search_answer)만 쓰는 3차 그라운딩 도구."""
        return dart_lookup.search_recent_disclosures(self.workspace_id, days)

    def read_disclosure(self, rcept_no: str) -> Optional[str]:
        """공시 1건의 실제 본문(HTML)."""
        return dart_lookup.read_disclosure(rcept_no)
```

모듈 docstring에 한 줄 추가: "그마저 없을 때는 search_web()으로 웹에서, search_recent_disclosures()/read_disclosure()로 최신 DART 공시를 찾는다."

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `pytest tests/test_agent_wiki_tools.py -v`
Expected: PASS (전체)

- [ ] **Step 5: 커밋**

```bash
git add src/agent/wiki_tools.py tests/test_agent_wiki_tools.py
git commit -m "Feat: WikiTools에 DART 공시 실시간 조회 위임 메서드 추가"
```

---

### Task 3: `core.py` 배선 — `WEB_SEARCH_TOOLS` 확장 + `_web_search_answer` 핸들러

**Files:**
- Modify: `src/agent/core.py`
- Test: `tests/test_agent_core.py`

**Interfaces:**
- Consumes: Task 2의 `WikiTools.search_recent_disclosures`/`read_disclosure`.
- Produces: 없음(이 플랜의 마지막 코드 변경 — `_web_search_answer`가 DART 공시도 근거로 쓸 수 있게 됨).

이 태스크는 기존 `_web_search_answer`의 `_enrich`/citation 후처리 로직(약 448~474행)을 **하나도 안 바꾼다** — `hit_by_url`이 이미 URL을 키로 쓰는 범용 캐시라, DART 공시의 `viewer_url(rcept_no)`도 그 안에 넣기만 하면 기존 로직이 그대로 동작한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_agent_core.py`에 추가(기존 `test_web_search_answer_passes_web_search_tools_not_document_tools` 근처):

```python
def test_web_search_answer_grounds_on_disclosure_via_read_disclosure(agent, wiki_tools, monkeypatch):
    """search_recent_disclosures로 찾은 공시를 read_disclosure로 읽어서 그라운딩되면,
    citation의 source_url이 DART 뷰어 URL이고 document_version_id는 None이어야 한다."""
    wiki_tools.search_web.return_value = []
    wiki_tools.search_recent_disclosures.return_value = [
        FakeDisclosureHit(
            rcept_no="20260805000123",
            report_name="주식등의대량보유상황보고서",
            corp_name="SK하이닉스",
            published_at="2026-08-05T00:00:00+00:00",
        )
    ]
    wiki_tools.read_disclosure.return_value = "본문에 지분율 5.2%로 변경됐다는 내용이 있다."
    citation = {"source_url": core.dart_lookup.viewer_url("20260805000123"), "quote": "지분율 5.2%로 변경"}
    responses = [
        tool_call_response(("call-1", "submit_no_answer", {"reason": "위키 근거 없음"})),
        tool_call_response(("call-2", "submit_no_answer", {"reason": "원문 근거 없음"})),
        tool_call_response(("call-3", "search_recent_disclosures", {"days": 14})),
        tool_call_response(("call-4", "read_disclosure", {"rcept_no": "20260805000123"})),
        tool_call_response(("call-5", "submit_answer", {
            "answer": "지분율이 5.2%로 변경됐다.[1]",
            "citations": [citation],
        })),
    ]
    monkeypatch.setattr(agent, "_call_model", MagicMock(side_effect=responses))

    result = agent.answer("SK하이닉스 최근 지분 변동 공시가 뭐야?", allow_web_search=True)

    assert result.has_answer is True
    assert result.citations[0].source_url == core.dart_lookup.viewer_url("20260805000123")
    assert result.citations[0].document_version_id is None
    assert result.citations[0].source_title == "주식등의대량보유상황보고서"
    assert result.citations[0].source_published_at == "2026-08-05T00:00:00+00:00"
    wiki_tools.search_recent_disclosures.assert_called_once_with(14)
    wiki_tools.read_disclosure.assert_called_once_with("20260805000123")


def test_web_search_tools_include_disclosure_tools(agent, wiki_tools, monkeypatch):
    wiki_tools.search_web.return_value = []
    captured_tools = []

    def fake_call_model(messages, use_tools=True, tools=None):
        captured_tools.append(tools)
        return tool_call_response(("call-1", "submit_no_answer", {"reason": "근거 없음"}))

    monkeypatch.setattr(agent, "_call_model", fake_call_model)

    agent._web_search_answer("질문")

    tool_names = {t["function"]["name"] for t in captured_tools[0]}
    assert {"search_web", "search_recent_disclosures", "read_disclosure"} <= tool_names
```

파일 상단(기존 `FakeWebSearchHit` 근처)에 fake 추가:
```python
@dataclass
class FakeDisclosureHit:
    rcept_no: str
    report_name: str
    corp_name: str
    published_at: Optional[str]
```

(`core`는 이 파일이 이미 `from src.agent import core` 형태로 import하고 있을 것이다 — 기존 `core.WEB_SEARCH_TOOLS`/`core.DOCUMENT_TOOLS` 참조 코드의 import 별칭을 그대로 따라라.)

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `pytest tests/test_agent_core.py -k disclosure -v`
Expected: FAIL — `search_recent_disclosures`/`read_disclosure` 도구가 `WEB_SEARCH_TOOLS`에 없음, `_web_search_answer`가 그 도구 이름을 처리 못 함

- [ ] **Step 3: 구현**

`src/agent/core.py`에는 현재 `pipeline_common` import가 전혀 없다(`wiki_tools.py`를 통해서만 간접 참조해왔다). 아래 줄을 `from .wiki_tools import WikiTools` 바로 뒤에 새로 추가해라:
```python
from ..pipeline_common import dart_lookup
```
(`core.dart_lookup.viewer_url(...)`처럼 테스트에서 직접 쓰므로 모듈 자체를 import해야 한다.)

`WEB_SEARCH_ANSWER_SYSTEM_PROMPT` 전체 교체:
```python
WEB_SEARCH_ANSWER_SYSTEM_PROMPT = """\
너는 myWiki의 답변 Agent다. 위키에도, 수집된 원문(뉴스+DART)에도 근거가 없어서
실시간 웹 검색으로 마지막으로 근거를 찾는 단계다. 규칙:
1. search_web으로 뉴스를 찾아라. 질문이 실적·지분·계약·투자 등 공시성 내용이면
   search_recent_disclosures로 최근 DART 공시 목록도 같이 확인하고, 관련 있어
   보이는 제목이 있으면 read_disclosure로 본문을 읽어라.
2. 찾은 결과(뉴스 요약 또는 공시 본문)에 실제로 있는 내용만 근거로 답변해라.
   사전 지식이나 추측으로 빈틈을 채우지 마라.
3. 답을 뒷받침할 근거를 찾았으면 submit_answer를 호출해라. 문장마다 어떤 근거
   (citations)를 썼는지 반드시 포함하고, citations의 source_url은 실제로 본
   결과(search_web의 url 또는 read_disclosure로 읽은 공시)에서만 골라라(지어내지
   마라). document_version_id는 비워둬라 — DB 문서가 아니다. 답변 본문에 쓰는 근거
   번호 [N]은 반드시 citations 배열의 N번째(1부터 시작) 항목과 정확히 대응해야
   한다 — citations에 없는 번호는 절대 쓰지 마라.
4. 근거를 찾지 못했거나 근거가 불충분하면 submit_answer 대신 반드시
   submit_no_answer를 호출해라.
5. 톤은 직접적이고 전문적으로, 가벼운 대화체는 쓰지 마라.
"""
```

`WEB_SEARCH_TOOLS` 리스트에 도구 2개 추가(기존 `search_web` 다음, `_SUBMIT_ANSWER_TOOL` 앞):
```python
WEB_SEARCH_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": (
                "질문 키워드로 실시간 웹(네이버 검색)을 찾는다. 위키·수집된 원문 어디에도 "
                "근거가 없을 때만 쓰는 최후 수단 — 검색 결과의 제목·요약·링크·게시일을 반환한다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "질문에서 뽑은 검색 키워드"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_recent_disclosures",
            "description": (
                "이 워크스페이스에 등록된 회사들의 최근 공시 목록(제목·접수번호·게시일)을 "
                "찾는다. 질문이 실적·지분·계약·투자 등 공시성 내용일 때 시도해라. 자유 "
                "검색어는 지원 안 됨 — 최근 공시 전체 목록만 준다, 관련 있어 보이는 제목을 "
                "read_disclosure로 읽어서 확인해라."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "최근 며칠치 공시를 볼지(기본 14일)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_disclosure",
            "description": "search_recent_disclosures 결과에서 접수번호(rcept_no)로 공시 원문 전체를 읽는다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "rcept_no": {
                        "type": "string",
                        "description": "search_recent_disclosures 결과의 rcept_no",
                    },
                },
                "required": ["rcept_no"],
            },
        },
    },
    _SUBMIT_ANSWER_TOOL,
    _SUBMIT_NO_ANSWER_TOOL,
]
```

`_web_search_answer` 전체 교체(기존 `handle_search_web`/`hit_by_url`/`_enrich`/강등 로직은 그대로 두고, `disclosure_hits` 캐시와 두 핸들러만 추가):
```python
    def _web_search_answer(self, question: str, history: Optional[list[dict]] = None) -> AgentResult:
        # search_web 결과의 (title, published_at)을 url로 찾아올 수 있게 기억해둔다 —
        # 모델은 citations에 source_url만 채우고 title/published_at은 안 채우므로
        # (submit_answer 스키마에 그 두 필드가 없다), 저장할 값은 여기서 직접 채운다.
        hit_by_url: dict[str, tuple[str, Optional[str]]] = {}
        # DART는 목록(search_recent_disclosures)에 본문이 없어 read_disclosure로 실제로
        # 읽어야만 인용 가능하다 — 목록만 보고 안 읽은 공시는 hit_by_url에 안 들어간다.
        disclosure_hits: dict[str, dart_lookup.DisclosureHit] = {}

        def handle_search_web(args: dict, seen: set[str]) -> object:
            hits = self.wiki_tools.search_web(args["query"])
            # 원문 단계와 다르게 read 단계가 따로 없다 — search_web 결과 자체가 그라운딩에
            # 쓸 내용(title/snippet) 전부라, 검색 시점에 바로 seen에 URL을 채운다.
            seen.update(h.url for h in hits)
            hit_by_url.update({h.url: (h.title, h.published_at) for h in hits})
            return [h.__dict__ for h in hits]

        def handle_search_recent_disclosures(args: dict, seen: set[str]) -> object:
            days = args.get("days") or dart_lookup.DEFAULT_LOOKBACK_DAYS
            hits = self.wiki_tools.search_recent_disclosures(days)
            disclosure_hits.update({h.rcept_no: h for h in hits})
            return [h.__dict__ for h in hits]

        def handle_read_disclosure(args: dict, seen: set[str]) -> object:
            rcept_no = args["rcept_no"]
            markdown = self.wiki_tools.read_disclosure(rcept_no)
            if markdown is None:
                return {"error": "공시를 찾을 수 없음"}
            url = dart_lookup.viewer_url(rcept_no)
            hit = disclosure_hits.get(rcept_no)
            seen.add(url)
            hit_by_url[url] = (hit.report_name if hit else None, hit.published_at if hit else None)
            return {
                "markdown": markdown,
                "canonical_url": url,
                "report_name": hit.report_name if hit else None,
                "corp_name": hit.corp_name if hit else None,
            }

        result = self._run_grounded_answer(
            question,
            history,
            system_prompt=WEB_SEARCH_ANSWER_SYSTEM_PROMPT,
            tools=WEB_SEARCH_TOOLS,
            tool_handlers={
                "search_web": handle_search_web,
                "search_recent_disclosures": handle_search_recent_disclosures,
                "read_disclosure": handle_read_disclosure,
            },
        )
        # submit_answer 스키마를 다른 단계와 공유하므로 document_version_id/wiki_slug
        # 필드 자체를 막지 못한다 — 모델이 실수로(또는 검색 결과 URL을) document_version_id
        # 칸에 채워 보내도 그 값이 이번 검색에서 실제로 본 URL(hit_by_url의 키)이면
        # source_url로 승격시킨다. source_url도 비어 있고 document_version_id도 이번
        # 검색 결과에 없는 값이면(식별자가 통째로 없는 것과 같다) 그 citation은 근거
        # 없음으로 취급해 답변 전체를 has_answer=False로 강등한다 — 지어낸/형식이
        # 어긋난 근거를 저장하면 안 된다는 이 파일의 기존 원칙과 동일하다.
        if result.has_answer and result.citations:
            def _enrich(c: Citation) -> Citation:
                url = c.source_url or (c.document_version_id if c.document_version_id in hit_by_url else None)
                title, published_at = hit_by_url.get(url, (None, None))
                return replace(
                    c,
                    document_version_id=None,
                    wiki_slug=None,
                    source_url=url,
                    source_title=title,
                    source_published_at=published_at,
                )

            enriched = [_enrich(c) for c in result.citations]
            if any(c.source_url is None for c in enriched):
                return AgentResult(
                    has_answer=False,
                    no_answer_reason="인용 근거가 실제로 조회한 검색 결과와 일치하지 않음",
                )
            result.citations = enriched
        return result
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `pytest tests/test_agent_core.py -v`
Expected: PASS (전체 — 기존 웹 검색 테스트들이 `wiki_tools.search_web`만 설정하고 `search_recent_disclosures`/`read_disclosure`는 안 건드리면, `wiki_tools` fixture가 `MagicMock`이라 `search_recent_disclosures()` 호출 시 빈 `MagicMock` 객체가 반환될 수 있다 — 모델이 그 도구를 호출 안 하면 문제없지만, 혹시 기존 테스트의 `responses` 리스트가 예상 못 한 도구 호출로 어긋나면 그 테스트의 `wiki_tools.search_recent_disclosures.return_value = []`를 추가해서 명시적으로 빈 목록을 반환하게 해라)

- [ ] **Step 5: 커밋**

```bash
git add src/agent/core.py tests/test_agent_core.py
git commit -m "Feat: 웹 검색 그라운딩에 DART 공시 실시간 조회 도구 추가"
```

---

### Task 4: 전체 회귀 + 실제 DB/API로 최종 검증

**Files:** 없음(검증 전용 태스크)

**Interfaces:** 없음

- [ ] **Step 1: 전체 테스트 스위트 실행**

Run: `pytest tests/ -q`
Expected: 이 플랜에서 추가/수정한 파일들의 테스트가 전부 통과하고, 그 외 실패는 이 브랜치와 무관한 기존 baseline(직전 검증들에서 이미 확인된 9~12건 — `test_analysis_*_missing_api_key`, `test_report_*`, `pipeline/test_pending_documents.py` 계열)과 일치하는지 확인한다.

- [ ] **Step 2: 실제 DART API로 공시 조회 자체 검증**

```bash
python -c "
import sys
sys.path.insert(0, r'C:\myWIKI\SK_Suni_5th_project-myWiki\.claude\worktrees\document-grounded-fallback')
from dotenv import load_dotenv
load_dotenv(r'C:\myWIKI\SK_Suni_5th_project-myWiki\.claude\worktrees\document-grounded-fallback\.env')
from src.pipeline_common import dart_lookup

hits = dart_lookup.search_recent_disclosures('98359399-ae4d-4c5c-beb1-8a47dc6cf6fe', days=14)
for h in hits[:5]:
    print(h.report_name, '|', h.rcept_no, '|', h.published_at)
if hits:
    body = dart_lookup.read_disclosure(hits[0].rcept_no)
    print('본문 길이:', len(body) if body else 0)
"
```
Expected: 실제 SK하이닉스 최근 공시 목록이 크래시 없이 출력되고, 첫 번째 공시의 본문을 실제로 읽어옴.

- [ ] **Step 3: 실제 DB로 `_web_search_answer` 경로 재현**

```bash
python -c "
import sys
sys.path.insert(0, r'C:\myWIKI\SK_Suni_5th_project-myWiki\.claude\worktrees\document-grounded-fallback')
from dotenv import load_dotenv
load_dotenv(r'C:\myWIKI\SK_Suni_5th_project-myWiki\.claude\worktrees\document-grounded-fallback\.env')
from src.agent.core import WikiAgent
from src.agent.wiki_tools import WikiTools

tools = WikiTools(workspace_id='98359399-ae4d-4c5c-beb1-8a47dc6cf6fe')
agent = WikiAgent(tools)
result = agent._web_search_answer('SK하이닉스 최근 지분 변동이나 공시 관련 최신 소식이 뭐야?')
print('has_answer:', result.has_answer, 'is_llm_fallback:', result.is_llm_fallback)
for c in result.citations:
    print('citation:', c.document_version_id, c.source_url, c.source_title)
print('no_answer_reason:', result.no_answer_reason)
"
```
Expected: 크래시 없이 완료. 근거를 찾으면 `source_url`이 `dart.fss.or.kr` 도메인이거나 뉴스 URL, `document_version_id`는 항상 `None`. 근거를 못 찾으면 정직하게 `has_answer=False`.

- [ ] **Step 4: 최종 커밋 없음**

문제를 발견하면 해당 Task로 돌아가 수정 후 그 Task의 커밋을 새로 만든다(이미 만든 커밋을 amend하지 않는다).

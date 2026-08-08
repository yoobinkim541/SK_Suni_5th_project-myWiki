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
import logging
import os
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from ..analysis.repository import get_supabase

logger = logging.getLogger(__name__)

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
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "dart_lookup: 공시 목록 조회 실패, 이 회사만 건너뜀 (corp_code=%s)",
                corp_code,
                exc_info=True,
            )
            continue

        status = payload.get("status")
        if status == _STATUS_NO_DATA:
            continue
        if status != _STATUS_OK:
            logger.warning(
                "dart_lookup: 공시검색 API 응답 오류, 이 회사만 건너뜀 (corp_code=%s, status=%s, message=%s)",
                corp_code, status, payload.get("message"),
            )
            continue

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

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

import html
import io
import logging
import os
import re
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
_PAGE_COUNT = 100
_MAX_PAGES = 5  # 한 회사당 최대 500건 — 나스닥 상장 직후처럼 특정 기간에 공시가
# 몰리는 회사도 실측상 이 안에서 커버되고(2026-08-09 확인: SK하이닉스 90일치 56건),
# 무한 페이지 호출로 응답이 느려지는 걸 막는 안전 상한이다.

_HTML_TAG = re.compile(r"<[^>]+>")
_MAX_TEXT_CHARS = 30_000  # 모델 컨텍스트 안에 안전하게 들어가는 상한


def _strip_tags(text: str) -> str:
    return html.unescape(_HTML_TAG.sub("", text)).strip()

DEFAULT_LOOKBACK_DAYS = 90
"""
파이프라인 수집기(DEFAULT_DART_LOOKBACK_DAYS=30, fetchers.py)보다 길다 — 최대주주
지분변동처럼 자주 나오지 않는 공시는 14일로는 대부분 놓쳤다. 이 모듈은 "배치가 아직
못 커버한 최근 공시"를 확실히 메꾸는 안전망 용도라, 배치 lookback(30일)보다 넉넉히
넓게 잡는다. list.json 호출은 날짜 파라미터만 넓어질 뿐 라운드 수·비용에 영향 없다.
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
    failed = 0
    for corp_code in corp_codes:
        # 나스닥 상장 직후처럼 특정 기간에 공시가 몰리는 회사는 90일치가 page_count(100)를
        # 넘길 수 있다 — 1페이지만 보면 최신/중요 공시가 조용히 누락된다(실측 버그:
        # SK하이닉스 ADR 상장 공시를 못 찾음). total_page를 보고 page_no를 늘려가며
        # _MAX_PAGES까지 이어 받는다. sort=date/sort_mth=desc로 최신순 보장 — 상한에
        # 걸려도 최신 공시가 먼저 잘리지 않는다.
        corp_hits: list[DisclosureHit] = []
        corp_failed = False
        try:
            page_no = 1
            while page_no <= _MAX_PAGES:
                response = httpx.get(
                    _DART_LIST_URL,
                    params={
                        "crtfc_key": api_key,
                        "corp_code": corp_code,
                        "bgn_de": bgn_de,
                        "end_de": end_de,
                        "page_no": page_no,
                        "page_count": _PAGE_COUNT,
                        "sort": "date",
                        "sort_mth": "desc",
                    },
                    timeout=_TIMEOUT_SEC,
                )
                payload = response.json()

                status = payload.get("status")
                if status == _STATUS_NO_DATA:
                    break
                if status != _STATUS_OK:
                    if page_no == 1:
                        corp_failed = True
                        logger.warning(
                            "dart_lookup: 공시검색 API 응답 오류, 이 회사만 건너뜀 (corp_code=%s, status=%s, message=%s)",
                            corp_code, status, payload.get("message"),
                        )
                    break

                for entry in payload.get("list", []):
                    rcept_no = (entry.get("rcept_no") or "").strip()
                    if not rcept_no:
                        continue
                    published = _parse_dart_date(entry.get("rcept_dt"))
                    corp_hits.append(
                        DisclosureHit(
                            rcept_no=rcept_no,
                            report_name=(entry.get("report_nm") or "").strip(),
                            corp_name=(entry.get("corp_name") or "").strip(),
                            published_at=published.isoformat() if published else None,
                        )
                    )

                try:
                    total_page = int(payload.get("total_page") or 1)
                except (TypeError, ValueError):
                    total_page = 1
                if page_no >= total_page:
                    break
                page_no += 1
        except Exception:  # noqa: BLE001
            corp_failed = True
            logger.warning(
                "dart_lookup: 공시 목록 조회 실패, 이 회사만 건너뜀 (corp_code=%s)",
                corp_code,
                exc_info=True,
            )

        if corp_failed:
            failed += 1
            continue
        hits.extend(corp_hits)

    # 등록된 회사 전부가 실패하면(네트워크/인증/한도 초과 등) "공시 0건"으로 조용히
    # 넘어가지 않는다 — fetchers.py의 네이버 관련 교훈과 같은 함정: 인증 실패도
    # items가 빈 리스트라 정상 호출인데 0건으로 보이면 모델에게는 "근거 없음"으로
    # 오인된다. 일부만 실패한 경우(failed < len(corp_codes))는 그대로 부분 결과를 낸다.
    if failed and failed == len(corp_codes):
        raise DartLookupError(f"등록된 disclosure 소스 {failed}건 전부 조회 실패")
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

    try:
        raw_text = html_body.decode("utf-8")
    except UnicodeDecodeError:
        # DART 문서 인코딩이 항상 UTF-8은 아니다(preprocessing/parsers.py::decode_body와
        # 같은 이유로 cp949도 시도) — 그래도 안 되면 손실 허용 디코드로 마지막 방어.
        try:
            raw_text = html_body.decode("cp949")
        except UnicodeDecodeError:
            raw_text = html_body.decode("utf-8", errors="replace")

    text = _strip_tags(raw_text)
    if not text:
        return None
    return text[:_MAX_TEXT_CHARS]

"""
DART Open API 실제 호출 — src.collectors.fetchers.fetch_disclosure 통합 테스트.

tests/pipeline/test_fetchers.py의 목 테스트는 DART 응답 구조 자체가 바뀌면
잡아내지 못한다(목 데이터가 2026-08-05 실제 응답을 옮긴 스냅샷이기 때문).
이 파일은 살아있는 DART_API_KEY로 실제 API를 호출해서 그 가정이 여전히
맞는지 확인한다. DART_API_KEY가 없으면(CI 등) 전부 skip한다.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from dotenv import load_dotenv

load_dotenv()

from src.collectors import fetchers
from src.pipeline_common.models import CollectRequest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DART_API_KEY"), reason="DART_API_KEY가 설정돼 있지 않다."
)

# corpCode.xml 벌크 파일에서 확인한 SK하이닉스의 DART 고유번호(2026-08-05).
SK_HYNIX_CORP_CODE = "00164779"


def test_fetch_disclosure_returns_real_filings_for_sk_hynix():
    source = {
        "id": str(uuid.uuid4()),
        "name": "DART - SK하이닉스 (실통합 테스트)",
        "source_type": "disclosure",
        "config": {"corp_code": SK_HYNIX_CORP_CODE, "request_delay_sec": 0},
    }
    request = CollectRequest(
        workspace_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        since=datetime.now(timezone.utc) - timedelta(days=60),
        limit=3,
    )

    outcome = fetchers.fetch_disclosure(source, request)

    # SK하이닉스는 정기·수시 공시가 잦아 60일 안에 0건일 수 없다 — 0건이면 우리
    # 코드나 DART 쪽 응답 구조가 바뀌었다는 신호로 본다.
    assert len(outcome.items) > 0
    for item in outcome.items:
        assert item.url.startswith("https://dart.fss.or.kr/dsaf001/main.do?rcpNo=")
        assert item.content_type == "text/html"
        # document.xml의 실제 내용은 보고서 종류마다 다르다 — 재무실적류는 리터럴
        # <html> 태그를 쓰지만, 임원·주요주주 보고서류는 DART 자체 태그
        # (<DOCUMENT>/<SECTION-N>/<P>)를 쓴다. 둘 다 문서 태그 <P>/<TR>/<TD> 같은
        # 마크업 문자는 반드시 있어야 하고(전처리 _parse_html이 이걸로 텍스트를
        # 뽑는다), 완전한 평문이면 추출이 안 된 것이다.
        assert b"<" in item.body and b">" in item.body
        assert item.title_hint
        assert item.published_at_hint is not None
        assert item.published_at_hint.tzinfo is not None

    # 실제 전처리 파서가 이 본문에서 읽을 수 있는 텍스트를 뽑아내는지까지 확인한다
    # — content_type만 맞고 실제로는 파싱이 안 되는 회귀를 잡기 위함.
    from src.preprocessing.parsers import _parse_html

    markdown, _title, _published_raw = _parse_html(outcome.items[0].body, "text/html")
    assert len(markdown.strip()) > 0

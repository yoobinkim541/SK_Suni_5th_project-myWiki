"""
날짜 문자열 파싱.

collect(RSS 발행일·DB 값 비교)와 preprocess(HTML 메타 태그) 양쪽이 쓴다.
어느 한쪽 모듈에 두면 상류(collectors)가 하류(preprocessing)를 import하게 되므로
공용 계층에 둔다.
"""
from __future__ import annotations

from datetime import datetime


def parse_datetime(value: str | None) -> datetime | None:
    """ISO 8601 / RFC 822 문자열을 datetime으로. 실패하면 None."""
    if not value:
        return None
    text = value.strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None

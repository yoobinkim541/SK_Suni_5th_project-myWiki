from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class DashboardSummary(BaseModel):
    collected_docs: int
    collected_docs_today: int
    generated_reports: int
    wiki_docs: int
    wiki_docs_new_today: int
    avg_reliability_label: str


class TrendDay(BaseModel):
    """하루치 수집·채택 집계. date는 UTC가 아니라 KST 기준 날짜다."""

    date: date
    collected: int
    adopted: int
    # 수집 경로별 내역. sources.source_type이 news/rss면 news, disclosure면 disclosure로
    # 접는다. 그 밖의 타입(report·website·manual_upload)이나 소스를 못 찾은 문서는
    # 어느 쪽에도 안 들어가므로 news + disclosure <= collected 다.
    news: int
    disclosure: int


class DashboardTrend(BaseModel):
    """오래된 날부터 오늘까지 순서대로. 빈 날도 0으로 채워 준다."""

    days: list[TrendDay]

from __future__ import annotations

from datetime import date, datetime

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


class DashboardKeyword(BaseModel):
    """'오늘의 키워드' 칩 하나.

    count는 "그 낱말이 제목에 등장한 문서 수"다(categories.keywords.count_keywords 계약).
    화면 문구가 '언급 순'이라 수집 질의어 건수를 쓰면 안 된다 — 그건 우리 검색어이지
    언급 빈도가 아니고, 실측으로 'SK하이닉스'가 56%를 차지해 필터로도 무의미하다.
    """

    word: str
    count: int


class DashboardKeywords(BaseModel):
    keywords: list[DashboardKeyword]


class DashboardNewsItem(BaseModel):
    """'최신 뉴스' 카드 하나.

    quote는 비어 있을 수 있다(2026-08-07 실측 커버리지 8%). 분석이 수집을 못 따라가서
    최신 문서일수록 인용문이 없고, 이 목록은 발행일 내림차순이라 하필 그 구간을 고른다.
    빈 자리를 본문 조각 같은 걸로 채우지 않는다 — 인용문 자리에 놓이는 순간 근거 없는
    인용이 된다(절대원칙 1·2). 화면이 빈 인용문을 접는다.

    tags는 항상 리스트다(빈 리스트일 수 있음). DashboardPage가 n.tags.map()을 가드 없이
    부르기 때문에 None을 주면 화면이 죽는다.

    published_at은 ISO 그대로 준다. '12분 전' 같은 상대 시간 문자열은 프론트
    services/dashboardApi.js가 만든다 — 서버 시각과 보는 사람 시각이 다를 수 있어서다.
    """

    title: str
    quote: str
    category: str
    tags: list[str]
    source_label: str
    source_url: str
    published_at: datetime | None
    is_doc: bool


class DashboardNews(BaseModel):
    items: list[DashboardNewsItem]


class DashboardIssue(BaseModel):
    """'최근 산업 이슈' 행 하나.

    최신 뉴스와 달리 **공시만** 담는다. 기사는 '최신 뉴스'가 이미 보여주고 있고,
    이 섹션은 "회사가 공식적으로 신고한 사실"을 모으는 자리다(DashboardNewsItem과
    분리해 둔 이유이기도 하다 — 모양이 비슷해도 뜻이 다르다).

    id는 document_id다. 화면이 key로만 쓰고 라우팅에는 안 쓴다.

    level은 카드 배지와 같은 3종(high/mid/low)이고, 신뢰도 점수를 카테고리 현황과
    **같은 임계값**으로 변환한다. 두 화면이 다른 기준으로 '보통'을 말하면 안 된다.
    분석이 아직 안 끝난 공시는 이 목록에 넣지 않는다 — level·summary가 분석
    산출물이라, 넣으면 근거 없이 등급이 붙는다(절대원칙 1).

    summary는 core_summary다. 비면 그 공시는 목록에서 뺀다. 제목만 있고 요약이 없는
    행을 이슈 카드로 만들면 화면에 제목이 두 번 나올 뿐이다.
    """

    id: str
    level: str
    category: str
    title: str
    summary: str
    source_label: str
    source_url: str
    published_at: datetime | None
    is_doc: bool = True


class DashboardIssues(BaseModel):
    items: list[DashboardIssue]

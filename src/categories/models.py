from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

# CategoryCard.jsx의 LEVEL_LABEL/LEVEL_CLASS가 이 세 값만 인식한다.
# 다른 값이 가면 크래시는 안 나지만 카드에 "신뢰도 : "만 남고 값이 빠진다.
CategoryLevel = Literal["high", "mid", "low"]


class CategoryKeyword(BaseModel):
    """원그래프 조각 하나 (KeywordPie.jsx의 items 원소)."""

    word: str
    count: int


class CategoryDocument(BaseModel):
    """관련 뉴스 모달의 항목 하나 (CategoryNewsModal.jsx).

    published_at은 ISO 문자열로 그대로 내려보내고 '1시간 전' 같은 상대시각은
    프론트가 만든다 — 응답이 캐시되거나 탭이 오래 열려 있으면 백엔드가 만든
    상대시각은 틀린 채로 굳는다. 포맷은 렌더 시점의 관심사다.
    """

    title: str
    quote: str
    source_label: str
    source_url: str
    published_at: str | None


class CategoryStat(BaseModel):
    """카테고리 현황 카드 1장에 대응한다 (CategoryCard.jsx)."""

    id: str
    name: str
    count: int
    top_issue: str
    tags: list[str]
    level: CategoryLevel
    # 원그래프 오른쪽(분류 내부 키워드). 왼쪽 파이는 위의 count를 그대로 쓴다.
    keywords: list[CategoryKeyword] = []
    recent_documents: list[CategoryDocument] = []


class CategoryComparison(BaseModel):
    """'증가 폭 최대'·'신규 이슈 분류' 두 KPI의 산출 근거.

    **전일(D-0 vs D-1)이 아니라 D-2 vs D-3을 비교한다.** 이유는 분석 커버리지다 —
    오늘 발행분은 아직 분석이 거의 안 끝나서(2026-08-12 실측 3.7%) 어제(16.9%)와
    비교하면 뉴스량과 무관하게 전 카테고리가 감소로 나온다. 실제로 전일 대비로
    계산하면 '증가 폭 최대'가 -9건이라는 값이 나온다.

    D-2·D-3은 둘 다 분석이 굳은 뒤라(18.1% / 18.8%) 커버리지가 상쇄돼 실제 발행량
    변화가 남는다. 분석이 최신순으로 처리되기 때문에(analysis/repository.py의
    order("created_at", desc=True)) 각 날짜는 '가장 최신이었을 때' 비슷한 몫을 받고
    굳는다 — 그래서 굳은 날끼리는 비교가 성립한다.

    ⚠ 그 전제가 깨지는 날이 있다. 스케줄러가 실패한 날은 커버리지가 튄다(08-08은
    나흘이 지나도 1.9%). 두 날의 커버리지 차가 크면 값을 만들지 않고 available=False로
    돌려준다 — 틀린 숫자를 보여주는 것보다 '집계 준비 중'이 낫다(절대원칙 1).
    """

    available: bool
    reason: str | None = None
    current_date: date | None = None
    baseline_date: date | None = None
    current_coverage: float | None = None
    baseline_coverage: float | None = None
    max_increase_name: str | None = None
    max_increase_delta: int | None = None
    new_category_name: str | None = None
    new_category_count: int | None = None


class CategoryStats(BaseModel):
    total_documents: int
    categories: list[CategoryStat]
    comparison: CategoryComparison

from __future__ import annotations

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


class CategoryStats(BaseModel):
    total_documents: int
    categories: list[CategoryStat]

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# CategoryCard.jsx의 LEVEL_LABEL/LEVEL_CLASS가 이 세 값만 인식한다.
# 다른 값이 가면 크래시는 안 나지만 카드에 "신뢰도 : "만 남고 값이 빠진다.
CategoryLevel = Literal["high", "mid", "low"]


class CategoryStat(BaseModel):
    """카테고리 현황 카드 1장에 대응한다 (CategoryCard.jsx)."""

    id: str
    name: str
    count: int
    top_issue: str
    tags: list[str]
    level: CategoryLevel


class CategoryStats(BaseModel):
    total_documents: int
    categories: list[CategoryStat]

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class EvidenceRef:
    document_version_id: str
    quoted_text: str
    source_start_line: Optional[int] = None
    source_end_line: Optional[int] = None
    relevance_score: Optional[float] = None


@dataclass
class SectionDraft:
    category: str  # 제품·기술 / 경쟁사 / 고객·수요산업 / 공급망·생산 / 정책·규제 / 시장·경영
    title: str
    content: Optional[str]  # None이면 "근거 부족"으로 처리 (섹션 미생성)
    confidence_score: Optional[float]
    evidences: list[EvidenceRef]
    status: str  # 'completed' | 'failed'(근거 부족)


def analyze(document_version_ids: list[str]) -> list[SectionDraft]:
    """
    문서 묶음을 읽어 분류·요약하고, 근거가 충분한 것만 SectionDraft(status='completed')로,
    부족한 건 status='failed'로 반환한다. 호출자(report 담당)는 completed만 report_sections에 저장한다.
    """
    raise NotImplementedError

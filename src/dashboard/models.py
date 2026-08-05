from __future__ import annotations

from pydantic import BaseModel


class DashboardSummary(BaseModel):
    collected_docs: int
    collected_docs_today: int
    generated_reports: int
    wiki_docs: int
    wiki_docs_new_today: int
    avg_reliability_label: str

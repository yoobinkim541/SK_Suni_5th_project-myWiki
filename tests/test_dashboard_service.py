from __future__ import annotations

from datetime import datetime, timezone

from src.dashboard import service
from src.dashboard.models import DashboardSummary

WORKSPACE_ID = "ws-1"
# KST 2026-08-05 12:00 == UTC 2026-08-05 03:00. "오늘"(KST) 창은
# UTC [2026-08-04T15:00:00, 2026-08-05T15:00:00) 이다.
NOW = datetime(2026, 8, 5, 3, 0, tzinfo=timezone.utc)


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []

    def select(self, _fields):
        return self

    def eq(self, field, value):
        self.filters.append(("eq", field, value))
        return self

    def gte(self, field, value):
        self.filters.append(("gte", field, value))
        return self

    def execute(self):
        rows = self.rows
        for op, field, value in self.filters:
            if op == "eq":
                rows = [r for r in rows if r.get(field) == value]
            elif op == "gte":
                rows = [r for r in rows if r.get(field) and r[field] >= value]
        return FakeResult([dict(r) for r in rows])


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return FakeTable(self.tables.setdefault(name, []))


def _doc(created_at, workspace_id=WORKSPACE_ID):
    return {"id": created_at, "created_at": created_at, "workspace_id": workspace_id}


def test_reliability_label_thresholds():
    assert service._reliability_label(None) == "데이터 없음"
    assert service._reliability_label(39) == "낮음"
    assert service._reliability_label(40) == "보통"
    assert service._reliability_label(69) == "보통"
    assert service._reliability_label(70) == "높음"


def test_get_dashboard_summary_counts_within_windows():
    db = FakeSupabase({
        "documents": [
            _doc("2026-08-04T16:00:00+00:00"),  # 오늘(KST) + 최근 7일
            _doc("2026-08-02T10:00:00+00:00"),  # 최근 7일만
            _doc("2026-07-20T10:00:00+00:00"),  # 7일 밖 — 제외
            _doc("2026-08-04T16:00:00+00:00", workspace_id="ws-2"),  # 다른 workspace — 제외
        ],
        "reports": [
            {"id": "r1", "workspace_id": WORKSPACE_ID, "status": "completed", "created_at": "2026-08-03T00:00:00+00:00"},
            {"id": "r2", "workspace_id": WORKSPACE_ID, "status": "failed", "created_at": "2026-08-03T00:00:00+00:00"},
            {"id": "r3", "workspace_id": WORKSPACE_ID, "status": "completed", "created_at": "2026-07-01T00:00:00+00:00"},
        ],
        "wiki_pages": [
            {"id": "w1", "workspace_id": WORKSPACE_ID, "status": "published", "published_at": "2026-08-04T16:00:00+00:00"},
            {"id": "w2", "workspace_id": WORKSPACE_ID, "status": "published", "published_at": "2026-01-01T00:00:00+00:00"},
            {"id": "w3", "workspace_id": WORKSPACE_ID, "status": "archived", "published_at": "2026-08-04T16:00:00+00:00"},
        ],
        "document_analysis_results": [
            {"document_version_id": "v1", "workspace_id": WORKSPACE_ID, "reliability_score": 30, "created_at": "2026-08-04T00:00:00+00:00"},
            {"document_version_id": "v2", "workspace_id": WORKSPACE_ID, "reliability_score": 90, "created_at": "2026-08-03T00:00:00+00:00"},
            {"document_version_id": "v3", "workspace_id": WORKSPACE_ID, "reliability_score": 10, "created_at": "2026-07-01T00:00:00+00:00"},
        ],
    })

    summary = service.get_dashboard_summary(WORKSPACE_ID, supabase=db, now=NOW)

    assert isinstance(summary, DashboardSummary)
    assert summary.collected_docs == 2
    assert summary.collected_docs_today == 1
    assert summary.generated_reports == 1
    assert summary.wiki_docs == 2
    assert summary.wiki_docs_new_today == 1
    assert summary.avg_reliability_label == "보통"  # (30+90)/2 = 60


def test_get_dashboard_summary_handles_empty_workspace():
    db = FakeSupabase({"documents": [], "reports": [], "wiki_pages": [], "document_analysis_results": []})

    summary = service.get_dashboard_summary(WORKSPACE_ID, supabase=db, now=NOW)

    assert summary.collected_docs == 0
    assert summary.collected_docs_today == 0
    assert summary.generated_reports == 0
    assert summary.wiki_docs == 0
    assert summary.wiki_docs_new_today == 0
    assert summary.avg_reliability_label == "데이터 없음"

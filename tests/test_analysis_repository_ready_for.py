"""get_documents_ready_for_classification / get_documents_ready_for_ranking 검증.

나머지 두 단계(reliability/importance)의 ready_for 함수는 이미
tests/test_analysis_reliability_persistence.py 등에서 다뤄지고 있어서, 여기서는
2026-08-04(wiki-page-type-expansion 검증 중 발견한 분석 배치 자동화 공백)에 새로
추가된 이 두 함수만 다룬다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.analysis.repository import (
    get_documents_ready_for_classification,
    get_documents_ready_for_importance,
    get_documents_ready_for_ranking,
    get_documents_ready_for_reliability,
)


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, supabase, name):
        self.rows = supabase.tables.setdefault(name, [])
        self.filters = []
        self.in_filters = []
        self.gte_filters = []
        self.ordering = []
        self._limit = None

    def select(self, _fields):
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def gte(self, field, value):
        self.gte_filters.append((field, value))
        return self

    def in_(self, field, values):
        self.in_filters.append((field, set(values)))
        return self

    def order(self, field, desc=False):
        self.ordering.append((field, desc))
        return self

    def limit(self, value):
        self._limit = value
        return self

    def execute(self):
        rows = [dict(row) for row in self.rows]
        for field, value in self.filters:
            rows = [row for row in rows if row.get(field) == value]
        for field, value in self.gte_filters:
            rows = [row for row in rows if (row.get(field) or "") >= value]
        for field, values in self.in_filters:
            rows = [row for row in rows if row.get(field) in values]
        for field, desc in reversed(self.ordering):
            rows.sort(key=lambda row: row.get(field) or "", reverse=desc)
        if self._limit is not None:
            rows = rows[: self._limit]
        return FakeResult(rows)


class FakeSupabase:
    def __init__(self):
        self.tables = {}

    def table(self, name):
        return FakeTable(self, name)


def test_get_documents_ready_for_classification_excludes_already_analyzed():
    db = FakeSupabase()
    now = datetime.now(timezone.utc).isoformat()
    db.tables["documents"] = [
        {"id": "doc-1", "workspace_id": "ws-1", "status": "active", "created_at": now},
        {"id": "doc-2", "workspace_id": "ws-1", "status": "active", "created_at": now},
        {"id": "doc-3", "workspace_id": "ws-other", "status": "active", "created_at": now},
    ]
    db.tables["document_versions"] = [
        {"id": "ver-1", "document_id": "doc-1", "created_at": now},
        {"id": "ver-2", "document_id": "doc-2", "created_at": now},
        {"id": "ver-3", "document_id": "doc-3", "created_at": now},
    ]
    db.tables["document_analysis_results"] = [
        {"document_version_id": "ver-1"},
    ]

    result = get_documents_ready_for_classification(workspace_id="ws-1", supabase=db)

    assert result == ["ver-2"]


def test_get_documents_ready_for_classification_respects_since_days_window():
    db = FakeSupabase()
    recent = datetime.now(timezone.utc).isoformat()
    stale = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    db.tables["documents"] = [
        {"id": "doc-recent", "workspace_id": "ws-1", "status": "active", "created_at": recent},
        {"id": "doc-stale", "workspace_id": "ws-1", "status": "active", "created_at": stale},
    ]
    db.tables["document_versions"] = [
        {"id": "ver-recent", "document_id": "doc-recent", "created_at": recent},
        {"id": "ver-stale", "document_id": "doc-stale", "created_at": stale},
    ]
    db.tables["document_analysis_results"] = []

    result = get_documents_ready_for_classification(workspace_id="ws-1", since_days=7, supabase=db)

    assert result == ["ver-recent"]


def test_get_documents_ready_for_ranking_requires_completed_importance():
    db = FakeSupabase()
    db.tables["document_analysis_results"] = [
        {
            "document_version_id": "ver-1",
            "workspace_id": "ws-1",
            "status": "completed",
            "reliability_status": "completed",
            "importance_status": "completed",
            "ranking_status": "pending",
        },
        {
            "document_version_id": "ver-2",
            "workspace_id": "ws-1",
            "status": "completed",
            "reliability_status": "completed",
            "importance_status": "pending",
            "ranking_status": "pending",
        },
        {
            "document_version_id": "ver-3",
            "workspace_id": "ws-1",
            "status": "completed",
            "reliability_status": "completed",
            "importance_status": "completed",
            "ranking_status": "completed",
        },
    ]

    result = get_documents_ready_for_ranking(workspace_id="ws-1", supabase=db)

    assert result == ["ver-1"]


def test_get_documents_ready_for_classification_restrict_to_document_ids_ignores_since_days():
    """restrict_to_document_ids가 주어지면 since_days 창을 벗어난 오래된 문서라도
    지정된 id면 대상이 된다 — 야간 배치가 "오늘자만" 대상을 넘겨줄 때, 우연히 오늘
    발행분이 since_days 창 밖(예: 서버 시계 오차)에 있어도 놓치지 않아야 한다."""
    db = FakeSupabase()
    stale = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    db.tables["documents"] = [
        {"id": "doc-stale-but-restricted", "workspace_id": "ws-1", "status": "active", "created_at": stale},
        {"id": "doc-stale-not-restricted", "workspace_id": "ws-1", "status": "active", "created_at": stale},
    ]
    db.tables["document_versions"] = [
        {"id": "ver-restricted", "document_id": "doc-stale-but-restricted", "created_at": stale},
        {"id": "ver-not-restricted", "document_id": "doc-stale-not-restricted", "created_at": stale},
    ]
    db.tables["document_analysis_results"] = []

    result = get_documents_ready_for_classification(
        workspace_id="ws-1", restrict_to_document_ids=["doc-stale-but-restricted"], supabase=db
    )

    assert result == ["ver-restricted"]


def test_get_documents_ready_for_reliability_restrict_to_version_ids():
    """restrict_to_version_ids가 주어지면 그 목록 밖의 문서는, 처리 시각이 아무리
    최근이어도 후보에서 빠진다 — 재정제된 오래된 문서가 오늘자 문서를 큐에서
    밀어내지 못하게 하는 핵심 동작."""
    db = FakeSupabase()
    db.tables["document_analysis_results"] = [
        {
            "document_version_id": "ver-today",
            "workspace_id": "ws-1",
            "status": "completed",
            "reliability_status": "pending",
            "classified_at": "2026-08-07T00:00:00+00:00",
        },
        {
            "document_version_id": "ver-old-but-recently-touched",
            "workspace_id": "ws-1",
            "status": "completed",
            "reliability_status": "pending",
            "classified_at": "2026-08-07T01:00:00+00:00",
        },
    ]

    result = get_documents_ready_for_reliability(
        workspace_id="ws-1", restrict_to_version_ids=["ver-today"], supabase=db
    )

    assert result == ["ver-today"]


def test_get_documents_ready_for_importance_restrict_to_version_ids():
    db = FakeSupabase()
    db.tables["document_analysis_results"] = [
        {
            "document_version_id": "ver-today",
            "workspace_id": "ws-1",
            "status": "completed",
            "reliability_status": "completed",
            "importance_status": "pending",
        },
        {
            "document_version_id": "ver-not-today",
            "workspace_id": "ws-1",
            "status": "completed",
            "reliability_status": "completed",
            "importance_status": "pending",
        },
    ]

    result = get_documents_ready_for_importance(
        workspace_id="ws-1", restrict_to_version_ids=["ver-today"], supabase=db
    )

    assert result == ["ver-today"]

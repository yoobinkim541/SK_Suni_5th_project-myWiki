"""
일별 수집·채택 추이 (GET /dashboard/trend) 집계 검증.

Fake는 이 파일 안에만 둔다. tests/conftest.py를 만들면 다른 파트 테스트에 영향이 간다.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from src.dashboard import service

WORKSPACE_ID = "ws-1"
OTHER_WORKSPACE_ID = "ws-2"

# KST 2026-08-06 12:00 == UTC 2026-08-06 03:00.
# "오늘"(KST 08-06) 창은 UTC [2026-08-05T15:00:00, 2026-08-06T15:00:00) 이다.
NOW = datetime(2026, 8, 6, 3, 0, tzinfo=timezone.utc)
TODAY_KST = date(2026, 8, 6)


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeTable:
    """eq / gte / lt / in_ 만 흉내낸다. service가 쓰는 것이 그게 전부다."""

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

    def lt(self, field, value):
        self.filters.append(("lt", field, value))
        return self

    def in_(self, field, values):
        self.filters.append(("in", field, list(values)))
        return self

    def execute(self):
        rows = self.rows
        for op, field, value in self.filters:
            if op == "eq":
                rows = [r for r in rows if r.get(field) == value]
            elif op == "gte":
                rows = [r for r in rows if r.get(field) and str(r[field]) >= str(value)]
            elif op == "lt":
                rows = [r for r in rows if r.get(field) and str(r[field]) < str(value)]
            elif op == "in":
                rows = [r for r in rows if str(r.get(field)) in {str(v) for v in value}]
        return FakeResult([dict(r) for r in rows])


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables
        self.calls: list[str] = []

    def table(self, name):
        self.calls.append(name)
        return FakeTable(self.tables.setdefault(name, []))


# ------------------------------------------------------------
# 헬퍼
# ------------------------------------------------------------


def _doc(doc_id, created_at, source_id="src-news", workspace_id=WORKSPACE_ID):
    return {
        "id": doc_id,
        "created_at": created_at,
        "source_id": source_id,
        "workspace_id": workspace_id,
    }


def _source(source_id, source_type, workspace_id=WORKSPACE_ID):
    return {"id": source_id, "source_type": source_type, "workspace_id": workspace_id}


def _analysis(version_id, ranking_status="completed", workspace_id=WORKSPACE_ID):
    return {
        "document_version_id": version_id,
        "ranking_status": ranking_status,
        "workspace_id": workspace_id,
    }


DEFAULT_SOURCES = [
    _source("src-news", "news"),
    _source("src-rss", "rss"),
    _source("src-dart", "disclosure"),
]


def _trend(tables, **kwargs):
    tables.setdefault("sources", list(DEFAULT_SOURCES))
    tables.setdefault("document_analysis_results", [])
    tables.setdefault("document_versions", [])
    db = FakeSupabase(tables)
    return service.get_dashboard_trend(WORKSPACE_ID, supabase=db, now=NOW, **kwargs)


def _day(result, day: date):
    return next(d for d in result.days if d.date == day)


# ------------------------------------------------------------
# 버킷 모양
# ------------------------------------------------------------


def test_returns_seven_days_oldest_first_ending_today():
    result = _trend({"documents": []})

    assert len(result.days) == 7
    assert [d.date for d in result.days] == [
        date(2026, 7, 31),
        date(2026, 8, 1),
        date(2026, 8, 2),
        date(2026, 8, 3),
        date(2026, 8, 4),
        date(2026, 8, 5),
        TODAY_KST,
    ]


def test_days_without_documents_are_zero_filled():
    result = _trend({"documents": []})

    assert all(d.collected == 0 and d.adopted == 0 for d in result.days)
    assert all(d.news == 0 and d.disclosure == 0 for d in result.days)


def test_days_parameter_controls_window_length():
    result = _trend({"documents": []}, days=3)

    assert [d.date for d in result.days] == [date(2026, 8, 4), date(2026, 8, 5), TODAY_KST]


# ------------------------------------------------------------
# KST 날짜 경계
# ------------------------------------------------------------


def test_buckets_split_on_kst_midnight_not_utc():
    """
    UTC 15:00이 KST 자정이다. UTC 기준으로 자르면 같은 날 오후 수집분이
    전날로 밀린다.
    """
    result = _trend({
        "documents": [
            # KST 08-05 23:59 — 어제
            _doc("d1", "2026-08-05T14:59:00+00:00"),
            # KST 08-06 00:00 — 오늘 (UTC로는 아직 08-05)
            _doc("d2", "2026-08-05T15:00:00+00:00"),
            # KST 08-06 23:59 — 오늘
            _doc("d3", "2026-08-06T14:59:00+00:00"),
        ]
    })

    assert _day(result, date(2026, 8, 5)).collected == 1
    assert _day(result, TODAY_KST).collected == 2


def test_documents_outside_the_window_are_excluded():
    result = _trend({
        "documents": [
            _doc("old", "2026-07-30T14:59:00+00:00"),      # KST 07-30 — 창 밖
            _doc("first", "2026-07-30T15:00:00+00:00"),    # KST 07-31 — 창 첫날
        ]
    })

    assert sum(d.collected for d in result.days) == 1
    assert _day(result, date(2026, 7, 31)).collected == 1


# ------------------------------------------------------------
# adopted — 문서 단위로 접는다
# ------------------------------------------------------------


def test_adopted_counts_documents_not_analysis_rows():
    """
    재수집으로 버전이 늘면 같은 문서에 완료 행이 여러 개 생긴다. 안 접으면
    adopted가 부풀고 collected를 넘을 수 있다.
    """
    result = _trend({
        "documents": [_doc("d1", "2026-08-06T01:00:00+00:00")],
        "document_analysis_results": [_analysis("v1"), _analysis("v2"), _analysis("v3")],
        "document_versions": [
            {"id": "v1", "document_id": "d1"},
            {"id": "v2", "document_id": "d1"},
            {"id": "v3", "document_id": "d1"},
        ],
    })

    today = _day(result, TODAY_KST)
    assert today.collected == 1
    assert today.adopted == 1


def test_adopted_never_exceeds_collected():
    result = _trend({
        "documents": [
            _doc("d1", "2026-08-06T01:00:00+00:00"),
            _doc("d2", "2026-08-06T02:00:00+00:00"),
        ],
        "document_analysis_results": [_analysis("v1"), _analysis("v2"), _analysis("v3")],
        "document_versions": [
            {"id": "v1", "document_id": "d1"},
            {"id": "v2", "document_id": "d1"},
            {"id": "v3", "document_id": "d2"},
        ],
    })

    assert all(d.adopted <= d.collected for d in result.days)
    assert _day(result, TODAY_KST).adopted == 2


def test_only_completed_ranking_status_counts_as_adopted():
    result = _trend({
        "documents": [
            _doc("d1", "2026-08-06T01:00:00+00:00"),
            _doc("d2", "2026-08-06T02:00:00+00:00"),
            _doc("d3", "2026-08-06T03:00:00+00:00"),
        ],
        "document_analysis_results": [
            _analysis("v1", "completed"),
            _analysis("v2", "pending"),
            _analysis("v3", "excluded"),
        ],
        "document_versions": [
            {"id": "v1", "document_id": "d1"},
            {"id": "v2", "document_id": "d2"},
            {"id": "v3", "document_id": "d3"},
        ],
    })

    assert _day(result, TODAY_KST).adopted == 1


def test_adopted_is_bucketed_by_collection_day_not_analysis_day():
    """
    분석은 수집보다 늦게 돈다. 3일 전에 수집된 문서가 오늘 채택돼도 그 문서는
    수집일 버킷에 잡혀야 한다 — 아니면 과거 막대가 영영 안 채워진다.
    """
    result = _trend({
        "documents": [_doc("d1", "2026-08-03T01:00:00+00:00")],
        "document_analysis_results": [_analysis("v1")],
        "document_versions": [{"id": "v1", "document_id": "d1"}],
    })

    assert _day(result, date(2026, 8, 3)).adopted == 1
    assert _day(result, TODAY_KST).adopted == 0


def test_adopted_ignores_documents_outside_the_window():
    """창 밖 문서가 채택돼 있어도 창 안 버킷을 건드리면 안 된다."""
    result = _trend({
        "documents": [_doc("old", "2026-07-01T01:00:00+00:00")],
        "document_analysis_results": [_analysis("v-old")],
        "document_versions": [{"id": "v-old", "document_id": "old"}],
    })

    assert sum(d.adopted for d in result.days) == 0


# ------------------------------------------------------------
# 수집 경로 분리
# ------------------------------------------------------------


def test_rss_is_counted_as_news():
    """구글 뉴스 RSS는 source_type이 rss지만 화면에서는 뉴스다."""
    result = _trend({
        "documents": [
            _doc("d1", "2026-08-06T01:00:00+00:00", source_id="src-news"),
            _doc("d2", "2026-08-06T02:00:00+00:00", source_id="src-rss"),
            _doc("d3", "2026-08-06T03:00:00+00:00", source_id="src-dart"),
        ]
    })

    today = _day(result, TODAY_KST)
    assert today.collected == 3
    assert today.news == 2
    assert today.disclosure == 1


def test_unknown_source_type_counts_in_collected_only():
    """
    news도 disclosure도 아닌 문서가 있으면 news + disclosure < collected 다.
    합이 안 맞는 게 아니라 계약이 그렇다.
    """
    result = _trend({
        "documents": [
            _doc("d1", "2026-08-06T01:00:00+00:00", source_id="src-web"),
            _doc("d2", "2026-08-06T02:00:00+00:00", source_id=None),
        ],
        "sources": DEFAULT_SOURCES + [_source("src-web", "website")],
    })

    today = _day(result, TODAY_KST)
    assert today.collected == 2
    assert today.news == 0
    assert today.disclosure == 0


# ------------------------------------------------------------
# workspace 격리
# ------------------------------------------------------------


def test_other_workspace_documents_are_not_counted():
    result = _trend({
        "documents": [
            _doc("mine", "2026-08-06T01:00:00+00:00"),
            _doc("theirs", "2026-08-06T02:00:00+00:00", workspace_id=OTHER_WORKSPACE_ID),
        ]
    })

    assert _day(result, TODAY_KST).collected == 1


def test_other_workspace_adoption_does_not_leak():
    """
    document_versions에는 workspace_id가 없다. 분석 행 조회에서 격리가 안 되면
    남의 채택이 내 버킷에 새어 들어온다.
    """
    result = _trend({
        "documents": [_doc("d1", "2026-08-06T01:00:00+00:00")],
        "document_analysis_results": [_analysis("v1", workspace_id=OTHER_WORKSPACE_ID)],
        "document_versions": [{"id": "v1", "document_id": "d1"}],
    })

    assert _day(result, TODAY_KST).adopted == 0


def test_other_workspace_sources_are_not_used_for_split():
    result = _trend({
        "documents": [_doc("d1", "2026-08-06T01:00:00+00:00", source_id="src-theirs")],
        "sources": DEFAULT_SOURCES + [_source("src-theirs", "news", workspace_id=OTHER_WORKSPACE_ID)],
    })

    today = _day(result, TODAY_KST)
    assert today.collected == 1
    assert today.news == 0


# ------------------------------------------------------------
# 쿼리 횟수
# ------------------------------------------------------------


def test_does_not_query_per_day():
    """하루에 한 번씩 부르면 7배 왕복이 된다. 창 전체를 한 번에 받아야 한다."""
    tables = {
        "documents": [_doc(f"d{i}", f"2026-08-0{i}T01:00:00+00:00") for i in range(3, 7)],
        "sources": list(DEFAULT_SOURCES),
        "document_analysis_results": [],
        "document_versions": [],
    }
    db = FakeSupabase(tables)

    service.get_dashboard_trend(WORKSPACE_ID, supabase=db, now=NOW)

    assert db.calls.count("documents") == 1
    assert db.calls.count("sources") == 1


def test_skips_version_lookup_when_nothing_is_adopted():
    tables = {
        "documents": [_doc("d1", "2026-08-06T01:00:00+00:00")],
        "sources": list(DEFAULT_SOURCES),
        "document_analysis_results": [],
        "document_versions": [],
    }
    db = FakeSupabase(tables)

    service.get_dashboard_trend(WORKSPACE_ID, supabase=db, now=NOW)

    assert db.calls.count("document_versions") == 0

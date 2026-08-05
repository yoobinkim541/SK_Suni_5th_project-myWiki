"""
카테고리 현황 집계 테스트.

tests/test_dashboard_service.py와 같은 방식이다 — tests/pipeline/fake_supabase.py는
gte를 지원하지 않아서(기간 필터가 필수인데) 파일 안에 로컬 Fake를 둔다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.categories import service
from src.categories.keywords import CATEGORY_SLUGS
from src.categories.models import CategoryStats

WORKSPACE_ID = "ws-1"
# KST 2026-08-05 12:00 == UTC 2026-08-05 03:00. 최근 7일 창은 2026-07-29T03:00 이후.
NOW = datetime(2026, 8, 5, 3, 0, tzinfo=timezone.utc)


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []
        self._limit = None

    def select(self, _fields):
        return self

    def eq(self, field, value):
        self.filters.append(("eq", field, value))
        return self

    def gte(self, field, value):
        self.filters.append(("gte", field, value))
        return self

    def in_(self, field, values):
        self.filters.append(("in", field, [str(v) for v in values]))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        rows = self.rows
        for op, field, value in self.filters:
            if op == "eq":
                rows = [r for r in rows if str(r.get(field)) == str(value)]
            elif op == "gte":
                rows = [r for r in rows if r.get(field) and r[field] >= value]
            elif op == "in":
                rows = [r for r in rows if str(r.get(field)) in value]
        if self._limit is not None:
            rows = rows[: self._limit]
        return FakeResult([dict(r) for r in rows])


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return FakeTable(self.tables.setdefault(name, []))


def _analysis(version_id, category, *, score=None, importance=None,
              created_at="2026-08-04T00:00:00+00:00", workspace_id=WORKSPACE_ID):
    return {
        "document_version_id": version_id,
        "primary_category": category,
        "reliability_score": score,
        "importance_score": importance,
        "created_at": created_at,
        "workspace_id": workspace_id,
    }


def _db(analysis_rows, documents):
    """analysis 행과 documents를 주면 document_versions는 1:1로 자동 생성한다."""
    versions = [
        {"id": r["document_version_id"], "document_id": f"d-{r['document_version_id']}"}
        for r in analysis_rows
    ]
    return FakeSupabase({
        "document_analysis_results": analysis_rows,
        "document_versions": versions,
        "documents": documents,
    })


def _doc(version_id, title, workspace_id=WORKSPACE_ID):
    return {"id": f"d-{version_id}", "title": title, "workspace_id": workspace_id}


# ------------------------------------------------------------
# level 변환
# ------------------------------------------------------------


def test_level_thresholds_대시보드와_같다():
    assert service._level(39) == "low"
    assert service._level(40) == "mid"
    assert service._level(69) == "mid"
    assert service._level(70) == "high"


def test_점수가_없으면_low로_내린다():
    """근거 없이 높게 보이는 쪽이 더 위험하다."""
    assert service._level(None) == "low"


# ------------------------------------------------------------
# 집계
# ------------------------------------------------------------


def test_카테고리별로_집계하고_카드_6장을_만든다():
    rows = [
        _analysis("v1", "제품·기술", score=30),
        _analysis("v2", "제품·기술", score=50),
        _analysis("v3", "시장·경영", score=80),
    ]
    docs = [_doc("v1", "HBM4 양산"), _doc("v2", "DRAM 공정 개선"), _doc("v3", "실적 발표")]

    stats = service.get_category_stats(WORKSPACE_ID, supabase=_db(rows, docs), now=NOW)

    assert isinstance(stats, CategoryStats)
    assert stats.total_documents == 3
    # 데이터가 없는 카테고리도 카드는 만든다 — 화면이 6장 그리드를 전제한다
    assert len(stats.categories) == 6

    by_id = {c.id: c for c in stats.categories}
    assert by_id["product-tech"].count == 2
    assert by_id["product-tech"].level == "mid"  # (30+50)/2 = 40
    assert by_id["market"].count == 1
    assert by_id["market"].level == "high"
    assert by_id["competitor"].count == 0


def test_기간_밖과_다른_workspace는_제외한다():
    rows = [
        _analysis("v1", "제품·기술", score=50),
        _analysis("v2", "제품·기술", score=50, created_at="2026-07-01T00:00:00+00:00"),  # 7일 밖
        _analysis("v3", "제품·기술", score=50, workspace_id="ws-2"),  # 다른 workspace
    ]
    docs = [_doc("v1", "HBM4"), _doc("v2", "옛날 기사"), _doc("v3", "남의 것")]

    stats = service.get_category_stats(WORKSPACE_ID, supabase=_db(rows, docs), now=NOW)

    assert stats.total_documents == 1


def test_다른_workspace_문서는_제목을_노출하지_않는다():
    """document_versions에는 workspace_id가 없다. documents 조회의 eq가 유일한 격리 지점이다."""
    rows = [_analysis("v1", "제품·기술", score=50)]
    docs = [_doc("v1", "남의 워크스페이스 제목", workspace_id="ws-2")]

    stats = service.get_category_stats(WORKSPACE_ID, supabase=_db(rows, docs), now=NOW)

    by_id = {c.id: c for c in stats.categories}
    assert by_id["product-tech"].count == 1  # 분석 행은 내 것이라 세지만
    assert by_id["product-tech"].top_issue == ""  # 제목은 새어나오지 않는다


def test_미분류_행은_어느_카드에도_넣지_않는다():
    rows = [_analysis("v1", None, score=50), _analysis("v2", "제품·기술", score=50)]
    docs = [_doc("v1", "미분류"), _doc("v2", "HBM4")]

    stats = service.get_category_stats(WORKSPACE_ID, supabase=_db(rows, docs), now=NOW)

    assert stats.total_documents == 1


def test_빈_workspace여도_카드_6장을_돌려준다():
    stats = service.get_category_stats(WORKSPACE_ID, supabase=_db([], []), now=NOW)

    assert stats.total_documents == 0
    assert len(stats.categories) == 6
    assert all(c.count == 0 and c.top_issue == "" and c.tags == [] for c in stats.categories)
    assert all(c.level == "low" for c in stats.categories)


# ------------------------------------------------------------
# top_issue
# ------------------------------------------------------------


def test_top_issue는_importance_score_최상위를_고른다():
    rows = [
        _analysis("v1", "제품·기술", importance=10),
        _analysis("v2", "제품·기술", importance=90),
    ]
    docs = [_doc("v1", "덜 중요한 기사"), _doc("v2", "가장 중요한 기사")]

    stats = service.get_category_stats(WORKSPACE_ID, supabase=_db(rows, docs), now=NOW)

    by_id = {c.id: c for c in stats.categories}
    assert by_id["product-tech"].top_issue == "가장 중요한 기사"


def test_importance_score가_없으면_최신_문서를_고른다():
    """중요도는 분석 뒷단계라 결손이 크다(2026-08-05 기준 26%). 그래도 카드는 채워야 한다."""
    rows = [
        _analysis("v1", "제품·기술", created_at="2026-08-01T00:00:00+00:00"),
        _analysis("v2", "제품·기술", created_at="2026-08-04T00:00:00+00:00"),
    ]
    docs = [_doc("v1", "오래된 기사"), _doc("v2", "최근 기사")]

    stats = service.get_category_stats(WORKSPACE_ID, supabase=_db(rows, docs), now=NOW)

    by_id = {c.id: c for c in stats.categories}
    assert by_id["product-tech"].top_issue == "최근 기사"


def test_점수가_있는_문서가_없는_문서보다_우선한다():
    rows = [
        _analysis("v1", "제품·기술", importance=5, created_at="2026-08-01T00:00:00+00:00"),
        _analysis("v2", "제품·기술", created_at="2026-08-04T00:00:00+00:00"),  # 더 최신이지만 점수 없음
    ]
    docs = [_doc("v1", "점수 있는 기사"), _doc("v2", "점수 없는 기사")]

    stats = service.get_category_stats(WORKSPACE_ID, supabase=_db(rows, docs), now=NOW)

    by_id = {c.id: c for c in stats.categories}
    assert by_id["product-tech"].top_issue == "점수 있는 기사"


def test_top_issue의_매체명_꼬리표를_벗긴다():
    """P2 수정 이전에 수집된 문서는 DB에 꼬리표가 남아 있다."""
    rows = [_analysis("v1", "제품·기술", importance=50)]
    docs = [_doc("v1", "SK하이닉스, HBF 첫 표준규격 공개 - 연합뉴스")]

    stats = service.get_category_stats(WORKSPACE_ID, supabase=_db(rows, docs), now=NOW)

    by_id = {c.id: c for c in stats.categories}
    assert by_id["product-tech"].top_issue == "SK하이닉스, HBF 첫 표준규격 공개"


def test_긴_제목은_잘라서_보낸다():
    """카드에 말줄임 CSS가 없어서 긴 제목이 오면 그리드가 무너진다."""
    rows = [_analysis("v1", "제품·기술", importance=50)]
    docs = [_doc("v1", "가" * 200)]

    stats = service.get_category_stats(WORKSPACE_ID, supabase=_db(rows, docs), now=NOW)

    by_id = {c.id: c for c in stats.categories}
    assert len(by_id["product-tech"].top_issue) == service.TOP_ISSUE_MAX_LEN
    assert by_id["product-tech"].top_issue.endswith("…")


# ------------------------------------------------------------
# 프론트 계약
# ------------------------------------------------------------


def test_id_슬러그가_프론트와_일치한다():
    """
    프론트 data/mockCategory.js의 MOCK_CATEGORIES[].id 및 MOCK_CATEGORY_KEYWORDS의
    키와 1:1로 맞아야 한다. 어긋나면 카테고리 현황의 원그래프 두 개가 조용히 빈
    상태가 된다 — 에러도 경고도 안 뜨는 회귀라 여기서 막는다.
    """
    assert set(CATEGORY_SLUGS.values()) == {
        "product-tech", "competitor", "customer-demand",
        "supply-chain", "policy", "market",
    }


def test_level은_소문자_3종만_나온다():
    """CategoryCard의 LEVEL_LABEL이 이 세 값만 인식한다."""
    rows = [_analysis(f"v{i}", "제품·기술", score=s) for i, s in enumerate([0, 45, 95])]
    docs = [_doc(f"v{i}", f"기사 {i}") for i in range(3)]

    stats = service.get_category_stats(WORKSPACE_ID, supabase=_db(rows, docs), now=NOW)

    assert all(c.level in {"high", "mid", "low"} for c in stats.categories)

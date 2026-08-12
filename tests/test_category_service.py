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

# PostgREST 기본 db-max-rows. FakeTable.execute 참조.
SERVER_MAX_ROWS = 1000


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []
        self._limit = None
        self._orders = []
        self._range = None

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
        self.filters.append(("in", field, [str(v) for v in values]))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def order(self, field, desc=False):
        self._orders.append((field, desc))
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        rows = self.rows
        for op, field, value in self.filters:
            if op == "eq":
                rows = [r for r in rows if str(r.get(field)) == str(value)]
            elif op == "gte":
                rows = [r for r in rows if r.get(field) and r[field] >= value]
            elif op == "lt":
                rows = [r for r in rows if r.get(field) and r[field] < value]
            elif op == "in":
                rows = [r for r in rows if str(r.get(field)) in value]
        for field, desc in reversed(self._orders):
            rows = sorted(rows, key=lambda r: str(r.get(field) or ""), reverse=desc)
        if self._range is not None:
            start, end = self._range
            rows = rows[start : end + 1]
        if self._limit is not None:
            rows = rows[: self._limit]
        # PostgREST의 db-max-rows를 흉내낸다. 서버가 .limit(5000)을 받아도 한 응답에
        # 1,000행까지만 주고 **에러도 경고도 없이** 자른다. 이걸 안 흉내내면
        # pagination 없는 코드가 테스트에서만 멀쩡해 보인다.
        return FakeResult([dict(r) for r in rows[:SERVER_MAX_ROWS]])


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return FakeTable(self.tables.setdefault(name, []))


def _analysis(version_id, category, *, score=None, importance=None,
              created_at="2026-08-04T00:00:00+00:00", workspace_id=WORKSPACE_ID,
              core_summary=None, quoted=None, reliability_status="completed",
              reliability_evaluated_at=None):
    return {
        "document_version_id": version_id,
        "primary_category": category,
        "reliability_score": score,
        "reliability_status": reliability_status,
        "reliability_evaluated_at": reliability_evaluated_at or created_at,
        "importance_score": importance,
        "created_at": created_at,
        "workspace_id": workspace_id,
        "core_summary": core_summary,
        "summary_evidence_refs": (
            [{"quoted_text": quoted, "supports": ["core_summary"]}] if quoted else []
        ),
    }


# 수집 소스 — 종류별로 키워드가 있는 자리가 다르다.
SOURCES = [
    {"id": "s-hbm", "name": "네이버 - HBM", "config": {"query": "HBM"},
     "base_url": "", "workspace_id": WORKSPACE_ID},
    {"id": "s-dram", "name": "네이버 - DRAM", "config": {"query": "DRAM"},
     "base_url": "", "workspace_id": WORKSPACE_ID},
    {"id": "s-rss", "name": "Google RSS - SK하이닉스", "config": {},
     "base_url": "https://news.google.com/rss/search?q=SK%ED%95%98%EC%9D%B4%EB%8B%89%EC%8A%A4&hl=ko",
     "workspace_id": WORKSPACE_ID},
    {"id": "s-dart", "name": "DART - SK하이닉스", "config": {}, "base_url": "",
     "workspace_id": WORKSPACE_ID},
]


def _db(analysis_rows, documents, versions=None, sources=None):
    """analysis 행과 documents를 주면 document_versions는 1:1로 자동 생성한다.

    한 문서에 버전이 여럿인 상황을 만들려면 versions를 직접 넘긴다.
    """
    if versions is None:
        versions = [
            {"id": r["document_version_id"], "document_id": f"d-{r['document_version_id']}"}
            for r in analysis_rows
        ]
    return FakeSupabase({
        "document_analysis_results": analysis_rows,
        "document_versions": versions,
        "documents": documents,
        "sources": sources if sources is not None else SOURCES,
    })


def _doc(version_id, title, workspace_id=WORKSPACE_ID, url=None, published_at=None,
         document_id=None, source_id="s-hbm"):
    return {
        "id": document_id or f"d-{version_id}",
        "title": title,
        "workspace_id": workspace_id,
        "canonical_url": url or f"https://www.example.com/{version_id}",
        "published_at": published_at or "2026-08-04T00:00:00+00:00",
        "source_id": source_id,
    }


# ------------------------------------------------------------
# level 변환
# ------------------------------------------------------------


def test_level_thresholds_match_real_score_buckets():
    assert service._level(39) == "low"
    assert service._level(40) == "mid"
    assert service._level(69) == "mid"
    assert service._level(70) == "high"


def test_missing_score_displays_as_low():
    """Missing score remains low because the Category page reflects real buckets."""
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


def test_다른_workspace_문서는_아예_세지_않는다():
    """document_versions에는 workspace_id가 없다. documents 조회의 eq가 유일한 격리 지점이다.

    건수를 문서 단위로 세면서, 볼 수 없는 문서는 카드에도 안 잡힌다 — 분석 행만
    세던 때는 "보이지 않는 문서 1건"이 숫자에 남았다.
    """
    rows = [_analysis("v1", "제품·기술", score=50)]
    docs = [_doc("v1", "남의 워크스페이스 제목", workspace_id="ws-2")]

    stats = service.get_category_stats(WORKSPACE_ID, supabase=_db(rows, docs), now=NOW)

    by_id = {c.id: c for c in stats.categories}
    assert by_id["product-tech"].count == 0
    assert by_id["product-tech"].top_issue == ""
    assert by_id["product-tech"].recent_documents == []


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


# ------------------------------------------------------------
# keywords — 원그래프 오른쪽 (수집 키워드 기준)
# ------------------------------------------------------------


def test_keywords는_수집_키워드별_문서_수다():
    rows = [_analysis(f"v{i}", "제품·기술") for i in range(3)]
    docs = [
        _doc("v0", "기사1", source_id="s-hbm"),
        _doc("v1", "기사2", source_id="s-hbm"),
        _doc("v2", "기사3", source_id="s-dram"),
    ]

    stats = service.get_category_stats(
        WORKSPACE_ID, supabase=_db(rows, docs, sources=SOURCES), now=NOW
    )

    by_id = {c.id: c for c in stats.categories}
    kws = {k.word: k.count for k in by_id["product-tech"].keywords}
    assert kws == {"HBM": 2, "DRAM": 1}


def test_조각_합이_카드_건수와_일치한다():
    """왼쪽 파이(문서 수)와 오른쪽 파이가 같은 축에서 읽혀야 한다."""
    rows = [_analysis(f"v{i}", "제품·기술") for i in range(4)]
    docs = [_doc(f"v{i}", f"기사{i}", source_id="s-hbm") for i in range(4)]

    stats = service.get_category_stats(
        WORKSPACE_ID, supabase=_db(rows, docs, sources=SOURCES), now=NOW
    )

    by_id = {c.id: c for c in stats.categories}
    card = by_id["product-tech"]
    assert sum(k.count for k in card.keywords) == card.count


def test_같은_문서의_버전이_여럿이면_조각도_한_번만_센다():
    rows = [
        _analysis("v1", "제품·기술", created_at="2026-08-01T00:00:00+00:00"),
        _analysis("v2", "제품·기술", created_at="2026-08-04T00:00:00+00:00"),
    ]
    versions = [
        {"id": "v1", "document_id": "d-same"},
        {"id": "v2", "document_id": "d-same"},
    ]
    docs = [_doc("v1", "같은 기사", document_id="d-same", source_id="s-hbm")]

    stats = service.get_category_stats(
        WORKSPACE_ID, supabase=_db(rows, docs, versions=versions, sources=SOURCES), now=NOW
    )

    by_id = {c.id: c for c in stats.categories}
    assert [(k.word, k.count) for k in by_id["product-tech"].keywords] == [("HBM", 1)]


def test_rss_소스는_base_url의_q에서_키워드를_뽑는다():
    """구글 뉴스 RSS는 config.query가 없고 검색어를 URL에 싣는다."""
    rows = [_analysis("v1", "제품·기술")]
    docs = [_doc("v1", "기사", source_id="s-rss")]

    stats = service.get_category_stats(
        WORKSPACE_ID, supabase=_db(rows, docs, sources=SOURCES), now=NOW
    )

    by_id = {c.id: c for c in stats.categories}
    assert [k.word for k in by_id["product-tech"].keywords] == ["SK하이닉스"]


def test_질의어가_없는_소스는_이름으로_대체한다():
    """DART 공시는 검색어 개념이 없다."""
    rows = [_analysis("v1", "제품·기술")]
    docs = [_doc("v1", "공시", source_id="s-dart")]

    stats = service.get_category_stats(
        WORKSPACE_ID, supabase=_db(rows, docs, sources=SOURCES), now=NOW
    )

    by_id = {c.id: c for c in stats.categories}
    assert [k.word for k in by_id["product-tech"].keywords] == ["DART - SK하이닉스"]


def test_keywords는_상한을_넘지_않는다():
    """KeywordPie의 PALETTE가 7색이라 조각이 너무 많으면 색이 돈다."""
    many = {f"s-{i}": {"id": f"s-{i}", "name": f"소스{i}", "config": {"query": f"kw{i}"},
                       "base_url": "", "workspace_id": WORKSPACE_ID} for i in range(12)}
    rows = [_analysis(f"v{i}", "제품·기술") for i in range(12)]
    docs = [_doc(f"v{i}", f"기사{i}", source_id=f"s-{i}") for i in range(12)]

    stats = service.get_category_stats(
        WORKSPACE_ID, supabase=_db(rows, docs, sources=list(many.values())), now=NOW
    )

    by_id = {c.id: c for c in stats.categories}
    assert len(by_id["product-tech"].keywords) == service.MAX_PIE_KEYWORDS


# ------------------------------------------------------------
# recent_documents — 관련 뉴스 모달
# ------------------------------------------------------------


def test_같은_문서의_버전이_여럿이면_한_번만_나온다():
    """재수집으로 버전이 늘면 분석 행이 여러 개 생긴다(실측 459행 -> 275문서)."""
    rows = [
        _analysis("v1", "제품·기술", created_at="2026-08-01T00:00:00+00:00", quoted="옛 인용"),
        _analysis("v2", "제품·기술", created_at="2026-08-04T00:00:00+00:00", quoted="새 인용"),
    ]
    # 두 버전이 같은 문서를 가리킨다
    versions = [
        {"id": "v1", "document_id": "d-same"},
        {"id": "v2", "document_id": "d-same"},
    ]
    docs = [_doc("v1", "같은 기사", document_id="d-same")]

    stats = service.get_category_stats(
        WORKSPACE_ID, supabase=_db(rows, docs, versions=versions), now=NOW
    )

    by_id = {c.id: c for c in stats.categories}
    recent = by_id["product-tech"].recent_documents
    assert len(recent) == 1
    # 최신 분석 행의 인용문을 쓴다
    assert recent[0].quote == "새 인용"


def test_recent_documents는_발행일_내림차순이다():
    rows = [_analysis(f"v{i}", "제품·기술") for i in range(3)]
    docs = [
        _doc("v0", "가장 오래된", published_at="2026-08-01T00:00:00+00:00"),
        _doc("v1", "가장 최근", published_at="2026-08-05T00:00:00+00:00"),
        _doc("v2", "중간", published_at="2026-08-03T00:00:00+00:00"),
    ]

    stats = service.get_category_stats(WORKSPACE_ID, supabase=_db(rows, docs), now=NOW)

    by_id = {c.id: c for c in stats.categories}
    titles = [d.title for d in by_id["product-tech"].recent_documents]
    assert titles == ["가장 최근", "중간", "가장 오래된"]


def test_recent_documents는_상한을_넘지_않는다():
    rows = [_analysis(f"v{i}", "제품·기술") for i in range(10)]
    docs = [_doc(f"v{i}", f"기사 {i}") for i in range(10)]

    stats = service.get_category_stats(WORKSPACE_ID, supabase=_db(rows, docs), now=NOW)

    by_id = {c.id: c for c in stats.categories}
    assert len(by_id["product-tech"].recent_documents) == service.MAX_RECENT_DOCUMENTS


def test_quote는_quoted_text_core_summary_순으로_폴백한다():
    rows = [
        _analysis("v1", "제품·기술", quoted="원문 인용", core_summary="합성 요약"),
        _analysis("v2", "경쟁사", core_summary="요약만 있음"),
        _analysis("v3", "정책·규제"),
    ]
    docs = [_doc("v1", "기사1"), _doc("v2", "기사2"), _doc("v3", "기사3")]

    stats = service.get_category_stats(WORKSPACE_ID, supabase=_db(rows, docs), now=NOW)

    by_id = {c.id: c for c in stats.categories}
    assert by_id["product-tech"].recent_documents[0].quote == "원문 인용"
    assert by_id["competitor"].recent_documents[0].quote == "요약만 있음"
    assert by_id["policy"].recent_documents[0].quote == ""


def test_긴_인용문은_자른다():
    rows = [_analysis("v1", "제품·기술", quoted="가" * 400)]
    docs = [_doc("v1", "기사")]

    stats = service.get_category_stats(WORKSPACE_ID, supabase=_db(rows, docs), now=NOW)

    by_id = {c.id: c for c in stats.categories}
    quote = by_id["product-tech"].recent_documents[0].quote
    assert len(quote) == service.QUOTE_MAX_LEN
    assert quote.endswith("…")


def test_source_label은_도메인에서_www를_뗀다():
    rows = [_analysis("v1", "제품·기술"), _analysis("v2", "경쟁사")]
    docs = [
        _doc("v1", "기사1", url="https://www.hankyung.com/article/123"),
        _doc("v2", "기사2", url="https://biz.chosun.com/it/456"),
    ]

    stats = service.get_category_stats(WORKSPACE_ID, supabase=_db(rows, docs), now=NOW)

    by_id = {c.id: c for c in stats.categories}
    assert by_id["product-tech"].recent_documents[0].source_label == "hankyung.com"
    assert by_id["competitor"].recent_documents[0].source_label == "biz.chosun.com"


def test_recent_documents의_제목도_꼬리표를_벗긴다():
    rows = [_analysis("v1", "제품·기술")]
    docs = [_doc("v1", "SK하이닉스 HBF 표준규격 공개 - 연합뉴스")]

    stats = service.get_category_stats(WORKSPACE_ID, supabase=_db(rows, docs), now=NOW)

    by_id = {c.id: c for c in stats.categories}
    assert by_id["product-tech"].recent_documents[0].title == "SK하이닉스 HBF 표준규격 공개"


def test_다른_workspace_문서는_뉴스에도_안_나온다():
    rows = [_analysis("v1", "제품·기술", quoted="남의 인용")]
    docs = [_doc("v1", "남의 기사", workspace_id="ws-2")]

    stats = service.get_category_stats(WORKSPACE_ID, supabase=_db(rows, docs), now=NOW)

    by_id = {c.id: c for c in stats.categories}
    assert by_id["product-tech"].recent_documents == []


def test_level_emits_three_known_values():
    """CategoryCard LEVEL_LABEL recognizes these three values."""
    rows = [_analysis(f"v{i}", "제품·기술", score=s) for i, s in enumerate([0, 45, 95])]
    docs = [_doc(f"v{i}", f"기사 {i}") for i in range(3)]

    stats = service.get_category_stats(WORKSPACE_ID, supabase=_db(rows, docs), now=NOW)

    assert all(c.level in {"high", "mid", "low"} for c in stats.categories)


# ------------------------------------------------------------
# .in_() 분할 — 문서가 쌓여도 화면이 죽지 않아야 한다
#
# PostgREST는 필터를 쿼리스트링으로 보내서, id를 통째로 넣으면 데이터가 늘수록
# 요청 URL이 길어지다가 400 Bad Request로 떨어진다. 2026-08-07에 실제로 이 화면이
# 통째로 죽었고(#145), 화면에는 이유 없이 "Failed to fetch"로만 보였다.
#
# 그 수정(#145)이 한 번 리버트됐다가 재적용된(#146 -> #147) 이력이 있는데 회귀
# 테스트가 없어서, 되돌아가도 아무도 못 잡는 상태였다. 그래서 뒤늦게 덧붙인다.
# ------------------------------------------------------------


class RecordingTable(FakeTable):
    """.in_()에 한 번에 넘어온 id 개수를 기록한다."""

    def __init__(self, rows, batches):
        super().__init__(rows)
        self._batches = batches

    def in_(self, field, values):
        self._batches.append(len(values))
        return super().in_(field, values)


class RecordingSupabase(FakeSupabase):
    def __init__(self, tables):
        super().__init__(tables)
        self.in_batches: list[int] = []

    def table(self, name):
        return RecordingTable(self.tables.setdefault(name, []), self.in_batches)


def _many(count):
    rows = [_analysis(f"v{i}", "제품·기술", score=80) for i in range(count)]
    docs = [_doc(f"v{i}", f"기사 {i}") for i in range(count)]
    versions = [{"id": f"v{i}", "document_id": f"d-v{i}"} for i in range(count)]
    return RecordingSupabase({
        "document_analysis_results": rows,
        "document_versions": versions,
        "documents": docs,
        "sources": SOURCES,
    })


def test_id가_많아도_in_에_한도_넘게_넣지_않는다():
    db = _many(service._IN_CLAUSE_CHUNK_SIZE * 2 + 37)

    service.get_category_stats(WORKSPACE_ID, supabase=db, now=NOW)

    assert db.in_batches, ".in_()이 한 번도 안 불렸다 — 테스트가 경로를 못 탔다"
    assert max(db.in_batches) <= service._IN_CLAUSE_CHUNK_SIZE


def test_분할해서_조회해도_건수가_맞는다():
    """나눠 부른 결과를 합치지 않으면 뒷 묶음이 통째로 사라진다."""
    count = service._IN_CLAUSE_CHUNK_SIZE * 2 + 37

    stats = service.get_category_stats(WORKSPACE_ID, supabase=_many(count), now=NOW)

    by_id = {c.id: c for c in stats.categories}
    assert stats.total_documents == count
    assert by_id["product-tech"].count == count


def test_fetches_more_than_postgrest_default_page_size():
    rows = [_analysis(f"v{i:04d}", "\uc81c\ud488\u00b7\uae30\uc220", score=80) for i in range(1001)]
    docs = [_doc(f"v{i:04d}", f"HBM article {i}") for i in range(1001)]

    stats = service.get_category_stats(WORKSPACE_ID, supabase=_db(rows, docs), now=NOW)

    by_id = {c.id: c for c in stats.categories}
    assert by_id["product-tech"].count == 1001
    assert by_id["product-tech"].level == "high"


def test_reliability_average_uses_latest_completed_score_per_document():
    rows = [
        _analysis(
            "v-old",
            "\uc81c\ud488\u00b7\uae30\uc220",
            score=0,
            created_at="2026-08-03T00:00:00+00:00",
            reliability_evaluated_at="2026-08-03T00:00:00+00:00",
        ),
        _analysis(
            "v-new",
            "\uc81c\ud488\u00b7\uae30\uc220",
            score=80,
            created_at="2026-08-04T00:00:00+00:00",
            reliability_evaluated_at="2026-08-04T00:00:00+00:00",
        ),
        _analysis("v-other", "\uc81c\ud488\u00b7\uae30\uc220", score=80),
    ]
    versions = [
        {"id": "v-old", "document_id": "doc-same"},
        {"id": "v-new", "document_id": "doc-same"},
        {"id": "v-other", "document_id": "doc-other"},
    ]
    docs = [
        _doc("v-new", "HBM same article", document_id="doc-same"),
        _doc("v-other", "HBM other article", document_id="doc-other"),
    ]

    stats = service.get_category_stats(WORKSPACE_ID, supabase=_db(rows, docs, versions=versions), now=NOW)

    by_id = {c.id: c for c in stats.categories}
    assert by_id["product-tech"].count == 2
    assert by_id["product-tech"].level == "high"


def test_reliability_average_ignores_pending_and_failed_rows():
    rows = [
        _analysis("v1", "\uc81c\ud488\u00b7\uae30\uc220", score=80),
        _analysis("v2", "\uc81c\ud488\u00b7\uae30\uc220", score=None, reliability_status="pending"),
        _analysis("v3", "\uc81c\ud488\u00b7\uae30\uc220", score=None, reliability_status="failed"),
    ]
    docs = [_doc("v1", "HBM one"), _doc("v2", "HBM two"), _doc("v3", "HBM three")]

    stats = service.get_category_stats(WORKSPACE_ID, supabase=_db(rows, docs), now=NOW)

    by_id = {c.id: c for c in stats.categories}
    assert by_id["product-tech"].count == 3
    assert by_id["product-tech"].level == "high"


# ------------------------------------------------------------
# 집계 창 — 분석 시각이 아니라 발행 시각으로 자른다 (2026-08-10)
# ------------------------------------------------------------


def test_발행일이_창_밖이면_분석이_최근이어도_빠진다():
    """이 변경의 핵심.

    분석이 수집보다 뒤처져서, created_at으로 자르면 3주 전 기사가 '최근 7일' 카드에
    들어온다. 2026-08-10 실측으로 1,306행 중 130행(10%)이 그런 행이었다.
    """
    rows = [
        _analysis("v1", "제품·기술", score=80),
        _analysis("v2", "제품·기술", score=0),  # 어제 분석됐지만 3주 전 기사
    ]
    docs = [
        _doc("v1", "HBM4 양산"),
        _doc("v2", "지난달 기사", published_at="2026-07-15T00:00:00+00:00"),
    ]

    stats = service.get_category_stats(WORKSPACE_ID, supabase=_db(rows, docs), now=NOW)

    by_id = {c.id: c for c in stats.categories}
    assert by_id["product-tech"].count == 1
    assert stats.total_documents == 1
    # 창 밖 기사의 0점이 평균을 끌어내리지 않는다 — 이게 배지가 틀어지던 경로다
    assert by_id["product-tech"].level == "high"


def test_발행일이_없으면_수집일로_대체한다():
    """published_at이 비는 문서(공시·수동 업로드)가 통째로 사라지면 안 된다."""
    rows = [_analysis("v1", "공급망·생산", score=80)]
    docs = [_doc("v1", "설비투자 공시")]
    # _doc은 published_at에 `or 기본값`을 쓰므로 인자로는 NULL을 못 만든다.
    docs[0]["published_at"] = None
    docs[0]["created_at"] = "2026-08-04T00:00:00+00:00"

    stats = service.get_category_stats(WORKSPACE_ID, supabase=_db(rows, docs), now=NOW)

    by_id = {c.id: c for c in stats.categories}
    assert by_id["supply-chain"].count == 1


def test_발행일이_없고_수집일도_창_밖이면_빠진다():
    rows = [_analysis("v1", "공급망·생산", score=80)]
    docs = [_doc("v1", "오래된 공시")]
    docs[0]["published_at"] = None
    docs[0]["created_at"] = "2026-07-01T00:00:00+00:00"

    stats = service.get_category_stats(WORKSPACE_ID, supabase=_db(rows, docs), now=NOW)

    assert stats.total_documents == 0


def test_prefilter_마진_안의_행도_발행일이_창_안이면_잡는다():
    """created_at이 창 시작보다 이른데 published_at은 창 안인 경우.

    published_at <= created_at이라 원래는 안 생기지만, 소스가 미래 시각을 주면
    (타임존 오류) 생긴다. 2026-08-10 실측으로 문서 1,386건 중 5건이 그랬고 최대
    7.3일 앞섰다 — PREFILTER_MARGIN_DAYS는 그 폭을 덮어야 한다.
    """
    # 수집 7.3일 뒤 발행으로 기록된 문서. 마진이 1일이면 여기서 떨어진다.
    rows = [_analysis("v1", "제품·기술", score=80, created_at="2026-07-25T00:00:00+00:00")]
    docs = [_doc("v1", "HBM 양산", published_at="2026-08-01T08:00:00+00:00")]

    stats = service.get_category_stats(WORKSPACE_ID, supabase=_db(rows, docs), now=NOW)

    by_id = {c.id: c for c in stats.categories}
    assert by_id["product-tech"].count == 1


def test_창_기준이_바뀌어도_최신_문서가_모달에_남는다():
    """관련 뉴스 모달은 발행일 내림차순이다. 창 필터가 정렬을 뒤집지 않는지 본다."""
    rows = [
        _analysis("v1", "제품·기술", score=50),
        _analysis("v2", "제품·기술", score=50),
    ]
    docs = [
        _doc("v1", "먼저 나온 기사", published_at="2026-08-01T00:00:00+00:00"),
        _doc("v2", "나중에 나온 기사", published_at="2026-08-04T00:00:00+00:00"),
    ]

    stats = service.get_category_stats(WORKSPACE_ID, supabase=_db(rows, docs), now=NOW)

    by_id = {c.id: c for c in stats.categories}
    titles = [d.title for d in by_id["product-tech"].recent_documents]
    assert titles == ["나중에 나온 기사", "먼저 나온 기사"]


# ------------------------------------------------------------
# 직전 대비(분석 완료 기준) — 증가 폭 최대 / 신규 이슈 분류 (2026-08-12)
#
# 전일이 아니라 D-2 vs D-3을 쓴다. NOW가 KST 2026-08-05 12:00이므로
# 기준일 = 08-03, 비교일 = 08-02다.
# ------------------------------------------------------------

CURRENT_DAY = "2026-08-03T04:00:00+00:00"   # KST 08-03 13:00
BASELINE_DAY = "2026-08-02T04:00:00+00:00"  # KST 08-02 13:00


def _cmp_db(rows, docs, published_totals):
    """비교용 DB. published_totals는 커버리지 분모(발행 문서 전수)를 만든다."""
    db = _db(rows, docs)
    extra = [
        {"id": f"pad-{i}", "workspace_id": WORKSPACE_ID, "status": "active",
         "published_at": day, "created_at": day, "title": f"pad {i}",
         "canonical_url": f"https://www.example.com/pad{i}", "source_id": "s-hbm"}
        for day, n in published_totals.items()
        for i in range(n)
    ]
    db.tables["documents"] = docs + extra
    return db


def test_비교는_전일이_아니라_D2_D3다():
    """오늘치는 분석이 안 끝나 항상 감소로 나온다 — 굳은 두 날을 비교한다."""
    rows = [
        _analysis("v1", "시장·경영", score=50),
        _analysis("v2", "시장·경영", score=50),
        _analysis("v3", "제품·기술", score=50),
    ]
    docs = [
        _doc("v1", "기준일 기사 A", published_at=CURRENT_DAY),
        _doc("v2", "기준일 기사 B", published_at=CURRENT_DAY),
        _doc("v3", "비교일 기사", published_at=BASELINE_DAY),
    ]
    # 발행 총수를 맞춰 커버리지를 같게 만든다 (2/10 = 20%, 1/5 = 20%)
    db = _cmp_db(rows, docs, {CURRENT_DAY: 8, BASELINE_DAY: 4})

    stats = service.get_category_stats(WORKSPACE_ID, supabase=db, now=NOW)
    c = stats.comparison

    assert c.available is True
    assert str(c.current_date) == "2026-08-03"
    assert str(c.baseline_date) == "2026-08-02"
    assert c.max_increase_name == "시장·경영"
    assert c.max_increase_delta == 2


def test_비교일에_없던_분류가_신규로_잡힌다():
    rows = [_analysis("v1", "정책·규제", score=50), _analysis("v2", "제품·기술", score=50)]
    docs = [
        _doc("v1", "새로 생긴 분류", published_at=CURRENT_DAY),
        _doc("v2", "원래 있던 분류", published_at=BASELINE_DAY),
    ]
    db = _cmp_db(rows, docs, {CURRENT_DAY: 4, BASELINE_DAY: 4})

    c = service.get_category_stats(WORKSPACE_ID, supabase=db, now=NOW).comparison

    assert c.new_category_name == "정책·규제"
    assert c.new_category_count == 1


def test_분석_진행률이_크게_다르면_값을_만들지_않는다():
    """08-08처럼 배치가 실패한 날이 끼면 발행량이 아니라 처리 진척도를 표시하게 된다."""
    rows = [_analysis("v1", "시장·경영", score=50), _analysis("v2", "시장·경영", score=50)]
    docs = [
        _doc("v1", "기준일", published_at=CURRENT_DAY),
        _doc("v2", "비교일", published_at=BASELINE_DAY),
    ]
    # 기준일 1/2 = 50%, 비교일 1/100 = 1%  -> 49%p 차이
    db = _cmp_db(rows, docs, {CURRENT_DAY: 1, BASELINE_DAY: 99})

    c = service.get_category_stats(WORKSPACE_ID, supabase=db, now=NOW).comparison

    assert c.available is False
    assert "분석 진행률" in c.reason
    assert c.max_increase_name is None


def test_비교_대상일에_발행_문서가_없으면_값을_만들지_않는다():
    rows = [_analysis("v1", "시장·경영", score=50)]
    docs = [_doc("v1", "기준일만 있음", published_at=CURRENT_DAY)]
    db = _cmp_db(rows, docs, {CURRENT_DAY: 4})

    c = service.get_category_stats(WORKSPACE_ID, supabase=db, now=NOW).comparison

    assert c.available is False
    assert "발행된 문서가 없" in c.reason


def test_증가_폭_동점이면_항상_같은_분류를_고른다():
    """같은 데이터에 같은 답이 나와야 한다 — 새로고침마다 카드가 바뀌면 안 된다."""
    rows = [_analysis("v1", "제품·기술", score=50), _analysis("v2", "경쟁사", score=50)]
    docs = [
        _doc("v1", "제품 기사", published_at=CURRENT_DAY),
        _doc("v2", "경쟁사 기사", published_at=CURRENT_DAY),
    ]
    db = _cmp_db(rows, docs, {CURRENT_DAY: 8, BASELINE_DAY: 10})
    db.tables["documents"].append(
        {"id": "pad-b", "workspace_id": WORKSPACE_ID, "status": "active",
         "published_at": BASELINE_DAY, "created_at": BASELINE_DAY, "title": "pad",
         "canonical_url": "https://www.example.com/padb", "source_id": "s-hbm"}
    )

    results = {
        service.get_category_stats(WORKSPACE_ID, supabase=_cmp_db(rows, docs, {CURRENT_DAY: 8, BASELINE_DAY: 10}), now=NOW).comparison.max_increase_name
        for _ in range(3)
    }

    assert len(results) == 1  # 매번 같은 답


def test_커버리지_차_상한_경계():
    """상한을 조용히 바꾸지 못하게 잠근다.

    이 값은 통계가 아니라 운영 판단이라(service.COMPARISON_COVERAGE_GAP_MAX 주석)
    바꿀 때는 근거를 같이 남겨야 한다. 경계 양쪽을 테스트로 고정해 둔다.
    """
    assert service.COMPARISON_COVERAGE_GAP_MAX == 8.0

    rows = [
        _analysis("v1", "시장·경영", score=50),
        _analysis("v2", "시장·경영", score=50),
        _analysis("v3", "제품·기술", score=50),
        _analysis("v4", "제품·기술", score=50),
        _analysis("v5", "제품·기술", score=50),
    ]
    docs = [
        _doc("v1", "기준 1", published_at=CURRENT_DAY),
        _doc("v2", "기준 2", published_at=CURRENT_DAY),
        _doc("v3", "비교 1", published_at=BASELINE_DAY),
        _doc("v4", "비교 2", published_at=BASELINE_DAY),
        _doc("v5", "비교 3", published_at=BASELINE_DAY),
    ]
    # 기준일 2/20 = 10%, 비교일 3/20 = 15% -> 5%p 차이. 상한 안이라 통과한다.
    passing = service.get_category_stats(
        WORKSPACE_ID,
        supabase=_cmp_db(rows, docs, {CURRENT_DAY: 18, BASELINE_DAY: 17}),
        now=NOW,
    ).comparison
    assert passing.available is True

    # 분자는 그대로 두고 분모만 늘린다: 2/50 = 4% vs 3/20 = 15% -> 11%p. 막힌다.
    blocked = service.get_category_stats(
        WORKSPACE_ID,
        supabase=_cmp_db(rows, docs, {CURRENT_DAY: 48, BASELINE_DAY: 17}),
        now=NOW,
    ).comparison
    assert blocked.available is False
    assert "분석 진행률" in blocked.reason


def test_08_08급_사고는_완화_후에도_걸러진다():
    """상한을 8%p로 늦춘 뒤에도 막으려던 것(1.9% vs 18%, 약 15%p)은 여전히 막힌다."""
    rows = [_analysis("v1", "시장·경영", score=50), _analysis("v2", "시장·경영", score=50)]
    docs = [
        _doc("v1", "기준일", published_at=CURRENT_DAY),
        _doc("v2", "비교일", published_at=BASELINE_DAY),
    ]
    # 기준일 1/53 = 1.9%, 비교일 1/6 = 16.7%
    c = service.get_category_stats(
        WORKSPACE_ID,
        supabase=_cmp_db(rows, docs, {CURRENT_DAY: 52, BASELINE_DAY: 5}),
        now=NOW,
    ).comparison

    assert c.available is False

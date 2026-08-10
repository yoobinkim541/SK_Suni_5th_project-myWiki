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
              created_at="2026-08-04T00:00:00+00:00", workspace_id=WORKSPACE_ID,
              core_summary=None, quoted=None):
    return {
        "document_version_id": version_id,
        "primary_category": category,
        "reliability_score": score,
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

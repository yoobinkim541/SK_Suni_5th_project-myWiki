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
        self._limit = None
        self._range = None

    def select(self, _fields):
        return self

    def eq(self, field, value):
        self.filters.append(("eq", field, value))
        return self

    def gte(self, field, value):
        self.filters.append(("gte", field, value))
        return self

    # in_/limit은 키워드·뉴스 조회가 쓴다 (documents_by_version이 청크로 .in_() 한다).
    def in_(self, field, values):
        self.filters.append(("in", field, [str(v) for v in values]))
        return self

    def order(self, _column, desc=False):
        return self

    def limit(self, n):
        self._limit = n
        return self

    # 페이지 조회(_fetch_all)가 쓴다. [start, end] 양끝 포함으로 PostgREST와 같다.
    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        rows = self.rows
        for op, field, value in self.filters:
            if op == "eq":
                rows = [r for r in rows if r.get(field) == value]
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


# ---------------------------------------------------------------------------
# 오늘의 키워드 · 최신 뉴스
# ---------------------------------------------------------------------------


def _analysis(version_id, category, *, created_at="2026-08-04T00:00:00+00:00",
              workspace_id=WORKSPACE_ID, core_summary=None, quoted=None):
    return {
        "document_version_id": version_id,
        "primary_category": category,
        "created_at": created_at,
        "workspace_id": workspace_id,
        "core_summary": core_summary,
        "summary_evidence_refs": [{"quoted_text": quoted}] if quoted else [],
    }


def _news_db(analyses, documents, sources=None):
    """분석 행 -> document_versions -> documents 를 잇는 최소 구성."""
    return FakeSupabase({
        "document_analysis_results": analyses,
        "document_versions": [
            {"id": a["document_version_id"], "document_id": f"doc-{a['document_version_id']}"}
            for a in analyses
        ],
        "documents": documents,
        "sources": sources or [],
    })


def _document(version_id, title, *, url="https://www.etnews.com/1",
              published_at="2026-08-04T00:00:00+00:00", source_id=None):
    return {
        "id": f"doc-{version_id}",
        "title": title,
        "canonical_url": url,
        "published_at": published_at,
        "source_id": source_id,
        "workspace_id": WORKSPACE_ID,
    }


def test_키워드는_제목에서_뽑고_횟수를_같이_준다():
    """수집 질의어가 아니라 제목 사전 매칭이다 — 화면 문구가 '언급 순'이다."""
    analyses = [_analysis("v1", "제품·기술"), _analysis("v2", "제품·기술")]
    documents = [
        _document("v1", "SK하이닉스 HBM 양산 확대"),
        _document("v2", "HBM 수요 급증"),
    ]

    result = service.get_dashboard_keywords(
        WORKSPACE_ID, supabase=_news_db(analyses, documents), now=NOW
    )

    by_word = {k.word: k.count for k in result.keywords}
    assert by_word["HBM"] == 2  # 제목 두 건에 등장


def test_키워드는_카테고리별_사전으로만_매칭한다():
    """
    CATEGORY_KEYWORDS가 카테고리별 사전이라, 문서의 primary_category에 맞는 사전으로만
    매칭해야 오탐이 안 난다. 사전을 전부 합쳐 돌리면 엉뚱한 낱말이 붙는다.
    """
    analyses = [_analysis("v1", "정책·규제")]
    documents = [_document("v1", "HBM 수출통제 논의")]

    result = service.get_dashboard_keywords(
        WORKSPACE_ID, supabase=_news_db(analyses, documents), now=NOW
    )

    words = {k.word for k in result.keywords}
    assert "HBM" not in words  # 제목에 있어도 정책·규제 사전에는 없다


def test_키워드가_없으면_빈_배열이다():
    result = service.get_dashboard_keywords(
        WORKSPACE_ID, supabase=_news_db([], []), now=NOW
    )

    assert result.keywords == []


def test_뉴스_태그는_칩과_같은_사전을_쓴다():
    """
    이게 안 맞으면 칩을 눌렀을 때 빈 화면이 된다. 화면 필터(newsMatchesInterest)가
    title+quote+category+sourceLabel+tags 텍스트 매칭이라, 칩의 낱말이 어느 카드의
    tags에도 없으면 걸리는 게 없다.
    """
    analyses = [_analysis("v1", "제품·기술")]
    documents = [_document("v1", "SK하이닉스 HBM 양산 확대")]
    db = _news_db(analyses, documents)

    keywords = service.get_dashboard_keywords(WORKSPACE_ID, supabase=db, now=NOW)
    news = service.get_dashboard_news(WORKSPACE_ID, supabase=_news_db(analyses, documents), now=NOW)

    chip_words = {k.word for k in keywords.keywords}
    assert chip_words  # 칩이 비어 있으면 이 테스트가 무의미하다
    assert chip_words & set(news.items[0].tags)


def test_뉴스_tags는_항상_배열이다():
    """DashboardPage가 n.tags.map()을 가드 없이 부른다. None이면 화면이 죽는다."""
    analyses = [_analysis("v1", "제품·기술")]
    documents = [_document("v1", "사전에 없는 낱말만 있는 제목")]

    news = service.get_dashboard_news(
        WORKSPACE_ID, supabase=_news_db(analyses, documents), now=NOW
    )

    assert news.items[0].tags == []


def test_인용문이_없으면_빈_문자열이다():
    """합성하지 않는다. 화면이 빈 인용문 블록을 접는다."""
    analyses = [_analysis("v1", "제품·기술")]
    documents = [_document("v1", "HBM 양산")]

    news = service.get_dashboard_news(
        WORKSPACE_ID, supabase=_news_db(analyses, documents), now=NOW
    )

    assert news.items[0].quote == ""


def test_인용문은_quoted_text_core_summary_순으로_고른다():
    analyses = [
        _analysis("v1", "제품·기술", quoted="원문 인용", core_summary="합성 요약"),
        _analysis("v2", "경쟁사", core_summary="요약만 있음"),
    ]
    documents = [
        _document("v1", "기사1", published_at="2026-08-04T02:00:00+00:00"),
        _document("v2", "기사2", published_at="2026-08-04T01:00:00+00:00"),
    ]

    news = service.get_dashboard_news(
        WORKSPACE_ID, supabase=_news_db(analyses, documents), now=NOW
    )

    assert news.items[0].quote == "원문 인용"
    assert news.items[1].quote == "요약만 있음"


def test_뉴스는_발행일_내림차순이다():
    analyses = [_analysis("v1", "제품·기술"), _analysis("v2", "경쟁사")]
    documents = [
        _document("v1", "오래된 기사", published_at="2026-08-01T00:00:00+00:00"),
        _document("v2", "최신 기사", published_at="2026-08-04T00:00:00+00:00"),
    ]

    news = service.get_dashboard_news(
        WORKSPACE_ID, supabase=_news_db(analyses, documents), now=NOW
    )

    assert [i.title for i in news.items] == ["최신 기사", "오래된 기사"]


def test_같은_문서의_분석_행이_여러_개여도_카드는_하나다():
    """재수집으로 버전이 늘면 분석 행이 여러 개 생긴다. 안 접으면 같은 기사가 두 장이 된다."""
    analyses = [
        _analysis("v1", "제품·기술", created_at="2026-08-03T00:00:00+00:00"),
        _analysis("v1", "제품·기술", created_at="2026-08-04T00:00:00+00:00"),
    ]
    documents = [_document("v1", "같은 기사")]

    news = service.get_dashboard_news(
        WORKSPACE_ID, supabase=_news_db(analyses, documents), now=NOW
    )

    assert len(news.items) == 1


def test_공시는_is_doc이_참이다():
    """화면이 !isDoc으로 기사만 거른다. 현재 이 경로에 공시가 거의 안 들어오지만 계약은 지킨다."""
    analyses = [_analysis("v1", "공급망·생산")]
    documents = [_document("v1", "설비투자 공시", url="https://dart.fss.or.kr/1",
                           source_id="src-dart")]
    sources = [{"id": "src-dart", "source_type": "disclosure", "name": "DART",
                "config": {}, "base_url": "", "workspace_id": WORKSPACE_ID}]

    news = service.get_dashboard_news(
        WORKSPACE_ID, supabase=_news_db(analyses, documents, sources), now=NOW
    )

    assert news.items[0].is_doc is True


def test_다른_워크스페이스_문서는_안_보인다():
    analyses = [_analysis("v1", "제품·기술", workspace_id="ws-other")]
    documents = [_document("v1", "남의 기사")]
    documents[0]["workspace_id"] = "ws-other"

    news = service.get_dashboard_news(
        WORKSPACE_ID, supabase=_news_db(analyses, documents), now=NOW
    )
    keywords = service.get_dashboard_keywords(
        WORKSPACE_ID, supabase=_news_db(analyses, documents), now=NOW
    )

    assert news.items == []
    assert keywords.keywords == []

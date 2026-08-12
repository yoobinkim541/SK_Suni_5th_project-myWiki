"""
분석 행 -> 화면에 내보낼 문서 정보로 옮기는 공통 계층.

categories/service.py에 private로 있던 것을 그대로 옮겼다. 로직은 바꾸지 않았다.
대시보드 '최신 뉴스'(dashboard/service.py)가 같은 변환을 필요로 하는데,
categories/service.py는 dashboard/service.py를 import하고 있어서(RELIABILITY_* 상수)
역방향으로 부르면 순환이 된다. 복제하면 아래 .in_() 청크 분할 같은 것을 두 곳에서
고치게 되는데, 그 버그는 2026-08-07에 실제로 /categories/stats를 500으로 만들었다.

이 모듈은 dashboard를 import하지 않는다. 그래야 양쪽이 안전하게 쓴다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from supabase import Client

from ..pipeline_common.text import has_readable_text
from ..pipeline_common.titles import normalize_title

# 카드에 말줄임 처리가 없어서(globals.css .top-issue) 긴 제목이 오면 카드가 세로로
# 늘어나고 같은 행 카드까지 같이 늘어난다. 백엔드에서 잘라 보낸다.
TOP_ISSUE_MAX_LEN = 80

# 모달 카드가 길어지지 않게 자른다. quoted_text는 최대 500자까지 올 수 있다.
QUOTE_MAX_LEN = 200

_IN_CLAUSE_CHUNK_SIZE = 150
"""
.in_() 한 번에 넣을 id 개수 상한. id 목록이 수백 개가 되면 전부 한 URL의 .in_(...)에
담을 때 PostgREST가 400 Bad Request로 거부한다(2026-08-07 확인: document_analysis_results가
656건으로 늘면서 documents_by_version()이 크래시 -> /categories/stats 500).
src/analysis/repository.py, src/pipeline_common/repository.py의 동일 상수와 같은 값.
"""

ANALYSIS_WINDOW_DAYS = 7
"""
카테고리 현황·대시보드가 '최근'이라고 부르는 기간. 두 화면이 같은 값을 쓴다
(dashboard/service.py의 WINDOW_DAYS가 이걸 재노출한다).

일일 리포트의 24시간(report/candidate_provider.get_report_time_range)을 따라가지
않는다. 리포트는 '어제 하루에 무슨 일이 있었나'를 묻고, 이 두 화면은 분포와 추세를
본다 — 표본이 1/7로 줄면 카드 배지가 하루 단위로 요동친다. 목적이 다르다.
"""

PREFILTER_MARGIN_DAYS = 8
"""
created_at prefilter에 주는 여유. 아래 fetch_analysis_rows 참조.

기사는 발행된 뒤에 수집되므로 보통 published_at <= created_at이고, 그러면
`created_at >= 창시작`은 `published_at >= 창시작`의 무손실 상위집합이 된다.
문제는 소스가 미래 시각을 줄 때다 — 그때만 부등식이 깨지고, 발행일 창 안인데
prefilter에서 떨어지는 행이 생긴다. 놓치지 않으려면 마진이 그 **앞선 폭**을
덮어야 한다.

2026-08-10 실측 (문서 1,386건): published_at이 created_at보다 앞선 문서가 5건,
앞선 폭은 중앙 10.2시간 / 최대 175.4시간(7.3일)이었다. 처음에 1일로 잡았던 값은
그 5건 중 2건을 놓친다. 최대치에 여유를 붙여 8일로 둔다.

비용은 같은 날 측정으로 0이다 — 마진 1·8·14·30일 모두 prefilter 행 수가 1,386으로
같았다(분석 행 자체가 최근 며칠에 몰려 있다). 나중에 분석 백로그가 풀려 오래된
행이 쌓이면 이 값이 조회량에 그대로 반영되므로 그때 다시 잰다.
"""

_PAGE_SIZE = 1000


def chunked(items: list, size: int = _IN_CLAUSE_CHUNK_SIZE) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def window_start(now: datetime, *, days: int = ANALYSIS_WINDOW_DAYS) -> datetime:
    """화면이 보여줄 발행일 창의 시작."""
    return now - timedelta(days=days)


def fetch_analysis_rows(
    db: Client,
    workspace_id: str,
    *,
    columns: str,
    since: datetime,
    limit: int = 5000,
) -> list[dict]:
    """분석 행을 페이지로 나눠 전건 받는다.

    ⚠ PostgREST는 한 응답에 1,000행까지만 주고 넘으면 **에러도 경고도 없이 자른다.**
    이 계층은 받은 목록을 len()으로 세고 평균을 내므로 잘리면 KPI가 조용히 틀린다.
    이 저장소는 같은 버그에 세 번 당했다(#176 수집 문서 수, #188 오늘 증가분,
    #259 카테고리 집계). 목록을 세는 코드는 반드시 이 함수를 거친다.

    `since`는 **created_at** 기준이다 — published_at 창의 prefilter일 뿐 최종 필터가
    아니다. 최종 판정은 문서를 붙인 뒤 in_published_window()가 한다. 이유는
    PREFILTER_MARGIN_DAYS와 in_published_window() 독스트링 참조.
    """
    since_iso = since.isoformat()
    rows: list[dict] = []
    offset = 0
    while offset < limit:
        page = (
            db.table("document_analysis_results")
            .select(columns)
            .eq("workspace_id", workspace_id)
            .gte("created_at", since_iso)
            # 순서를 고정해야 페이지가 겹치거나 빠지지 않는다.
            .order("id")
            .range(offset, min(offset + _PAGE_SIZE - 1, limit - 1))
            .execute()
            .data
        ) or []
        rows.extend(page)
        if len(page) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
    return rows


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    # DB 컬럼은 timestamptz지만 Fake/구 데이터에 naive 값이 섞일 수 있다. 창 비교가
    # TypeError로 죽지 않게 UTC로 본다.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def effective_published_at(document: dict) -> datetime | None:
    """문서의 발행 시각. 없으면 수집 시각으로 대체한다.

    published_at이 비는 소스가 있다(공시·수동 업로드). 그런 문서를 창 밖으로
    떨어뜨리면 화면에서 통째로 사라지므로, 그 경우에만 documents.created_at을
    대신 쓴다 — 수집 시각은 발행 시각의 상한이라 '실제보다 최신으로 보이는' 쪽으로만
    틀리고, 그건 원래 created_at 기준이 하던 것과 같다.
    """
    return parse_timestamp(document.get("published_at")) or parse_timestamp(
        document.get("created_at")
    )


def in_published_window(document: dict, start: datetime) -> bool:
    """문서가 발행일 기준 창 안인가.

    집계 기준을 documents.published_at으로 잡는 이유: 분석은 수집보다 뒤처지므로
    (2026-08-10 실측: 08-08 발행분 369건 중 7건만 분석됨) created_at으로 자르면
    3주 전 기사라도 어제 분석됐다는 이유로 '최근 7일'에 들어온다. 2026-08-10 실측
    1,306행 중 130행(10%)이 그런 행이었다.

    ⚠ 이 기준으로 바꾸면 분석 백로그가 화면에 드러난다 — 최근 며칠이 희박해 보인다.
    가려져 있던 것이 보이는 것이지 집계가 나빠진 게 아니다.

    발행 시각을 모르는 문서는 남긴다(effective_published_at 참조).
    """
    published = effective_published_at(document)
    if published is None:
        return True
    return published >= start


def truncate(text: str, max_len: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def display_title(text: str) -> str:
    """화면에 내보낼 제목 — 매체명 꼬리표를 벗기고 길이를 자른다.

    preprocess가 documents.title을 교정하지만(pipeline_common.titles), 그건 그 수정이
    들어간 뒤 정제된 문서부터다. 그 전에 수집된 문서는 DB에 '기사제목 - 매체명'이
    그대로 남아 있어서 표시 시점에도 한 번 더 벗긴다. 멱등이라 두 번 걸어도 안전하다.
    """
    return truncate(normalize_title(text or ""), TOP_ISSUE_MAX_LEN)


def source_label(canonical_url: str | None) -> str:
    """canonical_url -> 표시용 출처. 'www.'만 떼고 도메인을 그대로 쓴다.

    sources.name을 쓰지 않는 이유: 그건 'Google RSS - SK하이닉스' 같은 우리 수집
    설정 이름이라 사용자에게 "출처: Google RSS"로 보인다. 도메인이 실제 매체에 가깝다.
    다만 v.daum.net 같은 중계 사이트는 그대로 노출된다 — 도메인->매체명 사전이
    있어야 해결되는데 관측된 도메인이 120종이라 이번 범위 밖이다.
    """
    host = urlparse(canonical_url or "").netloc
    return host[4:] if host.startswith("www.") else host


def quote_for(row: dict) -> str:
    """화면에 보여줄 인용문. quoted_text -> core_summary -> 빈 문자열.

    summary_evidence_refs[].quoted_text는 기사 원문에서 그대로 뽑은 인용이라
    합성 요약인 core_summary보다 "인용문"에 맞는다. 둘 다 importance 단계 산출물이라
    커버리지가 낮다(2026-08-07 실측 8%) — 없으면 빈 문자열을 준다.

    비어 있을 때 본문 첫 문장 같은 걸로 채우지 않는다. 그건 인용이 아니라 원문 조각이고,
    인용문 자리에 놓이는 순간 근거 없는 인용이 된다(절대원칙 1·2).

    빈 값 판정에 .strip()이 아니라 has_readable_text를 쓴다. 차단 페이지를 본문으로
    저장해버린 문서는 인용문이 `![](403.jpg)`인데, 이건 공백이 아니라서 .strip()을
    통과해 카드에 그대로 노출됐다(2026-08-12 se-cu.com). 수집·정제 쪽을 막아도 이미
    저장된 행은 남으므로 화면에서도 걸러야 한다.
    """
    refs = row.get("summary_evidence_refs") or []
    if isinstance(refs, list):
        for ref in refs:
            if isinstance(ref, dict) and has_readable_text(ref.get("quoted_text") or ""):
                return truncate(ref["quoted_text"], QUOTE_MAX_LEN)
    core_summary = row.get("core_summary") or ""
    return truncate(core_summary, QUOTE_MAX_LEN) if has_readable_text(core_summary) else ""


def documents_by_version(
    db: Client, workspace_id: str, version_ids: list[str]
) -> dict[str, dict]:
    """document_version_id -> documents 행(title/canonical_url/published_at/created_at).

    document_versions에는 workspace_id 컬럼이 없다. 그래서 documents 조회에
    workspace_id를 반드시 직접 건다 — 여기가 격리가 성립하는 유일한 지점이다.

    sources는 조인하지 않는다. 관련 뉴스의 출처는 sources.name('Google RSS - SK하이닉스'
    같은 수집 설정 이름)이 아니라 canonical_url의 도메인을 쓰기 때문이다.
    """
    if not version_ids:
        return {}

    versions: list[dict] = []
    for chunk in chunked(version_ids):
        versions.extend(
            db.table("document_versions")
            .select("id, document_id")
            .in_("id", chunk)
            .execute()
            .data
        )
    document_ids = [str(v["document_id"]) for v in versions if v.get("document_id")]
    if not document_ids:
        return {}

    documents: list[dict] = []
    for chunk in chunked(document_ids):
        documents.extend(
            db.table("documents")
            # created_at은 published_at이 빈 문서의 대체값이다(effective_published_at).
            .select(
                "id, title, canonical_url, published_at, created_at, source_id, "
                "disclosure_type_code, disclosure_type_name"
            )
            .eq("workspace_id", workspace_id)
            .in_("id", chunk)
            .execute()
            .data
        )
    by_document = {str(d["id"]): d for d in documents}

    # 다른 workspace의 문서는 위 조회에서 빠지므로 여기서 자연히 제외된다.
    return {
        str(v["id"]): by_document[str(v["document_id"])]
        for v in versions
        if str(v.get("document_id")) in by_document
    }


def sources_by_id(db: Client, workspace_id: str) -> dict[str, dict]:
    """수집 소스 전체. 워크스페이스당 10여 개라 통째로 받아 파이썬에서 대조한다."""
    rows = (
        db.table("sources")
        .select("id, name, source_type, config, base_url")
        .eq("workspace_id", workspace_id)
        .execute()
        .data
    )
    return {str(r["id"]): r for r in rows}


def unique_documents(group: list[dict], documents: dict[str, dict]) -> dict[str, dict]:
    """그룹을 문서 단위로 접는다 — document_id -> 그 문서의 최신 분석 행.

    분석 행과 문서는 1:1이 아니다. 재수집으로 버전이 늘면 같은 문서에 분석 행이
    여러 개 생긴다(2026-08-05 실측 459행 -> 고유 275문서). 이걸 안 접으면 카드의
    건수가 실제 기사 수보다 부풀고, 원그래프 조각 합과도 어긋난다.

    한 문서에서는 created_at이 가장 최근인 행을 남긴다 — 인용문이 최신 버전
    기준이 되게 하기 위해서다.
    """
    latest: dict[str, dict] = {}
    for row in group:
        document = documents.get(str(row.get("document_version_id")))
        if document is None:
            continue
        key = str(document["id"])
        current = latest.get(key)
        if current is None or str(row.get("created_at") or "") > str(
            current["row"].get("created_at") or ""
        ):
            latest[key] = {"row": row, "document": document}
    return latest

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

from urllib.parse import urlparse

from supabase import Client

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


def chunked(items: list, size: int = _IN_CLAUSE_CHUNK_SIZE) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


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
    """
    refs = row.get("summary_evidence_refs") or []
    if isinstance(refs, list):
        for ref in refs:
            if isinstance(ref, dict) and (ref.get("quoted_text") or "").strip():
                return truncate(ref["quoted_text"], QUOTE_MAX_LEN)
    return truncate(row.get("core_summary") or "", QUOTE_MAX_LEN)


def documents_by_version(
    db: Client, workspace_id: str, version_ids: list[str]
) -> dict[str, dict]:
    """document_version_id -> documents 행(document_id/title/canonical_url/published_at).

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
            .select("id, title, canonical_url, published_at, source_id")
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

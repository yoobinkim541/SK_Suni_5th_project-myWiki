"""
원문 문서(documents/document_versions) 제목+본문 관련도 검색.

Agent가 위키에 근거가 없을 때(_document_answer) 수집된 원문(뉴스+DART, 위키 발행
여부 무관)에서 근거를 찾는 두 번째 그라운딩 단계가 쓴다.

src/wiki/repository.py::search_wiki_contexts()와 같은 스코어링(title 60% + 본문
30% + coverage 10% 토큰 오버랩)을 documents/document_versions에 적용한다. 위키
전용 모듈(src/wiki/)에 두지 않는 이유: documents/document_versions는 위키가
아니라 파이프라인 공용 테이블이고, pipeline_common이 이미 그 접근을 담당하는
자리다. wiki/repository.py를 import하지 않는다 — 위키 모듈이 pipeline_common을
참조하는 건 몰라도 반대 방향은 레이어 위반이라, 스코어링 로직은 이 모듈에
독립적으로 둔다(중복이지만 의도적 — 약 20줄).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from supabase import Client

from ..analysis.repository import get_supabase
from . import storage

DEFAULT_SCAN_LIMIT = 50
"""
스캔할 최근 문서 수 상한. search_wiki_contexts의 DEFAULT_MAX_PAGE_SCAN(30)과 같은
이유 — 후보마다 storage에서 markdown을 내려받아 스코어링하므로 무한정 스캔하면
느려진다. 50은 .in_() 청크 분할 임계치(150, src/analysis/repository.py의
_IN_CLAUSE_CHUNK_SIZE)보다 한참 작아 이 모듈의 .in_() 호출은 청크 분할이 필요 없다.
"""

_URL_PATTERN = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_NON_WORD_PATTERN = re.compile(r"[\W_]+", re.UNICODE)


@dataclass
class DocumentSearchHit:
    document_version_id: str
    title: str
    score: float


@dataclass
class DocumentDetail:
    document_version_id: str
    title: str
    markdown: str
    canonical_url: str | None
    source_name: str | None
    published_at: str | None


def search_documents(
    workspace_id: str, query: str, limit: int = 5, *, supabase: Client | None = None
) -> list[DocumentSearchHit]:
    db = supabase or get_supabase()

    document_rows = (
        db.table("documents")
        .select("id, title")
        .eq("workspace_id", workspace_id)
        .eq("status", "active")
        .order("published_at", desc=True)
        .limit(DEFAULT_SCAN_LIMIT)
        .execute()
        .data
    )
    if not document_rows:
        return []
    titles_by_document_id = {row["id"]: row["title"] for row in document_rows}
    document_ids = list(titles_by_document_id.keys())

    version_rows = (
        db.table("document_versions")
        .select("id, document_id, version_no, markdown_object_key")
        .in_("document_id", document_ids)
        .execute()
        .data
    )
    latest_version_by_document: dict[str, dict] = {}
    for row in version_rows:
        current = latest_version_by_document.get(row["document_id"])
        if current is None or row["version_no"] > current["version_no"]:
            latest_version_by_document[row["document_id"]] = row

    query_token_set = _tokenize_search_text(query)
    if not query_token_set:
        return []

    hits: list[DocumentSearchHit] = []
    for document_id, version in latest_version_by_document.items():
        title = titles_by_document_id[document_id]
        bucket, path = storage.split_key(version["markdown_object_key"])
        markdown_bytes = db.storage.from_(bucket).download(path)
        content = markdown_bytes.decode("utf-8")

        score = _score_document(title=str(title), content=content, query_token_set=query_token_set)
        if score is None:
            continue
        hits.append(DocumentSearchHit(document_version_id=str(version["id"]), title=str(title), score=score))

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:limit]


def get_document_detail(
    workspace_id: str, document_version_id: str, *, supabase: Client | None = None
) -> DocumentDetail | None:
    raise NotImplementedError  # Task 2에서 구현


def _score_document(*, title: str, content: str, query_token_set: set[str]) -> float | None:
    title_tokens = _tokenize_search_text(title)
    body_tokens = _tokenize_search_text(content)

    title_overlap = len(title_tokens & query_token_set)
    body_overlap = len(body_tokens & query_token_set)
    total_overlap = len((title_tokens | body_tokens) & query_token_set)
    if total_overlap == 0:
        return None

    query_size = len(query_token_set)
    return min(
        1.0,
        (title_overlap / query_size * 0.6)
        + (body_overlap / query_size * 0.3)
        + (total_overlap / query_size * 0.1),
    )


def _normalize_search_text(value: str | None) -> str:
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", value).lower()
    normalized = _URL_PATTERN.sub(" ", normalized)
    normalized = _NON_WORD_PATTERN.sub(" ", normalized)
    normalized = " ".join(normalized.split())
    return normalized.strip()


def _tokenize_search_text(value: str | None) -> set[str]:
    normalized = _normalize_search_text(value)
    if not normalized:
        return set()
    tokens: set[str] = set()
    for token in normalized.split():
        if len(token) > 1 or any(character.isdigit() for character in token):
            tokens.add(token)
    return tokens

"""
데이터 계약 (명세 §2).

- §2-1 DB 무관 계층: RawFetchResult / ParsedContent
  순수 데이터이고 DB·Storage를 모른다. 스키마가 바뀌어도 불변.
- §2-2 DB 의존 계층: CollectRequest / CollectedDocument / ProcessedDocument / DocumentRef
  각 필드 주석의 `table.column`이 대응 컬럼이다. [파생]은 DB 대응이 없는 값.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, HttpUrl

# ------------------------------------------------------------
# §2-1 DB 무관 계층
# ------------------------------------------------------------


@dataclass(frozen=True)
class RawFetchResult:
    """[파생] 외부 소스에서 가져온 원문 그대로. DB 대응 없음."""

    source_name: str
    url: str
    fetched_at: datetime
    content_type: str  # 'text/html' | 'application/pdf' | 'application/json'
    body: bytes
    title_hint: str | None = None
    published_at_hint: datetime | None = None


@dataclass(frozen=True)
class ParsedContent:
    """[파생] Markdown 정제 결과. DB 대응 없음."""

    markdown: str
    content_hash: str  # SHA-256 소문자 hex 64자. 계산 규칙은 preprocessing.parsers 참조
    title: str
    published_at: datetime | None
    language: str | None  # BCP-47 소문자 2자 ('ko' | 'en'), 판별 실패 시 None
    parser_version: str  # '{parser}-v{major}.{minor}' 예: 'html-v1.1'


# ------------------------------------------------------------
# §2-2 DB 의존 계층
# ------------------------------------------------------------


class CollectRequest(BaseModel):
    """[파생] collect() 입력."""

    workspace_id: UUID  # documents.workspace_id / sources.workspace_id
    source_id: UUID  # sources.id
    since: datetime | None = None  # [파생] 이 시각 이후 발행분만
    limit: int | None = None  # [파생] 1회 최대 수집 건수
    requested_by: UUID | None = None  # pipeline_jobs.requested_by (배치는 None)


class CollectedDocument(BaseModel):
    """수집 1건 결과. documents 행 생성 + raw 업로드 완료 상태."""

    workspace_id: UUID  # documents.workspace_id
    document_id: UUID  # documents.id
    source_id: UUID | None  # documents.source_id
    title: str  # documents.title
    canonical_url: HttpUrl | None  # documents.canonical_url
    published_at: datetime | None  # documents.published_at
    status: str  # documents.status
    raw_object_key: str  # [파생] collect job의 result에 기록된 정본 경로
    content_type: str  # [파생] 정제 단계의 파서 선택용
    collect_job_id: UUID  # pipeline_jobs.id (raw 경로 인계 근거)
    is_new_document: bool  # [파생] False면 기존 문서 재수집


class ProcessedDocument(BaseModel):
    """정제 1건 결과. documents + document_versions 조인 형태."""

    workspace_id: UUID  # documents.workspace_id (조인)
    document_id: UUID  # documents.id
    document_version_id: UUID  # document_versions.id  <- 하류 근거 ID
    source_id: UUID | None  # documents.source_id
    title: str  # documents.title
    canonical_url: HttpUrl | None  # documents.canonical_url
    published_at: datetime | None  # documents.published_at
    version_no: int  # document_versions.version_no
    content_hash: str  # document_versions.content_hash
    raw_object_key: str | None  # document_versions.raw_object_key
    markdown_object_key: str  # document_versions.markdown_object_key
    parser_version: str | None  # document_versions.parser_version
    language: str | None  # document_versions.language
    created_at: datetime  # document_versions.created_at
    is_new_version: bool  # [파생] False면 동일 해시 -> 기존 버전 반환


class DocumentRef(BaseModel):
    """[파생·신설] 하류가 출처 라벨을 만들 때 쓰는 조회 결과. 명세 §3-7 참조."""

    document_version_id: UUID  # document_versions.id
    document_id: UUID  # documents.id
    title: str  # documents.title
    canonical_url: HttpUrl | None  # documents.canonical_url
    published_at: datetime | None  # documents.published_at
    source_name: str | None  # sources.name (조인)
    source_type: str | None  # sources.source_type (조인)
    version_no: int  # document_versions.version_no

"""
하류 제공용 조회 헬퍼 (명세 §3-6, §3-7).

이 두 함수는 조회 전용이라 예외를 던진다. 배치 실패 기록 대상이 아니다 (명세 §1-3).

document_versions에는 workspace_id 컬럼이 없다. 조인 없이 조회하면 다른
workspace 데이터가 새어 나오고, 배치는 RLS를 우회하므로 DB가 막아주지 않는다.
그래서 두 함수 모두 workspace_id를 인자로 받는다.
"""
from __future__ import annotations

from uuid import UUID

from . import repository, storage
from .models import DocumentRef


def get_markdown(document_version_id: UUID, workspace_id: UUID) -> str:
    """
    정제된 Markdown 본문을 반환. analysis 파트가 사용한다.

    select dv.markdown_object_key
    from document_versions dv
    join documents d on d.id = dv.document_id
    where dv.id = :document_version_id and d.workspace_id = :workspace_id;

    행이 없거나 파일이 없으면 FileNotFoundError.
    """
    version = repository.get_version(document_version_id)
    if version is None:
        raise FileNotFoundError(f"document_version을 찾을 수 없다: {document_version_id}")

    # 조인 대신 2단계 조회. 다른 workspace의 문서면 여기서 빈 dict가 된다.
    documents = repository.get_documents_by_ids([version["document_id"]], workspace_id)
    if not documents:
        raise FileNotFoundError(
            f"document_version {document_version_id}은 workspace {workspace_id}에 속하지 않는다"
        )

    object_key = version.get("markdown_object_key")
    if not object_key:
        raise FileNotFoundError(f"markdown_object_key가 비어 있다: {document_version_id}")

    try:
        data = storage.download(object_key)
    except FileNotFoundError:
        raise
    except Exception as exc:  # noqa: BLE001 - Storage 클라이언트 예외 종류가 버전마다 다르다
        raise FileNotFoundError(f"Storage에서 읽을 수 없다: {object_key} ({exc})") from exc

    if data is None:
        raise FileNotFoundError(f"Storage에서 읽을 수 없다: {object_key}")
    return data.decode("utf-8")


def get_document_refs(
    document_version_ids: list[UUID],
    workspace_id: UUID,
) -> list[DocumentRef]:
    """
    document_version_id 목록 -> 출처 메타 일괄 조회. 화면 출처 라벨용이다.

    select dv.id, dv.version_no, d.id as document_id, d.title,
           d.canonical_url, d.published_at, s.name as source_name, s.source_type
    from document_versions dv
    join documents d on d.id = dv.document_id
    left join sources s on s.id = d.source_id
    where dv.id = any(:document_version_ids) and d.workspace_id = :workspace_id;

    N+1을 피하려고 목록 단위로 조회한다.
    입력에 없거나 다른 workspace의 id는 결과에서 제외되므로 길이가 다를 수 있다.
    """
    if not document_version_ids:
        return []

    versions = repository.get_versions_by_ids(document_version_ids)
    if not versions:
        return []

    documents = repository.get_documents_by_ids(
        [v["document_id"] for v in versions], workspace_id
    )
    source_ids = {
        d["source_id"] for d in documents.values() if d.get("source_id")
    }
    sources = repository.get_sources_by_ids([UUID(sid) for sid in source_ids], workspace_id)

    by_version_id = {str(v["id"]): v for v in versions}
    refs: list[DocumentRef] = []
    for version_id in document_version_ids:  # 입력 순서를 유지한다
        version = by_version_id.get(str(version_id))
        if version is None:
            continue
        document = documents.get(str(version["document_id"]))
        if document is None:  # 다른 workspace의 문서
            continue
        source = sources.get(str(document.get("source_id"))) if document.get("source_id") else None
        refs.append(
            DocumentRef(
                document_version_id=version["id"],
                document_id=document["id"],
                title=document["title"],
                canonical_url=document.get("canonical_url"),
                published_at=document.get("published_at"),
                source_name=source["name"] if source else None,
                source_type=source["source_type"] if source else None,
                version_no=version["version_no"],
            )
        )
    return refs

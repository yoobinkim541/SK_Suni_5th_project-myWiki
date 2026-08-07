"""src/pipeline_common/document_search.py 단위 테스트 — DB/Storage는 FakeSupabase로 대체한다."""
from __future__ import annotations

from src.pipeline_common import document_search

WORKSPACE_ID = "ws-1"


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeStorageBucket:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects

    def download(self, path: str) -> bytes:
        if path not in self.objects:
            raise FileNotFoundError(path)
        return self.objects[path]


class FakeStorage:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects

    def from_(self, _bucket: str) -> FakeStorageBucket:
        return FakeStorageBucket(self.objects)


class FakeTable:
    def __init__(self, rows: list[dict]):
        self.rows = [dict(r) for r in rows]
        self.eq_filters: list[tuple[str, object]] = []
        self.in_filters: list[tuple[str, set[object]]] = []
        self.ordering: list[tuple[str, bool]] = []
        self.row_limit: int | None = None
        self._want_single = False

    def select(self, _fields: str) -> "FakeTable":
        return self

    def eq(self, field: str, value: object) -> "FakeTable":
        self.eq_filters.append((field, value))
        return self

    def in_(self, field: str, values: list[object]) -> "FakeTable":
        self.in_filters.append((field, set(values)))
        return self

    def order(self, field: str, desc: bool = False) -> "FakeTable":
        self.ordering.append((field, desc))
        return self

    def limit(self, value: int) -> "FakeTable":
        self.row_limit = value
        return self

    def maybe_single(self) -> "FakeTable":
        self._want_single = True
        return self

    def execute(self) -> FakeResult:
        rows = self.rows
        for field, value in self.eq_filters:
            rows = [r for r in rows if r.get(field) == value]
        for field, values in self.in_filters:
            rows = [r for r in rows if r.get(field) in values]
        for field, desc in reversed(self.ordering):
            rows = sorted(rows, key=lambda r: r.get(field) or "", reverse=desc)
        if self.row_limit is not None:
            rows = rows[: self.row_limit]
        if self._want_single:
            return FakeResult(rows[0] if rows else None)
        return FakeResult(rows)


class FakeSupabase:
    def __init__(self, tables: dict[str, list[dict]], objects: dict[str, bytes] | None = None):
        self.tables = tables
        self.storage = FakeStorage(objects or {})

    def table(self, name: str) -> FakeTable:
        return FakeTable(self.tables.get(name, []))


def _document_row(doc_id: str, title: str, published_at: str, status: str = "active") -> dict:
    return {
        "id": doc_id,
        "workspace_id": WORKSPACE_ID,
        "title": title,
        "canonical_url": f"https://example.com/{doc_id}",
        "published_at": published_at,
        "status": status,
        "source_id": "source-1",
    }


def _version_row(version_id: str, doc_id: str, version_no: int, key: str) -> dict:
    return {
        "id": version_id,
        "document_id": doc_id,
        "version_no": version_no,
        "markdown_object_key": key,
    }


def test_search_documents_matches_title_and_body():
    supabase = FakeSupabase(
        tables={
            "documents": [
                _document_row("doc-1", "SK하이닉스 ADR 나스닥 상장", "2026-08-01T00:00:00+00:00"),
                _document_row("doc-2", "관련 없는 기사", "2026-08-02T00:00:00+00:00"),
            ],
            "document_versions": [
                _version_row("ver-1", "doc-1", 1, "processed/ws-1/doc-1/1.md"),
                _version_row("ver-2", "doc-2", 1, "processed/ws-1/doc-2/1.md"),
            ],
        },
        objects={
            "ws-1/doc-1/1.md": b"SK\xed\x95\x98\xec\x9d\xb4\xeb\x8b\x89\xec\x8a\xa4\xea\xb0\x80 \xeb\x82\x98\xec\x8a\xa4\xeb\x8b\xa5\xec\x97\x90 ADR\xec\x9d\x84 \xec\x83\x81\xec\x9e\xa5\xed\x96\x88\xeb\x8b\xa4.",
            "ws-1/doc-2/1.md": "자동차 산업 동향".encode("utf-8"),
        },
    )

    results = document_search.search_documents(WORKSPACE_ID, "SK하이닉스 ADR 상장", limit=5, supabase=supabase)

    assert len(results) == 1
    assert results[0].document_version_id == "ver-1"
    assert results[0].title == "SK하이닉스 ADR 나스닥 상장"
    assert 0.0 < results[0].score <= 1.0


def test_search_documents_uses_latest_version_per_document():
    supabase = FakeSupabase(
        tables={
            "documents": [_document_row("doc-1", "HBM 수요 전망", "2026-08-01T00:00:00+00:00")],
            "document_versions": [
                _version_row("ver-1a", "doc-1", 1, "processed/ws-1/doc-1/1.md"),
                _version_row("ver-1b", "doc-1", 2, "processed/ws-1/doc-1/2.md"),
            ],
        },
        objects={
            "ws-1/doc-1/1.md": "옛 버전 HBM 내용".encode("utf-8"),
            "ws-1/doc-1/2.md": "HBM 수요".encode("utf-8"),
        },
    )

    results = document_search.search_documents(WORKSPACE_ID, "HBM 수요", limit=5, supabase=supabase)

    assert len(results) == 1
    assert results[0].document_version_id == "ver-1b"


def test_search_documents_excludes_inactive_status():
    supabase = FakeSupabase(
        tables={
            "documents": [_document_row("doc-1", "HBM 수요", "2026-08-01T00:00:00+00:00", status="deleted")],
            "document_versions": [_version_row("ver-1", "doc-1", 1, "processed/ws-1/doc-1/1.md")],
        },
        objects={"ws-1/doc-1/1.md": "HBM 수요".encode("utf-8")},
    )

    results = document_search.search_documents(WORKSPACE_ID, "HBM 수요", limit=5, supabase=supabase)

    assert results == []


def test_search_documents_excludes_zero_overlap():
    supabase = FakeSupabase(
        tables={
            "documents": [_document_row("doc-1", "관련 없는 제목", "2026-08-01T00:00:00+00:00")],
            "document_versions": [_version_row("ver-1", "doc-1", 1, "processed/ws-1/doc-1/1.md")],
        },
        objects={"ws-1/doc-1/1.md": "관련 없는 본문".encode("utf-8")},
    )

    results = document_search.search_documents(WORKSPACE_ID, "HBM 반도체", limit=5, supabase=supabase)

    assert results == []

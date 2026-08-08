"""
Supabase 클라이언트 테스트 더블.

실제 DB 없이 파이프라인 전체를 돌리기 위한 최소 구현이다. 정본 SQL의
UNIQUE 제약을 그대로 흉내내서, 중복 방지 로직이 실제로 동작하는지 확인한다.

지원하는 호출 형태 (repository/jobs/storage가 쓰는 것만)
    table(t).select("*").eq(c, v).in_(c, vs).order(c, desc=).limit(n).execute()
    table(t).insert(row).execute()
    table(t).update(patch).eq(c, v).execute()
    storage.from_(bucket).upload(path=, file=, file_options=) / .download(path)
"""
from __future__ import annotations

import itertools
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

# 정본 SQL의 UNIQUE 제약 (myWiki_v2_supabase.sql)
UNIQUE_CONSTRAINTS: dict[str, list[tuple[str, tuple[str, ...]]]] = {
    "sources": [("uq_sources_workspace_name", ("workspace_id", "name"))],
    "documents": [("uq_documents_workspace_url", ("workspace_id", "canonical_url"))],
    "document_versions": [
        ("uq_dv_document_versionno", ("document_id", "version_no")),
        ("uq_dv_document_hash", ("document_id", "content_hash")),
        ("uq_dv_markdown_object_key", ("markdown_object_key",)),
    ],
    "pipeline_jobs": [("uq_pj_idempotency_key", ("idempotency_key",))],
}

# 7/29 적용된 컬럼 DEFAULT
COLUMN_DEFAULTS: dict[str, dict[str, Any]] = {
    "sources": {"config": {}, "enabled": True},
    "pipeline_jobs": {"progress": 0, "payload": {}, "retry_count": 0},
}

TIMESTAMPED = {"sources", "documents", "pipeline_jobs"}  # created_at + updated_at


class FakeUniqueViolation(Exception):
    """PostgreSQL 23505."""

    def __init__(self, constraint: str) -> None:
        super().__init__(f'duplicate key value violates unique constraint "{constraint}"')
        self.code = "23505"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _matches(row: dict, column: str, value: Any) -> bool:
    current = row.get(column)
    if value is None:
        return current is None
    if current is None:
        return False
    return str(current) == str(value)


class _Response:
    def __init__(self, data: Any) -> None:
        self.data = data


class _Query:
    def __init__(self, client: "FakeSupabase", table: str) -> None:
        self._client = client
        self._table = table
        self._op = "select"
        self._payload: Any = None
        self._filters: list[tuple[str, str, Any]] = []
        self._order: tuple[str, bool] | None = None
        self._limit: int | None = None
        self._range: tuple[int, int] | None = None
        self._single = False

    # --- 연산 선택 ---
    def select(self, *_columns: str) -> "_Query":
        self._op = "select"
        return self

    def insert(self, payload: dict | list) -> "_Query":
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload: dict) -> "_Query":
        self._op = "update"
        self._payload = payload
        return self

    def delete(self) -> "_Query":
        self._op = "delete"
        return self

    # --- 필터 ---
    def eq(self, column: str, value: Any) -> "_Query":
        self._filters.append(("eq", column, value))
        return self

    def in_(self, column: str, values: list) -> "_Query":
        self._filters.append(("in", column, [str(v) for v in values]))
        return self

    def is_(self, column: str, value: Any) -> "_Query":
        self._filters.append(("is", column, value))
        return self

    def order(self, column: str, desc: bool = False) -> "_Query":
        self._order = (column, desc)
        return self

    def limit(self, count: int) -> "_Query":
        self._limit = count
        return self

    def range(self, start: int, end: int) -> "_Query":
        """[start, end] 양끝 포함. PostgREST와 같은 규칙이다.

        페이지 조회(repository._PAGE_SIZE)가 이걸 쓴다. 실제 PostgREST는 한 응답에
        1,000행까지만 주고 넘으면 조용히 자르는데, 그 상한 자체는 흉내내지 않는다 —
        여기서 재현할 것은 "페이지를 이어 붙여 전건을 받는가"이지 서버 상한이 아니다.
        """
        self._range = (start, end)
        return self

    def maybe_single(self) -> "_Query":
        self._single = True
        return self

    def single(self) -> "_Query":
        self._single = True
        return self

    # --- 실행 ---
    def execute(self) -> _Response:
        rows = self._client.rows(self._table)
        if self._op == "insert":
            return _Response(self._insert())
        selected = [r for r in rows if self._passes(r)]
        if self._op == "update":
            for row in selected:
                row.update(self._payload)
                if self._table in TIMESTAMPED:  # trg_*_updated_at
                    row["updated_at"] = _now_iso()
            return _Response([dict(r) for r in selected])
        if self._op == "delete":
            for row in selected:
                rows.remove(row)
            return _Response([dict(r) for r in selected])

        if self._order is not None:
            column, desc = self._order
            selected.sort(key=lambda r: (str(r.get(column) or ""), r["_seq"]), reverse=desc)
        if self._range is not None:
            start, end = self._range
            selected = selected[start : end + 1]
        if self._limit is not None:
            selected = selected[: self._limit]
        copies = [dict(r) for r in selected]
        if self._single:
            return _Response(copies[0] if copies else None)
        return _Response(copies)

    def _passes(self, row: dict) -> bool:
        for kind, column, value in self._filters:
            if kind == "eq" and not _matches(row, column, value):
                return False
            if kind == "in" and str(row.get(column)) not in value:
                return False
            if kind == "is" and row.get(column) is not value:
                return False
        return True

    def _insert(self) -> list[dict]:
        payload = self._payload if isinstance(self._payload, list) else [self._payload]
        inserted = []
        for item in payload:
            row = dict(COLUMN_DEFAULTS.get(self._table, {}))
            row.update(item)
            row.setdefault("id", str(uuid4()))
            row.setdefault("created_at", _now_iso())
            if self._table in TIMESTAMPED:
                row.setdefault("updated_at", _now_iso())
            self._client.check_unique(self._table, row)
            row["_seq"] = next(self._client.sequence)
            self._client.rows(self._table).append(row)
            inserted.append(dict(row))
        return inserted


class _Bucket:
    def __init__(self, store: dict[str, bytes], bucket: str) -> None:
        self._store = store
        self._bucket = bucket

    def upload(self, path: str, file: bytes, file_options: dict | None = None) -> dict:
        self._store[f"{self._bucket}/{path}"] = file
        return {"path": path}

    def download(self, path: str) -> bytes:
        key = f"{self._bucket}/{path}"
        if key not in self._store:
            raise FileNotFoundError(f"Object not found: {key}")
        return self._store[key]

    def remove(self, paths: list[str]) -> list[dict]:
        for path in paths:
            self._store.pop(f"{self._bucket}/{path}", None)
        return [{"name": p} for p in paths]


class _Storage:
    def __init__(self, store: dict[str, bytes]) -> None:
        self._store = store

    def from_(self, bucket: str) -> _Bucket:
        return _Bucket(self._store, bucket)


class FakeSupabase:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict]] = {}
        self.objects: dict[str, bytes] = {}
        self.storage = _Storage(self.objects)
        self.sequence = itertools.count()

    def table(self, name: str) -> _Query:
        return _Query(self, name)

    def rows(self, name: str) -> list[dict]:
        return self.tables.setdefault(name, [])

    def check_unique(self, table: str, row: dict) -> None:
        for constraint, columns in UNIQUE_CONSTRAINTS.get(table, []):
            values = [row.get(c) for c in columns]
            if any(v is None for v in values):
                continue  # NULL은 UNIQUE 대상이 아니다
            for existing in self.rows(table):
                if all(_matches(existing, c, row.get(c)) for c in columns):
                    raise FakeUniqueViolation(constraint)

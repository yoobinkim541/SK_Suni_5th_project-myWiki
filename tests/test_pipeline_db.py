from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

from src.pipeline_common import db
from src.pipeline_common import repository


class FakePostgrestError(Exception):
    def __init__(self, payload: dict) -> None:
        super().__init__(payload)
        self.code = payload.get("code")


def test_execute_with_retry_retries_gateway_timeout_once() -> None:
    calls = 0

    def operation() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise FakePostgrestError({"code": 504, "message": "Gateway Timeout"})
        return "ok"

    assert db.execute_with_retry(operation, attempts=3, initial_delay_seconds=0) == "ok"
    assert calls == 2


def test_execute_with_retry_does_not_retry_missing_table_error() -> None:
    calls = 0

    def operation() -> None:
        nonlocal calls
        calls += 1
        raise FakePostgrestError(
            {
                "code": "PGRST205",
                "message": "Could not find the table 'public.wiki_page_keywords'",
            }
        )

    with pytest.raises(FakePostgrestError):
        db.execute_with_retry(operation, attempts=3, initial_delay_seconds=0)

    assert calls == 1


def test_list_active_documents_rebuilds_query_after_gateway_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    query_builds: list[str] = []
    executions = 0

    class Query:
        def select(self, columns: str) -> "Query":
            query_builds.append(columns)
            return self

        def eq(self, _column: str, _value: object) -> "Query":
            return self

        def order(self, _column: str) -> "Query":
            return self

        def range(self, _start: int, _end: int) -> "Query":
            return self

        def execute(self) -> SimpleNamespace:
            nonlocal executions
            executions += 1
            if executions == 1:
                raise FakePostgrestError({"code": 504, "message": "Gateway Timeout"})
            return SimpleNamespace(
                data=[
                    {
                        "id": "doc-1",
                        "workspace_id": "00000000-0000-0000-0000-000000000001",
                        "canonical_url": "https://example.com/1",
                    }
                ]
            )

    class Client:
        def table(self, _name: str) -> Query:
            return Query()

    monkeypatch.setattr(repository.db, "get_client", lambda: Client())

    rows = repository.list_active_documents(UUID("00000000-0000-0000-0000-000000000001"))

    assert rows[0]["id"] == "doc-1"
    assert query_builds == ["id, workspace_id, canonical_url", "id, workspace_id, canonical_url"]

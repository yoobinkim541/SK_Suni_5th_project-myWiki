from __future__ import annotations

from datetime import datetime, timezone

from src.pipeline_common import db
from src.pipeline_common.raw_retention import cleanup_raw_objects


class _Response:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows):
        self.rows = rows
        self.start = 0
        self.end = len(rows) - 1

    def select(self, *_columns):
        return self

    def eq(self, *_args):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def range(self, start, end):
        self.start, self.end = start, end
        return self

    def execute(self):
        return _Response(self.rows[self.start : self.end + 1])


class _Schema:
    def __init__(self, rows):
        self.rows = rows

    def table(self, _name):
        return _Query(self.rows)


class _Bucket:
    def __init__(self):
        self.removed = []

    def remove(self, names):
        self.removed.extend(names)
        return _Response([{"name": name} for name in names])


class _Storage:
    def __init__(self, bucket):
        self.bucket = bucket

    def from_(self, _bucket):
        return self.bucket


class _Client:
    def __init__(self, rows):
        self.bucket = _Bucket()
        self.storage = _Storage(self.bucket)
        self._schema = _Schema(rows)

    def schema(self, _name):
        return self._schema


def test_cleanup_deletes_old_objects_and_enforces_byte_cap():
    now = datetime(2026, 8, 31, tzinfo=timezone.utc)
    rows = [
        {"name": "old.html", "created_at": "2026-08-20T00:00:00+00:00", "metadata": {"size": 100}},
        {"name": "recent-a.html", "created_at": "2026-08-30T00:00:00+00:00", "metadata": {"size": 900}},
        {"name": "recent-b.html", "created_at": "2026-08-30T01:00:00+00:00", "metadata": {"size": 100}},
    ]
    client = _Client(rows)
    db.set_client(client)
    try:
        summary = cleanup_raw_objects(
            retention_days=3,
            max_bytes=850,
            now=now,
            batch_size=10,
        )
    finally:
        db.reset_client()

    assert summary.scanned == 3
    assert summary.candidates == 2
    assert summary.deleted == 2
    assert client.bucket.removed == ["old.html", "recent-a.html"]



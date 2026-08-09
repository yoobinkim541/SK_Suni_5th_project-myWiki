"""프로필 편집(이름 + 아바타) db.py 함수 테스트."""
from __future__ import annotations

import pytest

from src.api import db

USER_ID = "55555555-5555-5555-5555-555555555555"


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeUpdateQuery:
    def __init__(self, rows: list[dict], patch: dict):
        self._rows = rows
        self._patch = patch
        self._filters: list[tuple] = []

    def eq(self, key, value):
        self._filters.append((key, value))
        return self

    def execute(self):
        matched = [r for r in self._rows if all(r.get(k) == v for k, v in self._filters)]
        for r in matched:
            r.update(self._patch)
        return FakeResult(matched)


class FakeTable:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def update(self, patch: dict):
        return FakeUpdateQuery(self._rows, patch)


class FakeStorageBucket:
    def __init__(self, files: dict[str, bytes]):
        self._files = files
        self.uploaded: list[tuple] = []
        self.removed: list[list[str]] = []

    def upload(self, path, file, file_options=None):
        self._files[path] = file
        self.uploaded.append((path, file, file_options))

    def download(self, path):
        return self._files[path]

    def remove(self, paths):
        self.removed.append(paths)
        for p in paths:
            self._files.pop(p, None)


class FakeStorage:
    def __init__(self):
        self.buckets: dict[str, FakeStorageBucket] = {}

    def from_(self, bucket_name):
        return self.buckets.setdefault(bucket_name, FakeStorageBucket({}))


class FakeSupabaseClient:
    def __init__(self, data: dict[str, list[dict]]):
        self._data = data
        self.storage = FakeStorage()

    def table(self, name: str):
        return FakeTable(self._data.setdefault(name, []))


@pytest.fixture
def fake_db(monkeypatch):
    client = FakeSupabaseClient({
        "profiles": [{"id": USER_ID, "display_name": "기존이름", "avatar_object_key": None}],
    })
    monkeypatch.setattr(db, "get_supabase", lambda: client)
    return client


def test_update_profile_display_name(fake_db):
    updated = db.update_profile_display_name(USER_ID, "새이름")

    assert updated["display_name"] == "새이름"
    assert fake_db._data["profiles"][0]["display_name"] == "새이름"


def test_set_profile_avatar_object_key(fake_db):
    db.set_profile_avatar_object_key(USER_ID, f"{USER_ID}/avatar.jpg")

    assert fake_db._data["profiles"][0]["avatar_object_key"] == f"{USER_ID}/avatar.jpg"


def test_set_profile_avatar_object_key_clears_with_none(fake_db):
    db.set_profile_avatar_object_key(USER_ID, f"{USER_ID}/avatar.jpg")
    db.set_profile_avatar_object_key(USER_ID, None)

    assert fake_db._data["profiles"][0]["avatar_object_key"] is None


def test_upload_and_download_avatar_object(fake_db):
    object_key = f"{USER_ID}/avatar.png"
    db.upload_avatar_object(object_key, b"fake-image-bytes", "image/png")

    result = db.download_avatar_object(object_key)

    assert result == b"fake-image-bytes"
    bucket = fake_db.storage.buckets["avatars"]
    assert bucket.uploaded[0][2]["upsert"] == "true"


def test_delete_avatar_object(fake_db):
    object_key = f"{USER_ID}/avatar.png"
    db.upload_avatar_object(object_key, b"data", "image/png")

    db.delete_avatar_object(object_key)

    bucket = fake_db.storage.buckets["avatars"]
    assert bucket.removed == [[object_key]]

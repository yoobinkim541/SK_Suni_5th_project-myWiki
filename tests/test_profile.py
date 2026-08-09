"""프로필 편집(이름 + 아바타) db.py 함수 테스트."""
from __future__ import annotations

import pytest

from src.api import db

USER_ID = "55555555-5555-5555-5555-555555555555"
WORKSPACE_ID = "44444444-4444-4444-4444-444444444444"
OTHER_USER_ID = "66666666-6666-6666-6666-666666666666"
NON_MEMBER_ID = "77777777-7777-7777-7777-777777777777"


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


class FakeQuery:
    def __init__(self, rows: list[dict]):
        self._rows = rows
        self._single = False

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, key, value):
        self._rows = [r for r in self._rows if r.get(key) == value]
        return self

    def maybe_single(self):
        self._single = True
        return self

    def execute(self):
        if self._single:
            return FakeResult(self._rows[0] if self._rows else None)
        return FakeResult(list(self._rows))


class FakeTable:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def select(self, *args, **kwargs):
        return FakeQuery(list(self._rows)).select(*args, **kwargs)

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
        "profiles": [
            {"id": USER_ID, "display_name": "기존이름", "avatar_object_key": None},
            {"id": OTHER_USER_ID, "display_name": "동료", "avatar_object_key": f"{OTHER_USER_ID}/avatar.png"},
        ],
        "workspace_members": [
            {"workspace_id": WORKSPACE_ID, "user_id": USER_ID},
            {"workspace_id": WORKSPACE_ID, "user_id": OTHER_USER_ID},
        ],
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


def test_get_member_avatar_object_key_returns_key_for_fellow_member(fake_db):
    result = db.get_member_avatar_object_key(WORKSPACE_ID, OTHER_USER_ID)

    assert result == f"{OTHER_USER_ID}/avatar.png"


def test_get_member_avatar_object_key_none_when_no_avatar(fake_db):
    result = db.get_member_avatar_object_key(WORKSPACE_ID, USER_ID)

    assert result is None


def test_get_member_avatar_object_key_none_when_not_a_member(fake_db):
    result = db.get_member_avatar_object_key(WORKSPACE_ID, NON_MEMBER_ID)

    assert result is None

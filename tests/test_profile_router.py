"""프로필 편집(GET/PATCH /profile, GET/POST/DELETE /profile/avatar) 라우터 테스트.
db.* 함수를 monkeypatch해서 요청/응답 형식만 검증한다(db 함수 자체 동작은
tests/test_profile.py에서 이미 확인함)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import db
from src.api.auth import get_current_user
from src.api.main import app

USER_ID = "55555555-5555-5555-5555-555555555555"


@pytest.fixture
def client_as(monkeypatch):
    def _make(profile: dict) -> TestClient:
        app.dependency_overrides[get_current_user] = lambda: profile
        return TestClient(app)
    yield _make
    app.dependency_overrides.pop(get_current_user, None)


def test_get_profile_returns_display_name_and_has_avatar(client_as):
    client = client_as({"id": USER_ID, "display_name": "이유빈", "avatar_object_key": f"{USER_ID}/avatar.png"})

    res = client.get("/profile")

    assert res.status_code == 200
    assert res.json() == {"id": USER_ID, "display_name": "이유빈", "has_avatar": True}


def test_get_profile_has_avatar_false_when_none(client_as):
    client = client_as({"id": USER_ID, "display_name": "이유빈", "avatar_object_key": None})

    res = client.get("/profile")

    assert res.json()["has_avatar"] is False


def test_update_profile_updates_display_name(client_as, monkeypatch):
    client = client_as({"id": USER_ID, "display_name": "옛이름", "avatar_object_key": None})
    calls = []
    monkeypatch.setattr(
        db, "update_profile_display_name",
        lambda uid, name: calls.append((uid, name)) or {"id": uid, "display_name": name, "avatar_object_key": None},
    )

    res = client.patch("/profile", json={"display_name": "새이름"})

    assert res.status_code == 200
    assert res.json()["display_name"] == "새이름"
    assert calls == [(USER_ID, "새이름")]


def test_update_profile_rejects_empty_name(client_as):
    client = client_as({"id": USER_ID, "display_name": "옛이름", "avatar_object_key": None})

    res = client.patch("/profile", json={"display_name": ""})

    assert res.status_code == 422


def test_get_avatar_404_when_none(client_as):
    client = client_as({"id": USER_ID, "display_name": "이유빈", "avatar_object_key": None})

    res = client.get("/profile/avatar")

    assert res.status_code == 404


def test_get_avatar_streams_bytes_with_content_type(client_as, monkeypatch):
    client = client_as({"id": USER_ID, "display_name": "이유빈", "avatar_object_key": f"{USER_ID}/avatar.png"})
    monkeypatch.setattr(db, "download_avatar_object", lambda key: b"fake-png-bytes")

    res = client.get("/profile/avatar")

    assert res.status_code == 200
    assert res.content == b"fake-png-bytes"
    assert res.headers["content-type"] == "image/png"


def test_upload_avatar_rejects_unsupported_type(client_as):
    client = client_as({"id": USER_ID, "display_name": "이유빈", "avatar_object_key": None})

    res = client.post(
        "/profile/avatar",
        files={"file": ("doc.pdf", b"not-an-image", "application/pdf")},
    )

    assert res.status_code == 400


def test_upload_avatar_rejects_too_large(client_as):
    client = client_as({"id": USER_ID, "display_name": "이유빈", "avatar_object_key": None})
    oversized = b"a" * (3 * 1024 * 1024 + 1)

    res = client.post(
        "/profile/avatar",
        files={"file": ("avatar.png", oversized, "image/png")},
    )

    assert res.status_code == 400


def test_upload_avatar_success_sets_object_key(client_as, monkeypatch):
    client = client_as({"id": USER_ID, "display_name": "이유빈", "avatar_object_key": None})
    upload_calls = []
    set_calls = []
    monkeypatch.setattr(db, "upload_avatar_object", lambda key, data, ct: upload_calls.append((key, data, ct)))
    monkeypatch.setattr(db, "set_profile_avatar_object_key", lambda uid, key: set_calls.append((uid, key)))

    res = client.post(
        "/profile/avatar",
        files={"file": ("avatar.png", b"image-bytes", "image/png")},
    )

    assert res.status_code == 200
    assert res.json()["has_avatar"] is True
    assert upload_calls == [(f"{USER_ID}/avatar.png", b"image-bytes", "image/png")]
    assert set_calls == [(USER_ID, f"{USER_ID}/avatar.png")]


def test_upload_avatar_deletes_old_object_when_extension_changes(client_as, monkeypatch):
    client = client_as({"id": USER_ID, "display_name": "이유빈", "avatar_object_key": f"{USER_ID}/avatar.jpg"})
    deleted = []
    monkeypatch.setattr(db, "delete_avatar_object", lambda key: deleted.append(key))
    monkeypatch.setattr(db, "upload_avatar_object", lambda key, data, ct: None)
    monkeypatch.setattr(db, "set_profile_avatar_object_key", lambda uid, key: None)

    res = client.post(
        "/profile/avatar",
        files={"file": ("avatar.png", b"image-bytes", "image/png")},
    )

    assert res.status_code == 200
    assert deleted == [f"{USER_ID}/avatar.jpg"]


def test_delete_avatar_clears_when_present(client_as, monkeypatch):
    client = client_as({"id": USER_ID, "display_name": "이유빈", "avatar_object_key": f"{USER_ID}/avatar.png"})
    deleted = []
    cleared = []
    monkeypatch.setattr(db, "delete_avatar_object", lambda key: deleted.append(key))
    monkeypatch.setattr(db, "set_profile_avatar_object_key", lambda uid, key: cleared.append((uid, key)))

    res = client.delete("/profile/avatar")

    assert res.status_code == 204
    assert deleted == [f"{USER_ID}/avatar.png"]
    assert cleared == [(USER_ID, None)]


def test_delete_avatar_noop_when_already_absent(client_as, monkeypatch):
    client = client_as({"id": USER_ID, "display_name": "이유빈", "avatar_object_key": None})
    calls = []
    monkeypatch.setattr(db, "delete_avatar_object", lambda key: calls.append(key))

    res = client.delete("/profile/avatar")

    assert res.status_code == 204
    assert calls == []

"""
chat_sessions visibility(private/team) 기능 테스트 — DB/네트워크는 monkeypatch로 대체한다.

두 층을 나눠서 검증한다:
1. src/api/db.py의 get_chat_session/list_chat_sessions 접근 제어 로직 자체
   (get_supabase()를 최소 fake Supabase 클라이언트로 대체해서 실제 필터링 쿼리를 태운다).
2. src/api/main.py 라우터 계층 — db.* 함수를 직접 monkeypatch해서 엔드포인트가
   세션 조회 결과(None/세션)를 올바르게 200/404로 반영하는지, share-to-team이
   메시지 쌍과 citations를 올바른 순서로 복사하는지 확인한다.

tests/test_wiki_router.py, tests/test_auth.py와 동일하게 실제 SUPABASE_* 환경변수는
필요 없다.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import db
from src.api import main as main_module
from src.api.auth import get_current_user
from src.api.main import app

WORKSPACE_ID = "11111111-1111-1111-1111-111111111111"
OWNER_ID = "22222222-2222-2222-2222-222222222222"
OTHER_USER_ID = "33333333-3333-3333-3333-333333333333"

PRIVATE_SESSION = {
    "id": "sess-private",
    "workspace_id": WORKSPACE_ID,
    "user_id": OWNER_ID,
    "title": "내 에이전트",
    "visibility": "private",
    "created_at": "2026-08-01T00:00:00Z",
    "updated_at": "2026-08-01T00:00:00Z",
}
TEAM_SESSION = {
    "id": "sess-team",
    "workspace_id": WORKSPACE_ID,
    "user_id": OWNER_ID,
    "title": "팀 공유 에이전트",
    "visibility": "team",
    "created_at": "2026-08-01T00:00:00Z",
    "updated_at": "2026-08-01T00:00:00Z",
}


# ---------------------------------------------------------------------------
# 1. db.py 접근 제어 로직 — 최소 fake Supabase 클라이언트로 실제 쿼리를 태운다
# ---------------------------------------------------------------------------

class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, rows: list[dict]):
        self._rows = rows
        self._single = False

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, key, value):
        self._rows = [r for r in self._rows if r.get(key) == value]
        return self

    def lt(self, key, value):
        self._rows = [r for r in self._rows if r.get(key) < value]
        return self

    def order(self, key, desc: bool = False):
        self._rows = sorted(self._rows, key=lambda r: r.get(key), reverse=desc)
        return self

    def limit(self, n: int):
        self._rows = self._rows[:n]
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

    def select(self, *_args, **_kwargs):
        return FakeQuery(list(self._rows))


class FakeSupabaseClient:
    def __init__(self, data: dict[str, list[dict]]):
        self._data = data

    def table(self, name: str):
        return FakeTable(self._data.get(name, []))


@pytest.fixture
def fake_db(monkeypatch):
    client = FakeSupabaseClient({"chat_sessions": [PRIVATE_SESSION, TEAM_SESSION]})
    monkeypatch.setattr(db, "get_supabase", lambda: client)
    return client


def test_get_chat_session_owner_can_access_private(fake_db):
    result = db.get_chat_session("sess-private", WORKSPACE_ID, OWNER_ID)
    assert result is not None
    assert result["id"] == "sess-private"


def test_get_chat_session_blocks_other_user_from_private(fake_db):
    result = db.get_chat_session("sess-private", WORKSPACE_ID, OTHER_USER_ID)
    assert result is None


def test_get_chat_session_allows_team_session_for_any_member(fake_db):
    result = db.get_chat_session("sess-team", WORKSPACE_ID, OTHER_USER_ID)
    assert result is not None
    assert result["id"] == "sess-team"


def test_list_chat_sessions_mine_returns_only_own_private(fake_db):
    result = db.list_chat_sessions(WORKSPACE_ID, OWNER_ID, "mine")
    assert [r["id"] for r in result] == ["sess-private"]


def test_list_chat_sessions_mine_excludes_others_private(fake_db):
    result = db.list_chat_sessions(WORKSPACE_ID, OTHER_USER_ID, "mine")
    assert result == []


def test_list_chat_sessions_team_visible_to_any_member(fake_db):
    result = db.list_chat_sessions(WORKSPACE_ID, OTHER_USER_ID, "team")
    assert [r["id"] for r in result] == ["sess-team"]


# ---------------------------------------------------------------------------
# 1b. user_id/author_name 왕복 — insert 인자를 그대로 캡처하는 최소 fake
# ---------------------------------------------------------------------------

class FakeInsertQuery:
    def __init__(self, sink: list[dict], row: dict):
        self._row = {**row, "id": f"generated-{len(sink)}"}
        sink.append(self._row)

    def execute(self):
        return FakeResult([self._row])


class FakeInsertTable:
    def __init__(self, sink: list[dict]):
        self._sink = sink

    def insert(self, row: dict):
        return FakeInsertQuery(self._sink, row)


class FakeInsertClient:
    def __init__(self):
        self.inserted: dict[str, list[dict]] = {}

    def table(self, name: str):
        return FakeInsertTable(self.inserted.setdefault(name, []))


def test_save_user_message_includes_user_id(monkeypatch):
    client = FakeInsertClient()
    monkeypatch.setattr(db, "get_supabase", lambda: client)

    db.save_user_message("sess-1", "HBM4가 뭐야?", OWNER_ID)

    assert client.inserted["chat_messages"][0]["user_id"] == OWNER_ID


def test_copy_chat_message_preserves_original_author(monkeypatch):
    client = FakeInsertClient()
    monkeypatch.setattr(db, "get_supabase", lambda: client)

    db.copy_chat_message("target-session", {**USER_QUESTION, "user_id": OWNER_ID})

    assert client.inserted["chat_messages"][0]["user_id"] == OWNER_ID


# ---------------------------------------------------------------------------
# 2. 라우터 계층 — db.* 함수를 직접 monkeypatch
# ---------------------------------------------------------------------------

@pytest.fixture
def make_client(monkeypatch):
    monkeypatch.setattr(db, "get_default_workspace_id", lambda user_id: WORKSPACE_ID)

    def _make(user_id: str) -> TestClient:
        app.dependency_overrides[get_current_user] = lambda: {"id": user_id}
        return TestClient(app)

    yield _make
    app.dependency_overrides.clear()


def test_list_sessions_endpoint_passes_scope_through(make_client, monkeypatch):
    captured = {}

    def fake_list(workspace_id, user_id, scope):
        captured["args"] = (workspace_id, user_id, scope)
        return [PRIVATE_SESSION]

    monkeypatch.setattr(db, "list_chat_sessions", fake_list)

    res = make_client(OWNER_ID).get("/chat/sessions", params={"scope": "mine"})

    assert res.status_code == 200
    assert res.json()[0]["id"] == "sess-private"
    assert captured["args"] == (WORKSPACE_ID, OWNER_ID, "mine")


def test_list_sessions_endpoint_team_scope(make_client, monkeypatch):
    monkeypatch.setattr(db, "list_chat_sessions", lambda w, u, s: [TEAM_SESSION] if s == "team" else [])

    res = make_client(OTHER_USER_ID).get("/chat/sessions", params={"scope": "team"})

    assert res.status_code == 200
    assert res.json()[0]["id"] == "sess-team"


def test_get_messages_private_session_blocked_for_other_user_returns_404(make_client, monkeypatch):
    def fake_get_chat_session(session_id, workspace_id, user_id):
        if PRIVATE_SESSION["visibility"] == "private" and user_id != PRIVATE_SESSION["user_id"]:
            return None
        return PRIVATE_SESSION

    monkeypatch.setattr(db, "get_chat_session", fake_get_chat_session)

    res = make_client(OTHER_USER_ID).get(f"/chat/sessions/{PRIVATE_SESSION['id']}/messages")

    assert res.status_code == 404


def test_get_messages_team_session_allowed_for_any_member(make_client, monkeypatch):
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: TEAM_SESSION)
    monkeypatch.setattr(db, "list_chat_messages", lambda sid: [])

    res = make_client(OTHER_USER_ID).get(f"/chat/sessions/{TEAM_SESSION['id']}/messages")

    assert res.status_code == 200
    assert res.json() == []


def test_get_messages_includes_author_name(make_client, monkeypatch):
    """팀 공유 대화에서 각 질문을 누가 보냈는지 표시하기 위한 author_name 왕복."""
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: TEAM_SESSION)
    monkeypatch.setattr(
        db, "list_chat_messages",
        lambda sid: [{"id": "msg-1", "session_id": sid, "role": "user", "content": "질문", "author_name": "김주현", "created_at": "2026-08-01T00:00:00Z"}],
    )

    res = make_client(OTHER_USER_ID).get(f"/chat/sessions/{TEAM_SESSION['id']}/messages")

    assert res.status_code == 200
    assert res.json()[0]["author_name"] == "김주현"


# ---------------------------------------------------------------------------
# share-to-team
# ---------------------------------------------------------------------------

ASSISTANT_MESSAGE = {
    "id": "msg-assistant",
    "session_id": "sess-private",
    "role": "assistant",
    "content": "HBM4는 차세대 메모리다. [1]",
    "model_name": "deepseek/deepseek-v4-flash",
    "prompt_version": "v1",
    "created_at": "2026-08-01T00:05:00Z",
}
USER_QUESTION = {
    "id": "msg-user",
    "session_id": "sess-private",
    "role": "user",
    "content": "HBM4가 뭐야?",
    "created_at": "2026-08-01T00:04:00Z",
}
SAMPLE_CITATION = {
    "id": "c1",
    "document_version_id": "dv-1",
    "quoted_text": "HBM4는 차세대 메모리다.",
    "relevance_score": 0.9,
    "citation_order": 1,
    "source_url": "https://example.com/a",
}


@pytest.fixture
def share_setup(monkeypatch):
    def fake_get_chat_session(sid, wid, uid):
        if sid == PRIVATE_SESSION["id"] and uid == OWNER_ID:
            return PRIVATE_SESSION
        if sid == TEAM_SESSION["id"]:
            return TEAM_SESSION
        return None

    monkeypatch.setattr(db, "get_chat_session", fake_get_chat_session)
    monkeypatch.setattr(db, "get_chat_message", lambda mid: ASSISTANT_MESSAGE if mid == ASSISTANT_MESSAGE["id"] else None)
    monkeypatch.setattr(db, "get_preceding_user_message", lambda sid, before: USER_QUESTION)

    create_calls: list[tuple] = []

    def fake_create_chat_session(workspace_id, user_id, title=None, visibility="private"):
        create_calls.append((workspace_id, user_id, title, visibility))
        return {**TEAM_SESSION, "id": "new-team-session"}

    monkeypatch.setattr(db, "create_chat_session", fake_create_chat_session)

    copy_calls: list[tuple[str, str]] = []

    def fake_copy_chat_message(target_session_id, message):
        copy_calls.append((target_session_id, message["role"]))
        return {**message, "id": f"copied-{message['role']}", "session_id": target_session_id}

    monkeypatch.setattr(db, "copy_chat_message", fake_copy_chat_message)

    citation_calls: list[str] = []

    def fake_list_message_citations(message_id):
        citation_calls.append(message_id)
        return [SAMPLE_CITATION]

    monkeypatch.setattr(db, "list_message_citations", fake_list_message_citations)

    citation_copy_calls: list[tuple[str, list[dict]]] = []
    monkeypatch.setattr(
        db, "copy_message_citations",
        lambda target_message_id, citations: citation_copy_calls.append((target_message_id, citations)),
    )

    return {
        "create_calls": create_calls,
        "copy_calls": copy_calls,
        "citation_calls": citation_calls,
        "citation_copy_calls": citation_copy_calls,
    }


def test_share_to_team_without_target_creates_new_team_session(make_client, share_setup):
    res = make_client(OWNER_ID).post(
        f"/chat/sessions/{PRIVATE_SESSION['id']}/messages/{ASSISTANT_MESSAGE['id']}/share-to-team"
    )

    assert res.status_code == 200
    body = res.json()
    assert body["id"] == "copied-assistant"
    assert body["role"] == "assistant"
    assert body["content"] == ASSISTANT_MESSAGE["content"]
    assert body["citations"][0]["document_version_id"] == "dv-1"

    assert share_setup["create_calls"] == [(WORKSPACE_ID, OWNER_ID, "새 공유 대화", "team")]
    # user 질문 -> assistant 답변 순서로 새로 만든 팀 세션에 복사됐는지 확인
    assert share_setup["copy_calls"] == [("new-team-session", "user"), ("new-team-session", "assistant")]
    # 원본 메시지에서 citation을 읽고, 응답 조립 시 복사본 메시지 기준으로 다시 읽는다
    assert share_setup["citation_calls"] == [ASSISTANT_MESSAGE["id"], "copied-assistant"]
    assert share_setup["citation_copy_calls"] == [("copied-assistant", [SAMPLE_CITATION])]


def test_share_to_team_with_target_uses_existing_team_session(make_client, share_setup):
    res = make_client(OWNER_ID).post(
        f"/chat/sessions/{PRIVATE_SESSION['id']}/messages/{ASSISTANT_MESSAGE['id']}/share-to-team",
        json={"target_session_id": TEAM_SESSION["id"]},
    )

    assert res.status_code == 200
    assert share_setup["create_calls"] == []
    assert share_setup["copy_calls"] == [(TEAM_SESSION["id"], "user"), (TEAM_SESSION["id"], "assistant")]


def test_share_to_team_with_unknown_target_returns_400(make_client, share_setup):
    res = make_client(OWNER_ID).post(
        f"/chat/sessions/{PRIVATE_SESSION['id']}/messages/{ASSISTANT_MESSAGE['id']}/share-to-team",
        json={"target_session_id": "does-not-exist"},
    )

    assert res.status_code == 400
    assert share_setup["copy_calls"] == []


def test_share_to_team_with_non_team_target_returns_400(make_client, share_setup):
    res = make_client(OWNER_ID).post(
        f"/chat/sessions/{PRIVATE_SESSION['id']}/messages/{ASSISTANT_MESSAGE['id']}/share-to-team",
        json={"target_session_id": PRIVATE_SESSION["id"]},
    )

    assert res.status_code == 400
    assert share_setup["copy_calls"] == []


def test_share_to_team_without_matching_question_returns_404(make_client, monkeypatch):
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: PRIVATE_SESSION if uid == OWNER_ID else None)
    monkeypatch.setattr(db, "get_chat_message", lambda mid: ASSISTANT_MESSAGE)
    monkeypatch.setattr(db, "get_preceding_user_message", lambda sid, before: None)

    res = make_client(OWNER_ID).post(
        f"/chat/sessions/{PRIVATE_SESSION['id']}/messages/{ASSISTANT_MESSAGE['id']}/share-to-team"
    )

    assert res.status_code == 404


def test_share_to_team_blocked_for_non_owner(make_client, monkeypatch):
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: PRIVATE_SESSION if uid == OWNER_ID else None)

    res = make_client(OTHER_USER_ID).post(
        f"/chat/sessions/{PRIVATE_SESSION['id']}/messages/{ASSISTANT_MESSAGE['id']}/share-to-team"
    )

    assert res.status_code == 404


# ---------------------------------------------------------------------------
# save-to-wiki
# ---------------------------------------------------------------------------

def test_save_to_wiki_without_citations_returns_400(make_client, monkeypatch):
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: PRIVATE_SESSION if uid == OWNER_ID else None)
    monkeypatch.setattr(db, "get_chat_message", lambda mid: ASSISTANT_MESSAGE if mid == ASSISTANT_MESSAGE["id"] else None)
    monkeypatch.setattr(db, "list_message_citations", lambda mid: [])

    res = make_client(OWNER_ID).post(
        f"/chat/sessions/{PRIVATE_SESSION['id']}/messages/{ASSISTANT_MESSAGE['id']}/save-to-wiki"
    )

    assert res.status_code == 400


def test_save_to_wiki_with_citations_creates_wiki_version(make_client, monkeypatch):
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: PRIVATE_SESSION if uid == OWNER_ID else None)
    monkeypatch.setattr(db, "get_chat_message", lambda mid: ASSISTANT_MESSAGE if mid == ASSISTANT_MESSAGE["id"] else None)
    monkeypatch.setattr(db, "list_message_citations", lambda mid: [SAMPLE_CITATION])
    monkeypatch.setattr(db, "get_preceding_user_message", lambda sid, before: USER_QUESTION)

    captured = {}

    def fake_upsert_wiki_page(workspace_id, slug, title, page_type):
        captured["upsert_args"] = (workspace_id, slug, title, page_type)
        return "page-1"

    def fake_create_wiki_version(draft):
        captured["draft"] = draft
        return "version-1"

    monkeypatch.setattr(main_module, "upsert_wiki_page", fake_upsert_wiki_page)
    monkeypatch.setattr(main_module, "create_wiki_version", fake_create_wiki_version)
    monkeypatch.setattr(main_module, "record_wiki_validation", lambda *a, **kw: None)
    monkeypatch.setattr(main_module, "review_wiki_version", lambda *a, **kw: None)
    monkeypatch.setattr(main_module, "publish_wiki_version", lambda *a, **kw: None)

    res = make_client(OWNER_ID).post(
        f"/chat/sessions/{PRIVATE_SESSION['id']}/messages/{ASSISTANT_MESSAGE['id']}/save-to-wiki"
    )

    assert res.status_code == 200
    expected_slug = f"chat-{ASSISTANT_MESSAGE['id'][:8]}"
    assert res.json() == {"page_id": "page-1", "version_id": "version-1", "slug": expected_slug}

    assert captured["upsert_args"] == (WORKSPACE_ID, expected_slug, USER_QUESTION["content"][:80], "issue")

    draft = captured["draft"]
    assert draft.workspace_id == WORKSPACE_ID
    assert draft.slug == expected_slug
    assert draft.page_type == "issue"
    assert draft.markdown == ASSISTANT_MESSAGE["content"]
    assert len(draft.sources) == 1
    assert draft.sources[0].document_version_id == SAMPLE_CITATION["document_version_id"]
    assert draft.sources[0].claim_text == SAMPLE_CITATION["quoted_text"]


def test_save_to_wiki_auto_publishes_version(make_client, monkeypatch):
    """
    save-to-wiki는 사람 검수를 거치지 않으므로, 저장 직후 자동으로
    validation -> review -> publish까지 진행해서 위키 페이지가 즉시
    published 상태가 되는지 확인한다(record_wiki_validation/review_wiki_version/
    publish_wiki_version 호출로 검증 — 실제 DB 상태는 test_wiki_service.py의
    통합 테스트가 별도로 검증한다).
    """
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: PRIVATE_SESSION if uid == OWNER_ID else None)
    monkeypatch.setattr(db, "get_chat_message", lambda mid: ASSISTANT_MESSAGE if mid == ASSISTANT_MESSAGE["id"] else None)
    monkeypatch.setattr(db, "list_message_citations", lambda mid: [SAMPLE_CITATION])
    monkeypatch.setattr(db, "get_preceding_user_message", lambda sid, before: USER_QUESTION)
    monkeypatch.setattr(main_module, "upsert_wiki_page", lambda workspace_id, slug, title, page_type: "page-1")
    monkeypatch.setattr(main_module, "create_wiki_version", lambda draft: "version-1")

    calls: list[tuple[str, tuple]] = []
    monkeypatch.setattr(main_module, "record_wiki_validation", lambda *a, **kw: calls.append(("record_wiki_validation", a)))
    monkeypatch.setattr(main_module, "review_wiki_version", lambda *a, **kw: calls.append(("review_wiki_version", a)))
    monkeypatch.setattr(main_module, "publish_wiki_version", lambda *a, **kw: calls.append(("publish_wiki_version", a)))

    res = make_client(OWNER_ID).post(
        f"/chat/sessions/{PRIVATE_SESSION['id']}/messages/{ASSISTANT_MESSAGE['id']}/save-to-wiki"
    )

    assert res.status_code == 200
    assert calls == [
        ("record_wiki_validation", ("version-1", "passed", None)),
        ("review_wiki_version", ("version-1", None, "approved")),
        ("publish_wiki_version", ("page-1", "version-1")),
    ]

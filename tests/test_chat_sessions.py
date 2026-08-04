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

from typing import Optional

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

    def is_(self, key, value):
        if value == "null":
            self._rows = [r for r in self._rows if r.get(key) is None]
        else:
            self._rows = [r for r in self._rows if r.get(key) is not None]
        return self

    def in_(self, key, values):
        values = set(values)
        self._rows = [r for r in self._rows if r.get(key) in values]
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

    def single(self):
        self._single = True
        return self

    def execute(self):
        if self._single:
            return FakeResult(self._rows[0] if self._rows else None)
        return FakeResult(list(self._rows))


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


class FakeUpsertQuery:
    def __init__(self, rows: list[dict], row: dict, on_conflict: Optional[str], ignore_duplicates: bool):
        self._rows = rows
        self._row = row
        self._conflict_keys = on_conflict.split(",") if on_conflict else []
        self._ignore_duplicates = ignore_duplicates

    def execute(self):
        existing = None
        if self._conflict_keys:
            existing = next(
                (r for r in self._rows if all(r.get(k) == self._row.get(k) for k in self._conflict_keys)),
                None,
            )
        if existing is not None:
            if self._ignore_duplicates:
                return FakeResult([])
            existing.update(self._row)
            return FakeResult([existing])
        new_row = {**self._row, "id": f"generated-{len(self._rows)}"}
        self._rows.append(new_row)
        return FakeResult([new_row])


class FakeDeleteQuery:
    def __init__(self, rows: list[dict]):
        self._rows = rows
        self._filters: list[tuple] = []

    def eq(self, key, value):
        self._filters.append((key, value))
        return self

    def execute(self):
        matched = [r for r in self._rows if all(r.get(k) == v for k, v in self._filters)]
        for r in matched:
            self._rows.remove(r)
        return FakeResult(matched)


class FakeInsertIntoQuery:
    def __init__(self, rows: list[dict], row: dict):
        self._row = {**row, "id": row.get("id") or f"generated-{len(rows)}"}
        rows.append(self._row)

    def execute(self):
        return FakeResult([self._row])


class FakeTable:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def select(self, *_args, **_kwargs):
        return FakeQuery(list(self._rows))

    def insert(self, row: dict):
        return FakeInsertIntoQuery(self._rows, row)

    def update(self, patch: dict):
        return FakeUpdateQuery(self._rows, patch)

    def upsert(self, row: dict, on_conflict: Optional[str] = None, ignore_duplicates: bool = False):
        return FakeUpsertQuery(self._rows, row, on_conflict, ignore_duplicates)

    def delete(self):
        return FakeDeleteQuery(self._rows)


class FakeSupabaseClient:
    def __init__(self, data: dict[str, list[dict]]):
        self._data = data

    def table(self, name: str):
        return FakeTable(self._data.get(name, []))


@pytest.fixture
def fake_db(monkeypatch):
    # 세션마다 새 dict로 복사 — update()가 그대로 mutate하므로 테스트 간 상태가 새지 않게 한다.
    # TEAM_SESSION은 만든 사람(OWNER_ID)이 곧 참여자다 — create_chat_session이 그렇게 만든다.
    client = FakeSupabaseClient({
        "chat_sessions": [dict(PRIVATE_SESSION), dict(TEAM_SESSION)],
        "chat_session_participants": [
            {"id": "part-1", "session_id": "sess-team", "user_id": OWNER_ID, "created_at": "2026-08-01T00:00:00Z"},
        ],
    })
    monkeypatch.setattr(db, "get_supabase", lambda: client)
    return client


def test_get_chat_session_owner_can_access_private(fake_db):
    result = db.get_chat_session("sess-private", WORKSPACE_ID, OWNER_ID)
    assert result is not None
    assert result["id"] == "sess-private"


def test_get_chat_session_blocks_other_user_from_private(fake_db):
    result = db.get_chat_session("sess-private", WORKSPACE_ID, OTHER_USER_ID)
    assert result is None


def test_get_chat_session_allows_team_session_for_participant(fake_db):
    result = db.get_chat_session("sess-team", WORKSPACE_ID, OWNER_ID)
    assert result is not None
    assert result["id"] == "sess-team"


def test_get_chat_session_blocks_non_participant_from_team(fake_db):
    """team이라고 워크스페이스 멤버 전체가 아니라, chat_session_participants에 있는
    사람만 접근할 수 있다(2026-08-05 참여자 관리 기능)."""
    result = db.get_chat_session("sess-team", WORKSPACE_ID, OTHER_USER_ID)
    assert result is None


def test_list_chat_sessions_mine_returns_only_own_private(fake_db):
    result = db.list_chat_sessions(WORKSPACE_ID, OWNER_ID, "mine")
    assert [r["id"] for r in result] == ["sess-private"]


def test_list_chat_sessions_mine_excludes_others_private(fake_db):
    result = db.list_chat_sessions(WORKSPACE_ID, OTHER_USER_ID, "mine")
    assert result == []


def test_list_chat_sessions_team_visible_to_participant(fake_db):
    result = db.list_chat_sessions(WORKSPACE_ID, OWNER_ID, "team")
    assert [r["id"] for r in result] == ["sess-team"]


def test_list_chat_sessions_team_excludes_non_participant(fake_db):
    result = db.list_chat_sessions(WORKSPACE_ID, OTHER_USER_ID, "team")
    assert result == []


def test_list_chat_sessions_excludes_deleted(fake_db):
    db.soft_delete_chat_session("sess-team")

    result = db.list_chat_sessions(WORKSPACE_ID, OWNER_ID, "team")

    assert result == []


def test_get_chat_session_returns_none_for_deleted(fake_db):
    db.soft_delete_chat_session("sess-private")

    result = db.get_chat_session("sess-private", WORKSPACE_ID, OWNER_ID)

    assert result is None


def test_set_chat_session_archived_toggles(fake_db):
    archived = db.set_chat_session_archived("sess-private", archived=True)
    assert archived["archived_at"] is not None

    unarchived = db.set_chat_session_archived("sess-private", archived=False)
    assert unarchived["archived_at"] is None


def test_list_chat_sessions_still_includes_archived(fake_db):
    """보관은 숨김이 아니다 — 목록에서 빠지는 건 삭제된 세션뿐이다."""
    db.set_chat_session_archived("sess-team", archived=True)

    result = db.list_chat_sessions(WORKSPACE_ID, OWNER_ID, "team")

    assert [r["id"] for r in result] == ["sess-team"]


# ---------------------------------------------------------------------------
# 1c. 참여자 관리 — add/remove/list, create_chat_session의 자동 참여자 등록
# ---------------------------------------------------------------------------

def test_create_chat_session_team_auto_adds_creator_as_participant(fake_db):
    session = db.create_chat_session(WORKSPACE_ID, OTHER_USER_ID, title="새 대화", visibility="team")

    assert db.is_chat_session_participant(session["id"], OTHER_USER_ID)


def test_create_chat_session_private_does_not_add_participant_row(fake_db):
    session = db.create_chat_session(WORKSPACE_ID, OTHER_USER_ID, title="개인", visibility="private")

    assert fake_db._data["chat_session_participants"] == [
        {"id": "part-1", "session_id": "sess-team", "user_id": OWNER_ID, "created_at": "2026-08-01T00:00:00Z"},
    ]
    assert not db.is_chat_session_participant(session["id"], OTHER_USER_ID)


def test_add_chat_session_participant_then_gains_access(fake_db):
    assert not db.is_chat_session_participant("sess-team", OTHER_USER_ID)

    db.add_chat_session_participant("sess-team", OTHER_USER_ID)

    assert db.is_chat_session_participant("sess-team", OTHER_USER_ID)
    assert db.get_chat_session("sess-team", WORKSPACE_ID, OTHER_USER_ID) is not None


def test_add_chat_session_participant_is_idempotent(fake_db):
    db.add_chat_session_participant("sess-team", OTHER_USER_ID)
    db.add_chat_session_participant("sess-team", OTHER_USER_ID)

    rows = [r for r in fake_db._data["chat_session_participants"] if r["user_id"] == OTHER_USER_ID]
    assert len(rows) == 1


def test_remove_chat_session_participant_revokes_access(fake_db):
    db.remove_chat_session_participant("sess-team", OWNER_ID)

    assert not db.is_chat_session_participant("sess-team", OWNER_ID)
    assert db.get_chat_session("sess-team", WORKSPACE_ID, OWNER_ID) is None


def test_list_chat_session_participants_flattens_display_name_key(fake_db):
    """FakeQuery는 PostgREST embed 조인을 실제로 흉내내지 않아서(profiles 서브셀렉트는
    항상 빈 값) display_name 값 자체는 여기서 검증 못 한다 — _flatten_display_name이
    profiles를 display_name 키로 펼치는 계약만 확인한다."""
    result = db.list_chat_session_participants("sess-team")

    assert result[0]["user_id"] == OWNER_ID
    assert "display_name" in result[0]
    assert "profiles" not in result[0]


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

    # 실제 OpenRouter를 부르지 않게 막는다 — 제목 생성 자체는 별도 테스트에서 확인한다.
    monkeypatch.setattr(main_module, "generate_session_title", lambda question, answer: None)
    title_calls: list[str] = []
    monkeypatch.setattr(db, "update_chat_session_title", lambda session_id, title: title_calls.append(session_id))

    return {
        "create_calls": create_calls,
        "copy_calls": copy_calls,
        "citation_calls": citation_calls,
        "citation_copy_calls": citation_copy_calls,
        "title_calls": title_calls,
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
    # 기존 세션으로 공유한 거라 제목을 새로 안 붙인다.
    assert share_setup["title_calls"] == []


def test_share_to_team_new_session_gets_generated_title(make_client, share_setup, monkeypatch):
    captured = {}

    def fake_generate_title(question, answer):
        captured["args"] = (question, answer)
        return "HBM4 주간 정리"

    monkeypatch.setattr(main_module, "generate_session_title", fake_generate_title)

    titled: list[tuple[str, str]] = []
    monkeypatch.setattr(db, "update_chat_session_title", lambda session_id, title: titled.append((session_id, title)))

    res = make_client(OWNER_ID).post(
        f"/chat/sessions/{PRIVATE_SESSION['id']}/messages/{ASSISTANT_MESSAGE['id']}/share-to-team"
    )

    assert res.status_code == 200
    assert captured["args"] == (USER_QUESTION["content"], ASSISTANT_MESSAGE["content"])
    assert titled == [("new-team-session", "HBM4 주간 정리")]


def test_share_to_team_title_generation_failure_does_not_break_response(make_client, share_setup, monkeypatch):
    """generate_session_title이 None을 돌려주면(LLM 실패 등) 제목은 그냥 플레이스홀더로 남고,
    공유 자체는 정상적으로 끝나야 한다."""
    monkeypatch.setattr(main_module, "generate_session_title", lambda question, answer: None)
    titled: list[str] = []
    monkeypatch.setattr(db, "update_chat_session_title", lambda session_id, title: titled.append(session_id))

    res = make_client(OWNER_ID).post(
        f"/chat/sessions/{PRIVATE_SESSION['id']}/messages/{ASSISTANT_MESSAGE['id']}/share-to-team"
    )

    assert res.status_code == 200
    assert titled == []


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


# ---------------------------------------------------------------------------
# 다시 생성(regenerate) — 같은 질문으로 Agent를 다시 불러 답변을 그 자리에서 교체
# ---------------------------------------------------------------------------

@pytest.fixture
def regenerate_setup(monkeypatch):
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: PRIVATE_SESSION if uid == OWNER_ID else None)
    monkeypatch.setattr(db, "get_chat_message", lambda mid: ASSISTANT_MESSAGE if mid == ASSISTANT_MESSAGE["id"] else None)
    monkeypatch.setattr(db, "get_preceding_user_message", lambda sid, before: USER_QUESTION)
    monkeypatch.setattr(db, "list_chat_messages", lambda sid: [USER_QUESTION, ASSISTANT_MESSAGE])
    monkeypatch.setattr(main_module, "WikiAgent", FakeAgent)

    calls: list[tuple[str, object]] = []

    def fake_update_agent_message(message_id, result, prompt_version="v1"):
        calls.append((message_id, result))
        return {**ASSISTANT_MESSAGE, "content": result.answer}

    monkeypatch.setattr(db, "update_agent_message", fake_update_agent_message)
    monkeypatch.setattr(db, "list_message_citations", lambda mid: [])
    return {"calls": calls}


def test_regenerate_replaces_message_in_place(make_client, regenerate_setup):
    res = make_client(OWNER_ID).post(
        f"/chat/sessions/{PRIVATE_SESSION['id']}/messages/{ASSISTANT_MESSAGE['id']}/regenerate"
    )

    assert res.status_code == 200
    body = res.json()
    assert body["id"] == ASSISTANT_MESSAGE["id"]
    assert body["content"] == "HBM4는 차세대 메모리다."

    assert len(regenerate_setup["calls"]) == 1
    called_message_id, result = regenerate_setup["calls"][0]
    assert called_message_id == ASSISTANT_MESSAGE["id"]
    assert result.answer == "HBM4는 차세대 메모리다."


def test_regenerate_excludes_target_pair_from_agent_history(make_client, monkeypatch, regenerate_setup):
    """재답변할 때 옛 질문/답변 쌍을 이력에 다시 넣으면 Agent가 자기 옛 답을 참고하게 되므로,
    history에서 반드시 빠져야 한다."""
    captured = {}

    class CapturingFakeAgent(FakeAgent):
        def answer(self, content, history=None):
            captured["content"] = content
            captured["history"] = history
            return super().answer(content, history=history)

    monkeypatch.setattr(main_module, "WikiAgent", CapturingFakeAgent)
    monkeypatch.setattr(
        db, "list_chat_messages",
        lambda sid: [USER_QUESTION, ASSISTANT_MESSAGE, {**USER_QUESTION, "id": "other-msg", "content": "다른 질문"}],
    )

    res = make_client(OWNER_ID).post(
        f"/chat/sessions/{PRIVATE_SESSION['id']}/messages/{ASSISTANT_MESSAGE['id']}/regenerate"
    )

    assert res.status_code == 200
    assert captured["content"] == USER_QUESTION["content"]
    assert [h["content"] for h in captured["history"]] == ["다른 질문"]


def test_regenerate_without_matching_question_returns_404(make_client, monkeypatch, regenerate_setup):
    monkeypatch.setattr(db, "get_preceding_user_message", lambda sid, before: None)

    res = make_client(OWNER_ID).post(
        f"/chat/sessions/{PRIVATE_SESSION['id']}/messages/{ASSISTANT_MESSAGE['id']}/regenerate"
    )

    assert res.status_code == 404
    assert regenerate_setup["calls"] == []


def test_regenerate_blocked_for_non_owner(make_client, regenerate_setup):
    res = make_client(OTHER_USER_ID).post(
        f"/chat/sessions/{PRIVATE_SESSION['id']}/messages/{ASSISTANT_MESSAGE['id']}/regenerate"
    )

    assert res.status_code == 404
    assert regenerate_setup["calls"] == []


# ---------------------------------------------------------------------------
# 질문/답변 쌍 완전 삭제 — DELETE /chat/sessions/{id}/messages/{id}
# (정상 답변/근거 부족 답변 모두 대상 — 이미 위키·팀 공유로 복사된 게 있으면 그건
# 별도 행이라 원본을 지워도 영향받지 않는다)
# ---------------------------------------------------------------------------

@pytest.fixture
def delete_message_setup(monkeypatch):
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: PRIVATE_SESSION if uid == OWNER_ID else None)
    monkeypatch.setattr(db, "get_chat_message", lambda mid: ASSISTANT_MESSAGE if mid == ASSISTANT_MESSAGE["id"] else None)
    monkeypatch.setattr(db, "get_preceding_user_message", lambda sid, before: USER_QUESTION)

    calls: list[str] = []
    monkeypatch.setattr(db, "delete_chat_message", lambda mid: calls.append(mid))
    return {"calls": calls}


def test_delete_message_deletes_pair(make_client, delete_message_setup):
    res = make_client(OWNER_ID).delete(
        f"/chat/sessions/{PRIVATE_SESSION['id']}/messages/{ASSISTANT_MESSAGE['id']}"
    )

    assert res.status_code == 204
    assert delete_message_setup["calls"] == [ASSISTANT_MESSAGE["id"], USER_QUESTION["id"]]


def test_delete_no_answer_message_also_deletable(make_client, monkeypatch):
    """근거 부족 응답도 똑같이 삭제 대상이다."""
    no_answer_message = {**ASSISTANT_MESSAGE, "content": "[근거 부족] 관련 근거를 찾지 못했습니다."}
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: PRIVATE_SESSION if uid == OWNER_ID else None)
    monkeypatch.setattr(db, "get_chat_message", lambda mid: no_answer_message if mid == ASSISTANT_MESSAGE["id"] else None)
    monkeypatch.setattr(db, "get_preceding_user_message", lambda sid, before: USER_QUESTION)
    calls: list[str] = []
    monkeypatch.setattr(db, "delete_chat_message", lambda mid: calls.append(mid))

    res = make_client(OWNER_ID).delete(
        f"/chat/sessions/{PRIVATE_SESSION['id']}/messages/{ASSISTANT_MESSAGE['id']}"
    )

    assert res.status_code == 204
    assert calls == [ASSISTANT_MESSAGE["id"], USER_QUESTION["id"]]


def test_delete_message_without_preceding_question_only_deletes_answer(make_client, monkeypatch):
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: PRIVATE_SESSION if uid == OWNER_ID else None)
    monkeypatch.setattr(db, "get_chat_message", lambda mid: ASSISTANT_MESSAGE if mid == ASSISTANT_MESSAGE["id"] else None)
    monkeypatch.setattr(db, "get_preceding_user_message", lambda sid, before: None)
    calls: list[str] = []
    monkeypatch.setattr(db, "delete_chat_message", lambda mid: calls.append(mid))

    res = make_client(OWNER_ID).delete(
        f"/chat/sessions/{PRIVATE_SESSION['id']}/messages/{ASSISTANT_MESSAGE['id']}"
    )

    assert res.status_code == 204
    assert calls == [ASSISTANT_MESSAGE["id"]]


def test_delete_message_blocked_for_non_owner(make_client, delete_message_setup):
    res = make_client(OTHER_USER_ID).delete(
        f"/chat/sessions/{PRIVATE_SESSION['id']}/messages/{ASSISTANT_MESSAGE['id']}"
    )

    assert res.status_code == 404
    assert delete_message_setup["calls"] == []


# ---------------------------------------------------------------------------
# 보관/삭제
# ---------------------------------------------------------------------------

def test_archive_session_owner_can_toggle_private_session(make_client, monkeypatch):
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: PRIVATE_SESSION if uid == OWNER_ID else None)

    captured = {}

    def fake_set_archived(session_id, archived):
        captured["args"] = (session_id, archived)
        return {**PRIVATE_SESSION, "archived_at": "2026-08-05T00:00:00Z" if archived else None}

    monkeypatch.setattr(db, "set_chat_session_archived", fake_set_archived)

    res = make_client(OWNER_ID).patch(f"/chat/sessions/{PRIVATE_SESSION['id']}/archive")

    assert res.status_code == 200
    assert captured["args"] == (PRIVATE_SESSION["id"], True)
    assert res.json()["archived_at"] is not None


def test_archive_session_blocked_for_non_owner_of_private_session(make_client, monkeypatch):
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: PRIVATE_SESSION if uid == OWNER_ID else None)

    res = make_client(OTHER_USER_ID).patch(f"/chat/sessions/{PRIVATE_SESSION['id']}/archive")

    assert res.status_code == 404


def test_archive_session_any_team_member_can_toggle(make_client, monkeypatch):
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: TEAM_SESSION)
    monkeypatch.setattr(
        db, "set_chat_session_archived",
        lambda session_id, archived: {**TEAM_SESSION, "archived_at": "2026-08-05T00:00:00Z" if archived else None},
    )

    res = make_client(OTHER_USER_ID).patch(f"/chat/sessions/{TEAM_SESSION['id']}/archive")

    assert res.status_code == 200
    assert res.json()["archived_at"] is not None


def test_archive_session_unarchives_when_already_archived(make_client, monkeypatch):
    already_archived = {**PRIVATE_SESSION, "archived_at": "2026-08-01T00:00:00Z"}
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: already_archived)

    captured = {}

    def fake_set_archived(session_id, archived):
        captured["args"] = (session_id, archived)
        return {**already_archived, "archived_at": None}

    monkeypatch.setattr(db, "set_chat_session_archived", fake_set_archived)

    res = make_client(OWNER_ID).patch(f"/chat/sessions/{PRIVATE_SESSION['id']}/archive")

    assert res.status_code == 200
    assert captured["args"] == (PRIVATE_SESSION["id"], False)
    assert res.json()["archived_at"] is None


def test_delete_session_creator_can_delete(make_client, monkeypatch):
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: PRIVATE_SESSION)

    calls = []
    monkeypatch.setattr(db, "soft_delete_chat_session", lambda session_id: calls.append(session_id))

    res = make_client(OWNER_ID).delete(f"/chat/sessions/{PRIVATE_SESSION['id']}")

    assert res.status_code == 204
    assert calls == [PRIVATE_SESSION["id"]]


def test_delete_session_blocked_for_non_owner_of_private_session(make_client, monkeypatch):
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: PRIVATE_SESSION if uid == OWNER_ID else None)

    res = make_client(OTHER_USER_ID).delete(f"/chat/sessions/{PRIVATE_SESSION['id']}")

    assert res.status_code == 404


def test_delete_session_blocked_for_non_creator_team_member(make_client, monkeypatch):
    """팀 세션은 보관과 달리, 멤버라고 아무나 지울 수 없다 — 생성자만 가능하다."""
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: TEAM_SESSION)

    calls = []
    monkeypatch.setattr(db, "soft_delete_chat_session", lambda session_id: calls.append(session_id))

    res = make_client(OTHER_USER_ID).delete(f"/chat/sessions/{TEAM_SESSION['id']}")

    assert res.status_code == 403
    assert calls == []


def test_delete_session_creator_can_delete_own_team_session(make_client, monkeypatch):
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: TEAM_SESSION)

    calls = []
    monkeypatch.setattr(db, "soft_delete_chat_session", lambda session_id: calls.append(session_id))

    res = make_client(OWNER_ID).delete(f"/chat/sessions/{TEAM_SESSION['id']}")

    assert res.status_code == 204
    assert calls == [TEAM_SESSION["id"]]


# ---------------------------------------------------------------------------
# send_message — team 세션 첫 메시지 자동 제목
# ---------------------------------------------------------------------------

class FakeAgent:
    """WikiAgent 대역 — LLM/위키 조회 없이 고정된 결과만 돌려준다."""

    def __init__(self, wiki_tools):
        self.wiki_tools = wiki_tools

    def answer(self, content, history=None):
        return type("FakeAgentResult", (), {
            "has_answer": True,
            "answer": "HBM4는 차세대 메모리다.",
            "no_answer_reason": None,
            "model_name": "deepseek/deepseek-v4-flash",
            "citations": [],
        })()


@pytest.fixture
def send_message_setup(monkeypatch):
    monkeypatch.setattr(db, "save_user_message", lambda sid, content, uid: {**USER_QUESTION, "id": "new-user-msg", "session_id": sid})
    monkeypatch.setattr(db, "save_agent_message", lambda sid, result, prompt_version="v1": {**ASSISTANT_MESSAGE, "id": "new-assistant-msg", "session_id": sid})
    monkeypatch.setattr(db, "list_message_citations", lambda mid: [])
    monkeypatch.setattr(main_module, "WikiAgent", FakeAgent)

    titled: list[tuple[str, str]] = []
    monkeypatch.setattr(db, "update_chat_session_title", lambda session_id, title: titled.append((session_id, title)))
    return {"titled": titled}


def test_send_message_first_team_message_triggers_titling(make_client, monkeypatch, send_message_setup):
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: TEAM_SESSION)
    monkeypatch.setattr(db, "list_chat_messages", lambda sid: [])  # 이번 게 처음이라 기록이 없음

    captured = {}

    def fake_generate_title(question, answer):
        captured["args"] = (question, answer)
        return "HBM4 주간 정리"

    monkeypatch.setattr(main_module, "generate_session_title", fake_generate_title)

    res = make_client(OWNER_ID).post(
        f"/chat/sessions/{TEAM_SESSION['id']}/messages", json={"content": "HBM4가 뭐야?"}
    )

    assert res.status_code == 200
    # save_agent_message 목이 ASSISTANT_MESSAGE를 그대로 돌려주므로, 그 content가 넘어간다
    # (FakeAgent.answer()의 반환값 자체는 save_agent_message 안에서만 쓰이는데 여기선 목으로 대체됨).
    assert captured["args"] == ("HBM4가 뭐야?", ASSISTANT_MESSAGE["content"])
    assert send_message_setup["titled"] == [(TEAM_SESSION["id"], "HBM4 주간 정리")]


def test_send_message_non_first_team_message_does_not_retitle(make_client, monkeypatch, send_message_setup):
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: TEAM_SESSION)
    # save_user_message로 새로 넣은 메시지 말고 이미 있던 메시지가 하나 더 있다 = 처음이 아님
    monkeypatch.setattr(db, "list_chat_messages", lambda sid: [USER_QUESTION, {**ASSISTANT_MESSAGE, "id": "old"}])
    monkeypatch.setattr(main_module, "generate_session_title", lambda q, a: "안 불려야 정상")

    res = make_client(OWNER_ID).post(
        f"/chat/sessions/{TEAM_SESSION['id']}/messages", json={"content": "그럼 경쟁사는?"}
    )

    assert res.status_code == 200
    assert send_message_setup["titled"] == []


def test_send_message_private_session_first_message_does_not_retitle(make_client, monkeypatch, send_message_setup):
    """자동 제목은 팀 공유 대화 전용이다 — 개인 대화는 첫 메시지여도 안 건드린다."""
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: PRIVATE_SESSION)
    monkeypatch.setattr(db, "list_chat_messages", lambda sid: [])
    monkeypatch.setattr(main_module, "generate_session_title", lambda q, a: "안 불려야 정상")

    res = make_client(OWNER_ID).post(
        f"/chat/sessions/{PRIVATE_SESSION['id']}/messages", json={"content": "HBM4가 뭐야?"}
    )

    assert res.status_code == 200
    assert send_message_setup["titled"] == []


# ---------------------------------------------------------------------------
# 참여자 관리
# ---------------------------------------------------------------------------

def test_list_participants_endpoint(make_client, monkeypatch):
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: TEAM_SESSION)
    monkeypatch.setattr(
        db, "list_chat_session_participants",
        lambda sid: [{"user_id": OWNER_ID, "display_name": "김주현"}],
    )

    res = make_client(OWNER_ID).get(f"/chat/sessions/{TEAM_SESSION['id']}/participants")

    assert res.status_code == 200
    assert res.json() == [{"user_id": OWNER_ID, "display_name": "김주현"}]


def test_list_participants_blocked_for_non_participant(make_client, monkeypatch):
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: None)

    res = make_client(OTHER_USER_ID).get(f"/chat/sessions/{TEAM_SESSION['id']}/participants")

    assert res.status_code == 404


def test_add_participant_success(make_client, monkeypatch):
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: TEAM_SESSION)
    monkeypatch.setattr(db, "get_default_workspace_id", lambda uid: WORKSPACE_ID)

    calls = []
    monkeypatch.setattr(db, "add_chat_session_participant", lambda sid, uid: calls.append((sid, uid)))
    monkeypatch.setattr(db, "get_profile", lambda uid: {"id": uid, "display_name": "박하늘"})

    res = make_client(OWNER_ID).post(
        f"/chat/sessions/{TEAM_SESSION['id']}/participants", json={"user_id": OTHER_USER_ID}
    )

    assert res.status_code == 201
    assert res.json() == {"user_id": OTHER_USER_ID, "display_name": "박하늘"}
    assert calls == [(TEAM_SESSION["id"], OTHER_USER_ID)]


def test_add_participant_rejects_different_workspace(make_client, monkeypatch):
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: TEAM_SESSION)

    def fake_get_default_workspace_id(user_id):
        return WORKSPACE_ID if user_id == OWNER_ID else "other-workspace"

    monkeypatch.setattr(db, "get_default_workspace_id", fake_get_default_workspace_id)

    calls = []
    monkeypatch.setattr(db, "add_chat_session_participant", lambda sid, uid: calls.append((sid, uid)))

    res = make_client(OWNER_ID).post(
        f"/chat/sessions/{TEAM_SESSION['id']}/participants", json={"user_id": OTHER_USER_ID}
    )

    assert res.status_code == 400
    assert calls == []


def test_add_participant_rejected_for_private_session(make_client, monkeypatch):
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: PRIVATE_SESSION)

    res = make_client(OWNER_ID).post(
        f"/chat/sessions/{PRIVATE_SESSION['id']}/participants", json={"user_id": OTHER_USER_ID}
    )

    assert res.status_code == 400


def test_remove_participant_self_allowed(make_client, monkeypatch):
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: TEAM_SESSION)
    calls = []
    monkeypatch.setattr(db, "remove_chat_session_participant", lambda sid, uid: calls.append((sid, uid)))

    res = make_client(OTHER_USER_ID).delete(f"/chat/sessions/{TEAM_SESSION['id']}/participants/{OTHER_USER_ID}")

    assert res.status_code == 204
    assert calls == [(TEAM_SESSION["id"], OTHER_USER_ID)]


def test_remove_participant_others_blocked_for_non_creator(make_client, monkeypatch):
    """TEAM_SESSION의 생성자는 OWNER_ID다 — 다른 참여자가 제3자를 빼려고 하면 막혀야 한다."""
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: TEAM_SESSION)
    calls = []
    monkeypatch.setattr(db, "remove_chat_session_participant", lambda sid, uid: calls.append((sid, uid)))

    res = make_client(OTHER_USER_ID).delete(f"/chat/sessions/{TEAM_SESSION['id']}/participants/{OWNER_ID}")

    assert res.status_code == 403
    assert calls == []


def test_remove_participant_creator_can_remove_others(make_client, monkeypatch):
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: TEAM_SESSION)
    calls = []
    monkeypatch.setattr(db, "remove_chat_session_participant", lambda sid, uid: calls.append((sid, uid)))

    res = make_client(OWNER_ID).delete(f"/chat/sessions/{TEAM_SESSION['id']}/participants/{OTHER_USER_ID}")

    assert res.status_code == 204
    assert calls == [(TEAM_SESSION["id"], OTHER_USER_ID)]


def test_list_workspace_members_endpoint(make_client, monkeypatch):
    monkeypatch.setattr(
        db, "list_workspace_members",
        lambda wid: [{"user_id": OWNER_ID, "display_name": "김주현"}, {"user_id": OTHER_USER_ID, "display_name": "박하늘"}],
    )

    res = make_client(OWNER_ID).get("/workspace/members")

    assert res.status_code == 200
    assert res.json() == [
        {"user_id": OWNER_ID, "display_name": "김주현", "email": None},
        {"user_id": OTHER_USER_ID, "display_name": "박하늘", "email": None},
    ]


def test_list_workspace_members_endpoint_passes_email_through(make_client, monkeypatch):
    """동명이인이면 db.list_workspace_members가 email(전체 이메일 주소)을 채워 주는데,
    엔드포인트가 그 값을 그대로 응답에 실어 보내는지만 확인한다(중복 판별
    로직 자체는 db-레벨 테스트에서 확인)."""
    monkeypatch.setattr(
        db, "list_workspace_members",
        lambda wid: [{"user_id": OWNER_ID, "display_name": "김유빈", "email": "yoobinkim541@gmail.com"}],
    )

    res = make_client(OWNER_ID).get("/workspace/members")

    assert res.status_code == 200
    assert res.json() == [{"user_id": OWNER_ID, "display_name": "김유빈", "email": "yoobinkim541@gmail.com"}]


def test_list_workspace_members_adds_email_only_for_duplicate_names(fake_db, monkeypatch):
    fake_db._data["workspace_members"] = [
        {"workspace_id": WORKSPACE_ID, "user_id": "u1", "profiles": {"display_name": "김유빈"}},
        {"workspace_id": WORKSPACE_ID, "user_id": "u2", "profiles": {"display_name": "김유빈"}},
        {"workspace_id": WORKSPACE_ID, "user_id": "u3", "profiles": {"display_name": "박하늘"}},
    ]

    calls: list[str] = []

    def fake_email(user_id):
        calls.append(user_id)
        return f"{user_id}@example.com"

    monkeypatch.setattr(db, "_get_email", fake_email)

    result = db.list_workspace_members(WORKSPACE_ID)

    by_id = {r["user_id"]: r for r in result}
    assert by_id["u1"]["email"] == "u1@example.com"
    assert by_id["u2"]["email"] == "u2@example.com"
    assert by_id["u3"]["email"] is None
    assert sorted(calls) == ["u1", "u2"]

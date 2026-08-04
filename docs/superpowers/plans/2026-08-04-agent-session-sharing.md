# 에이전트 팀/개인 세션 실연결 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 에이전트 페이지의 "팀 공유 / 내 에이전트" 탭이 mock 데이터 대신 이미 배포된 백엔드(GET /chat/sessions, share-to-team, save-to-wiki)를 실제로 사용하게 만들고, 팀 대화 작성자 표시·공유 대상 세션 선택 기능을 추가해 머지·배포·실사용자 테스트까지 완료한다.

**Architecture:** 백엔드는 `chat_messages.user_id` 컬럼 추가 + `share-to-team`이 대상 세션을 받도록 확장하는 최소 변경만 하고(엔드포인트는 이미 다 있음), 프론트는 `agentApi.js`의 mock 반환을 실제 API 호출로 교체한다. 백엔드(`develop`)와 프론트(`develop-frontend`)는 별도 브랜치/워크트리에서 독립적으로 작업하고 순서대로 머지한다(백엔드 먼저 — 프론트가 새 필드를 바로 쓸 수 있어야 함).

**Tech Stack:** FastAPI + Supabase(Postgres) 백엔드, React + Vite 프론트, pytest(monkeypatch 기반, 실제 네트워크 없음).

## Global Constraints

- 브랜치명: `feature/<주제>`, 커밋 메시지: `Feat: ...`/`Fix: ...`/`Docs: ...` (collaboration_rule.md)
- PR 본문은 작업내용/변경이유/테스트결과/참고사항/관련Issue 섹션 포함
- 머지는 `gh pr merge --squash`만 사용(이 저장소는 merge commit 비허용)
- 브랜치 push 전 `gh pr list --state open`으로 병렬 세션과의 중복 확인
- CI/CD 시크릿(GitHub/Vercel)은 직접 등록하지 않음 — 이번 작업은 새 시크릿이 필요 없음
- DB 마이그레이션은 Supabase MCP `apply_migration`으로 라이브 DB에 직접 적용 + 같은 SQL을 `supabase/migrations/`에 커밋
- 스키마 변경 시 ERDCloud 다이어그램(`https://www.erdcloud.com/d/qgLNBqodLMJAqG9FG`)도 같이 동기화
- 백엔드는 `develop` push 시 GitHub Actions로 Oracle VM에 자동 배포, 프론트는 `develop-frontend` push 시 Vercel이 자동 배포 — 별도 수동 배포 단계 없음, 머지 후 라이브에서 확인만 하면 됨
- 라이브 주소: 프론트 https://mywiki.pe.kr , 백엔드 https://api.mywiki.pe.kr
- 웹 검색 도구, "복사"/"다시 생성" 버튼 연결, 에이전트 컨텍스트/멀티문서 튜닝은 이번 계획의 범위 밖(별도 브레인스토밍 예정)

---

## 백엔드 (이 워크트리, `develop` 기반)

### Task 1: `chat_messages.user_id` DB 마이그레이션 + ERD 동기화

**Files:**
- Create: `supabase/migrations/20260804010000_add_chat_messages_user_id.sql`

**Interfaces:**
- Produces: `chat_messages.user_id` (uuid, nullable, FK → `profiles.id`) — 이후 모든 백엔드 태스크가 이 컬럼에 의존

- [ ] **Step 1: 브랜치 준비**

```bash
git fetch origin
git checkout -b feature/agent-session-sharing origin/develop
git cherry-pick fb6c7eb
```

(`fb6c7eb`는 이 워크트리의 `claude/social-login-api-integration-dc6deb` 브랜치에 이미 커밋된 스펙 문서 — 새 브랜치에도 가져온다. 커밋 해시가 다르면 `git log --oneline -- docs/superpowers/specs/2026-08-04-agent-session-sharing-design.md`로 실제 해시를 확인해서 대체한다.)

- [ ] **Step 2: 마이그레이션 파일 작성**

```sql
-- supabase/migrations/20260804010000_add_chat_messages_user_id.sql
ALTER TABLE public.chat_messages
  ADD COLUMN user_id uuid REFERENCES public.profiles(id);
```

- [ ] **Step 3: Supabase MCP로 라이브 DB에 적용**

`mcp__supabase__apply_migration` 도구로 project_id `uhzjshqmnlahhvqzygkp`에 위 SQL을 이름 `add_chat_messages_user_id`로 적용한다.

- [ ] **Step 4: 적용 확인**

```sql
select column_name, data_type, is_nullable
from information_schema.columns
where table_name = 'chat_messages'
order by ordinal_position;
```

`user_id`(uuid, YES) 행이 추가됐는지 확인한다.

- [ ] **Step 5: ERDCloud 동기화**

`chat_messages` 테이블(다이어그램 `https://www.erdcloud.com/d/qgLNBqodLMJAqG9FG`)에 `mcp__erdcloud__create_relation`으로 `childTableId=<chat_messages 테이블 id>`, `parentTableId=<profiles 테이블 id>`, `cardinality=ZERO_OR_MANY` 관계를 만든다. `create_relation`은 항상 새 FK 컬럼을 자동 생성하므로(예: `id2`), 먼저 `mcp__erdcloud__list_tables`로 `chat_messages`에 이미 있는 컬럼 목록·id를 확인한 뒤 `update_column`으로 자동 생성된 컬럼 이름을 `user_id`로 바꾼다(`push_subscriptions` 작업 때와 동일한 절차 — [[erdcloud-mcp]] 메모 참고).

- [ ] **Step 6: 커밋**

```bash
git add supabase/migrations/20260804010000_add_chat_messages_user_id.sql
git commit -m "$(cat <<'EOF'
Feat: chat_messages에 user_id 컬럼 추가

팀 공유 대화에서 각 질문을 누가 보냈는지 표시하기 위해 작성자를
기록할 컬럼이 필요하다. 과거 행은 작성자 불명으로 남긴다(nullable).
EOF
)"
```

---

### Task 2: `src/api/db.py` — 작성자 저장/조회

**Files:**
- Modify: `src/api/db.py:49-95` (`create_chat_session` 아래, `save_user_message`/`get_or_create_team_session` 자리)

**Interfaces:**
- Consumes: Task 1의 `chat_messages.user_id` 컬럼
- Produces: `save_user_message(session_id: str, content: str, user_id: str) -> dict`, `copy_chat_message(target_session_id: str, message: dict) -> dict`(user_id 보존), `get_display_names(user_ids: list[str]) -> dict[str, str]` — Task 4(main.py)가 그대로 씀. `get_or_create_team_session`은 삭제(더 이상 호출하는 곳이 없어짐 — Task 4에서 대체).

- [ ] **Step 1: `save_user_message`에 `user_id` 파라미터 추가**

`src/api/db.py:134-146`을 다음으로 교체:

```python
def save_user_message(session_id: str, content: str, user_id: str) -> dict:
    res = (
        get_supabase()
        .table("chat_messages")
        .insert({
            "session_id": session_id,
            "role": "user",
            "content": content,
            "user_id": user_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        .execute()
    )
    return res.data[0]
```

- [ ] **Step 2: `copy_chat_message`이 `user_id`도 복사하게 수정**

`src/api/db.py:240-254`을 다음으로 교체:

```python
def copy_chat_message(target_session_id: str, message: dict) -> dict:
    res = (
        get_supabase()
        .table("chat_messages")
        .insert({
            "session_id": target_session_id,
            "role": message["role"],
            "content": message["content"],
            "model_name": message.get("model_name"),
            "prompt_version": message.get("prompt_version"),
            "user_id": message.get("user_id"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        .execute()
    )
    return res.data[0]
```

- [ ] **Step 3: `get_or_create_team_session` 삭제**

`src/api/db.py:80-95`의 `get_or_create_team_session` 함수 전체를 삭제한다(Task 4에서 `share_message_to_team`이 `create_chat_session`을 직접 쓰도록 바뀌면서 더 이상 호출되지 않음).

- [ ] **Step 4: `get_display_names` 추가**

`get_or_create_team_session`이 있던 자리에 추가:

```python
def get_display_names(user_ids: list[str]) -> dict[str, str]:
    """user_id -> display_name. 값이 없거나(비어있는 이름) 조회 안 되는 id는 매핑에서 빠진다."""
    ids = list({uid for uid in user_ids if uid})
    if not ids:
        return {}
    res = get_supabase().table("profiles").select("id,display_name").in_("id", ids).execute()
    return {row["id"]: row["display_name"] for row in res.data if row.get("display_name")}
```

- [ ] **Step 5: 커밋**

```bash
git add src/api/db.py
git commit -m "$(cat <<'EOF'
Feat: chat_messages 작성자 저장/조회 함수 추가

save_user_message/copy_chat_message가 user_id를 같이 다루도록 하고,
여러 메시지의 작성자 이름을 한 번에 조회하는 get_display_names를 추가.
더 이상 쓰이지 않는 get_or_create_team_session은 제거.
EOF
)"
```

---

### Task 3: `src/api/schemas.py` — 응답/요청 스키마 추가

**Files:**
- Modify: `src/api/schemas.py:37-53` (`ChatMessageOut`)
- Modify: `src/api/schemas.py` 끝부분 (새 요청 스키마 추가)

**Interfaces:**
- Produces: `ChatMessageOut.author_name: Optional[str]`, `ShareToTeamRequest(target_session_id: Optional[str] = None)` — Task 4가 사용

- [ ] **Step 1: `ChatMessageOut`에 `author_name` 추가**

`src/api/schemas.py:37-45`의 `ChatMessageOut`을 다음으로 교체:

```python
class ChatMessageOut(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    model_name: Optional[str] = None
    prompt_version: Optional[str] = None
    author_name: Optional[str] = None
    created_at: datetime
    citations: list[CitationOut] = []
```

- [ ] **Step 2: `ShareToTeamRequest` 추가**

파일 끝에 추가:

```python
# ---------------------------------------------------------------------------
# 팀 공유 — POST /chat/sessions/{id}/messages/{message_id}/share-to-team 전용
# ---------------------------------------------------------------------------

class ShareToTeamRequest(BaseModel):
    target_session_id: Optional[str] = None
```

- [ ] **Step 3: 커밋**

```bash
git add src/api/schemas.py
git commit -m "$(cat <<'EOF'
Feat: 채팅 메시지 작성자 표시 및 팀 공유 대상 선택용 스키마 추가
EOF
)"
```

---

### Task 4: `src/api/main.py` — 엔드포인트 연결

**Files:**
- Modify: `src/api/main.py:17-25` (import)
- Modify: `src/api/main.py:51-53` (`_to_message_out`)
- Modify: `src/api/main.py:70-109` (`get_messages`, `send_message`)
- Modify: `src/api/main.py:126-142` (`share_message_to_team`)

**Interfaces:**
- Consumes: `db.save_user_message(session_id, content, user_id)`, `db.copy_chat_message`, `db.get_display_names(user_ids)`, `schemas.ShareToTeamRequest`
- Produces: `GET/POST /chat/sessions/{id}/messages` 응답에 `author_name` 포함, `POST .../share-to-team`이 body로 `target_session_id`를 받음

- [ ] **Step 1: import에 `ShareToTeamRequest` 추가**

`src/api/main.py:17-25`:

```python
from .schemas import (
    ChatMessageOut,
    ChatSessionOut,
    CitationOut,
    CreateSessionRequest,
    SaveToWikiResponse,
    SendMessageRequest,
    SendMessageResponse,
    ShareToTeamRequest,
)
```

- [ ] **Step 2: `_to_message_out`이 작성자 이름을 받게 수정**

`src/api/main.py:51-53`을 다음으로 교체(`**message`로 통째로 펼치던 걸 명시적 필드 나열로 바꿔서, `message` dict에 이제 들어있는 `user_id` 키가 `ChatMessageOut`에 정의 안 된 필드로 새는 걸 막는다):

```python
def _to_message_out(message: dict, author_names: dict[str, str]) -> ChatMessageOut:
    citations = db.list_message_citations(message["id"]) if message["role"] == "assistant" else []
    author_name = author_names.get(message.get("user_id")) if message["role"] == "user" else None
    return ChatMessageOut(
        id=message["id"],
        session_id=message["session_id"],
        role=message["role"],
        content=message["content"],
        model_name=message.get("model_name"),
        prompt_version=message.get("prompt_version"),
        author_name=author_name,
        created_at=message["created_at"],
        citations=[CitationOut(**c) for c in citations],
    )
```

- [ ] **Step 3: `get_messages`가 작성자 이름을 채워서 반환**

`src/api/main.py:70-78`을 다음으로 교체:

```python
@app.get("/chat/sessions/{session_id}/messages", response_model=list[ChatMessageOut])
def get_messages(session_id: str, profile: dict = Depends(get_current_user)):
    workspace_id = _require_workspace(profile)
    session = db.get_chat_session(session_id, workspace_id, profile["id"])
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="세션을 찾을 수 없음")

    messages = db.list_chat_messages(session_id)
    author_names = db.get_display_names([m["user_id"] for m in messages if m.get("user_id")])
    return [_to_message_out(m, author_names) for m in messages]
```

- [ ] **Step 4: `send_message`가 `user_id`를 저장하고 응답에 작성자 이름을 채움**

`src/api/main.py:81-109`을 다음으로 교체:

```python
@app.post("/chat/sessions/{session_id}/messages", response_model=SendMessageResponse)
def send_message(
    session_id: str, body: SendMessageRequest, profile: dict = Depends(get_current_user)
):
    workspace_id = _require_workspace(profile)
    session = db.get_chat_session(session_id, workspace_id, profile["id"])
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="세션을 찾을 수 없음")

    user_message = db.save_user_message(session_id, body.content, profile["id"])
    author_names = {profile["id"]: profile.get("display_name")}

    # 이전 대화 이력을 Agent에게 넘겨서 멀티턴 맥락을 유지한다.
    history = [
        {"role": "user" if m["role"] == "user" else "assistant", "content": m["content"]}
        for m in db.list_chat_messages(session_id)
        if m["id"] != user_message["id"]
    ]

    wiki_tools = WikiTools(workspace_id=workspace_id)
    agent = WikiAgent(wiki_tools)
    result = agent.answer(body.content, history=history)

    assistant_message = db.save_agent_message(session_id, result)

    return SendMessageResponse(
        user_message=_to_message_out(user_message, author_names),
        assistant_message=_to_message_out(assistant_message, author_names),
        has_answer=result.has_answer,
    )
```

- [ ] **Step 5: `share_message_to_team`이 대상 세션을 받도록 수정**

`src/api/main.py:126-142`을 다음으로 교체:

```python
@app.post("/chat/sessions/{session_id}/messages/{message_id}/share-to-team", response_model=ChatMessageOut)
def share_message_to_team(
    session_id: str,
    message_id: str,
    body: ShareToTeamRequest = ShareToTeamRequest(),
    profile: dict = Depends(get_current_user),
):
    workspace_id = _require_workspace(profile)
    message = _get_owned_message(session_id, message_id, workspace_id, profile["id"])

    user_message = db.get_preceding_user_message(session_id, message["created_at"])
    if user_message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="짝이 되는 질문 메시지를 찾을 수 없음")

    if body.target_session_id:
        team_session = db.get_chat_session(body.target_session_id, workspace_id, profile["id"])
        if team_session is None or team_session["visibility"] != "team":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="공유 대상 팀 세션을 찾을 수 없음")
    else:
        team_session = db.create_chat_session(workspace_id, profile["id"], title="팀 공유 대화", visibility="team")

    db.copy_chat_message(team_session["id"], user_message)
    copied_assistant = db.copy_chat_message(team_session["id"], message)

    citations = db.list_message_citations(message_id)
    db.copy_message_citations(copied_assistant["id"], citations)

    return _to_message_out(copied_assistant, {})
```

(`save_message_to_wiki`, `_get_owned_message`는 변경 없음 — 그대로 둔다.)

- [ ] **Step 6: 커밋**

```bash
git add src/api/main.py
git commit -m "$(cat <<'EOF'
Feat: 채팅 메시지 응답에 작성자 표시 + 팀 공유 대상 세션 선택 지원

share-to-team이 target_session_id를 받아 사용자가 고른 팀 세션으로
공유하고, 미지정 시 새 팀 세션을 만든다. 기존처럼 가장 오래된 팀
세션으로 암묵적으로 몰아넣던 동작은 제거.
EOF
)"
```

---

### Task 5: 기존 테스트 갱신 + 신규 테스트 작성

**Files:**
- Modify: `tests/test_chat_sessions.py`

**Interfaces:**
- Consumes: Task 2~4의 모든 시그니처 변경

- [ ] **Step 1: 실패 확인(변경 전 테스트가 새 시그니처와 안 맞아 깨지는지)**

```bash
pytest tests/test_chat_sessions.py -v
```

Expected: `test_share_to_team_copies_message_pair_and_citations`가 `db.get_or_create_team_session` 관련 monkeypatch 대상이 없어져서 실패(AttributeError 또는 실제 Supabase 호출 시도).

- [ ] **Step 2: `share_setup` 픽스처 및 관련 테스트를 새 동작에 맞게 교체**

`tests/test_chat_sessions.py:239-309`(`share_setup` 픽스처부터 파일 끝까지)를 다음으로 교체:

```python
@pytest.fixture
def share_setup(monkeypatch):
    def fake_get_chat_session(sid, wid, uid):
        if sid == PRIVATE_SESSION["id"]:
            return PRIVATE_SESSION if uid == OWNER_ID else None
        if sid == "team-session-1":
            return {**TEAM_SESSION, "id": "team-session-1"}
        return None

    monkeypatch.setattr(db, "get_chat_session", fake_get_chat_session)
    monkeypatch.setattr(db, "get_chat_message", lambda mid: ASSISTANT_MESSAGE if mid == ASSISTANT_MESSAGE["id"] else None)
    monkeypatch.setattr(db, "get_preceding_user_message", lambda sid, before: USER_QUESTION)

    created_sessions: list[dict] = []

    def fake_create_chat_session(workspace_id, user_id, title=None, visibility="private"):
        session = {**TEAM_SESSION, "id": "new-team-session", "title": title, "visibility": visibility}
        created_sessions.append(session)
        return session

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
        "copy_calls": copy_calls,
        "citation_calls": citation_calls,
        "citation_copy_calls": citation_copy_calls,
        "created_sessions": created_sessions,
    }


def test_share_to_team_with_target_session_copies_message_pair_and_citations(make_client, share_setup):
    res = make_client(OWNER_ID).post(
        f"/chat/sessions/{PRIVATE_SESSION['id']}/messages/{ASSISTANT_MESSAGE['id']}/share-to-team",
        json={"target_session_id": "team-session-1"},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["id"] == "copied-assistant"
    assert body["role"] == "assistant"
    assert body["content"] == ASSISTANT_MESSAGE["content"]
    assert body["citations"][0]["document_version_id"] == "dv-1"

    assert share_setup["copy_calls"] == [("team-session-1", "user"), ("team-session-1", "assistant")]
    assert share_setup["citation_calls"] == [ASSISTANT_MESSAGE["id"], "copied-assistant"]
    assert share_setup["citation_copy_calls"] == [("copied-assistant", [SAMPLE_CITATION])]
    assert share_setup["created_sessions"] == []


def test_share_to_team_without_target_creates_new_team_session(make_client, share_setup):
    res = make_client(OWNER_ID).post(
        f"/chat/sessions/{PRIVATE_SESSION['id']}/messages/{ASSISTANT_MESSAGE['id']}/share-to-team",
        json={},
    )

    assert res.status_code == 200
    assert len(share_setup["created_sessions"]) == 1
    assert share_setup["created_sessions"][0]["visibility"] == "team"
    assert share_setup["copy_calls"] == [("new-team-session", "user"), ("new-team-session", "assistant")]


def test_share_to_team_rejects_non_team_target_session(make_client, share_setup):
    res = make_client(OWNER_ID).post(
        f"/chat/sessions/{PRIVATE_SESSION['id']}/messages/{ASSISTANT_MESSAGE['id']}/share-to-team",
        json={"target_session_id": PRIVATE_SESSION["id"]},
    )

    assert res.status_code == 404
    assert share_setup["copy_calls"] == []


def test_share_to_team_rejects_unknown_target_session(make_client, share_setup):
    res = make_client(OWNER_ID).post(
        f"/chat/sessions/{PRIVATE_SESSION['id']}/messages/{ASSISTANT_MESSAGE['id']}/share-to-team",
        json={"target_session_id": "unknown-session"},
    )

    assert res.status_code == 404
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
# 작성자 표시 — get_display_names / _to_message_out
# ---------------------------------------------------------------------------

def test_get_display_names_maps_known_ids(fake_db):
    fake_db._data["profiles"] = [
        {"id": OWNER_ID, "display_name": "김주현"},
        {"id": OTHER_USER_ID, "display_name": None},
    ]

    result = db.get_display_names([OWNER_ID, OTHER_USER_ID, "missing-id"])

    assert result == {OWNER_ID: "김주현"}


def test_get_messages_includes_author_name(make_client, monkeypatch):
    monkeypatch.setattr(db, "get_chat_session", lambda sid, wid, uid: PRIVATE_SESSION)
    monkeypatch.setattr(
        db, "list_chat_messages",
        lambda sid: [{**USER_QUESTION, "user_id": OWNER_ID}],
    )
    monkeypatch.setattr(db, "get_display_names", lambda ids: {OWNER_ID: "김주현"})

    res = make_client(OWNER_ID).get(f"/chat/sessions/{PRIVATE_SESSION['id']}/messages")

    assert res.status_code == 200
    assert res.json()[0]["author_name"] == "김주현"
```

`FakeTable.select`이 `.in_()`을 지원하지 않으므로, 파일 상단의 `FakeQuery`에 메서드를 추가한다. `tests/test_chat_sessions.py:64-70`(`eq`/`lt` 정의 사이)에 추가:

```python
    def in_(self, key, values):
        values = set(values)
        self._rows = [r for r in self._rows if r.get(key) in values]
        return self
```

- [ ] **Step 3: 전체 테스트 통과 확인**

```bash
pytest tests/test_chat_sessions.py -v
```

Expected: 전부 PASS.

- [ ] **Step 4: 전체 스위트 회귀 확인**

```bash
pytest -q
```

Expected: 기존에 통과하던 다른 테스트 파일들도 그대로 PASS(이번 변경이 건드린 함수를 참조하는 다른 파일이 없음을 앞서 grep으로 확인함).

- [ ] **Step 5: 커밋**

```bash
git add tests/test_chat_sessions.py
git commit -m "$(cat <<'EOF'
Test: 팀 공유 대상 세션 선택 및 작성자 표시 테스트 추가
EOF
)"
```

---

### Task 6: 백엔드 PR 생성 → 머지 → 배포 확인

**Files:** 없음(git/gh 작업)

- [ ] **Step 1: 중복 작업 확인 후 푸시**

```bash
gh pr list --state open
git push -u origin feature/agent-session-sharing
```

- [ ] **Step 2: PR 생성**

```bash
gh pr create --base develop --title "Feat: 에이전트 팀/개인 세션 실연결 — 백엔드" --body "$(cat <<'EOF'
## 작업내용
- chat_messages.user_id 컬럼 추가(팀 공유 대화 작성자 표시용)
- GET /chat/sessions/{id}/messages, POST .../messages 응답에 author_name 포함
- POST .../share-to-team이 target_session_id를 받아 사용자가 고른 팀 세션으로 공유(미지정 시 새로 생성) — 기존 "가장 오래된 팀 세션으로 암묵 병합" 동작 제거

## 변경이유
에이전트 페이지의 팀/개인 세션 실연결 작업(docs/superpowers/specs/2026-08-04-agent-session-sharing-design.md) 중 백엔드 부분. 프론트가 mock 대신 실제 API를 쓰려면 팀 대화 작성자 정보와, 공유 대상을 고를 수 있는 API가 필요함.

## 테스트결과
pytest tests/test_chat_sessions.py -v 전체 통과, pytest -q 전체 스위트 회귀 없음

## 참고사항
ERDCloud에 chat_messages.user_id -> profiles.id 관계 반영 완료. 프론트 쪽(develop-frontend) 작업은 이 PR 머지 후 별도 PR로 진행.

## 관련Issue
없음
EOF
)"
```

- [ ] **Step 3: 머지**

```bash
gh pr merge --squash
```

- [ ] **Step 4: 배포 확인**

```bash
gh run list --workflow=deploy-backend.yml --limit 3
```

Expected: `develop` push로 트리거된 배포 실행이 `success`. 완료 후:

```bash
curl -s https://api.mywiki.pe.kr/chat/sessions -H "Authorization: Bearer invalid" -o /dev/null -w "%{http_code}\n"
```

Expected: `401`(서버가 살아있고 인증을 요구함 — 500이 아님을 확인하는 스모크 테스트).

---

## 프론트엔드 (신규 워크트리, `develop-frontend` 기반)

### Task 7: 프론트 워크트리 준비 + `api/agent.js` 확장

**Files:**
- Modify: `frontend/src/api/agent.js`

**Interfaces:**
- Produces: `fetchChatSessions(scope)`, `shareMessageToTeam(sessionId, messageId, targetSessionId)`, `saveMessageToWiki(sessionId, messageId)`, `createChatSession(title, visibility)` — Task 9(`agentApi.js`)가 사용

- [ ] **Step 1: 새 워크트리 생성**

```bash
git fetch origin
git worktree add "C:/Users/asus/Desktop/SK suni myWiki/.claude/worktrees/agent-session-sharing-frontend" -b feature/agent-session-sharing-frontend origin/develop-frontend
cd "C:/Users/asus/Desktop/SK suni myWiki/.claude/worktrees/agent-session-sharing-frontend"
```

(이후 Task 7~12의 모든 작업은 이 워크트리에서 진행한다.)

- [ ] **Step 2: `createChatSession`이 visibility를 받게 수정**

`frontend/src/api/agent.js`의 `createChatSession`을 다음으로 교체:

```js
/** @returns {Promise<{id, workspace_id, user_id, title, created_at, updated_at}>} */
export function createChatSession(title, visibility = 'private') {
  return apiFetch('/chat/sessions', { method: 'POST', body: { title, visibility } });
}
```

- [ ] **Step 3: `fetchChatSessions`/`shareMessageToTeam`/`saveMessageToWiki` 추가**

`frontend/src/api/agent.js` 끝에 추가:

```js
/** @returns {Promise<{id, workspace_id, user_id, title, visibility, created_at, updated_at}[]>} */
export function fetchChatSessions(scope) {
  return apiFetch(`/chat/sessions?scope=${scope}`);
}

/**
 * target_session_id를 생략하면 백엔드가 새 팀 세션을 만들어 그쪽으로 복사한다.
 * @returns {Promise<{id, session_id, role, content, author_name, created_at, citations}>}
 */
export function shareMessageToTeam(sessionId, messageId, targetSessionId) {
  return apiFetch(`/chat/sessions/${sessionId}/messages/${messageId}/share-to-team`, {
    method: 'POST',
    body: targetSessionId ? { target_session_id: targetSessionId } : {},
  });
}

/** @returns {Promise<{page_id, version_id, slug}>} */
export function saveMessageToWiki(sessionId, messageId) {
  return apiFetch(`/chat/sessions/${sessionId}/messages/${messageId}/save-to-wiki`, { method: 'POST' });
}
```

- [ ] **Step 4: 커밋**

```bash
git add frontend/src/api/agent.js
git commit -m "$(cat <<'EOF'
Feat: 채팅 세션 목록 조회·팀 공유·위키 저장 API 클라이언트 추가
EOF
)"
```

---

### Task 8: `TeamShareModal.jsx` 신규 컴포넌트

**Files:**
- Create: `frontend/src/components/agent/TeamShareModal.jsx`

**Interfaces:**
- Consumes: 없음(순수 표시 컴포넌트)
- Produces: `<TeamShareModal open teamSessions onShare(targetSessionIdOrNull) onClose />` — Task 11(`AgentPage.jsx`)이 사용

- [ ] **Step 1: 컴포넌트 작성**

```jsx
// 개인 대화 답변을 어느 팀 공유 세션으로 보낼지 고르는 모달.
// WikiKeywordModal(.mw-scrim/.mw-modal)과 같은 모달 뼈대를 재사용한다.

import { useEffect } from 'react';

export default function TeamShareModal({ open, teamSessions, onShare, onClose }) {
  useEffect(() => {
    if (!open) return;
    function handleKey(e) {
      if (e.key === 'Escape') onClose?.();
    }
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <>
      <div className="mw-scrim open" onClick={onClose}></div>
      <div className="mw-modal open" role="dialog" aria-modal="true" aria-label="팀에 공유">
        <div className="mw-hd">
          <div>
            <div className="eb">팀 공유</div>
            <h3>어느 대화로 공유할까요?</h3>
          </div>
          <button className="mw-x" onClick={onClose} aria-label="닫기">✕</button>
        </div>

        <div className="mw-body">
          <div className="mw-lb">팀 공유 대화</div>
          <div className="kwm-list">
            <button type="button" className="kwm-item" onClick={() => onShare(null)}>
              <span className="tx"><b>+ 새 공유 대화 만들어서 공유</b></span>
            </button>
            {teamSessions.length === 0 ? (
              <div className="kwm-empty">아직 팀 공유 대화가 없습니다.</div>
            ) : (
              teamSessions.map((s) => (
                <button type="button" className="kwm-item" key={s.id} onClick={() => onShare(s.id)}>
                  <span className="tx">
                    <b>{s.title}</b>
                    <span className="s">{s.meta}</span>
                  </span>
                </button>
              ))
            )}
          </div>
        </div>
      </div>
    </>
  );
}
```

- [ ] **Step 2: 커밋**

```bash
git add frontend/src/components/agent/TeamShareModal.jsx
git commit -m "$(cat <<'EOF'
Feat: 팀 공유 대상 세션 선택 모달 추가
EOF
)"
```

---

### Task 9: `agentApi.js` — mock을 실제 API 호출로 교체

**Files:**
- Modify: `frontend/src/services/agentApi.js`

**Interfaces:**
- Consumes: Task 7의 `agentApi.fetchChatSessions/shareMessageToTeam/saveMessageToWiki/createChatSession`
- Produces: `fetchAgentPanes()`, `createConversation(title, visibility)`, `shareMessageToTeam(sessionId, messageId, targetSessionId) -> {message, sessionId}`, `saveMessageToWiki(sessionId, messageId)` — Task 11(`AgentPage.jsx`)이 사용

- [ ] **Step 1: `toViewMessage`가 작성자 정보를 포함하게 수정**

`frontend/src/services/agentApi.js`의 `toViewMessage` 함수에서 `if (role === 'me') { ... }` 블록을 다음으로 교체:

```js
  if (role === 'me') {
    return {
      role: 'me',
      text: msg.content,
      _id: msg.id,
      ...(msg.author_name ? { author: { initial: msg.author_name.charAt(0), name: msg.author_name } } : {}),
    };
  }
```

- [ ] **Step 2: `fetchAgentPanes`가 실제 세션 목록을 불러오게 수정**

`fetchAgentPanes` 함수 전체를 다음으로 교체:

```js
function paneWithSessions(mockPane, sessions) {
  return { ...mockPane, conversations: sessions.map(toViewConversation) };
}

/**
 * 팀/개인 두 pane 전체.
 * 정적 UI 텍스트(라벨/힌트/placeholder 등)는 MOCK_AGENT_PANES를 그대로 재사용하고,
 * conversations만 실제 세션 목록으로 교체한다.
 */
export async function fetchAgentPanes() {
  if (USE_MOCK) return MOCK_AGENT_PANES;

  const [teamSessions, mineSessions] = await Promise.all([
    agentApi.fetchChatSessions('team'),
    agentApi.fetchChatSessions('mine'),
  ]);

  return {
    team: paneWithSessions(MOCK_AGENT_PANES.team, teamSessions),
    mine: paneWithSessions(MOCK_AGENT_PANES.mine, mineSessions),
  };
}
```

- [ ] **Step 3: `createConversation`이 visibility를 전달하게 수정**

```js
/** 새 대화 생성. visibility는 'team' | 'private'. */
export async function createConversation(title, visibility) {
  if (USE_MOCK) {
    return {
      id: `local-${Date.now()}`,
      title: title || '새 대화',
      meta: '오늘',
      messages: [],
      evidence: [],
    };
  }

  const session = await agentApi.createChatSession(title || '새 대화', visibility);
  return toViewConversation(session);
}
```

- [ ] **Step 4: `shareMessageToTeam`/`saveMessageToWiki` 어댑터 추가**

파일 끝에 추가:

```js
/**
 * 팀에 공유. targetSessionId가 null이면 백엔드가 새 팀 세션을 만든다.
 * @returns {Promise<{message, sessionId}>} sessionId는 공유된 팀 세션 id(새로 만들어졌을 수도 있음).
 */
export async function shareMessageToTeam(sessionId, messageId, targetSessionId) {
  const copied = await agentApi.shareMessageToTeam(sessionId, messageId, targetSessionId);
  return { message: toViewMessage(copied), sessionId: copied.session_id };
}

/** @returns {Promise<{page_id, version_id, slug}>} */
export async function saveMessageToWiki(sessionId, messageId) {
  return agentApi.saveMessageToWiki(sessionId, messageId);
}
```

- [ ] **Step 5: 커밋**

```bash
git add frontend/src/services/agentApi.js
git commit -m "$(cat <<'EOF'
Feat: 에이전트 세션 목록·팀 공유·위키 저장을 mock 대신 실제 API로 연결
EOF
)"
```

---

### Task 10: `ChatMessage.jsx` — 액션 버튼 연결

**Files:**
- Modify: `frontend/src/components/agent/ChatMessage.jsx`

**Interfaces:**
- Consumes: 없음
- Produces: `<ChatMessage message flag flagPriv onAction(label, message) />` — Task 11이 `onAction`을 넘김

- [ ] **Step 1: 파일 전체를 다음으로 교체**

```jsx
// 에이전트 전용 — 대화 한 턴(.turn)
// 사용자 메시지(.turn.me)와 에이전트 답변(.turn.ai)을 같은 컴포넌트에서 처리합니다.
//
// 팀 공유 대화에서는 사용자 메시지 위에 작성자(.au)가, 답변 헤더에는
// "팀 공유 / 개인" 배지(.who .fl)가 붙습니다 — 시안과 동일합니다.
// 답변 문장의 근거 번호와 하단 근거 칩은 CitationTag가 그립니다.
//
// acts(팀에 공유/위키에 저장/복사/다시 생성) 중 "팀에 공유"·"위키에 저장"만
// onAction으로 실제 동작에 연결합니다. 나머지는 아직 장식 상태입니다.

import CitationTag from '../wiki/CitationTag';

const WIRED_ACTIONS = new Set(['팀에 공유', '위키에 저장']);

export default function ChatMessage({ message, flag, flagPriv = false, onAction }) {
  if (message.role === 'me') {
    return (
      <div className="turn me">
        {message.author && (
          <div className="au"><i>{message.author.initial}</i>{message.author.name}</div>
        )}
        <div className="msg">{message.text}</div>
      </div>
    );
  }

  return (
    <div className="turn ai">
      <div className="mark"></div>
      <div>
        <div className="who">
          MYWIKI{flag && <span className={`fl${flagPriv ? ' priv' : ''}`}>{flag}</span>}
        </div>

        {message.none ? (
          <div className="none">
            <h6>{message.none.title}</h6>
            <p>{message.none.desc}</p>
          </div>
        ) : (
          (message.paragraphs || []).map((parts, pi) => (
            <p key={pi}>
              {parts.map((part, i) =>
                typeof part === 'number'
                  ? <CitationTag key={i} no={part} sourceKey={(message.cites || []).find((c) => c.no === part)?.key} />
                  : <span key={i}>{part}</span>
              )}
            </p>
          ))
        )}

        {message.cites && message.cites.length > 0 && (
          <div className="cites">
            {message.cites.map((c) => (
              <CitationTag key={c.no} no={c.no} sourceKey={c.key} chip />
            ))}
          </div>
        )}

        {message.acts && message.acts.length > 0 && (
          <div className="acts">
            {message.acts.map((a) =>
              WIRED_ACTIONS.has(a) ? (
                <span
                  key={a}
                  className="act-wired"
                  role="button"
                  tabIndex={0}
                  style={{ cursor: 'pointer' }}
                  onClick={() => onAction?.(a, message)}
                >
                  {a}
                </span>
              ) : (
                <span key={a}>{a}</span>
              )
            )}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 커밋**

```bash
git add frontend/src/components/agent/ChatMessage.jsx
git commit -m "$(cat <<'EOF'
Feat: 답변 카드의 "팀에 공유"·"위키에 저장" 버튼 클릭 연결
EOF
)"
```

---

### Task 11: `AgentPage.jsx` — 전체 연결 + 빈 상태 버그 수정

**Files:**
- Modify: `frontend/src/pages/AgentPage.jsx`

**Interfaces:**
- Consumes: Task 9의 `agentApi.js` 함수 전체, Task 8의 `TeamShareModal`, Task 10의 `ChatMessage` `onAction` prop
- Produces: `<AgentPage profile />` — Task 12(`App.jsx`)가 `profile`을 넘김

- [ ] **Step 1: 파일 전체를 다음으로 교체**

```jsx
// 에이전트 페이지 — PC/모바일 공용 (#v-agent)
//
// 시안 구조 그대로 "팀 공유 에이전트 / 내 에이전트"를 세그먼트(.ag-seg)로 나눕니다.
//  · 각 탭은 컨텍스트 배너(.ag-ctx) + 대화 목록(.ag-list) + 스레드(.thread)
//    + 입력창(.composer) + 근거 원문 컬럼(.col)으로 구성됩니다.
//  · 대화방(.ag-conv)을 누르면 스레드와 우측 근거 원문이 같이 바뀝니다.
//  · "+ 새 대화"를 누르면 빈 대화가 하나 생기고 바로 그 대화로 들어갑니다.
//  · 입력창에서 보낸 질문은 그 대화에만 쌓입니다(탭을 옮겨도 유지).
//
// 데이터는 services/agentApi.js를 통해서만 가져옵니다.
// VITE_USE_MOCK=true면 목업, false면 실제 백엔드(api/agent.js)를 호출합니다.

import { useEffect, useState } from 'react';
import { getSource } from '../services/wikiApi';
import {
  fetchAgentPanes,
  fetchConversation,
  createConversation,
  askAgent,
  shareMessageToTeam,
  saveMessageToWiki,
} from '../services/agentApi';
import ChatMessage from '../components/agent/ChatMessage';
import ChatComposer from '../components/agent/ChatComposer';
import TeamShareModal from '../components/agent/TeamShareModal';

const PANE_KEYS = ['team', 'mine'];

// 출처 key가 없을 때 쓰는 기본값.
// 백엔드 citations에는 document_version_id만 있고 출처 종류(공시/뉴스)가 없습니다.
// 임의로 지어내면 잘못된 근거를 표시하게 되므로, 확인 불가임을 그대로 드러냅니다.
const UNKNOWN_SOURCE = { name: '출처 확인 중', url: null, title: '출처 정보 없음' };

function displayNameOf(profile) {
  return profile?.user_metadata?.full_name || profile?.user_metadata?.name || profile?.email || '나';
}

export default function AgentPage({ profile }) {
  const [panes, setPanes] = useState(null);
  const [activePane, setActivePane] = useState('team');
  const [currentIds, setCurrentIds] = useState({ team: null, mine: null });
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);
  const [shareModal, setShareModal] = useState(null); // { sessionId, messageId } | null

  // 최초 진입 시 대화 목록을 불러옵니다.
  useEffect(() => {
    let alive = true;
    fetchAgentPanes()
      .then((data) => {
        if (!alive) return;
        setPanes(data);
        setCurrentIds({
          team: data.team.conversations[0]?.id ?? null,
          mine: data.mine.conversations[0]?.id ?? null,
        });
      })
      .catch((e) => alive && setError(e.message || '대화 목록을 불러오지 못했습니다.'));
    return () => { alive = false; };
  }, []);

  const pane = panes?.[activePane];
  const current =
    pane?.conversations.find((c) => c.id === currentIds[activePane]) ||
    pane?.conversations[0] ||
    null;

  // 대화방을 바꿀 때 아직 메시지를 안 불러왔으면 여기서 채웁니다.
  useEffect(() => {
    if (!current || current._loaded === undefined || current._loaded) return;
    let alive = true;
    fetchConversation(current.id)
      .then(({ messages, evidence }) => {
        if (!alive) return;
        updateConversation(current.id, (c) => ({ ...c, messages, evidence, _loaded: true }));
      })
      .catch((e) => alive && setError(e.message || '대화를 불러오지 못했습니다.'));
    return () => { alive = false; };
  }, [current?.id]);

  // 현재 pane의 대화 하나만 바꾸는 공용 헬퍼.
  function updateConversation(id, fn) {
    setPanes((prev) => ({
      ...prev,
      [activePane]: {
        ...prev[activePane],
        conversations: prev[activePane].conversations.map((c) => (c.id !== id ? c : fn(c))),
      },
    }));
  }

  async function handleSend(text) {
    if (!current || sending) return;
    setSending(true);
    setError(null);

    const displayName = displayNameOf(profile);
    // 보낸 질문을 먼저 화면에 올려 응답을 기다리는 동안 비어 보이지 않게 합니다.
    const optimistic = {
      role: 'me',
      text,
      ...(activePane === 'team' ? { author: { initial: displayName.charAt(0).toUpperCase(), name: displayName } } : {}),
    };
    updateConversation(current.id, (c) => ({ ...c, messages: [...c.messages, optimistic] }));

    try {
      const { aiMessage, evidence } = await askAgent(current.id, text);
      updateConversation(current.id, (c) => ({
        ...c,
        messages: [...c.messages, aiMessage],
        evidence: evidence.length ? evidence : c.evidence,
      }));
    } catch (e) {
      setError(e.message || '답변을 가져오지 못했습니다.');
      // 실패한 질문은 되돌립니다.
      updateConversation(current.id, (c) => ({ ...c, messages: c.messages.slice(0, -1) }));
    } finally {
      setSending(false);
    }
  }

  async function handleNewConversation() {
    const n = pane.conversations.length + 1;
    try {
      const conv = await createConversation(`새 대화 ${n}`, activePane === 'team' ? 'team' : 'private');
      setPanes((prev) => ({
        ...prev,
        [activePane]: {
          ...prev[activePane],
          conversations: [...prev[activePane].conversations, { ...conv, _loaded: true }],
        },
      }));
      setCurrentIds((prev) => ({ ...prev, [activePane]: conv.id }));
    } catch (e) {
      setError(e.message || '새 대화를 만들지 못했습니다.');
    }
  }

  function handleAction(label, message) {
    if (!current) return;
    if (label === '팀에 공유') {
      setShareModal({ sessionId: current.id, messageId: message._id });
    } else if (label === '위키에 저장') {
      handleSaveToWiki(current.id, message._id);
    }
  }

  async function handleShare(targetSessionId) {
    const target = shareModal;
    setShareModal(null);
    if (!target) return;
    try {
      const { sessionId: landedSessionId } = await shareMessageToTeam(
        target.sessionId, target.messageId, targetSessionId,
      );
      const data = await fetchAgentPanes();
      setPanes(data);
      setActivePane('team');
      setCurrentIds((prev) => ({ ...prev, team: landedSessionId }));
    } catch (e) {
      setError(e.message || '팀에 공유하지 못했습니다.');
    }
  }

  async function handleSaveToWiki(sessionId, messageId) {
    try {
      await saveMessageToWiki(sessionId, messageId);
      setError(null);
    } catch (e) {
      setError(e.message || '위키에 저장하지 못했습니다.');
    }
  }

  if (error && !panes) {
    return (
      <section className="view on" id="v-agent">
        <div className="empty-conv">{error}</div>
      </section>
    );
  }

  if (!panes) {
    return (
      <section className="view on" id="v-agent">
        <div className="empty-conv">불러오는 중…</div>
      </section>
    );
  }

  return (
    <section className="view on" id="v-agent">
      <div className="ph">
        <h2>에이전트</h2>
        <span className="dt">축적된 위키 문서만 근거로 사용</span>
        <span className="st">참조 범위 <b>위키 124문서</b></span>
      </div>

      <div className="sp-seg ag-seg" role="tablist" aria-label="에이전트 구분">
        {PANE_KEYS.map((key) => (
          <button
            key={key}
            className={activePane === key ? 'on' : ''}
            role="tab"
            aria-selected={activePane === key}
            onClick={() => setActivePane(key)}
          >
            {panes[key].label}<span className="c">{panes[key].conversations.length}</span>
          </button>
        ))}
      </div>

      <div className={`chat ag-pane ${pane.key} on`}>
        <div>
          {/* 컨텍스트 배너 — 팀은 참여 멤버, 개인은 "비공개" 배지 */}
          <div className={`ag-ctx ${pane.key}`}>
            <span className="ic">{pane.ctx.badge}</span>
            <div className="tx">
              <b>{pane.ctx.title}</b>
              <span>{pane.ctx.desc}</span>
            </div>
            {pane.ctx.avatars ? (
              <span className="avs" aria-label="참여 멤버">
                {pane.ctx.avatars.map((a) => <i key={a}>{a}</i>)}
                {pane.ctx.more && <i className="more">{pane.ctx.more}</i>}
              </span>
            ) : (
              <span className="priv">{pane.ctx.priv}</span>
            )}
          </div>

          {/* 대화 목록 */}
          <div className="ag-list">
            <span className="lb">{pane.listLabel}</span>
            {pane.conversations.map((c) => (
              <button
                key={c.id}
                className={`ag-conv${current && c.id === current.id ? ' on' : ''}`}
                onClick={() => setCurrentIds((prev) => ({ ...prev, [activePane]: c.id }))}
              >
                {c.title}<span className="d">{c.meta}</span>
              </button>
            ))}
            <button className="ag-conv new" onClick={handleNewConversation}>
              {pane.newLabel}
            </button>
          </div>

          {/* 스레드 */}
          <div className="thread">
            {!current ? (
              <div className="empty-conv">
                아직 대화가 없습니다. 위의 「{pane.newLabel}」 버튼으로 시작해보세요.
              </div>
            ) : current.messages.length === 0 ? (
              <div className="empty-conv">
                「{current.title}」 대화입니다. 아래 입력창에 질문을 입력하면 위키에 축적된 문서만 근거로 답변합니다.
              </div>
            ) : (
              current.messages.map((m, i) => (
                <ChatMessage key={m._id ?? i} message={m} flag={pane.flag} flagPriv={pane.flagPriv} onAction={handleAction} />
              ))
            )}
            {sending && <div className="empty-conv">근거를 확인하는 중…</div>}
          </div>

          {error && <div className="empty-conv">{error}</div>}

          {current && (
            <ChatComposer
              placeholder={pane.placeholder}
              ariaLabel={pane.inputLabel}
              onSend={handleSend}
            />
          )}

          <div className="hint">
            {pane.hints.map((h) => <span key={h}>{h}</span>)}
          </div>
        </div>

        {/* 근거 원문 */}
        <div className="col">
          <h5>근거 원문<span className="c">{current?.evidence.length ?? 0}</span></h5>
          {(current?.evidence ?? []).map((e) => {
            // e.key가 null일 수 있습니다(백엔드가 출처 종류를 주지 않는 경우).
            const src = (e.key && getSource(e.key)) || UNKNOWN_SOURCE;
            const isDoc = src.name.includes('공시') || src.name.includes('IR');
            return (
              <div className="ev" key={e.no}>
                <div className="t">
                  <span className="no">{e.no}</span>
                  <span className={`src${isDoc ? ' doc' : ''}`}>{src.name}</span>
                </div>
                <h6>{e.title}</h6>
                <div className="x">{e.excerpt}</div>
                <div className="f">{e.foot}</div>
                {src.url && (
                  <a className="lk" href={src.url} target="_blank" rel="noopener">
                    {isDoc ? 'DART 원문 열기 ↗' : '원문 열기 ↗'}
                  </a>
                )}
              </div>
            );
          })}
        </div>
      </div>

      <TeamShareModal
        open={shareModal !== null}
        teamSessions={panes.team.conversations}
        onShare={handleShare}
        onClose={() => setShareModal(null)}
      />
    </section>
  );
}
```

- [ ] **Step 2: 커밋**

```bash
git add frontend/src/pages/AgentPage.jsx
git commit -m "$(cat <<'EOF'
Feat: 에이전트 페이지를 mock 대신 실제 세션 데이터로 연결

- 대화가 0개인 pane에서 "불러오는 중"이 무한히 뜨던 버그 수정
- 팀 탭 "새 공유 대화"가 visibility=team으로 생성되게 연결
- "팀에 공유"가 대상 세션 선택 모달을 거쳐 공유 후 해당 세션으로 이동
- "위키에 저장" 버튼 연결
- 팀 대화 낙관적 업데이트가 하드코딩된 이름 대신 실제 로그인 사용자 이름 사용
EOF
)"
```

---

### Task 12: `App.jsx` — `profile` prop 전달

**Files:**
- Modify: `frontend/src/App.jsx:380` 부근

**Interfaces:**
- Consumes: Task 11의 `<AgentPage profile />`

- [ ] **Step 1: `AgentPage` 렌더 부분 수정**

`frontend/src/App.jsx`에서 `{view === 'agent' && <AgentPage />}`를 찾아 다음으로 교체:

```jsx
{view === 'agent' && <AgentPage profile={profile} />}
```

(`profile`은 이미 이 컴포넌트 상단에서 Supabase 세션으로부터 관리되고 있음 — `TopBar`/`ProfilePanel`에 넘기는 것과 같은 변수.)

- [ ] **Step 2: 커밋**

```bash
git add frontend/src/App.jsx
git commit -m "$(cat <<'EOF'
Feat: AgentPage에 로그인 사용자 profile 전달
EOF
)"
```

---

### Task 13: 프론트 PR 생성 → 머지 → 배포 확인

**Files:** 없음(git/gh 작업)

- [ ] **Step 1: 중복 확인 후 푸시**

```bash
gh pr list --state open
git push -u origin feature/agent-session-sharing-frontend
```

- [ ] **Step 2: PR 생성**

```bash
gh pr create --base develop-frontend --title "Feat: 에이전트 팀/개인 세션 실연결 — 프론트엔드" --body "$(cat <<'EOF'
## 작업내용
- agentApi.js의 fetchAgentPanes/createConversation이 mock 대신 실제 GET /chat/sessions를 사용
- 팀 대화 답변에서 "팀에 공유" 클릭 시 대상 세션을 고르는 모달 추가, 선택 후 해당 세션으로 자동 이동
- "위키에 저장" 버튼 연결
- 대화가 0개인 pane에서 "불러오는 중"이 무한히 뜨던 버그 수정
- 팀 탭에서 작성자 이름 표시(백엔드 author_name 사용, 하드코딩 제거)

## 변경이유
docs/superpowers/specs/2026-08-04-agent-session-sharing-design.md — 백엔드(PR 참고사항에 링크)는 이미 머지됨.

## 테스트결과
로컬 dev 서버에서 개인 대화 생성→전송→새로고침 후 유지, 팀 세션 선택해서 공유→팀 탭 반영, 팀 세션 0개 상태에서 공유(새로 생성됨), 빈 워크스페이스 빈 상태 확인. 자동화 테스트는 이 저장소 프론트 관례상 없음.

## 참고사항
백엔드 PR: (머지된 PR 번호로 교체)

## 관련Issue
없음
EOF
)"
```

- [ ] **Step 3: 머지**

```bash
gh pr merge --squash
```

- [ ] **Step 4: Vercel 자동 배포 확인**

```bash
gh api repos/yoobinkim541/SK_Suni_5th_project-myWiki/commits/develop-frontend/status 2>/dev/null || true
```

(Vercel은 Git 연동이라 GH Actions 로그가 없음 — Task 14의 브라우저 확인이 실제 검증 수단.)

---

### Task 14: 실배포 환경 종단 테스트

**Files:** 없음(브라우저 검증)

- [ ] **Step 1: 개인 대화 흐름 확인**

`mcp__Claude_Browser__navigate`로 `https://mywiki.pe.kr`에 접속 → 로그인 → 에이전트 페이지 → "내 에이전트" 탭 → "+ 새 대화" → 질문 전송 → 응답 확인 → 브라우저 새로고침 → 방금 만든 대화가 목록에 그대로 남아있고 클릭하면 메시지 이력이 다시 보이는지 확인.

- [ ] **Step 2: 팀 공유 흐름 확인**

방금 받은 답변의 "팀에 공유" 클릭 → 모달에서 "+ 새 공유 대화 만들어서 공유" 선택 → 팀 탭으로 자동 전환되고 방금 공유한 질문+답변이 보이는지, 작성자 이름이 실제 로그인 계정 이름으로 표시되는지 확인.

- [ ] **Step 3: 기존 팀 세션으로 공유 확인**

다른 질문에 "팀에 공유" 클릭 → 이번엔 모달에 방금 만들어진 팀 세션이 목록에 떠 있는지, 그걸 선택하면 같은 세션에 누적되는지 확인.

- [ ] **Step 4: 위키 저장 확인**

"위키에 저장" 클릭 → 에러 없이 처리되는지 확인(성공 시 특별한 UI 피드백은 없음 — 에러 발생 시에만 인라인 메시지가 뜨는 게 현재 설계이므로, 에러가 안 뜨면 성공으로 간주). 필요하면 위키 페이지에서 실제로 저장됐는지 교차 확인.

- [ ] **Step 5: 빈 상태 확인**

가능하면 팀 세션이 아직 하나도 없는 워크스페이스(또는 새 테스트 계정)로 팀 탭을 열어 "아직 대화가 없습니다" 문구가 뜨고 무한 로딩이 아닌지 확인.

- [ ] **Step 6: 콘솔 에러 확인**

`mcp__Claude_Browser__read_console_messages`로 위 시나리오 진행 중 에러가 없었는지 확인.

- [ ] **Step 7: 문제 발견 시**

버그가 발견되면 `fix/agent-session-sharing-<n>` 브랜치로 별도 수정 후 같은 방식(PR → squash 머지)으로 처리하고, 라이브에서 재확인한다.

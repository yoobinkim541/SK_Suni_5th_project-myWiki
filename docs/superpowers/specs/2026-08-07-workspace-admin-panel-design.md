# 오너 전용 워크스페이스 관리 패널 설계

## 배경

`frontend/src/constants/roles.js`에 오너(관리자)/어드민(팀장)/에디터(팀원)/게스트 4단계 역할과 권한표가 이미 정의돼 있고, "세션 초대"/"세션에서 제외"는 이전 작업(#151)으로 백엔드까지 연결됐다. 하지만 권한표의 나머지 항목 — 팀 방출, 팀장/팀원 역할 지정 — 은 프론트에 UI 자체가 없다(`canRemoveFromWorkspace`/`canChangeRole` 함수만 정의돼 있고 어디서도 안 쓰임).

추가로 이번 작업 범위에는 오너가 워크스페이스의 모든 에이전트 세션(팀 공유 세션 + 개인 세션 전체)을 열람할 수 있는 감독 기능도 포함한다. "팀 영입"은 신규 가입자가 자동으로 워크스페이스에 합류하는 기존 트리거(`handle_new_user_auto_join_mvp_workspace`)로 이미 해결되어 있어 이번 범위에서 제외한다.

## 목표

1. 오너가 워크스페이스 멤버를 방출할 수 있다(본인 제외).
2. 오너가 멤버의 역할을 팀장/팀원/게스트로 바꿀 수 있다(본인 제외, 오너로 바꾸는 건 불가 — 소유권 이전은 범위 밖).
3. 오너가 워크스페이스의 모든 팀 공유 세션을 참여 여부와 무관하게 열람할 수 있다.
4. 오너가 워크스페이스의 모든 개인(비공개) 세션을 소유자와 무관하게 열람할 수 있다.
5. 위 기능은 `SettingsPage`에 오너에게만 보이는 "관리" 섹션으로 노출된다.

## 비목표

- 소유권(오너) 이전 — 오너를 다른 사람으로 바꾸는 기능은 이번 범위 밖(운영 중 필요해지면 별도 스펙).
- "팀 영입" UI — 자동합류로 이미 해결됨.
- 오너가 세션에 직접 개입(메시지 삭제, 답변 재생성 등) — 읽기 전용 열람만.
- 멤버 방출/역할 변경에 대한 알림(이메일 등) — 이번 범위는 즉시 반영만.

## 아키텍처

기존 개인/팀 세션 조회 함수(`get_chat_session`, `list_chat_sessions`)는 건드리지 않고, 완전히 분리된 관리자 전용 함수·엔드포인트를 새로 만든다. 일반 사용자의 접근 제어 로직에 "오너면 통과" 같은 예외를 끼워넣지 않는 이유는, 개인정보 접근 경로에 조건을 겹겹이 쌓는 게 버그 위험이 크기 때문이다 — 관리자 열람은 별도 경로로 완전히 분리해서, 실수로 일반 사용자의 프라이버시 경계가 느슨해질 여지를 없앤다.

```
src/api/db.py (기존 파일에 추가)
├── remove_workspace_member(workspace_id, user_id) -> None
│     workspace_members 행 삭제 + 그 사람이 참여 중인, 이 워크스페이스 소속 세션의
│     chat_session_participants 행도 함께 삭제(방출됐는데 팀 세션엔 계속 남는 상태 방지).
├── update_workspace_member_role(workspace_id, user_id, role) -> None
│     workspace_members.role UPDATE. role은 admin/editor/viewer만 허용(호출부에서 검증).
├── list_workspace_sessions_for_admin(workspace_id, visibility) -> list[dict]
│     visibility='team' 또는 'private' 세션 전체를, 참여자/소유자 필터 없이 조회.
│     각 행에 세션 소유자 display_name을 함께 붙인다(누구 세션인지 목록에서 바로 보이게).
└── get_chat_session_for_admin(session_id, workspace_id) -> Optional[dict]
      get_chat_session과 달리 참여자/소유자 여부를 전혀 확인하지 않고 workspace_id
      일치만 확인한다 — 메시지 조회 엔드포인트가 이 함수로 세션 존재만 검증한 뒤
      list_chat_messages를 그대로 재사용한다.

src/api/main.py (기존 파일에 추가)
├── _require_owner(profile, workspace_id) -> None
│     db.get_workspace_role(workspace_id, profile["id"]) != "owner"면 403.
│     아래 4개 엔드포인트가 모두 이 체크를 먼저 통과해야 한다.
├── DELETE /workspace/members/{user_id}       — remove_workspace_member. 본인 대상이면 400.
├── PATCH  /workspace/members/{user_id}/role  — update_workspace_member_role. 본인 대상이면 400,
│                                                role이 admin/editor/viewer 밖이면 400.
├── GET  /workspace/sessions?visibility=team|private — list_workspace_sessions_for_admin.
└── GET  /workspace/sessions/{session_id}/messages   — get_chat_session_for_admin으로 존재 확인 후
                                                         기존 db.list_chat_messages + _to_message_out 재사용.
```

기존 `ChatSessionOut`/`ChatMessageOut` 스키마를 그대로 재사용한다(세션 목록·메시지 형식은 이미 확정돼 있으므로 새로 만들 이유가 없음). 목록 엔드포인트만 소유자 이름을 붙이기 위해 `owner_name: Optional[str]` 필드를 얹은 새 응답 모델(`AdminSessionOut`)을 하나 추가한다.

## API 변경

### `DELETE /workspace/members/{user_id}`
- 오너 전용(403 if not owner). `user_id == 본인`이면 400("오너 본인은 방출할 수 없음").
- 성공 시 204. `workspace_members` 삭제 + 해당 워크스페이스 세션들의 `chat_session_participants`에서도 제거.

### `PATCH /workspace/members/{user_id}/role`
- Request body: `UpdateMemberRoleRequest { role: Literal["admin", "editor", "viewer"] }` — 세 값 밖은 pydantic이 스키마 레벨에서 422로 이미 차단(별도 400 처리 불필요).
- 오너 전용. `user_id == 본인`이면 400.
- 성공 시 변경된 `WorkspaceMemberOut` 반환(role 포함, 기존 #151에서 이미 있는 필드).

### `GET /workspace/sessions?visibility=team|private`
- 오너 전용. `visibility` 필수 쿼리 파라미터(둘 중 하나).
- Response: `list[AdminSessionOut]` — `ChatSessionOut` 필드 전부 + `owner_name: Optional[str]`.

### `GET /workspace/sessions/{session_id}/messages`
- 오너 전용. 세션이 이 워크스페이스 소속이 아니면 404.
- Response: `list[ChatMessageOut]`(기존과 동일 — citations 포함).

## 프론트엔드

### 배치
`SettingsPage.jsx`의 계정/알림 섹션과 같은 패턴으로 "관리" 섹션 추가. `myRole === 'owner'`일 때만 렌더링(현재 `App.jsx`가 이미 `myRole`을 들고 있음 — #151에서 살아난 값).

### 새 파일
```
frontend/src/api/admin.js
├── removeWorkspaceMember(userId)
├── updateWorkspaceMemberRole(userId, role)
├── listWorkspaceSessions(visibility)   // 'team' | 'private'
└── getWorkspaceSessionMessages(sessionId)

frontend/src/components/settings/AdminPanel.jsx
  "관리" 섹션 전체 — 팀원 목록(역할 배지 + 역할 변경 드롭다운 + 방출 버튼) +
  팀 세션 목록 + 개인 세션 목록, 3개 하위 블록을 SettingsPage 계정/알림처럼 세로로 쌓는다.
  방출은 회원 탈퇴 모달과 같은 패턴(확인 문구 없이 간단 confirm 모달 — 대상이 본인이
  아니라 타인이라 "탈퇴" 같은 문구 입력 확인까지는 과함, 버튼 2단계 확인이면 충분).

frontend/src/components/settings/AdminSessionViewModal.jsx
  세션 하나를 읽기 전용으로 보여주는 모달. AgentPage를 재사용하지 않고 새로 만든다 —
  AgentPage는 입력창/재생성/공유 등 액션이 많아 읽기 전용으로 억지로 끄는 것보다
  새로 만드는 게 더 단순하고 안전하다. 메시지 role+content를 마크다운으로 렌더링하되
  각주 클릭 이동 같은 인터랙션은 없음(오너가 내용을 확인하는 용도로 충분).
```

### 기존 파일 변경
- `SettingsPage.jsx`: `AdminPanel` import + `myRole === 'owner'` 조건부 렌더링 추가.

## 에러 처리

- 오너가 아닌 사용자가 4개 엔드포인트 중 하나를 직접 호출 → 403(프론트에서 버튼을 안 보여줘도 서버가 반드시 막는다 — `roles.js` 기존 관례).
- 오너가 본인을 방출/역할변경 대상으로 지정 → 400, 명확한 사유 메시지.
- 방출 대상이 이미 멤버가 아님(중복 클릭 등) → `remove_workspace_member`가 조용히 0건 삭제로 끝남(에러 아님 — 최종 상태는 어차피 "멤버 아님"으로 동일하므로 idempotent하게 둔다).
- 세션 목록/메시지 조회 시 해당 세션이 다른 워크스페이스 소속 → 404(존재 자체를 숨김, workspace_id로 항상 필터).

## 테스트

- `tests/test_workspace_admin.py`(신규):
  - `remove_workspace_member`: 대상 삭제 + 참여 중이던 세션들의 참여자 행도 함께 삭제되는지(fake Supabase).
  - `update_workspace_member_role`: role 업데이트 반영 확인.
  - `list_workspace_sessions_for_admin`: 참여자/소유자 필터 없이 workspace 전체가 나오는지, `visibility`로 걸러지는지.
  - `get_chat_session_for_admin`: 참여자가 아니어도(또는 소유자가 아니어도) 워크스페이스만 맞으면 조회되는지, 다른 워크스페이스면 None인지.
- 라우터 레벨(`test_chat_sessions.py`에 추가 또는 신규 파일):
  - 4개 엔드포인트 각각 오너 아니면 403.
  - `DELETE /workspace/members/{user_id}`, `PATCH .../role` 본인 대상 400.
  - `GET /workspace/sessions` — `visibility` 파라미터별 응답, `owner_name` 포함 확인.
  - `GET /workspace/sessions/{id}/messages` — 다른 workspace 세션 404.

프론트엔드는 별도 자동 테스트 프레임워크가 없는 프로젝트라(기존 관례) `npm run build` 통과 확인 + 로컬 수동 확인으로 대체한다.

## 영향받는 파일

| 파일 | 변경 |
|---|---|
| `src/api/db.py` | `remove_workspace_member`, `update_workspace_member_role`, `list_workspace_sessions_for_admin`, `get_chat_session_for_admin` 신규 |
| `src/api/schemas.py` | `AdminSessionOut`, `UpdateMemberRoleRequest` 신규 |
| `src/api/main.py` | `_require_owner` 헬퍼 + 4개 엔드포인트 신규 |
| `tests/test_workspace_admin.py` | 신규 |
| `tests/test_chat_sessions.py` 또는 신규 라우터 테스트 파일 | 4개 엔드포인트 테스트 추가 |
| `frontend/src/api/admin.js` | 신규 |
| `frontend/src/components/settings/AdminPanel.jsx` | 신규 |
| `frontend/src/components/settings/AdminSessionViewModal.jsx` | 신규 |
| `frontend/src/pages/SettingsPage.jsx` | `AdminPanel` 조건부 렌더링 추가 |

DB 스키마 변경 없음(기존 `workspace_members.role`, `chat_sessions`, `chat_session_participants` 테이블만 사용) — ERDCloud 동기화 불필요.

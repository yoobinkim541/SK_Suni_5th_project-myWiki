# 에이전트 팀/개인 세션 실연결 설계

## 배경

배포된 사이트의 에이전트 페이지(`AgentPage.jsx`)는 "팀 공유 에이전트 / 내 에이전트" 탭과 대화 목록·스레드 UI를 이미 갖추고 있지만, `agentApi.js`의 `fetchAgentPanes()`가 항상 `MOCK_AGENT_PANES`(가짜 대화 데이터)를 반환한다. 반면 백엔드(`src/api/main.py`, `src/api/db.py`)는 이미 다음을 갖추고 있다:

- `chat_sessions.visibility` = `private`(개인) / `team`(팀 공유)
- `GET /chat/sessions?scope=mine|team` — 세션 목록 조회
- `POST /chat/sessions` — `visibility` 지정 가능한 세션 생성
- `POST /chat/sessions/{id}/messages/{message_id}/share-to-team` — 개인 대화의 답변 한 쌍(질문+답변)을 팀 세션으로 복사
- `POST /chat/sessions/{id}/messages/{message_id}/save-to-wiki` — 답변을 위키 페이지로 저장

즉 데이터 모델과 엔드포인트는 이미 배포되어 있고, 프론트가 mock에서 실제 API로 갈아끼워지지 않은 상태다. 이번 스펙은 그 연결 작업만 다룬다.

**범위 밖**(별도 브레인스토밍 예정): 에이전트의 세션 내 대화 컨텍스트 유지 강화, 연관 위키 문서 다중 참조 튜닝, 웹 검색 도구 추가. 이 세 가지는 Agent의 답변 생성 로직(`src/agent/core.py`, `src/agent/wiki_tools.py`) 및 "근거 없으면 답 안 한다"는 핵심 신뢰 모델과 직결되는 별개 하위 프로젝트라 이번 스펙에서 제외한다.

## 목표

1. 팀 탭 / 내 탭 모두 실제 저장된 세션 목록·대화 이력을 보여준다(새로고침해도 유지).
2. 개인 대화의 답변을 사용자가 고른 팀 세션으로 공유할 수 있다.
3. 답변을 위키 문서로 저장할 수 있다.
4. 팀 공유 대화에서 각 질문을 누가 보냈는지 표시한다.

## 비목표

- "복사", "다시 생성" 버튼 연결 — 이번 범위 밖, 장식 상태 유지.
- 팀 세션 삭제/이름 변경, 멤버 관리 UI — 요청받지 않음.
- 에이전트 답변 로직 자체 변경 — 별도 스펙.

## 데이터 모델 변경 (DB)

`chat_messages`에 작성자 컬럼이 없다(현재 "누가 보낸 메시지인지" 저장 안 됨). 팀 공유 대화에서 작성자 표시가 필요하므로 추가한다.

```sql
ALTER TABLE public.chat_messages ADD COLUMN user_id uuid REFERENCES public.profiles(id);
```

- Nullable — 과거 행(마이그레이션 이전에 저장된 메시지)은 작성자 불명으로 남고, 프론트에서 작성자 배지를 생략한다.
- ERDCloud 다이어그램에 `chat_messages.user_id → profiles.id` 관계선 추가(기존 `push_subscriptions` 작업과 동일한 방식 — 컬럼 삭제 없이 `create_relation`으로 새로 만들고 이름을 맞추는 대신, 이번엔 처음부터 관계로 만들어서 리네임 불필요하게 함).

## 백엔드 변경

### `src/api/db.py`
- `save_user_message(session_id, content, user_id)` — 저장 시 `user_id` 포함.
- `copy_chat_message()` — 팀 공유로 복사할 때 원본 메시지의 `user_id`를 그대로 복사(공유자가 아니라 원작성자 유지 — 공유 자체는 항상 메시지 소유자만 가능하므로 둘은 항상 동일인).
- `list_chat_messages()` 결과에 작성자 표시용 이름을 붙여야 한다. 별도 멤버 목록 API를 만들지 않고, 메시지 조회 시 `profiles` 테이블에서 이름을 조회해 응답에 포함시킨다(구현 방식은 계획 단계에서 확정 — profiles 조인 또는 후속 조회 중 택1).

### `src/api/schemas.py`
- `ChatMessageOut`에 `author_name: Optional[str]` 추가(role='user'일 때만 값이 있고, assistant는 null).
- `ShareToTeamRequest(BaseModel)`: `target_session_id: Optional[str] = None` — 지정 시 해당 팀 세션으로, 미지정 시 새 팀 세션을 만들어 그쪽으로 복사(팀 세션이 하나도 없는 워크스페이스 대응).

### `src/api/main.py`
- `share_message_to_team`이 `ShareToTeamRequest` body를 받도록 변경. `target_session_id`가 있으면 `db.get_chat_session()`으로 그 세션이 같은 workspace의 `visibility='team'` 세션인지 검증(권한 없거나 team이 아니면 404/400) 후 그쪽으로 복사. 없으면 새 team 세션을 만들어 복사.
- 기존 `get_or_create_team_session()`(항상 가장 오래된 team 세션 반환)은 "target_session_id 미지정 시 새로 만들기" 경로로 대체되며, 더 이상 "가장 오래된 세션으로 암묵적 병합"은 하지 않는다.

## 프론트엔드 변경 (`develop-frontend`)

### `frontend/src/api/agent.js`
- `fetchChatSessions(scope)` — `GET /chat/sessions?scope=...` 호출 추가.
- `shareMessageToTeam(sessionId, messageId, targetSessionId)` — body에 `target_session_id` 포함(없으면 생략).
- `saveMessageToWiki(sessionId, messageId)` — 기존 엔드포인트 호출 추가.

### `frontend/src/services/agentApi.js`
- `fetchAgentPanes()` — mock 대신 `fetchChatSessions('team')`·`fetchChatSessions('mine')`를 병렬 호출해 `toViewConversation()`으로 변환, 기존 정적 UI 텍스트(라벨/힌트/placeholder)와 합쳐서 반환. `VITE_USE_MOCK=true`일 때는 기존 mock 경로 유지.
- `createConversation(title, visibility)` — pane에 맞는 `visibility`(`team`|`private`)를 `agentApi.createChatSession()`에 전달.
- `toViewMessage()` — `author_name`이 있으면 화면의 `author: {initial, name}` 형태로 매핑(팀 탭에서만 의미 있음).
- `shareMessageToTeam`, `saveMessageToWiki` 어댑터 추가.

### `frontend/src/pages/AgentPage.jsx`
- `App.jsx`로부터 `profile` prop을 받아 실제 로그인 사용자 이름/이니셜 사용(하드코딩된 "김주현" 제거).
- **빈 상태 버그 수정**: 현재 `pane.conversations`가 0개면 `current`가 null이 되어 "불러오는 중…"이 무한히 뜬다(신규 워크스페이스는 team 세션이 없을 수 있음). `panes`는 로드됐지만 `current`가 없는 경우를 구분해 "아직 대화가 없습니다" 빈 상태 UI를 보여준다.
- `handleNewConversation` — team 탭에서는 `visibility='team'`으로 생성.
- 팀 공유 세션 선택 모달(신규, `WikiKeywordModal.jsx`/`ReportDetailModal.jsx`와 동일한 기존 모달 패턴 재사용): "팀에 공유" 클릭 → 현재 workspace의 team 세션 목록(이미 로드된 `panes.team.conversations` 재사용) + "+ 새 공유 대화 만들어서 공유" 옵션을 보여주는 모달 → 선택 시 `shareMessageToTeam()` 호출 → 성공하면 팀 탭으로 전환하고 해당 세션을 활성화, 팀 pane을 다시 불러와 공유된 내용이 바로 보이게 함.
- "위키에 저장" 클릭 → `saveMessageToWiki()` 호출, 성공/실패 인라인 안내.

### `frontend/src/components/agent/ChatMessage.jsx`
- `acts`를 그대로 span으로 찍던 걸 `onAction(label, message)` 콜백을 받아 `팀에 공유`/`위키에 저장`만 클릭 가능하게 변경. 나머지 라벨(복사/다시 생성)은 기존처럼 비활성 상태 유지.

### `frontend/src/App.jsx`
- `<AgentPage profile={profile} />`로 prop 전달.

## 테스트

- 백엔드: `save_user_message`/`copy_chat_message` 시그니처 변경에 맞춰 기존 단위 테스트 수정. `user_id`/`author_name` 왕복, `share-to-team`의 `target_session_id` 검증(다른 workspace/비-team 세션 거부 포함) 테스트 추가.
- 프론트: 자동화 테스트 없는 레포 관례대로, 로컬 dev 서버 및 배포 후 실제 사이트에서 다음 시나리오 확인 — 개인 대화 생성→전송→새로고침 후 유지, 팀 세션 선택해서 공유→팀 탭에 반영, 팀 세션이 하나도 없는 상태에서 공유(새로 생성됨), 빈 워크스페이스 빈 상태 표시.

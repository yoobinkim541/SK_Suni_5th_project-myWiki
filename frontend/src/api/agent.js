// [LIVE] src/api/main.py 실제 연결 — 이미 구현·배포된 채팅 엔드포인트(윤혜민 담당).
// AgentPage.jsx의 MOCK_THREAD를 이 함수들로 교체한다.
import { apiFetch } from './client';

/**
 * scope='mine': 본인 소유 비공개 세션만. scope='team': workspace 공유 세션 전체(여러 개일 수 있음).
 * @param {'mine'|'team'} scope
 * @returns {Promise<{id, workspace_id, user_id, title, visibility, created_at, updated_at}[]>}
 */
export function fetchChatSessions(scope) {
  return apiFetch(`/chat/sessions?scope=${scope}`);
}

/**
 * @param {'private'|'team'} visibility 기본값 'private'.
 * @returns {Promise<{id, workspace_id, user_id, title, visibility, created_at, updated_at}>}
 */
export function createChatSession(title, visibility = 'private') {
  return apiFetch('/chat/sessions', { method: 'POST', body: { title, visibility } });
}

/**
 * ChatMessage.jsx가 기대하는 형태로 오지 않는다 — role이 'user'|'assistant'(BE) vs
 * 'me'|'ai'(FE 목업)라 매핑이 필요하다. citations는 message_citations 그대로 옴
 * (document_version_id만 있고 출처 라벨은 없음 — wiki.js의 sources와 동일한 제약).
 * author_name은 role='user'일 때만 값이 있다(팀 공유 대화 작성자 표시용).
 * @returns {Promise<{id, session_id, role, content, model_name, prompt_version, author_name,
 *   created_at, citations: {id, document_version_id, quoted_text, relevance_score, citation_order}[]}[]>}
 */
export function fetchChatMessages(sessionId) {
  return apiFetch(`/chat/sessions/${sessionId}/messages`);
}

/**
 * 근거 부족(has_answer=false)일 땐 assistant_message.content가
 * "[근거 부족] <사유>" 문자열로 옴 — AgentPage.jsx의 `none:{title, desc}` 카드 분기는
 * 이 접두사로 판별해서 프론트에서 구성해야 한다(백엔드가 title/desc를 나눠 주지 않음).
 * @returns {Promise<{user_message, assistant_message, has_answer}>}
 */
export function sendChatMessage(sessionId, content) {
  return apiFetch(`/chat/sessions/${sessionId}/messages`, {
    method: 'POST',
    body: { content },
  });
}

// AgentPage.jsx 우측 "근거 원문"(MOCK_EVIDENCE: excerpt/footer 포함)에 대응하는 백엔드는
// 없음 — citations에는 quoted_text/relevance_score까지만 있고, 원문 발췌 카드 형태의
// 별도 조회는 필요시 추가 논의.

/**
 * 개인 세션의 답변 하나(직전 user 질문과 함께)를 팀 공유 세션으로 복사한다.
 * @param {string} targetSessionId 지정하면 그 team 세션으로, 생략하면 새 team 세션을 만들어
 *   그쪽으로 복사한다(팀 세션이 여러 개일 수 있으므로 항상 사용자가 골라야 한다).
 * @returns {Promise<{id, session_id, role, content, model_name, prompt_version, author_name,
 *   created_at, citations: object[]}>} 팀 세션에 복사된 assistant 메시지
 */
export function shareMessageToTeam(sessionId, messageId, targetSessionId) {
  return apiFetch(`/chat/sessions/${sessionId}/messages/${messageId}/share-to-team`, {
    method: 'POST',
    body: targetSessionId ? { target_session_id: targetSessionId } : {},
  });
}

/**
 * "다시 생성" — 같은 질문으로 Agent를 다시 호출해 이 assistant 메시지 행을 그 자리에서
 * 교체한다(새 메시지를 추가하지 않음 — 새로고침해도 옛 답변이 다시 보이지 않는다).
 * 근거 부족(has_answer=false) 응답도 대상이 될 수 있다.
 * @returns {Promise<{id, session_id, role, content, model_name, prompt_version, author_name,
 *   created_at, citations: object[]}>} 교체된 assistant 메시지
 */
export function regenerateChatMessage(sessionId, messageId) {
  return apiFetch(`/chat/sessions/${sessionId}/messages/${messageId}/regenerate`, {
    method: 'POST',
  });
}

/**
 * 질문/답변 쌍 하나를 완전 삭제한다(정상 답변도 대상). 성공하면 204라 apiFetch가
 * null을 돌려준다.
 */
export function deleteChatMessage(sessionId, messageId) {
  return apiFetch(`/chat/sessions/${sessionId}/messages/${messageId}`, { method: 'DELETE' });
}

/**
 * assistant 답변을 위키 문서로 저장한다. citation이 없는 답변(근거 부족 응답)은
 * 백엔드가 400을 던진다 — 호출부에서 ApiError(status===400)로 구분해서 처리한다.
 * @returns {Promise<{page_id: string, version_id: string, slug: string}>}
 */
export function saveMessageToWiki(sessionId, messageId) {
  return apiFetch(`/chat/sessions/${sessionId}/messages/${messageId}/save-to-wiki`, {
    method: 'POST',
  });
}

/**
 * 대화 제목 직접 수정. 개인 세션은 소유자만, 팀 세션은 참여자 누구나 호출할 수 있다.
 * 빈 제목이거나 100자를 넘으면 백엔드가 400을 던진다.
 * @returns {Promise<{id, workspace_id, user_id, title, visibility, archived_at, created_at, updated_at}>}
 */
export function renameChatSession(sessionId, title) {
  return apiFetch(`/chat/sessions/${sessionId}/title`, { method: 'PATCH', body: { title } });
}

/**
 * 보관 토글. 개인 세션은 소유자만, 팀 세션은 워크스페이스 멤버 누구나 호출할 수 있다
 * (백엔드가 권한 없으면 404를 던진다).
 * @returns {Promise<{id, workspace_id, user_id, title, visibility, archived_at, created_at, updated_at}>}
 */
export function archiveChatSession(sessionId) {
  return apiFetch(`/chat/sessions/${sessionId}/archive`, { method: 'PATCH' });
}

/**
 * 소프트 삭제. 개인/팀 세션 모두 생성자만 가능하다(팀 세션이어도 다른 멤버는 403).
 * 성공하면 204라 apiFetch가 null을 돌려준다.
 */
export function deleteChatSession(sessionId) {
  return apiFetch(`/chat/sessions/${sessionId}`, { method: 'DELETE' });
}

/**
 * 팀 세션의 참여자 목록. 참여자만 조회할 수 있다(팀 세션은 이제 워크스페이스 전체가
 * 아니라 참여자만 볼 수 있다).
 * @returns {Promise<{user_id: string, display_name: string|null}[]>}
 */
export function fetchSessionParticipants(sessionId) {
  return apiFetch(`/chat/sessions/${sessionId}/participants`);
}

/**
 * 참여자 추가. 이미 참여 중인 사람이면 누구나 다른 워크스페이스 멤버를 추가할 수 있다.
 * @returns {Promise<{user_id: string, display_name: string|null}>}
 */
export function addSessionParticipant(sessionId, userId) {
  return apiFetch(`/chat/sessions/${sessionId}/participants`, {
    method: 'POST',
    body: { user_id: userId },
  });
}

/**
 * 참여자 제거. 본인 탈퇴는 항상 되고, 다른 사람을 빼는 건 세션 생성자만 가능하다
 * (아니면 403).
 */
export function removeSessionParticipant(sessionId, userId) {
  return apiFetch(`/chat/sessions/${sessionId}/participants/${userId}`, { method: 'DELETE' });
}

/**
 * "참여자 추가" 선택지에 쓸 워크스페이스 멤버 전체 목록.
 * @returns {Promise<{user_id: string, display_name: string|null}[]>}
 */
export function fetchWorkspaceMembers() {
  return apiFetch('/workspace/members');
}

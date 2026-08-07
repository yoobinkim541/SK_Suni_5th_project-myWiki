// [LIVE] src/api/main.py의 오너 전용 워크스페이스 관리 엔드포인트 연결.
// 4개 전부 서버가 오너 role을 확인해서 막는다(403) — 여기선 UI만 가린다.
import { apiFetch } from './client';

/**
 * 워크스페이스에서 멤버를 방출한다. 오너 본인은 대상이 될 수 없다(서버가 400).
 * @returns {Promise<null>}
 */
export function removeWorkspaceMember(userId) {
  return apiFetch(`/workspace/members/${userId}`, { method: 'DELETE' });
}

/**
 * 멤버 역할을 바꾼다.
 * @param {'admin'|'editor'|'viewer'} role
 * @returns {Promise<{user_id, display_name, email, role}>}
 */
export function updateWorkspaceMemberRole(userId, role) {
  return apiFetch(`/workspace/members/${userId}/role`, { method: 'PATCH', body: { role } });
}

/**
 * 워크스페이스의 모든 팀/개인 세션(참여 여부·소유자 무관)을 조회한다.
 * @param {'team'|'private'} visibility
 * @returns {Promise<{id, workspace_id, user_id, title, visibility, owner_name, archived_at, created_at, updated_at}[]>}
 */
export function listWorkspaceSessions(visibility) {
  return apiFetch(`/workspace/sessions?visibility=${visibility}`);
}

/**
 * 세션 하나의 대화 내용을 읽기 전용으로 조회한다.
 * @returns {Promise<{id, session_id, role, content, created_at, citations}[]>}
 */
export function getWorkspaceSessionMessages(sessionId) {
  return apiFetch(`/workspace/sessions/${sessionId}/messages`);
}

// [LIVE] src/api/main.py의 팀 관리 엔드포인트 연결.
// 팀 CRUD·전체 배치는 서버가 오너 role을 확인해서 막고(403), 초대/영입/제외는
// 서버가 호출자의 team_id가 대상 팀과 일치하는지까지 확인한다 — 여기선 UI만 가린다.
import { apiFetch } from './client';

/** 팀 목록 + 인원수. 워크스페이스 멤버 누구나 조회 가능.
 * @returns {Promise<{id, name, member_count}[]>}
 */
export function listTeams() {
  return apiFetch('/teams');
}

/** 팀별 멤버 명단. 워크스페이스 멤버 누구나 조회 가능.
 * @returns {Promise<{user_id, display_name, role}[]>}
 */
export function listTeamMembers(teamId) {
  return apiFetch(`/teams/${teamId}/members`);
}

/** 팀 생성 — 관리자(오너) 전용. */
export function createTeam(name) {
  return apiFetch('/teams', { method: 'POST', body: { name } });
}

/** 팀 삭제 — 관리자(오너) 전용. 소속 인원이 있으면 서버가 400. */
export function deleteTeam(teamId) {
  return apiFetch(`/teams/${teamId}`, { method: 'DELETE' });
}

/** 전체 사용자 + 소속 팀 — 관리자(오너) 전용.
 * @returns {Promise<{user_id, display_name, role, team_id, team_name}[]>}
 */
export function listAllUsersWithTeam() {
  return apiFetch('/admin/users');
}

/** 사용자를 임의 팀에 배치/제외(teamId=null) — 관리자(오너) 전용, 자기 팀 범위 제한 없음. */
export function assignUserTeam(userId, teamId) {
  return apiFetch(`/admin/users/${userId}/team`, { method: 'PATCH', body: { team_id: teamId } });
}

/** 팀원 초대 — 팀원/팀장 공통, 자기 팀에만. 대상은 미배치 사용자만(서버가 400으로 거부). */
export function inviteTeamMember(teamId, userId) {
  return apiFetch(`/teams/${teamId}/members`, { method: 'POST', body: { user_id: userId } });
}

/** 팀원 영입 — 팀장 전용, 자기 팀만. 대상이 다른 팀 소속이어도 데려올 수 있다. */
export function recruitTeamMember(teamId, userId) {
  return apiFetch(`/teams/${teamId}/members/recruit`, { method: 'POST', body: { user_id: userId } });
}

/** 팀원 제외(팀에서만, 워크스페이스 방출 아님) — 팀장 전용, 자기 팀만. */
export function removeTeamMember(teamId, userId) {
  return apiFetch(`/teams/${teamId}/members/${userId}`, { method: 'DELETE' });
}

// 워크스페이스 역할 정의 및 권한 판정.
//
// DB(workspace_members.role)는 owner/admin/editor/viewer 4개 값을 쓰는데,
// 화면에서 부르는 이름(관리자/팀장/팀원/게스트)과 달라서 여기서 한 번 매핑한다.
// ⚠ 역할 값이 바뀌면 이 파일만 고치면 된다.
//
// 2026-08-05 팀 확정:
//   owner  = 관리자   방출·역할지정까지 전부
//   admin  = 팀장     영입·초대·세션에서 제외
//   editor = 팀원     초대만
//   viewer = 게스트   대시보드만 열람
//
// ⚠ 여기서 하는 건 화면 제어일 뿐이고, 실제 차단은 백엔드가 한다.
//   버튼을 숨겨도 API를 직접 부르면 그대로 나가므로 서버 권한 체크가 반드시 필요하다.

export const ROLE = {
  ADMIN: 'owner',    // 관리자
  LEADER: 'admin',   // 팀장
  MEMBER: 'editor',  // 팀원
  GUEST: 'viewer',   // 게스트
};

export const ROLE_LABEL = {
  [ROLE.ADMIN]: '관리자',
  [ROLE.LEADER]: '팀장',
  [ROLE.MEMBER]: '팀원',
  [ROLE.GUEST]: '게스트',
};

// 배지 색 구분용 클래스 접미사 (globals.css의 .pt-role.* 참조)
export const ROLE_CLASS = {
  [ROLE.ADMIN]: 'admin',
  [ROLE.LEADER]: 'leader',
  [ROLE.MEMBER]: 'member',
  [ROLE.GUEST]: 'guest',
};

export function roleLabel(role) {
  return ROLE_LABEL[role] ?? '';
}

export function roleClass(role) {
  return ROLE_CLASS[role] ?? '';
}

// ---------- 권한 판정 ----------
//
//                관리자  팀장  팀원  게스트
// 팀 영입           O      O     X     X
// 팀 방출           O      X     X     X
// 팀장/팀원 지정    O      X     X     X
// 세션 초대         O      O     O     X
// 세션에서 제외     O      O     X     X

/** 워크스페이스에 멤버를 영입할 수 있는가 */
export function canInviteToWorkspace(role) {
  return role === ROLE.ADMIN || role === ROLE.LEADER;
}

/** 워크스페이스에서 멤버를 방출할 수 있는가 */
export function canRemoveFromWorkspace(role) {
  return role === ROLE.ADMIN;
}

/** 다른 사람의 역할을 바꿀 수 있는가 */
export function canChangeRole(role) {
  return role === ROLE.ADMIN;
}

/** 세션에 참여자를 초대할 수 있는가 */
export function canInviteToSession(role) {
  return role === ROLE.ADMIN || role === ROLE.LEADER || role === ROLE.MEMBER;
}

/**
 * 세션에서 참여자를 뺄 수 있는가.
 * 본인이 나가는 것(자진 탈퇴)은 역할과 무관하게 항상 가능하다.
 */
export function canRemoveFromSession(role, { isSelf = false } = {}) {
  if (isSelf) return true;
  return role === ROLE.ADMIN || role === ROLE.LEADER;
}

// ---------- 팀(teams 테이블) 스코프 권한 판정 ----------
//
// 위 canInviteToWorkspace 등과는 별개다 — 저건 "워크스페이스"(우리 팀 전체) 단위이고
// 여기는 워크스페이스 안의 하위 그룹인 teams 테이블 기준이다. 팀장/팀원의 액션은
// 항상 자기 소속 팀 범위 안에서만 허용되며, 그 범위 체크는 화면(TeamPanel)에서
// myTeamId와 대상 teamId를 비교해서 한다 — 여기 함수들은 역할만 판정한다.
//
//                관리자  팀장  팀원
// 팀 생성/삭제      O      X     X
// 전체 배치 관리    O      X     X
// 팀원 초대         X      O     O   (미배치 사용자만, 자기 팀에)
// 팀원 영입         X      O     X   (타 팀 소속자도 가능, 자기 팀에)
// 팀원 제외         X      O     X   (자기 팀에서만)

/** 팀 생성·삭제·전체 사용자 배치 관리를 할 수 있는가 */
export function canManageTeams(role) {
  return role === ROLE.ADMIN;
}

/** 자기 팀에 미배치 사용자를 초대할 수 있는가 */
export function canInviteToTeam(role) {
  return role === ROLE.LEADER || role === ROLE.MEMBER;
}

/** 자기 팀으로 타 팀 소속자를 영입할 수 있는가 */
export function canRecruitToTeam(role) {
  return role === ROLE.LEADER;
}

/** 자기 팀에서 팀원을 제외할 수 있는가 */
export function canRemoveFromTeam(role) {
  return role === ROLE.LEADER;
}

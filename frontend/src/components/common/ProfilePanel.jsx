// 공통 컴포넌트 — 상단바 우측 프로필 드롭다운 ("작은 모달": 계정 정보 + 로그인 · 로그아웃)
//
// .profile-panel/.pp-* 클래스(로그인 전 .pp-oauth 소셜 버튼, 로그인 후 .pp-me/.pp-item)는
// 시안 CSS에 이미 준비돼 있었는데 실제로 연결된 컴포넌트가 없었습니다. 이번에 처음 붙입니다.
//
//  · 로그인 상태(authed=true): 실제 Supabase 세션의 profile(계정 정보) + 소속 팀 + 로그아웃 + 회원 탈퇴
//  · 로그아웃 상태(authed=false): 소셜 로그인 버튼 — App.jsx의 onLogin이 signInWithOAuth로 리다이렉트한다.
//    카카오는 Supabase provider가 아직 활성화 안 돼 있어서 버튼을 빼뒀다(Google/GitHub만 활성화됨).
//
// ⚠ 소속 팀: workspace(이름) + 내 role(역할)을 받아 표시한다. 아직 안 내려오면 영역을 숨긴다
//   (없는 값을 "소속 없음"처럼 단정해 보여주지 않는다).
// ⚠ 회원 탈퇴는 되돌릴 수 없어서 여기서 바로 실행하지 않고 onDeleteAccount로 확인 모달을 연다.

import { roleLabel, roleClass } from '../../constants/roles';

// EntryFlow.jsx의 OAUTH_PROVIDERS와 동일하게 유지한다(둘 중 하나만 고치면 화면마다 버튼이 달라진다).
const OAUTH_PROVIDERS = [
  { key: 'google', label: 'Google로 계속하기', ic: 'G' },
  { key: 'github', label: 'GitHub로 계속하기', ic: 'Gh' },
  { key: 'custom:naver', label: '네이버로 계속하기', ic: 'N' },
];

export default function ProfilePanel({
  isOpen,
  authed,
  profile,
  displayName,
  avatarUrl,
  workspaceName,
  myRole,
  // 관심사 고르기(선호조사)에서 고른 직무. workspace 안에서의 권한을 뜻하는 위의
  // myRole(오너/관리자/멤버)과 이름이 겹치기 쉬워서 jobTitle로 따로 받는다.
  jobTitle,
  onLogin,
  onLogout,
  onDeleteAccount,
}) {
  // profiles.display_name(설정 화면에서 편집 가능)이 있으면 그걸 쓰고, 아직 안
  // 내려왔으면(로딩 중 등) OAuth 로그인 이름으로 잠깐 대체한다.
  const name = displayName || profile?.user_metadata?.full_name || profile?.user_metadata?.name || profile?.email || '';
  const email = profile?.email || '';
  const hasTeam = Boolean(workspaceName || myRole);

  return (
    <div className={`profile-panel${isOpen ? ' open' : ''}`}>
      {authed ? (
        <>
          <div className="pp-me">
            {avatarUrl ? (
              <img src={avatarUrl} alt="" className="pp-av" style={{ objectFit: 'cover' }} />
            ) : (
              <span className="pp-av">{name.charAt(0).toUpperCase()}</span>
            )}
            <div className="pp-info">
              <div className="pp-name">{name}</div>
              <div className="pp-mail">{email}</div>
            </div>
          </div>

          {/* 소속 팀 — 워크스페이스 이름과 역할이 내려올 때만 보여준다. 직무(jobTitle)는
              관심사 고르기에서 고른 값이라 팀과는 출처가 다르지만, 한 사람을 소개하는
              정보라는 점에서 같은 줄에 붙여 보여준다("3팀 · 반도체 공정기술"). 팀 정보가
              아예 없는데 직무만 있는 경우엔 "직무"로 라벨을 바꿔서 따로 보여준다. */}
          {hasTeam && (
            <div className="pp-team">
              <span className="lb">소속 팀</span>
              <span className="tx">
                {workspaceName || '이름 없음'}
                {myRole && (
                  <span className={`pt-role ${roleClass(myRole)}`}>{roleLabel(myRole)}</span>
                )}
                {jobTitle && <span className="pp-job"> · {jobTitle}</span>}
              </span>
            </div>
          )}
          {!hasTeam && jobTitle && (
            <div className="pp-team">
              <span className="lb">직무</span>
              <span className="tx">{jobTitle}</span>
            </div>
          )}

          <button className="pp-item danger" onClick={onLogout}>로그아웃</button>
          <button className="pp-item danger" onClick={onDeleteAccount}>회원 탈퇴</button>
        </>
      ) : (
        <>
          <div className="pp-hd">
            <div className="pp-ttl">로그인</div>
            <div className="pp-sub">계정으로 로그인하고 계속하세요</div>
          </div>
          {OAUTH_PROVIDERS.map((p) => (
            <button key={p.key} className={`pp-oauth ${p.key}`} onClick={() => onLogin(p.key)}>
              <span className="ic">{p.ic}</span>{p.label}
            </button>
          ))}
        </>
      )}
    </div>
  );
}

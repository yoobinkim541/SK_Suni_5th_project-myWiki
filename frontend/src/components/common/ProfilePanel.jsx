// 공통 컴포넌트 — 상단바 우측 프로필 드롭다운 ("작은 모달": 계정 정보 + 로그인 · 로그아웃)
//
// .profile-panel/.pp-* 클래스(로그인 전 .pp-oauth 소셜 버튼, 로그인 후 .pp-me/.pp-item)는
// 시안 CSS에 이미 준비돼 있었는데 실제로 연결된 컴포넌트가 없었습니다. 이번에 처음 붙입니다.
//
//  · 로그인 상태(authed=true): 실제 Supabase 세션의 profile(계정 정보) + 로그아웃(.pp-item.danger)
//  · 로그아웃 상태(authed=false): 소셜 로그인 버튼 — App.jsx의 onLogin이 signInWithOAuth로 리다이렉트한다.
//    카카오는 Supabase provider가 아직 활성화 안 돼 있어서 버튼을 빼뒀다(Google/GitHub만 활성화됨).

// EntryFlow.jsx의 OAUTH_PROVIDERS와 동일하게 유지한다(둘 중 하나만 고치면 화면마다 버튼이 달라진다).
const OAUTH_PROVIDERS = [
  { key: 'google', label: 'Google로 계속하기', ic: 'G' },
  { key: 'github', label: 'GitHub로 계속하기', ic: 'Gh' },
  { key: 'custom:naver', label: '네이버로 계속하기', ic: 'N' },
];

export default function ProfilePanel({ isOpen, authed, profile, onLogin, onLogout }) {
  const name = profile?.user_metadata?.full_name || profile?.user_metadata?.name || profile?.email || '';
  const email = profile?.email || '';

  return (
    <div className={`profile-panel${isOpen ? ' open' : ''}`}>
      {authed ? (
        <>
          <div className="pp-me">
            <span className="pp-av">{name.charAt(0).toUpperCase()}</span>
            <div className="pp-info">
              <div className="pp-name">{name}</div>
              <div className="pp-mail">{email}</div>
            </div>
          </div>
          <button className="pp-item danger" onClick={onLogout}>로그아웃</button>
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

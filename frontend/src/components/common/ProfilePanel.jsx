// 공통 컴포넌트 — 상단바 우측 프로필 드롭다운 ("작은 모달": 계정 정보 + 로그인 · 로그아웃)
//
// .profile-panel/.pp-* 클래스(로그인 전 .pp-oauth 소셜 버튼, 로그인 후 .pp-me/.pp-item)는
// 시안 CSS에 이미 준비돼 있었는데 실제로 연결된 컴포넌트가 없었습니다. 이번에 처음 붙입니다.
//
//  · 로그인 상태(authed=true): 계정 정보(.pp-me) + 로그아웃(.pp-item.danger)
//  · 로그아웃 상태(authed=false): 소셜 로그인 버튼(.pp-oauth) 3종
//    — App.jsx handleLogin이 실제 Supabase OAuth(api/auth.js signInWithProvider)를 호출합니다.
//      account는 더 이상 mockAccount 목업이 아니라 App.jsx가 세션에서 뽑아 내려주는 값입니다.
//
// ⚠ 카카오는 아직 Supabase 프로젝트(Authentication → Providers)에서 활성화되지 않았습니다
//   (client_id/secret 미등록 — /auth/v1/authorize?provider=kakao 가 400 "provider is not
//   enabled"를 돌려줌, 2026-08-04 확인). 활성화 전에 버튼을 누르게 두면 Supabase가 돌려주는
//   원본 에러 JSON 화면으로 튕겨나가 버립니다. 활성화되기 전까지는 비활성 처리하고
//   "준비 중"이라고 표시합니다 — Supabase 콘솔에서 카카오 프로바이더를 켜면
//   DISABLED_PROVIDERS에서 'kakao'만 빼면 됩니다.
const OAUTH_PROVIDERS = [
  { key: 'google', label: 'Google로 계속하기', ic: 'G' },
  { key: 'github', label: 'GitHub로 계속하기', ic: 'Gh' },
  { key: 'kakao', label: '카카오로 계속하기', ic: 'K' },
];

const DISABLED_PROVIDERS = new Set(['kakao']);

export default function ProfilePanel({ isOpen, authed, account, onLogin, onLogout }) {
  return (
    <div className={`profile-panel${isOpen ? ' open' : ''}`}>
      {authed ? (
        <>
          <div className="pp-me">
            <span className="pp-av">{account?.name?.charAt(0) || ''}</span>
            <div className="pp-info">
              <div className="pp-name">{account?.name || '사용자'}</div>
              <div className="pp-mail">{account?.email || ''}</div>
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
          {OAUTH_PROVIDERS.map((p) => {
            const disabled = DISABLED_PROVIDERS.has(p.key);
            return (
              <button
                key={p.key}
                className={`pp-oauth ${p.key}`}
                onClick={() => onLogin(p.key)}
                disabled={disabled}
                title={disabled ? '준비 중입니다' : undefined}
              >
                <span className="ic">{p.ic}</span>{p.label}{disabled ? ' (준비 중)' : ''}
              </button>
            );
          })}
          <div className="pp-note">Google/GitHub 계정으로 로그인할 수 있습니다.</div>
        </>
      )}
    </div>
  );
}

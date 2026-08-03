// 공통 컴포넌트 — 상단바 우측 프로필 드롭다운 ("작은 모달": 계정 정보 + 로그인 · 로그아웃)
//
// .profile-panel/.pp-* 클래스(로그인 전 .pp-oauth 소셜 버튼, 로그인 후 .pp-me/.pp-item)는
// 시안 CSS에 이미 준비돼 있었는데 실제로 연결된 컴포넌트가 없었습니다. 이번에 처음 붙입니다.
//
//  · 로그인 상태(authed=true): 계정 정보(.pp-me) + 로그아웃(.pp-item.danger)
//  · 로그아웃 상태(authed=false): 소셜 로그인 버튼(.pp-oauth) 3종
//    — 백엔드 인증이 아직 없어서, 셋 중 아무 버튼이나 누르면 그 자리에서 데모 계정으로
//      "로그인" 처리만 됩니다(App.jsx handleLogin). 실제 OAuth 연동 전 자리만 잡아둔 것.

import { ACCOUNT } from '../../data/mockAccount';

const OAUTH_PROVIDERS = [
  { key: 'google', label: 'Google로 계속하기', ic: 'G' },
  { key: 'github', label: 'GitHub로 계속하기', ic: 'Gh' },
  { key: 'kakao', label: '카카오로 계속하기', ic: 'K' },
];

export default function ProfilePanel({ isOpen, authed, onLogin, onLogout }) {
  return (
    <div className={`profile-panel${isOpen ? ' open' : ''}`}>
      {authed ? (
        <>
          <div className="pp-me">
            <span className="pp-av">{ACCOUNT.name.charAt(0)}</span>
            <div className="pp-info">
              <div className="pp-name">{ACCOUNT.name}</div>
              <div className="pp-mail">{ACCOUNT.email}</div>
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
          <div className="pp-note">백엔드 인증 연동 전이라, 어떤 버튼을 눌러도 데모 계정으로 로그인됩니다.</div>
        </>
      )}
    </div>
  );
}

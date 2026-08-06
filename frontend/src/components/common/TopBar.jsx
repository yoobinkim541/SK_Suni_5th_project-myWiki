// 공통 컴포넌트 1/6 — 상단바
// PC/모바일 공용. PC는 시안 CSS의 .deck, 모바일은 .m-topbar 클래스를 씁니다.
//
// ⚠ 로고: PC 상단바(.deck)와 모바일 상단바(.m-topbar) 모두 이미지 로고
//   (logo.png / logo-dark.png)를 씁니다. 라이트/다크 두 버전을 모두 렌더링해두고,
//   CSS(:root[data-theme="dark"])로 하나만 보이게 전환합니다(민트그린 다크 버전).
//   사이드바(SideNav)는 기존 LogoMark(SVG)를 그대로 유지합니다.
//
// ⚠ 모바일 로고는 아이콘+텍스트가 합쳐진 이미지라, 기존 LogoMark + "myWiki" 텍스트 조합을
//   <img> 하나로 대체했습니다. 상단바 높이에 맞춰 CSS(.m-logo-img)에서 높이만 제한합니다.
//
// ⚠ 우측 상단 프로필 버튼(PC만): 톱니바퀴(SettingsPanel) + .avatar(ProfilePanel).
//   .deck-right로 감싸고 margin-left:auto로 우측 끝에 붙입니다. 열고 닫기는 App.jsx가 합니다.
//
// ⚠ 사이드바 접기 버튼(PC만) 추가: .brand2 왼쪽에 햄버거 버튼을 새로 붙였습니다. 누르면
//   App.jsx의 sideCollapsed 상태가 토글되고 SideNav가 아이콘만 남은 폭으로 접힙니다.
//   모바일 변형은 원래 쓰던 메뉴 버튼(.m-icobtn, onMenuClick=드로어 열기)을 그대로 씁니다 —
//   이 접기 버튼과는 별개 기능이라 손대지 않았습니다.

import logo from '../../assets/logo.png';
import logoDark from '../../assets/logo-dark.png';

export default function TopBar({
  variant = 'mobile',
  onMenuClick,
  onMoreClick,
  onSettingsClick,
  onLogoClick,
  settingsOpen = false,
  onProfileClick,
  profileOpen = false,
  authed = true,
  avatarInitial = '',
  onSideToggle,
  sideCollapsed = false,
}) {
  if (variant === 'mobile') {
    return (
      <header className="m-topbar">
        <button className="m-icobtn" aria-label="메뉴 열기" aria-expanded="false" onClick={onMenuClick}>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
            <path d="M4 7h16M4 12h16M4 17h16" />
          </svg>
        </button>

        <button className="m-logo" onClick={onLogoClick} title="myWiki — 처음 화면으로 새로고침">
          <img src={logo} alt="myWiki" className="m-logo-img logo-light" />
          <img src={logoDark} alt="myWiki" className="m-logo-img logo-dark" />
        </button>

        <div className="m-right">
          <button className="m-icobtn" aria-label="프로필 / 더보기" onClick={onMoreClick}>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="8" r="3.4" />
              <path d="M5.5 20a6.5 6.5 0 0 1 13 0" />
            </svg>
          </button>
          <span className="m-dot" aria-hidden="true"></span>
        </div>
      </header>
    );
  }

  return (
    <header className="deck">
      <button
        className="side-toggle"
        aria-label={sideCollapsed ? '사이드바 펼치기' : '사이드바 접기'}
        aria-expanded={!sideCollapsed}
        title={sideCollapsed ? '사이드바 펼치기' : '사이드바 접기'}
        onClick={onSideToggle}
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
          <path d="M4 7h16M4 12h16M4 17h16" />
        </svg>
      </button>

      <button className="brand2" onClick={onLogoClick} title="myWiki — 처음 화면으로 새로고침">
        <img src={logo} alt="myWiki" className="brand2-logo-img logo-light" />
        <img src={logoDark} alt="myWiki" className="brand2-logo-img logo-dark" />
      </button>

      <div className="deck-right">
        <button
          className={`gear${settingsOpen ? ' open' : ''}`}
          aria-label="환경 설정"
          title="환경 설정"
          onClick={onSettingsClick}
        >
          ⚙
        </button>

        <button
          className={`avatar${profileOpen ? ' open' : ''}${authed ? ' auth' : ''}`}
          aria-label="프로필"
          title="프로필"
          onClick={onProfileClick}
        >
          {authed ? (
            <span className="ini">{avatarInitial}</span>
          ) : (
            <svg className="ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="8" r="3.4" />
              <path d="M5.5 20a6.5 6.5 0 0 1 13 0" />
            </svg>
          )}
        </button>
      </div>
    </header>
  );
}

// 공통 컴포넌트 1/6 — 상단바
// PC/모바일 공용. PC는 시안 CSS의 .deck, 모바일은 .m-topbar 클래스를 씁니다.
//
// ⚠ 수정한 부분: 모바일 쪽을 완전히 새로 그렸습니다.
//   기존엔 .mobile-topbar/.hbtn/.brand2라는, 실제 시안(HTML) 어디에도 없던 클래스를 쓰고
//   있었는데, 최신 시안에서 팀원이 .m-topbar(햄버거+로고+프로필아이콘) 기반의 완성도 있는
//   모바일 상단바를 새로 만들어서 그 구조에 맞춰 다시 작성했습니다.
//   - 왼쪽 햄버거(☰) → onMenuClick (좌측 드로어 열기)
//   - 오른쪽 프로필 아이콘 → onMoreClick ("더보기" 바텀시트 열기 — MobileNav.jsx의 MoreSheet)
//   PC(.deck) 쪽은 원래 시안과 이미 일치했어서 그대로 뒀습니다.
//
// ⚠ 로고 아이콘 추가: 텍스트만 있던 자리에 LogoMark(SVG)를 붙였습니다. PC 상단바가
//   화면 맨 왼쪽 위 자리라 여기 아이콘이 제일 먼저 보입니다.
//
// ⚠ 우측 상단 프로필 버튼 추가(PC만): 톱니바퀴(환경설정) + .avatar 버튼을 붙였습니다.
//   .avatar/.profile-panel 클래스는 시안 CSS에 이미 있었는데 실제로 연결이 안 돼 있어서
//   이번에 처음 씁니다. 톱니바퀴는 SettingsPanel(다크모드·글자크기·알림), 프로필은
//   ProfilePanel(계정 정보 + 로그인/로그아웃)을 엽니다 — 둘 다 App.jsx가 열고 닫습니다.
//   모바일은 기존 "프로필 / 더보기" 아이콘이 이미 이 역할(설정·로그아웃 포함)을 하고 있어
//   그대로 뒀습니다.
//
//   ⚠ 로고 바로 옆이 아니라 페이지 우측 끝에 붙게 .deck-right로 감싸고 margin-left:auto를
//     줬습니다(처음엔 로고 옆에 나란히 뒀었는데, 그러면 우측 상단이 아니라 로고 우측이라
//     의도한 위치가 아니었습니다).

import LogoMark from './LogoMark';

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
          <LogoMark className="m-logo-ic" />myWiki
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
      <button className="brand2" onClick={onLogoClick} title="myWiki — 처음 화면으로 새로고침">
        <LogoMark className="brand2-ic" />myWiki
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

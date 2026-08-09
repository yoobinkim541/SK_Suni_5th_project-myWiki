// 공통 컴포넌트 3/6 — 모바일 전용 내비게이션 (드로어 + 하단 탭바 + "더보기" 바텀시트)
// PC에서는 이 컴포넌트 대신 SideNav.jsx를 씁니다.
//
// ⚠ 전면 재작성했습니다.
//   기존엔 .bottomnav/.side.open/.backdrop/.drawer-close 라는, 실제 최신 시안 어디에도
//   없는 클래스를 쓰고 있었습니다(예전 시안 기준으로 짠 것). 최신 시안에서 팀원이
//   .m-drawer(좌측 드로어) / .m-tabbar(하단 5탭, 마지막 "더보기") / .m-sheet(바텀시트)
//   라는 훨씬 완성도 있는 모바일 내비게이션을 새로 만들어서 그 구조에 맞춰 다시 짰습니다.
//
//   구조가 3개로 늘어나서 export도 3개입니다:
//   - Drawer: 좌측 슬라이드 메뉴 (기존과 같은 역할, 클래스만 .m-drawer로 교체)
//   - BottomNav: 하단 5탭(대시보드/리포트/에이전트/위키/더보기).
//     "더보기" 탭은 페이지 이동이 아니라 onMoreClick으로 MoreSheet를 엽니다.
//   - MoreSheet(신규): "더보기" 눌렀을 때 뜨는 바텀시트 — 계정 설정/환경 설정/PWA 설치/로그아웃.
//     시안 원본은 PWA 설치까지 지원(beforeinstallprompt 이벤트)하는데, 이건 브라우저 전역
//     이벤트라 App.jsx에서 훅으로 관리하고 여기엔 콜백만 받게 했습니다.
//
// ⚠ 로고 아이콘 추가: 드로어 브랜드도 사이드바와 같은 LogoMark(SVG)를 씁니다.

import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import LogoMark from './LogoMark';
import { NAV_PATHS } from '../../constants/navPaths';

// 항목 아이콘 — SideNav.jsx(PC)와 같은 path를 씁니다. globals.css의 `.m-drawer a .ic svg`가
// 이미 이 마크업(`<span className="ic">`)을 전제로 스타일을 준비해뒀는데 지금까지 안 쓰이고
// 있었습니다 — PC 사이드바처럼 모바일 드로어도 글자 옆에 아이콘이 보이도록 채워 넣습니다.
const DRAWER_ICONS = {
  dash: (
    <svg viewBox="0 0 24 24"><path d="M3 10.5 12 3l9 7.5" /><path d="M5 9.7V20h14V9.7" /></svg>
  ),
  report: (
    <svg viewBox="0 0 24 24"><rect x="5" y="3" width="14" height="18" rx="2" /><path d="M8 8h8M8 12h8M8 16h5" /></svg>
  ),
  cat: (
    <svg viewBox="0 0 24 24"><path d="M4 19V10M10 19V4M16 19V13" /><path d="M4 19h16" /></svg>
  ),
  wiki: (
    <svg viewBox="0 0 24 24"><path d="M5 4h9a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z" /><path d="M17 6.5h2V20" /></svg>
  ),
  agent: (
    <svg viewBox="0 0 24 24"><path d="M4 5h16v10H9l-4 3v-3H4z" /></svg>
  ),
  settings: (
    <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3" /><path d="M12 3v2M12 19v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M3 12h2M19 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4" /></svg>
  ),
};

const DRAWER_ITEMS = [
  { group: 'MONITOR', items: [
    { key: 'dash', label: '대시보드' },
    { key: 'report', label: '일일 리포트' },
    { key: 'cat', label: '카테고리 현황' },
  ]},
  { group: 'KNOWLEDGE', items: [
    { key: 'wiki', label: '위키' },
    { key: 'agent', label: '에이전트' },
  ]},
  { group: 'CONFIG', items: [
    { key: 'settings', label: '설정' },
  ]},
];

export function Drawer({ isOpen, onClose, onLogoClick, lastCollected = '07:42', nextCollected = '08:00' }) {
  return (
    <>
      <div className={`m-drawer-scrim${isOpen ? ' open' : ''}`} onClick={onClose}></div>
      <aside className={`m-drawer${isOpen ? ' open' : ''}`} aria-label="사이드 메뉴">
        <div className="brand brand-btn" role="button" tabIndex={0}
          title="myWiki — 처음 화면으로 새로고침"
          onClick={() => { onLogoClick?.(); onClose?.(); }}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onLogoClick?.(); onClose?.(); } }}
        >
          <div className="eb">반도체 동향 시스템</div>
          <div className="nm"><LogoMark className="nm-ic" />myWiki</div>
          <div className="rule"></div>
        </div>
        {DRAWER_ITEMS.map((section) => (
          <nav key={section.group}>
            <div className="lb">{section.group}</div>
            {section.items.map((item) => (
              <NavLink
                key={item.key}
                to={NAV_PATHS[item.key]}
                end={item.key === 'dash'}
                className={({ isActive }) => (isActive ? 'on' : '')}
                onClick={() => onClose?.()}
              >
                <span className="ic">{DRAWER_ICONS[item.key]}</span>
                {item.label}
              </NavLink>
            ))}
          </nav>
        ))}
        <div className="m-drawer-foot">마지막 수집 {lastCollected}<br />다음 수집 {nextCollected}</div>
      </aside>
    </>
  );
}

const BOTTOM_TABS = [
  {
    key: 'dash', label: '대시보드',
    icon: (<svg viewBox="0 0 24 24"><path d="M3 10.5 12 3l9 7.5" /><path d="M5 9.7V20h14V9.7" /></svg>),
  },
  {
    key: 'report', label: '리포트',
    icon: (<svg viewBox="0 0 24 24"><rect x="5" y="3" width="14" height="18" rx="2" /><path d="M8 8h8M8 12h8M8 16h5" /></svg>),
  },
  {
    key: 'agent', label: '에이전트',
    icon: (<svg viewBox="0 0 24 24"><path d="M4 5h16v10H9l-4 3v-3H4z" /></svg>),
  },
  {
    key: 'wiki', label: '위키',
    icon: (<svg viewBox="0 0 24 24"><path d="M5 4h9a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z" /><path d="M17 6.5h2V20" /></svg>),
  },
];

const MORE_ICON = (
  <svg viewBox="0 0 24 24"><circle cx="5" cy="12" r="1.5" /><circle cx="12" cy="12" r="1.5" /><circle cx="19" cy="12" r="1.5" /></svg>
);

export function BottomNav({ onMoreClick }) {
  // "더보기"는 현재 경로가 탭 4개(dash/report/agent/wiki)의 경로 밖일 때(예: /category, /settings) 활성 표시
  const location = useLocation();
  const isMoreActive = !BOTTOM_TABS.some((tab) => {
    const path = NAV_PATHS[tab.key];
    return path === '/' ? location.pathname === '/' : location.pathname.startsWith(path);
  });
  return (
    <nav className="m-tabbar" aria-label="하단 탭">
      {BOTTOM_TABS.map((tab) => (
        <NavLink
          key={tab.key}
          to={NAV_PATHS[tab.key]}
          end={tab.key === 'dash'}
          className={({ isActive }) => `mtab${isActive ? ' active' : ''}`}
        >
          <span className="ic">{tab.icon}</span>{tab.label}
        </NavLink>
      ))}
      <button className={`mtab${isMoreActive ? ' active' : ''}`} onClick={onMoreClick}>
        <span className="ic">{MORE_ICON}</span>더보기
      </button>
    </nav>
  );
}

// ⚠ 수정: "계정 설정" 항목을 뺐습니다.
//   설정 페이지의 "계정" 섹션이 프로필·이름·이메일을 그냥 보여주는 읽기 전용으로 바뀌면서
//   따로 들어갈 계정 설정 화면이 없어졌습니다. onAccountClick prop도 같이 제거했습니다.
export function MoreSheet({
  isOpen,
  onClose,
  onPwaInstallClick,
  pwaStateLabel = '홈 화면에 추가',
  onLogoutClick,
}) {
  const navigate = useNavigate();
  function close(action) {
    action?.();
    onClose?.();
  }
  return (
    <>
      <div className={`m-sheet-scrim${isOpen ? ' open' : ''}`} onClick={onClose}></div>
      <div className={`m-sheet${isOpen ? ' open' : ''}`} role="dialog" aria-label="더보기">
        <div className="m-grip"></div>
        <div className="m-sheet-h">더보기</div>
        <button className="m-sheet-item" onClick={() => close(() => navigate(NAV_PATHS.settings))}>
          <span className="ic">
            <svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="3" /><path d="M12 3v2M12 19v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M3 12h2M19 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4" /></svg>
          </span>설정
        </button>
        <button className="m-sheet-item" onClick={() => close(onPwaInstallClick)}>
          <span className="ic">
            <svg viewBox="0 0 24 24" fill="none"><path d="M12 3v11M8 10l4 4 4-4" /><path d="M5 20h14" /></svg>
          </span>PWA 설치
          <span className="m-sub">{pwaStateLabel}</span>
        </button>
        <button className="m-sheet-item danger" onClick={() => close(onLogoutClick)}>
          <span className="ic">
            <svg viewBox="0 0 24 24" fill="none"><path d="M15 4h3a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-3" /><path d="M10 8l-4 4 4 4M6 12h9" /></svg>
          </span>로그아웃
        </button>
      </div>
    </>
  );
}

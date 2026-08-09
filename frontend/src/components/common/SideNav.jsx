// 공통 컴포넌트 2/6 — PC 전용 사이드 내비게이션
// PC 시안의 <aside class="side"> 구조를 그대로 이식.
// 모바일에서는 이 컴포넌트 대신 MobileNav.jsx를 씁니다.
//
// ⚠ 수정사항 2) 사이드바 상단 브랜드도 눌러서 새로고침할 수 있게 했습니다.
//   PC에서는 상단바보다 이쪽 로고가 더 눈에 띄어서, 둘 다 같은 동작(App.jsx handleLogoClick)에 걸었습니다.
//
// ⚠ [로고 교체] 기존 LogoMark(SVG) + "myWiki" 텍스트 → mySUNI 로고 이미지로 교체.
//   - 펼친 상태: suni-logo.png (아이콘+워드마크 전체)
//   - 접힌 상태: suni-mark.png (왼쪽 삼각형 "my" 마크만 잘라낸 별도 파일)
//   두 파일 모두 assets/ 에 있습니다. 크기·정렬은 globals.css의 .suni-logo / .suni-mark 에서 조정.
//
// ⚠ 접기(collapsed) 모드 + 항목별 아이콘 + 접기 토글 위치:
//   - "반도체 산업 동향 자동 큐레이션" 문구는 상단바(TopBar.jsx .deck-title) 정중앙으로
//     옮겼습니다 — 여기 사이드바에는 더 이상 없습니다. 접기 토글은 mySUNI 로고 왼쪽에
//     나란히 둡니다(.nm-row). 토글이 brand(로고 클릭=새로고침) 블록 안에 있으므로,
//     클릭이 로고 새로고침으로 번지지 않도록 stopPropagation을 건다.
//   - 접힌 상태에서도 토글이 보여야 다시 펼 수 있어서, 접힌 모드에서는 마크 아래에
//     세로로 토글을 둔다.
//   - 항목 아이콘은 접힌 상태뿐 아니라 펼친 상태에서도 글자 옆에 항상 보입니다
//     (`.side-label`을 접힌 모드에서만 CSS로 숨김 — globals.css `.side.collapsed a .side-label`).
//   - 아이콘은 MobileNav.jsx의 하단 탭바(BOTTOM_TABS)와 같은 선 굵기·스타일을 씁니다.
//   - "설정" 아이콘은 원래 쓰던 원+스포크 SVG로(TopBar.jsx .gear 버튼과 동일한 path).

import { NavLink } from 'react-router-dom';
import { NAV_PATHS } from '../../constants/navPaths';
import SuniLogo from '../../assets/suni-logo.png';
import SuniMark from '../../assets/suni-mark.png';

const ICONS = {
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

const NAV_ITEMS = [
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

function ToggleButton({ collapsed, onToggleCollapsed }) {
  return (
    <button
      type="button"
      className="side-toggle"
      aria-label={collapsed ? '사이드바 펼치기' : '사이드바 접기'}
      aria-expanded={!collapsed}
      title={collapsed ? '사이드바 펼치기' : '사이드바 접기'}
      onClick={(e) => {
        // brand(로고) 블록 안에 있어서, 누르면 로고 클릭(새로고침)으로 이벤트가
        // 번지지 않도록 막는다.
        e.stopPropagation();
        onToggleCollapsed?.();
      }}
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
        <path d="M4 7h16M4 12h16M4 17h16" />
      </svg>
    </button>
  );
}

export default function SideNav({ onLogoClick, collapsed = false, onToggleCollapsed }) {
  return (
    <aside className={`side${collapsed ? ' collapsed' : ''}`}>
      <div className="brand brand-btn" role="button" tabIndex={0}
        title="mySUNI — 처음 화면으로 새로고침"
        onClick={onLogoClick}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onLogoClick?.(); } }}
      >
        {collapsed ? (
          <>
            <img src={SuniMark} alt="mySUNI" className="suni-mark" />
            <ToggleButton collapsed={collapsed} onToggleCollapsed={onToggleCollapsed} />
          </>
        ) : (
          <>
            <div className="nm-row">
              <ToggleButton collapsed={collapsed} onToggleCollapsed={onToggleCollapsed} />
              <div className="nm">
                <img src={SuniLogo} alt="mySUNI" className="suni-logo" />
              </div>
            </div>
          </>
        )}
      </div>
      {!collapsed && <div className="rule"></div>}

      {NAV_ITEMS.map((section) => (
        <nav key={section.group}>
          {!collapsed && <div className="lb">{section.group}</div>}
          {section.items.map((item) => (
            <NavLink
              key={item.key}
              to={NAV_PATHS[item.key]}
              end={item.key === 'dash'}
              className={({ isActive }) => (isActive ? 'on' : '')}
              title={collapsed ? item.label : undefined}
            >
              <span className="side-ic">{ICONS[item.key]}</span>
              <span className="side-label">{item.label}</span>
            </NavLink>
          ))}
        </nav>
      ))}
    </aside>
  );
}

// 공통 컴포넌트 2/6 — PC 전용 사이드 내비게이션
// PC 시안의 <aside class="side"> 구조를 그대로 이식.
// 모바일에서는 이 컴포넌트 대신 MobileNav.jsx를 씁니다.
//
// 확인 결과 이 파일은 시안 마크업(.side/.brand/.rule/.lb/a.on)과 정확히 일치해서
// 고칠 게 없었습니다.
//
// ⚠ 수정사항 2) 사이드바 상단 브랜드(myWiki)도 눌러서 새로고침할 수 있게 했습니다.
//   PC에서는 상단바보다 이쪽 로고가 더 눈에 띄어서, 둘 다 같은 동작(App.jsx handleLogoClick)에 걸었습니다.
//
// ⚠ 로고 아이콘 추가: "myWiki" 텍스트 앞에 LogoMark(SVG)를 붙였습니다.
//
// ⚠ 접기(collapsed) 모드 추가: TopBar.jsx의 햄버거 버튼(App.jsx의 sideCollapsed 상태)을 누르면
//   이 사이드바가 아이콘만 남은 좁은 폭으로 접힙니다. 펼친 상태의 마크업/스타일은 그대로 두고,
//   `collapsed`가 true일 때만 그룹 라벨·글자를 숨기고 각 항목을 아이콘 칩으로 렌더링합니다.
//   접힌 상태에서도 title 속성으로 라벨을 유지해 hover 시 툴팁으로 확인할 수 있습니다.
//   아이콘은 MobileNav.jsx의 하단 탭바(BOTTOM_TABS)와 같은 선 굵기·스타일을 씁니다
//   (완전히 같은 정의를 재사용하진 않습니다 — 두 파일이 서로의 존재를 모르는 채 독립적으로
//   유지되는 게 기존 코드베이스 관례라, 아이콘만 대응되게 새로 그렸습니다).

import LogoMark from './LogoMark';

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

export default function SideNav({ activeKey, onNavigate, onLogoClick, collapsed = false }) {
  return (
    <aside className={`side${collapsed ? ' collapsed' : ''}`}>
      <div className="brand brand-btn" role="button" tabIndex={0}
        title="myWiki — 처음 화면으로 새로고침"
        onClick={onLogoClick}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onLogoClick?.(); } }}
      >
        {collapsed ? (
          <LogoMark className="nm-ic" />
        ) : (
          <>
            <div className="eb">반도체 동향 시스템</div>
            <div className="nm"><LogoMark className="nm-ic" />myWiki</div>
            <div className="rule"></div>
          </>
        )}
      </div>

      {NAV_ITEMS.map((section) => (
        <nav key={section.group}>
          {!collapsed && <div className="lb">{section.group}</div>}
          {section.items.map((item) => (
            <a
              key={item.key}
              className={activeKey === item.key ? 'on' : ''}
              title={collapsed ? item.label : undefined}
              onClick={() => onNavigate(item.key)}
            >
              {collapsed ? <span className="side-ic">{ICONS[item.key]}</span> : item.label}
            </a>
          ))}
        </nav>
      ))}
    </aside>
  );
}

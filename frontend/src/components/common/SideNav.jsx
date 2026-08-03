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

import LogoMark from './LogoMark';

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

export default function SideNav({ activeKey, onNavigate, onLogoClick }) {
  return (
    <aside className="side">
      <div className="brand brand-btn" role="button" tabIndex={0}
        title="myWiki — 처음 화면으로 새로고침"
        onClick={onLogoClick}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onLogoClick?.(); } }}
      >
        <div className="eb">반도체 동향 시스템</div>
        <div className="nm"><LogoMark className="nm-ic" />myWiki</div>
        <div className="rule"></div>
      </div>

      {NAV_ITEMS.map((section) => (
        <nav key={section.group}>
          <div className="lb">{section.group}</div>
          {section.items.map((item) => (
            <a
              key={item.key}
              className={activeKey === item.key ? 'on' : ''}
              onClick={() => onNavigate(item.key)}
            >
              {item.label}
            </a>
          ))}
        </nav>
      ))}
    </aside>
  );
}

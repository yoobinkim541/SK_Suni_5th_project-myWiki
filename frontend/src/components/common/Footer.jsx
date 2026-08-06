// 공통 컴포넌트 — 사이트 하단 footer.
// globals.css에 이미 있던 .site-footer 클래스(팀원이 만들어 두고 아직 아무 데서도 안 쓰던
// 것)를 그대로 씁니다. PC(App.jsx의 <main> 아래)·모바일(하단 탭바 위) 양쪽에서 다 보이도록
// App.jsx가 항상 렌더링합니다.
//
// PWA 설치 버튼: 모바일에서는 원래 "더보기" 바텀시트(MobileNav.jsx MoreSheet) 안에만 있었는데,
// PC에는 설치 진입점이 아예 없었습니다. 여기 footer에 공용으로 하나 더 두면 PC·모바일 모두
// 반응형으로 노출됩니다(같은 App.jsx 상태 deferredPrompt/pwaStateLabel/handlePwaInstallClick을
// 그대로 재사용 — 로직 중복 없음).
//
// ⚠ "개인정보 처리방침"은 실제 서버 라우팅이 없는 SPA라 <a href="/privacy">로 걸면 새로고침 시
//   404가 난다. 그래서 App.jsx의 view 상태(navigateTo('privacy'))로 여닫는 내부 링크로 만들고,
//   PrivacyPage.jsx를 최소 내용으로 새로 만들었다.

export default function Footer({ onNavigate, onPwaInstallClick, pwaStateLabel = '홈 화면에 추가' }) {
  return (
    <footer className="site-footer">
      <span className="ft-brand">myWiki</span>
      <button type="button" className="ft-link" onClick={() => onNavigate?.('privacy')}>
        개인정보 처리방침
      </button>
      <button type="button" className="ft-pwa" onClick={onPwaInstallClick}>
        {pwaStateLabel}
      </button>
      <span className="ft-copy">© {new Date().getFullYear()} myWiki. All rights reserved.</span>
    </footer>
  );
}

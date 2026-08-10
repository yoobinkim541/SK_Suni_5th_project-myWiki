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
import { Link } from 'react-router-dom';

export default function Footer({ onPwaInstallClick, pwaStateLabel = '홈 화면에 추가' }) {
  return (
    <footer className="site-footer">
      <span className="ft-brand">myWiki</span>
      <Link to="/privacy" className="ft-link">
        개인정보 처리방침
      </Link>
      <button type="button" className="ft-pwa" onClick={onPwaInstallClick}>
        {pwaStateLabel}
      </button>
      <span className="ft-copy">© {new Date().getFullYear()} myWiki. All rights reserved.</span>
    </footer>
  );
}

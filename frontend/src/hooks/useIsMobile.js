// App.jsx가 PC(TopBar/SideNav)와 모바일(TopBar variant="mobile"/MobileNav) 중
// 뭘 렌더링할지 정할 때 쓰는 훅입니다.
//
// 브레이크포인트는 768px — 최신 시안 CSS에서 모바일 전용 내비게이션
// (.m-topbar / .m-tabbar / .m-drawer / .m-sheet)이 `@media (max-width:768px)`에서만
// 켜지도록 되어 있기 때문입니다.
//
// ⚠ 고친 부분: 예전엔 1020px이었는데, 그러면 769~1020px 구간에서
//   JS는 모바일이라 판단해 .m-topbar/.m-tabbar를 렌더링하지만 CSS는 아직
//   display:none이라 내비게이션이 통째로 사라지는 문제가 있었습니다.
//   1020px 미디어쿼리는 "PC 레이아웃 1열 축소"용이라 판별 기준이 아닙니다.

import { useState, useEffect } from 'react';

const BREAKPOINT = '(max-width: 768px)';

export default function useIsMobile() {
  const [isMobile, setIsMobile] = useState(() => {
    if (typeof window === 'undefined') return false;
    return window.matchMedia(BREAKPOINT).matches;
  });

  useEffect(() => {
    const mql = window.matchMedia(BREAKPOINT);
    const handleChange = (e) => setIsMobile(e.matches);

    // 최신 브라우저는 addEventListener, 구형은 addListener만 지원
    if (mql.addEventListener) {
      mql.addEventListener('change', handleChange);
      return () => mql.removeEventListener('change', handleChange);
    }
    mql.addListener(handleChange);
    return () => mql.removeListener(handleChange);
  }, []);

  return isMobile;
}

// 스크롤로 화면에 실제로 들어오는 시점에 한 번만 true가 되는 훅.
// TrendChart.jsx가 쓰던 "IntersectionObserver + getBoundingClientRect 보강" 패턴을
// 그대로 재사용한다 — IntersectionObserver만 믿으면 탭이 백그라운드거나 컴포지팅이
// 지연되는 환경에서 콜백이 아예 안 불릴 수 있어서(KnowledgeGraph.jsx 코멘트 참고),
// 스크롤/리사이즈 때마다 실제 위치를 직접 확인하는 경로를 같이 둔다.
//
// ⚠ 일반 useRef가 아니라 콜백 ref를 쓴다 — 이 훅을 호출하는 컴포넌트가 로딩 중엔
//   다른 JSX(스켈레톤)를 그리다가 나중에야 실제 대상 엘리먼트를 렌더링하는 경우
//   (예: DashboardPage의 로딩 분기), 마운트 시점에 한 번 도는 이펙트 안에서
//   `ref.current`를 읽으면 그때는 아직 null이라 관찰을 영영 못 시작한다.
//   콜백 ref는 엘리먼트가 실제로 DOM에 붙는 시점에 다시 호출되므로 이 문제가 없다.
//
// 사용법:
//   const [ref, revealed] = useRevealOnScroll();
//   <div ref={ref} className={`목록${revealed ? ' in' : ''}`}>...</div>
// 한 번 true가 되면 다시 false로 안 돌아간다(반복 재생 없음).

import { useCallback, useEffect, useState } from 'react';

export default function useRevealOnScroll(threshold = 0.2) {
  const [node, setNode] = useState(null);
  const [revealed, setRevealed] = useState(false);
  const ref = useCallback((el) => setNode(el), []);

  useEffect(() => {
    if (!node || revealed) return;
    let done = false;

    function reveal() {
      if (done) return;
      done = true;
      setRevealed(true);
      cleanup();
    }
    function checkPosition() {
      const rect = node.getBoundingClientRect();
      const vh = window.innerHeight || document.documentElement.clientHeight;
      if (rect.top < vh * 0.85 && rect.bottom > 0) reveal();
    }

    let observer = null;
    if (typeof IntersectionObserver !== 'undefined') {
      observer = new IntersectionObserver(
        ([entry]) => {
          if (entry.isIntersecting) reveal();
        },
        { threshold }
      );
      observer.observe(node);
    }
    window.addEventListener('scroll', checkPosition, { passive: true });
    window.addEventListener('resize', checkPosition);
    checkPosition(); // 이 시점에 이미 화면 안이면(뷰포트가 큰 화면 등) 바로 확인한다.

    function cleanup() {
      observer?.disconnect();
      window.removeEventListener('scroll', checkPosition);
      window.removeEventListener('resize', checkPosition);
    }
    return cleanup;
  }, [node, revealed, threshold]);

  return [ref, revealed];
}

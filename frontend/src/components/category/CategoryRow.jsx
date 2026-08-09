// 카테고리 현황 페이지 전용 — "분류별 상세" 섹션 (카드 목록 + 하단 범례)
// CategoryCard를 6개 나열하는 .cat-card-grid 래퍼입니다. (IssueList가 issue 배열을 감싸는 것과 같은 역할)
//
// 반응형 참고: `.cat-card-grid`는 PC에서 2열(grid-template-columns: repeat(2,1fr)),
// 1020px 이하에서는 CSS가 자동으로 1열(1fr)로 바꿔줍니다. 이 컴포넌트에서 화면 폭을 신경 쓸 필요는 없고,
// 그냥 배열을 그대로 map만 하면 됩니다.
//
// 카드 클릭 시 그 카테고리의 관련 뉴스를 모달로 보여줍니다(CategoryNewsModal).
// 뉴스는 카테고리 객체의 recentDocuments로 함께 오므로 여기서 따로 받아오지 않습니다 —
// 예전엔 마운트마다 카테고리별로 6번을 더 불러서 화면당 7요청이었습니다.

import { useState } from 'react';
import CategoryCard from './CategoryCard';
import CategoryNewsModal from './CategoryNewsModal';
import useRevealOnScroll from '../../hooks/useRevealOnScroll';

export default function CategoryRow({ categories }) {
  const [selected, setSelected] = useState(null);
  // 카드 진입 애니메이션 — 스크롤로 실제로 보이는 시점에 한 번만 재생.
  const [gridRef, gridIn] = useRevealOnScroll();

  return (
    <section className="sec">
      <div className="sh">
        <span className="t">분류별 상세</span>
        <span className="s">비중 순 · 대표 키워드와 대표 이슈</span>
      </div>

      <div className={`cat-card-grid${gridIn ? ' in' : ''}`} ref={gridRef}>
        {categories.map((c) => (
          <CategoryCard
            key={c.id}
            name={c.name}
            // 백엔드가 문서 단위로 센 건수. 모달에 뜨는 기사 수(최대 5건)와는 다릅니다 —
            // 모달은 최신 몇 건만 보여주고 카드는 그 분류 전체를 셉니다.
            count={c.count}
            topIssue={c.topIssue}
            level={c.level}
            onClick={() => setSelected(c)}
          />
        ))}
      </div>

      <div className="legend">
        <span>분류 기준</span>
        <span>제품·기술 · 경쟁사 · 고객·수요산업 · 공급망·생산 · 정책·규제 · 시장·경영</span>
        <span><b>가중치</b> 카테고리별 대표 키워드는 신뢰도·최신성 기준으로 자동 랭킹</span>
      </div>

      <CategoryNewsModal
        category={selected}
        newsItems={selected?.recentDocuments ?? []}
        onClose={() => setSelected(null)}
      />
    </section>
  );
}

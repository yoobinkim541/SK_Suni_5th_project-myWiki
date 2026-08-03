// 카테고리 현황 페이지 전용 — "분류별 상세" 섹션 (카드 목록 + 하단 범례)
// CategoryCard를 6개 나열하는 .cat-card-grid 래퍼입니다. (IssueList가 issue 배열을 감싸는 것과 같은 역할)
//
// 반응형 참고: `.cat-card-grid`는 PC에서 2열(grid-template-columns: repeat(2,1fr)),
// 1020px 이하에서는 CSS가 자동으로 1열(1fr)로 바꿔줍니다. 이 컴포넌트에서 화면 폭을 신경 쓸 필요는 없고,
// 그냥 배열을 그대로 map만 하면 됩니다.
//
// ⚠ 수정한 부분:
//  1) 카드 클릭 시 그 카테고리의 관련 뉴스를 모달로 보여줍니다(CategoryNewsModal).
//  2) data/mockDashboard.js를 직접 뒤져서 카테고리별 뉴스를 걸러내던 걸,
//     services/categoryApi.js의 fetchNewsByCategory()를 통해 받아오도록 바꿨습니다.
//     → 카드 6개 전부의 "N건" 배지를 마운트 시점에 한 번에 받아와서 state에 캐시해두고,
//       카드를 클릭했을 때 뜨는 모달도 같은 캐시를 재사용합니다(같은 소스라 숫자가 항상 일치).
//     실제 API가 붙으면 fetchNewsByCategory 안쪽만 바뀌고 이 컴포넌트는 그대로 씁니다.

import { useState, useEffect } from 'react';
import CategoryCard from './CategoryCard';
import CategoryNewsModal from './CategoryNewsModal';
import { fetchNewsByCategory } from '../../services/categoryApi';

export default function CategoryRow({ categories }) {
  const [selected, setSelected] = useState(null);
  const [newsByCategory, setNewsByCategory] = useState({});

  useEffect(() => {
    let alive = true;
    Promise.all(
      categories.map((c) => fetchNewsByCategory(c.name).then((list) => [c.name, list]))
    ).then((pairs) => {
      if (!alive) return;
      setNewsByCategory(Object.fromEntries(pairs));
    });
    return () => { alive = false; };
  }, [categories]);

  return (
    <section className="sec">
      <div className="sh">
        <span className="t">분류별 상세</span>
        <span className="s">비중 순 · 대표 키워드와 대표 이슈</span>
      </div>

      <div className="cat-card-grid">
        {categories.map((c) => {
          const news = newsByCategory[c.name] || [];
          return (
            <CategoryCard
              key={c.id}
              name={c.name}
              count={news.length}
              topIssue={c.topIssue}
              tags={c.tags}
              level={c.level}
              onClick={() => setSelected(c)}
            />
          );
        })}
      </div>

      <div className="legend">
        <span>분류 기준</span>
        <span>제품·기술 · 경쟁사 · 고객·수요산업 · 공급망·생산 · 정책·규제 · 시장·경영</span>
        <span><b>가중치</b> 카테고리별 대표 키워드는 신뢰도·최신성 기준으로 자동 랭킹</span>
      </div>

      <CategoryNewsModal
        category={selected}
        newsItems={selected ? (newsByCategory[selected.name] || []) : []}
        onClose={() => setSelected(null)}
      />
    </section>
  );
}

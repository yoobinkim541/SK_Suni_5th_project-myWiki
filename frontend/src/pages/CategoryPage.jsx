// 카테고리 현황 페이지 — PC/모바일 공용
//
// ⚠ 이번에 고친 것: data/mockCategory.js를 직접 보던 걸 services/categoryApi.js를
//   거치도록 바꿨습니다. fetchCategories()/fetchCategorySummary()가 지금은 목업을
//   Promise로 감싸서 돌려주지만, 나중에 그 함수 안을 실제 fetch로 바꾸기만 하면
//   이 파일은 그대로 씁니다.
//   카드 클릭 시 뜨는 "관련 뉴스"(건수 포함)는 CategoryRow.jsx 안에서
//   fetchNewsByCategory()로 따로 받아옵니다 — 카테고리 목록/요약과는 갱신 주기가
//   다를 수 있어서 이 페이지에서 미리 안 가져오고 그쪽에서 필요할 때 가져옵니다.

import { useState, useEffect } from 'react';
import CategoryDetail from '../components/category/CategoryDetail';
import { fetchCategories, fetchCategorySummary } from '../services/categoryApi';

export default function CategoryPage() {
  const [loading, setLoading] = useState(true);
  const [categories, setCategories] = useState([]);
  const [summary, setSummary] = useState(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.all([fetchCategories(), fetchCategorySummary()]).then(([cats, sum]) => {
      if (!alive) return;
      setCategories(cats);
      setSummary(sum);
      setLoading(false);
    });
    return () => { alive = false; };
  }, []);

  if (loading) {
    return (
      <section className="view on" id="v-cat">
        <div className="ph"><h2>카테고리 현황</h2></div>
        <div className="loading">불러오는 중…</div>
      </section>
    );
  }

  return <CategoryDetail summary={summary} categories={categories} />;
}

// 카테고리 현황 페이지 — PC/모바일 공용
//
// 데이터는 services/categoryApi.js를 거쳐 받습니다. 카드·요약은 실백엔드
// (GET /categories/stats)에 연결돼 있고, 카드 클릭 시 뜨는 "관련 뉴스"는
// CategoryRow.jsx 안에서 fetchNewsByCategory()로 따로 받아옵니다(아직 목업).

import { useState, useEffect } from 'react';
import CategoryDetail from '../components/category/CategoryDetail';
import { fetchCategories, fetchCategorySummary } from '../services/categoryApi';

export default function CategoryPage() {
  const [loading, setLoading] = useState(true);
  const [categories, setCategories] = useState([]);
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    Promise.all([fetchCategories(), fetchCategorySummary()])
      .then(([cats, sum]) => {
        if (!alive) return;
        setCategories(cats);
        setSummary(sum);
        setLoading(false);
      })
      // .catch가 없으면 요청이 실패했을 때 setLoading(false)가 실행되지 않아
      // "불러오는 중…"에서 영구히 멈춘다. WikiPage.jsx와 같은 처리를 둔다.
      .catch((e) => {
        if (!alive) return;
        setError(e.message || '카테고리 현황을 불러오지 못했습니다.');
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

  if (error) {
    return (
      <section className="view on" id="v-cat">
        <div className="ph"><h2>카테고리 현황</h2></div>
        <p>{error}</p>
      </section>
    );
  }

  return <CategoryDetail summary={summary} categories={categories} />;
}

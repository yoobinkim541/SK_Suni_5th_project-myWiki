// 메인 대시보드 페이지 — PC/모바일 공용. 바깥 App.jsx에서 SideNav 또는 MobileNav로 감싸줍니다.
//
// ⚠ 이번에 고친 것: data/mockDashboard.js를 직접 보던 걸 services/dashboardApi.js를
//   거치도록 바꿨습니다. fetchDashboard()가 지금은 목업을 Promise로 감싸서 즉시 돌려주지만,
//   나중에 그 함수 안을 실제 fetch('/api/dashboard')로 바꾸기만 하면 이 파일은 그대로 씁니다.
//   KPI 숫자(수집 문서 312건 등)도 전엔 이 파일에 그냥 박혀 있었는데, data/mockDashboard.js의
//   MOCK_KPI_SUMMARY로 빼서 같이 fetchDashboard()로 받아오게 했습니다.
//
// (3번 수정사항 반영은 그대로 유지)
//  1) 섹션 순서: "최근 현황"(KPI) → "산업 동향 분석"(그래프)이 맨 위, 그다음 최신 뉴스 →
//     카테고리·키워드 → 최근 산업 이슈.
//  2) 검색창(.search)은 완전히 제거. 대신 "관심사"(App.jsx)와 "오늘의 키워드" 클릭으로
//     뉴스를 좁히는 두 갈래 탐색만 남겨뒀습니다.

import { useState, useEffect } from 'react';
import KpiCard from '../components/dashboard/KpiCard';
import TrendChart from '../components/dashboard/TrendChart';
import IssueList from '../components/dashboard/IssueList';
import CategoryPreview from '../components/dashboard/CategoryPreview';
import { fetchDashboard } from '../services/dashboardApi';
import { filterNewsByInterests } from '../data/mockOnboarding';

// 파이프라인 단계 — 시안 ".pipe" 그대로
const PIPELINE_STEPS = [
  { name: '수집', time: '07:12' },
  { name: '정제·검증', time: '07:28' },
  { name: '요약', time: '07:39' },
  { name: '보고서 생성', time: '07:42 · 1건' },
];

// 원문/출처 아이콘 — "공시 원문"은 아래 화살표, 그 외 "뉴스"는 사선 화살표
function ExtLinkIcon({ isDoc }) {
  return isDoc ? (
    <svg viewBox="0 0 24 24" fill="none">
      <path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ) : (
    <svg viewBox="0 0 24 24" fill="none">
      <path d="M7 17 17 7M9 7h8v8" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function kpiDesc(desc) {
  if (desc && typeof desc === 'object') {
    return <>{desc.text} <b>{desc.highlight}</b></>;
  }
  return desc;
}

export default function DashboardPage({ onNavigate, interests = [] }) {
  const [loading, setLoading] = useState(true);
  const [news, setNews] = useState([]);
  const [issues, setIssues] = useState([]);
  const [trend, setTrend] = useState([]);
  const [categoryPreview, setCategoryPreview] = useState([]);
  const [keywords, setKeywords] = useState([]);
  const [kpiSummary, setKpiSummary] = useState(null);

  const [showAllNews, setShowAllNews] = useState(false);
  // 키워드 칩 필터. null이면 관심사 필터만 적용됩니다.
  const [keywordFilter, setKeywordFilter] = useState(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    fetchDashboard().then((data) => {
      if (!alive) return;
      setNews(data.news);
      setIssues(data.issues);
      setTrend(data.trend);
      setCategoryPreview(data.categoryPreview);
      setKeywords(data.keywords);
      setKpiSummary(data.kpiSummary);
      setLoading(false);
    });
    return () => { alive = false; };
  }, []);

  // 필터 우선순위: 키워드 칩을 누르면 그 키워드만, 아니면 첫 화면에서 고른 관심사 기준.
  const activeFilters = keywordFilter ? [keywordFilter] : interests;
  const filteredNews = filterNewsByInterests(news, activeFilters);
  const isFiltered = activeFilters.length > 0;
  const visibleNews = showAllNews || keywordFilter ? filteredNews : filteredNews.slice(0, 4);

  function handleKeywordClick(word) {
    setKeywordFilter((prev) => (prev === word ? null : word));
    document.querySelector('.news-feed')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  if (loading) {
    return (
      <section className="view on" id="v-dash">
        <div className="ph"><h2>메인 대시보드</h2></div>
        <div className="loading">불러오는 중…</div>
      </section>
    );
  }

  return (
    <section className="view on" id="v-dash">
      <div className="ph">
        <h2>메인 대시보드</h2>
        <span className="dt">2026.07.24 금요일</span>
        <span className="st">반도체 도메인 · 일 배치 <b>정상</b></span>
      </div>

      <div className="pipe">
        {PIPELINE_STEPS.map((step, i) => (
          <span key={step.name} style={{ display: 'contents' }}>
            <span className="st"><span className="n">{step.name}</span><span className="tm">{step.time}</span></span>
            {i < PIPELINE_STEPS.length - 1 && <span className="ar">→</span>}
          </span>
        ))}
        <span className="nx">다음 실행 08:00 · 무인 자동</span>
      </div>

      {/* 1) 최근 현황 — 화면에 들어오자마자 보이는 첫 섹션 */}
      <section className="sec">
        <div className="sh"><span className="t">최근 현황</span><span className="r">7일 누적 기준</span></div>
        <div className="kpi">
          <KpiCard label="수집 문서" value={kpiSummary.collectedDocs.value} desc={kpiDesc(kpiSummary.collectedDocs.desc)} />
          <KpiCard label="생성 보고서" value={kpiSummary.generatedReports.value} desc={kpiSummary.generatedReports.desc} />
          <KpiCard label="위키 문서" value={kpiSummary.wikiDocs.value} desc={kpiDesc(kpiSummary.wikiDocs.desc)} />
          {/* 평균 신뢰도는 색상 없이 기본 텍스트색으로 표시 (KpiCard 기본값) */}
          <KpiCard label="평균 신뢰도" value={kpiSummary.avgConfidence.value} isText desc={kpiSummary.avgConfidence.desc} />
        </div>
      </section>

      {/* 2) 산업 동향 분석 그래프 */}
      <section className="sec">
        <div className="sh">
          <span className="t">산업 동향 분석</span>
          <span className="s">최근 7일 수집·채택 추이</span>
          <span className="r">일 배치 기준</span>
        </div>
        <TrendChart data={trend} />
      </section>

      {/* 3) 최신 뉴스 */}
      <section className="sec news-feed">
        <div className="sh">
          <span className="t">최신 뉴스</span>
          <span className="s">최신순 · {filteredNews.length}건</span>
        </div>

        {isFiltered && (
          <div className="feed-filter">
            <span className="lb">{keywordFilter ? '키워드' : '내 관심사'}</span>
            {activeFilters.map((f) => (
              <span className="chip" key={f}>{f}</span>
            ))}
            <button type="button" className="clr" onClick={() => setKeywordFilter(null)}>
              {keywordFilter ? '키워드 해제' : `전체 ${news.length}건 보기`}
            </button>
          </div>
        )}

        <div className="news-grid">
          {visibleNews.map((n) => (
            <article className="news-card" key={n.title}>
              <div className="card-top">
                <span className="badge">{n.category}</span>
                <a className="ext-link" href={n.sourceUrl} target="_blank" rel="noopener"
                  title={n.isDoc ? `${n.sourceLabel} 원문으로 이동` : '원문 기사로 이동'}>
                  <ExtLinkIcon isDoc={n.isDoc} />
                  {n.isDoc ? '공시 원문' : '뉴스'}
                </a>
              </div>
              <h4>{n.title}</h4>
              <div className="quote">{n.quote}</div>
              <div className="tags">
                {n.tags.map((t) => <span className="tag" key={t}>{t}</span>)}
              </div>
              <div className="card-foot">
                <a className="src-btn" href={n.sourceUrl} target="_blank" rel="noopener" title={`${n.sourceLabel} 원문 보기`}>
                  {n.sourceLabel}
                </a>
                <span className="time"> · {n.time}</span>
              </div>
            </article>
          ))}
          {visibleNews.length === 0 && (
            <div className="feed-empty">해당 조건으로 수집된 뉴스가 없습니다.</div>
          )}
        </div>

        {!keywordFilter && filteredNews.length > 4 && (
          <button className="news-more" onClick={() => setShowAllNews((v) => !v)}>
            {showAllNews ? '접기 ↑' : '더보기 ↓'}
          </button>
        )}
      </section>

      {/* 4) 카테고리 현황 미리보기 + 오늘의 키워드 */}
      <section className="sec">
        <div className="split">
          <CategoryPreview
            categories={categoryPreview}
            onViewAll={() => onNavigate?.('cat')}
          />
          <div>
            <div className="sh">
              <span className="t">오늘의 키워드</span>
              <span className="s">누르면 뉴스가 좁혀집니다</span>
              <span className="r">언급 순</span>
            </div>
            <div className="kwlist">
              {keywords.map((kw) => (
                <div
                  className={`kwrow${keywordFilter === kw.word ? ' on' : ''}`}
                  key={kw.word}
                  onClick={() => handleKeywordClick(kw.word)}
                >
                  <span className="h">#</span>{kw.word}<span className="ct">{kw.count}회</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* 5) 최근 산업 이슈 */}
      <section className="sec">
        <div className="sh">
          <span className="t">최근 산업 이슈</span>
          <span className="c">{issues.length}건</span>
          <span className="s">신뢰도 → 제목 → 출처 순</span>
          <span className="r"><a onClick={() => onNavigate?.('report')}>일일 리포트 →</a></span>
        </div>
        <IssueList items={issues} onSelectWiki={(wikiId) => onNavigate?.('wiki', wikiId)} />
      </section>
    </section>
  );
}

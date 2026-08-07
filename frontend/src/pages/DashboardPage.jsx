// 메인 대시보드 페이지 — PC/모바일 공용. 바깥 App.jsx에서 SideNav 또는 MobileNav로 감싸줍니다.
//
// ⚠ 이번에 고친 것: data/mockDashboard.js를 직접 보던 걸 services/dashboardApi.js를
//   거치도록 바꿨습니다. fetchDashboard()가 지금은 목업을 Promise로 감싸서 즉시 돌려주지만,
//   나중에 그 함수 안을 실제 fetch('/api/dashboard')로 바꾸기만 하면 이 파일은 그대로 씁니다.
//   KPI 숫자(수집 문서 312건 등)도 전엔 이 파일에 그냥 박혀 있었는데, data/mockDashboard.js의
//   MOCK_KPI_SUMMARY로 빼서 같이 fetchDashboard()로 받아오게 했습니다.
//
// 섹션 순서: 지식 축적화(KnowledgeGraph, 장식용 — 진입 직후 바로 보이도록 최상단) → 최근 현황(KPI)
//   → 산업 동향 분석(그래프) → 관심 키워드(InterestsBar, 추가·삭제) → 최신 뉴스 → 오늘의 키워드
//   → 최근 산업 이슈.
// 검색창(.search)은 없고, "관심사"(App.jsx, 선호조사에서 고른 키워드)와 "오늘의 키워드" 클릭
// 두 갈래로만 뉴스를 좁힙니다.
//
// "카테고리 현황" 섹션은 삭제했습니다(CategoryPreview.jsx는 더 이상 이 페이지에서 안 씀 —
// 카테고리 현황 페이지 자체는 그대로 있습니다). 대신 "최신 뉴스"와 "최근 산업 이슈"를
// 명확히 구분합니다 — 최신 뉴스는 관심 키워드에 따라 달라지는 언론사 기사만, 최근 산업
// 이슈는 관심사와 무관하게 모두에게 같은 항목을 공시·IR 등 공식 문서 출처로 보여줍니다.

import { useState, useEffect } from 'react';
import KpiCard from '../components/dashboard/KpiCard';
import TrendChart from '../components/dashboard/TrendChart';
import IssueList from '../components/dashboard/IssueList';
import KnowledgeGraph from '../components/dashboard/KnowledgeGraph';
import InterestsBar from '../components/dashboard/InterestsBar';
import { fetchDashboard } from '../services/dashboardApi';
import { filterNewsByInterests } from '../data/mockOnboarding';
import { formatKoreanDate } from '../lib/formatDate';

// [목업] 파이프라인 단계 — 시안 ".pipe" 그대로. 시각이 고정값이라 실제 배치 시각이
// 아니다. 배치 상태를 실데이터로 바꾸려면 스케줄러가 매 회차 완주해야 하는데
// 아직 그렇지 않다(수집·정제·분석이 한 실행의 시간 예산을 나눠 쓴다).
const PIPELINE_STEPS = [
  { name: '수집', time: '07:12' },
  { name: '정제·검증', time: '07:28' },
  { name: '요약', time: '07:39' },
  { name: '보고서 생성', time: '07:42 · 1건' },
];

function kpiDesc(desc) {
  if (desc && typeof desc === 'object') {
    return <>{desc.text} <b>{desc.highlight}</b></>;
  }
  return desc;
}

export default function DashboardPage({ onNavigate, interests = [], onUpdateInterests }) {
  const [loading, setLoading] = useState(true);
  const [news, setNews] = useState([]);
  const [issues, setIssues] = useState([]);
  const [trend, setTrend] = useState([]);
  const [keywords, setKeywords] = useState([]);
  const [kpiSummary, setKpiSummary] = useState(null);

  const [showAllNews, setShowAllNews] = useState(false);
  // 키워드 칩 필터. null이면 관심사 필터만 적용됩니다.
  const [keywordFilter, setKeywordFilter] = useState(null);
  // "전체 N건 보기"를 눌러 관심사 필터를 일시적으로 무시하는 상태. 관심사 자체가
  // 바뀌면(추가·삭제) 그 변경을 다시 반영해야 하니 아래 useEffect에서 초기화한다.
  const [ignoreInterests, setIgnoreInterests] = useState(false);

  useEffect(() => {
    setIgnoreInterests(false);
  }, [interests]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    fetchDashboard()
      .then((data) => {
        if (!alive) return;
        setNews(data.news);
        setIssues(data.issues);
        setTrend(data.trend);
        setKeywords(data.keywords);
        setKpiSummary(data.kpiSummary);
        setLoading(false);
      })
      .catch((err) => {
        // ⚠ .catch가 없으면 fetchDashboard()가 실패했을 때 setLoading(false)가 영영
        //   안 불려서 화면이 "메인 대시보드" 헤더 + 로딩 스켈레톤에 멈춰 있는 것처럼 보인다
        //   (예: 게스트 모드에서 인증이 필요한 API를 불렀다가 401을 받는 경우).
        //   콘솔에 원인은 남기고, 최소한 빈 상태로라도 화면은 뜨게 한다.
        if (!alive) return;
        console.error('[DashboardPage] fetchDashboard 실패:', err);
        setNews([]);
        setIssues([]);
        setTrend([]);
        setKeywords([]);
        setKpiSummary({
          collectedDocs: { value: '—', desc: '' },
          generatedReports: { value: '—', desc: '' },
          wikiDocs: { value: '—', desc: '' },
          avgConfidence: { value: '—', desc: '' },
        });
        setLoading(false);
      });
    return () => { alive = false; };
  }, []);

  // "최신 뉴스"는 언론사 기사만 보여준다 — 공시·IR 같은 원문 문서는 아래 "최근 산업 이슈"
  // 쪽 소스이므로 여기서 제외한다(안 그러면 관심사를 아무것도 안 고른 사용자에게 두 섹션이
  // 같은 항목을 중복으로 보여주게 된다).
  const articleNews = news.filter((n) => !n.isDoc);
  // 필터 우선순위: 키워드 칩을 누르면 그 키워드만, 아니면 첫 화면(선호조사)에서 고른 관심 키워드 기준.
  // 관심 키워드를 하나도 안 골랐으면 필터 없이 전체 기사를 최신순으로 보여준다.
  const activeFilters = keywordFilter ? [keywordFilter] : (ignoreInterests ? [] : interests);
  const filteredNews = filterNewsByInterests(articleNews, activeFilters);
  const isFiltered = activeFilters.length > 0;
  const visibleNews = showAllNews || keywordFilter ? filteredNews : filteredNews.slice(0, 4);

  function handleKeywordClick(word) {
    setKeywordFilter((prev) => (prev === word ? null : word));
    document.querySelector('.news-feed')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // "불러오는 중…" 텍스트 대신, 실제 대시보드 레이아웃(지식 축적화 그래프 → KPI 4개 →
  // 산업 동향 분석 그래프) 자리를 흉내 낸 실루엣 블록이 위에서부터 순서대로 나타나는
  // 스켈레톤을 보여준다(globals.css .dash-skeleton).
  if (loading) {
    return (
      <section className="view on" id="v-dash">
        <div className="ph"><h2>메인 대시보드</h2></div>
        <div className="dash-skeleton">
          <div className="sk-block sk-hero" />
          <div className="sk-row">
            <div className="sk-block" />
            <div className="sk-block" />
            <div className="sk-block" />
            <div className="sk-block" />
          </div>
          <div className="sk-block sk-tall" />
        </div>
      </section>
    );
  }

  return (
    <section className="view on" id="v-dash">
      <div className="ph ph-tight">
        <h2>메인 대시보드</h2>
        <span className="dt">{formatKoreanDate()}</span>
        {/* [목업] '일 배치 정상'은 실제와 반대다 — 배치가 매 회차 시간 예산에 걸려
            잘리고 있다. 카테고리 현황 헤더(CategoryDetail.jsx)와 같은 상태이고,
            배치 상태 실데이터화는 그게 풀린 뒤 두 화면을 함께 다룬다. */}
        <span className="st">반도체 도메인 · 일 배치 <b>정상</b></span>
      </div>

      <div className="pipe pipe-tight">
        {PIPELINE_STEPS.map((step, i) => (
          <span key={step.name} style={{ display: 'contents' }}>
            <span className="st"><span className="n">{step.name}</span><span className="tm">{step.time}</span></span>
            {i < PIPELINE_STEPS.length - 1 && <span className="ar">→</span>}
          </span>
        ))}
        <span className="nx">다음 실행 08:00 · 무인 자동</span>
      </div>

      {/* 1) 지식 축적화 네트워크 — 파이프라인 바로 아래, 최근 현황보다도 먼저 바로 보이도록
          최상단에 배치(장식용 그래프). 헤더·파이프라인 바의 위아래 여백을 좁혀서(ph-tight/
          pipe-tight) 화면에 들어오자마자 이 그래프가 더 잘 보이게 했다. */}
      <section className="sec">
        <div className="sh">
          <span className="t">지식 축적화</span>
          <span className="s">myWiki가 자동으로 분류·연결하는 카테고리와 키워드</span>
        </div>
        <KnowledgeGraph />
      </section>

      {/* 2) 최근 현황 — 카테고리 현황 페이지의 "오늘의 분류 요약"과 같은 .kpi/KpiCard를 쓰지만,
          여기서는 .kpi-compact로 카드 크기만 살짝 줄인다(다른 페이지의 .kpi는 그대로 둠). */}
      <section className="sec">
        <div className="sh"><span className="t">최근 현황</span><span className="r">7일 누적 기준</span></div>
        <div className="kpi kpi-compact">
          <KpiCard label="수집 문서" value={kpiSummary.collectedDocs.value} desc={kpiDesc(kpiSummary.collectedDocs.desc)} />
          <KpiCard label="생성 보고서" value={kpiSummary.generatedReports.value} desc={kpiSummary.generatedReports.desc} />
          <KpiCard label="위키 문서" value={kpiSummary.wikiDocs.value} desc={kpiDesc(kpiSummary.wikiDocs.desc)} />
          {/* 평균 신뢰도는 색상 없이 기본 텍스트색으로 표시 (KpiCard 기본값) */}
          <KpiCard label="평균 신뢰도" value={kpiSummary.avgConfidence.value} isText desc={kpiSummary.avgConfidence.desc} />
        </div>
      </section>

      {/* 3) 산업 동향 분석 그래프 */}
      <section className="sec">
        <div className="sh">
          <span className="t">산업 동향 분석</span>
          <span className="s">최근 7일 수집·채택 추이</span>
          <span className="r">일 배치 기준</span>
        </div>
        <TrendChart data={trend} />
      </section>

      {/* 3.5) 관심 키워드 — 온보딩과 별개로 대시보드에서 바로 추가·삭제. "산업 동향 분석"과
          "최신 뉴스" 사이에 배치(고른 키워드가 바로 아래 최신 뉴스 필터에 반영되니 자연스럽게 이어짐) */}
      <InterestsBar interests={interests} onUpdateInterests={onUpdateInterests} />

      {/* 4) 최신 뉴스 */}
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
            <button
              type="button"
              className="clr"
              onClick={() => {
                if (keywordFilter) setKeywordFilter(null);
                else setIgnoreInterests(true);
              }}
            >
              {keywordFilter ? '키워드 해제' : `전체 ${articleNews.length}건 보기`}
            </button>
          </div>
        )}

        <div className="news-grid">
          {visibleNews.map((n) => (
            <article className="news-card" key={n.title}>
              <div className="card-top">
                <span className="badge">{n.category}</span>
                <a className="ext-link" href={n.sourceUrl} target="_blank" rel="noopener" title="원문 기사로 이동">
                  뉴스 보기 →
                </a>
              </div>
              <h4>{n.title}</h4>
              {/* 인용문은 분석(importance) 산출물이라 최신 기사일수록 비어 있습니다
                  (2026-08-07 실측 커버리지 8%). 없는 걸 본문 조각으로 채우면 근거 없는
                  인용이 되므로, 빈 블록을 그리는 대신 접습니다. */}
              {n.quote && <div className="quote">{n.quote}</div>}
              {n.tags?.length > 0 && (
                <div className="tags">
                  <span className="tag">{n.tags.join(' · ')}</span>
                </div>
              )}
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

      {/* 5) 오늘의 키워드 — 세로 목록 대신 가로 칩으로 배치("카테고리 현황" 섹션은 삭제) */}
      <section className="sec">
        <div className="sh">
          <span className="t">오늘의 키워드</span>
          <span className="s">누르면 뉴스가 좁혀집니다</span>
          <span className="r">언급 순</span>
        </div>
        <div className="kwchips">
          {keywords.map((kw) => (
            <button
              type="button"
              className={`kwchip${keywordFilter === kw.word ? ' on' : ''}`}
              key={kw.word}
              onClick={() => handleKeywordClick(kw.word)}
            >
              <span className="h">#</span>{kw.word}<span className="ct">{kw.count}회</span>
            </button>
          ))}
        </div>
      </section>

      {/* 6) 최근 산업 이슈 — "최신 뉴스"와 구분되게 톤 다른 패널에 담고, 관심사와 무관하게
          모든 사용자에게 동일한 항목을 보여준다(출처도 공시·IR 등 공식 문서 위주). */}
      <section className="sec sec-issues">
        <div className="sh">
          <span className="t">최근 산업 이슈</span>
          <span className="badge-official">공식 근거 기반</span>
          <span className="c">{issues.length}건</span>
          <span className="s">신뢰도 → 제목 → 출처 순</span>
          <span className="r"><a onClick={() => onNavigate?.('report')}>일일 리포트 →</a></span>
        </div>
        <IssueList items={issues} onSelectWiki={(wikiId) => onNavigate?.('wiki', wikiId)} />
      </section>
    </section>
  );
}

// 대시보드 API 호출부.
// news/issues/trend/categoryPreview/keywords는 아직 백엔드가 없어 data/mockDashboard.js를
// 그대로 돌려줍니다. kpiSummary(수집 문서·생성 보고서·위키 문서·평균 신뢰도)만
// api/dashboard.js를 거쳐 실제 백엔드(GET /dashboard/summary)에 연결합니다.
// 화면 컴포넌트는 이 파일만 보게 해두면, 나머지도 나중에 fetch로 바꿀 때 컴포넌트는
// 손댈 필요가 없습니다.

import { fetchDashboardSummary } from '../api/dashboard';
import {
  MOCK_NEWS,
  MOCK_ISSUES,
  MOCK_TREND,
  MOCK_CATEGORY_PREVIEW,
  MOCK_KEYWORDS,
  MOCK_KPI_SUMMARY,
} from '../data/mockDashboard';

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false';

// TODO: 실제 연동 시 fetch('/api/dashboard/...') 로 교체
const delay = (value) => Promise.resolve(value);

export function fetchNews() {
  return delay(MOCK_NEWS);
}

export function fetchIssues() {
  return delay(MOCK_ISSUES);
}

export function fetchTrend() {
  return delay(MOCK_TREND);
}

export function fetchCategoryPreview() {
  return delay(MOCK_CATEGORY_PREVIEW);
}

export function fetchKeywords() {
  return delay(MOCK_KEYWORDS);
}

// 백엔드 DashboardSummaryOut -> KpiCard 4개가 기대하는 kpiSummary shape.
function toKpiSummary(summary) {
  return {
    collectedDocs: {
      value: String(summary.collected_docs),
      desc: { text: '오늘', highlight: `+${summary.collected_docs_today}` },
    },
    generatedReports: {
      value: String(summary.generated_reports),
      desc: '자동 생성',
    },
    wikiDocs: {
      value: String(summary.wiki_docs),
      desc: { text: '신규', highlight: `+${summary.wiki_docs_new_today}` },
    },
    avgConfidence: {
      value: summary.avg_reliability_label,
      desc: '체크리스트 기준',
    },
  };
}

export function fetchKpiSummary() {
  if (USE_MOCK) return delay(MOCK_KPI_SUMMARY);
  return fetchDashboardSummary().then(toKpiSummary);
}

// 대시보드 화면 하나가 여러 API를 한 번에 부르지 않게, 한 번에 다 가져오는 편의 함수도 둡니다.
export async function fetchDashboard() {
  const kpiSummary = await fetchKpiSummary();
  return {
    news: MOCK_NEWS,
    issues: MOCK_ISSUES,
    trend: MOCK_TREND,
    categoryPreview: MOCK_CATEGORY_PREVIEW,
    keywords: MOCK_KEYWORDS,
    kpiSummary,
  };
}

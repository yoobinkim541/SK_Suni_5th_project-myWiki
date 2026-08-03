// 대시보드 API 호출부.
// 백엔드가 붙기 전까지는 data/mockDashboard.js를 그대로 돌려줍니다.
// 화면 컴포넌트는 이 파일만 보게 해두면, 나중에 fetch로 바꿔도 컴포넌트는 손댈 필요가 없습니다.

import {
  MOCK_NEWS,
  MOCK_ISSUES,
  MOCK_TREND,
  MOCK_CATEGORY_PREVIEW,
  MOCK_KEYWORDS,
  MOCK_KPI_SUMMARY,
} from '../data/mockDashboard';

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

export function fetchKpiSummary() {
  return delay(MOCK_KPI_SUMMARY);
}

// 대시보드 화면 하나가 여러 API를 한 번에 부르지 않게, 한 번에 다 가져오는 편의 함수도 둡니다.
export function fetchDashboard() {
  return delay({
    news: MOCK_NEWS,
    issues: MOCK_ISSUES,
    trend: MOCK_TREND,
    categoryPreview: MOCK_CATEGORY_PREVIEW,
    keywords: MOCK_KEYWORDS,
    kpiSummary: MOCK_KPI_SUMMARY,
  });
}

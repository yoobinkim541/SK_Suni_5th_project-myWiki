// 대시보드 API 호출부.
//
// 화면 컴포넌트는 이 파일만 봅니다. 나머지 항목을 실제 fetch로 바꿀 때도
// pages/DashboardPage.jsx는 손댈 필요가 없습니다.
//
// 항목별 연동 현황 (2026-08-05 확인):
//   [LIVE] kpiSummary   GET /dashboard/summary -> src/api/dashboard_router.py
//                       수집 문서·생성 보고서·위키 문서·평균 신뢰도 4종
//   [목업] news         백엔드 없음
//   [목업] issues       백엔드 없음
//   [목업] trend        백엔드 없음
//   [목업] categoryPreview  백엔드 없음. 분류 체계 미합의 상태라 착수 전 팀 결정 필요
//   [목업] keywords     백엔드 없음
//
// 목업 항목은 백엔드가 생기기 전까지 지우지 않습니다 — 지우면 화면이 빕니다.
//
// ⚠ VITE_USE_MOCK은 전역 스위치입니다. 'false'로 두면 이 파일뿐 아니라
//   agentApi·wikiApi·settingsApi도 함께 실백엔드로 붙습니다.

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

// 목업을 Promise로 감싸 반환합니다. 화면 쪽 코드가 실연동 후에도 그대로 동작하게
// 하려는 장치라, 실제 백엔드가 생기면 이 함수가 아니라 각 fetch* 함수 안을 바꿉니다.
const delay = (value) => Promise.resolve(value);

// [목업] 백엔드 없음
export function fetchNews() {
  return delay(MOCK_NEWS);
}

// [목업] 백엔드 없음
export function fetchIssues() {
  return delay(MOCK_ISSUES);
}

// [목업] 백엔드 없음
export function fetchTrend() {
  return delay(MOCK_TREND);
}

// [목업] 백엔드 없음. 분류 체계가 합의되기 전에는 실연동하지 않습니다 (api/category.js 참고)
export function fetchCategoryPreview() {
  return delay(MOCK_CATEGORY_PREVIEW);
}

// [목업] 백엔드 없음
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

// [LIVE] VITE_USE_MOCK !== 'false' 일 때만 목업입니다.
export function fetchKpiSummary() {
  if (USE_MOCK) return delay(MOCK_KPI_SUMMARY);
  return fetchDashboardSummary().then(toKpiSummary);
}

// 대시보드 화면 하나가 여러 API를 한 번에 부르지 않게, 한 번에 다 가져오는 편의 함수도 둡니다.
// kpiSummary만 실데이터이고 나머지는 목업인 혼합 상태입니다 — 항목별로 하나씩 교체합니다.
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

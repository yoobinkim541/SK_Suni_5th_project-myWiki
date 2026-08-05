// [LIVE] src/api/dashboard_router.py 실제 연결 — 2026-08-05 구현 완료.
//
// 이 파일에 있던 이전 제안 계약(GET /dashboard/kpis 등, KpiCard 3개짜리 옛 레이아웃
// 기준)은 지금 DashboardPage.jsx의 실제 KPI 카드 4개(수집 문서/생성 보고서/위키 문서/
// 평균 신뢰도) 구성과 안 맞고 백엔드도 없는 상태였다. 아래 fetchDashboardSummary()가
// 그 자리를 대신한다 — trend(TrendChart)/issues(IssueList)/news/categoryPreview/keywords는
// 이번 범위 밖이라 여전히 목업이다(services/dashboardApi.js 참고).
import { apiFetch } from './client';

/**
 * DashboardPage KPI 카드(수집 문서·생성 보고서·위키 문서·평균 신뢰도)용 집계치.
 * @returns {Promise<{
 *   collected_docs, collected_docs_today, generated_reports,
 *   wiki_docs, wiki_docs_new_today, avg_reliability_label,
 * }>}
 */
export function fetchDashboardSummary() {
  return apiFetch('/dashboard/summary');
}

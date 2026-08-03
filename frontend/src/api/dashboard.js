// [대기 · 백엔드 없음] 담당: 김보연(데이터 파이프라인) + 이환희(분석·보고서) 교집합으로 추정.
// pipeline_jobs(수집 건수) / reports·report_sections(이슈·신뢰도) 집계가 필요해서
// 두 파트 중 어느 쪽이 낼지 팀에서 먼저 정해야 함. 아래는 DashboardPage.jsx 목업 기준 제안 계약.
import { apiFetch } from './client';

/**
 * KpiCard 3개(오늘 수집/주의 이슈/신뢰 확보) 값.
 * 제안: GET /dashboard/kpis
 * @returns {Promise<{today_collected: number, delta: string, warning_issues: number, trust_rate: string}>}
 */
export function fetchDashboardKpis() {
  return apiFetch('/dashboard/kpis');
}

/**
 * TrendChart용 시계열. TrendChart.jsx 주석에 [{date, value}, ...] 형태로 명시돼 있음 — 그대로 맞춤.
 * 제안: GET /dashboard/trend?days=14
 * @returns {Promise<{date: string, value: number}[]>}
 */
export function fetchDashboardTrend(days = 14) {
  return apiFetch(`/dashboard/trend?days=${days}`);
}

/**
 * IssueList용. IssueList.jsx가 기대하는 필드는 {id, title, confidence} — report의
 * level/levelLabel(문자열)과 다르게 confidence는 숫자(%)로 와야 진행바 width 계산이 된다.
 * 제안: GET /dashboard/issues?limit=5
 * @returns {Promise<{id, title, confidence: number}[]>}
 */
export function fetchDashboardIssues(limit = 5) {
  return apiFetch(`/dashboard/issues?limit=${limit}`);
}

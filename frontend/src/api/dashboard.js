// [LIVE] src/api/dashboard_router.py 실제 연결 — 2026-08-05 구현 완료.
//
// 이 파일에 있던 이전 제안 계약(GET /dashboard/kpis 등, KpiCard 3개짜리 옛 레이아웃
// 기준)은 지금 DashboardPage.jsx의 실제 KPI 카드 4개(수집 문서/생성 보고서/위키 문서/
// 평균 신뢰도) 구성과 안 맞고 백엔드도 없는 상태였다. 아래 fetchDashboardSummary()가
// 그 자리를 대신한다 — issues(IssueList)/news/keywords는
// 아직 백엔드가 없어 목업이다(services/dashboardApi.js 참고).
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

/**
 * TrendChart용 일별 수집·채택 추이 (최근 7일, KST 기준).
 *
 * days는 오래된 날부터 오늘 순이고, 수집이 없던 날도 0으로 채워 옵니다.
 * date는 'YYYY-MM-DD' 문자열입니다 — 차트 축 라벨 변환은 services/dashboardApi.js가 합니다.
 *
 * ⚠ 오늘 버킷의 adopted는 거의 0으로 옵니다. 분석 배치가 수집보다 하루쯤
 *   뒤처지기 때문이고(스케줄러 timeout), 집계 버그가 아닙니다.
 *
 * ⚠ news + adopted는 서로 다른 축입니다. news/disclosure는 collected의 내역이고,
 *   그 밖의 source_type이 생기면 news + disclosure < collected 가 될 수 있습니다.
 *
 * @returns {Promise<{
 *   days: {date: string, collected: number, adopted: number,
 *          news: number, disclosure: number}[]
 * }>}
 */
export function fetchDashboardTrend() {
  return apiFetch('/dashboard/trend');
}

/**
 * '오늘의 키워드' 칩용 — 제목에 등장한 낱말 상위 8개 (최근 7일).
 *
 * count는 "그 낱말이 등장한 문서 수"입니다. 수집 질의어 건수가 아닙니다 —
 * 화면 문구가 '언급 순'이라 그쪽을 쓰면 뜻이 어긋납니다.
 *
 * @returns {Promise<{keywords: {word: string, count: number}[]}>}
 */
export function fetchDashboardKeywords() {
  return apiFetch('/dashboard/keywords');
}

/**
 * '최신 뉴스' 카드용 — 문서 단위로 접은 뒤 발행일 내림차순.
 *
 * ⚠ quote는 빈 문자열로 올 수 있습니다(2026-08-07 실측 커버리지 8%).
 *   분석이 수집을 못 따라가 최신 문서일수록 인용문이 없고, 이 목록은 최신순이라
 *   하필 그 구간을 고릅니다. 채워 넣지 않고 화면에서 접습니다.
 *
 * ⚠ is_doc은 이 경로에서 사실상 항상 false입니다. 발행일 내림차순 상위 N이라
 *   건수가 적은 공시가 그 구간에 못 듭니다(실측 60건 중 0건).
 *
 * @returns {Promise<{items: {
 *   title, quote, category, tags: string[],
 *   source_label, source_url, published_at, is_doc,
 * }[]}>}
 */
export function fetchDashboardNews() {
  return apiFetch('/dashboard/news');
}

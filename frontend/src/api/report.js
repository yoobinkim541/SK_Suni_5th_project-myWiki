// [대기 · 백엔드 없음] 담당: 이환희(AI 분석·보고서, src/report/).
// reports / report_sections / report_citations 테이블은 이미 스키마에 있지만
// FastAPI에 조회 엔드포인트가 아직 없다 — 아래는 ReportPage.jsx 목업 구조에 맞춘 제안 계약.
// 백엔드가 이 경로로 나오면 ReportPage.jsx는 import만 바꾸면 된다(구조 변경 없음).
import { apiFetch } from './client';

/**
 * ReportSummary(kpis/categories/keywords) + 이슈 목록(MOCK_ISSUES) 전체를 한 번에.
 * 제안: GET /reports/daily?date=YYYY-MM-DD (생략 시 최신 reports.report_type='daily')
 * @returns {Promise<{
 *   date, status,
 *   kpis: {label, value, delta}[],
 *   categories: {name, count, strong?}[],
 *   keywords: string[],
 *   issues: {id, level, levelLabel, barWidth, category, title, desc, source, sourceDoc, wiki}[],
 * }>}
 * 확인 필요: level/levelLabel/barWidth(신뢰도 %)는 report_sections에 없음 —
 * confidence_score 같은 컬럼 추가가 필요한지 이환희 파트와 확인.
 * wiki 필드(이슈 → 연관 위키 제목)는 report_citations.document_version_id로는 못 구하고
 * report_sections ↔ wiki_pages 연결이 스키마에 없음 — 이 부분도 확인 필요.
 */
export function fetchDailyReport(date) {
  const q = date ? `?date=${date}` : '';
  return apiFetch(`/reports/daily${q}`);
}

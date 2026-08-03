// 일일 리포트 API 호출부. 지금은 data/mockReport.js를 그대로 돌려줍니다.

import {
  MOCK_REPORT_SUMMARY,
  MOCK_REPORT_ISSUES,
  MOCK_REPORT_ARCHIVE,
  MOCK_REPORT_TODAY,
  MOCK_REPORT_DETAILS,
} from '../data/mockReport';

const delay = (value) => Promise.resolve(value);

export function fetchReportSummary() {
  return delay(MOCK_REPORT_SUMMARY);
}

export function fetchReportIssues() {
  return delay(MOCK_REPORT_ISSUES);
}

export function fetchReportArchive() {
  return delay(MOCK_REPORT_ARCHIVE);
}

export function fetchTodayReport() {
  return delay(MOCK_REPORT_TODAY);
}

// 전체 리포트 상세 — 주요 이슈 카드 / 이슈 행 / 리포트 히스토리 카드 클릭 시 모달이 씁니다.
// 보관함(MOCK_REPORT_ARCHIVE)의 머리말 정보와 상세 본문(MOCK_REPORT_DETAILS)을 한 덩어리로 합쳐서 넘깁니다.
// 실제 API가 붙으면 GET /api/reports/{date} 한 번으로 같은 shape을 받아오면 됩니다.
export function fetchReportDetail(date) {
  const head = MOCK_REPORT_ARCHIVE.find((r) => r.date === date);
  const body = MOCK_REPORT_DETAILS[date];
  if (!head && !body) return delay(null);
  return delay({
    date,
    label: head?.label ?? date,
    day: head?.day ?? '',
    title: head?.title ?? '일일 동향 보고서',
    summary: head?.summary ?? '',
    level: head?.level ?? 'mid',
    issueCount: head?.issues ?? body?.issues?.length ?? 0,
    wikiCount: head?.wiki ?? 0,
    overview: body?.overview ?? head?.summary ?? '',
    issues: body?.issues ?? [],
  });
}

// 다운로드는 아직 백엔드가 없어 요청 정보만 돌려줍니다.
export function downloadReport(date, format) {
  return delay({ date, format, ok: false, reason: '백엔드 연동 예정' });
}

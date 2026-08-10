import { extractCatalogKeywords } from '../data/wikiKeywords';
import {
  downloadDailyReport as downloadDailyReportApi,
  fetchDailyReport as fetchDailyReportApi,
  fetchDailyReportHistory as fetchDailyReportHistoryApi,
  generateDailyReport as generateDailyReportApi,
} from '../api/report';
import {
  MOCK_REPORT_SUMMARY,
  MOCK_REPORT_ARCHIVE,
  MOCK_REPORT_TODAY,
  MOCK_REPORT_DETAILS,
} from '../data/mockReport';

// 게스트(비로그인)는 토큰이 없어 실백엔드 요청이 401(missing bearer token)로 실패한다.
// 이 파일은 목업/실데이터 스위치가 따로 없어(항상 실백엔드를 호출) 그 경우엔 에러를
// 화면에 그대로 흘려보내는 대신 mockReport.js 목업으로 대체해 둘러볼 수 있게 한다.
function isAuthError(error) {
  return error?.status === 401;
}

function mockDetail(date) {
  const found = MOCK_REPORT_DETAILS[date] || MOCK_REPORT_DETAILS[MOCK_REPORT_TODAY.date];
  const archiveItem =
    MOCK_REPORT_ARCHIVE.find((item) => item.date === date) || MOCK_REPORT_ARCHIVE[0];
  return {
    date: archiveItem.date,
    label: archiveItem.label,
    day: archiveItem.day,
    title: archiveItem.title,
    summary: archiveItem.summary,
    level: archiveItem.level,
    issueCount: found.issues.length,
    wikiCount: archiveItem.wiki,
    overview: found.overview,
    issues: found.issues,
  };
}

const HISTORY_ARCHIVE_LIMIT = 30;
const reportCache = new Map();
const reportArchiveCache = new Map();
const reportGenerationCache = new Map();

const LEVEL_ORDER = { low: 1, mid: 2, high: 3 };
const KEYWORD_LIMIT = 6; // 오늘의 키워드 노출 개수

const LEVEL_BY_SCORE = [
  { min: 80, level: 'high' },
  { min: 50, level: 'mid' },
  { min: 0, level: 'low' },
];

function getTodayKSTDate() {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date());
}

function formatDateLabel(date) {
  if (!date) return '';
  const parsed = new Date(`${date}T00:00:00+09:00`);
  const weekday = new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul',
    weekday: 'short',
  }).format(parsed);
  return `${date.replaceAll('-', '.')} ${weekday}`;
}

function getLevelFromScore(score) {
  const safe = Number(score ?? 0);
  return LEVEL_BY_SCORE.find((item) => safe >= item.min)?.level ?? 'low';
}

function getOverallLevel(sections) {
  return sections.reduce((current, section) => {
    return LEVEL_ORDER[section.level] > LEVEL_ORDER[current] ? section.level : current;
  }, 'low');
}

// 오늘의 키워드.
//
// 위키 연동 키워드 카탈로그(data/wikiKeywords.js, 분류 6종)를 그대로 사전으로 씁니다.
// 리포트와 위키가 같은 키워드 체계를 쓰게 하려는 목적입니다.
//
// 이전에는 key_facts 문장을 잘라 그대로 노출했는데, 문장이라 칩으로 길고 화면마다
// 표기가 달라졌습니다. 이제 이슈 제목·요약·key_facts를 합친 텍스트에서 카탈로그
// 키워드만 뽑고, 등장 횟수 순으로 상위 KEYWORD_LIMIT개를 씁니다.
//
// 카탈로그 키워드가 하나도 안 잡히면 이슈 제목으로 대체합니다 — 없는 키워드를
// 지어내지 않으면서 화면이 비지 않게 하려는 처리입니다.
function pickKeywords(sections) {
  const text = sections
    .map((section) => {
      const content = section.content && typeof section.content === 'object' ? section.content : {};
      const facts = Array.isArray(content.key_facts) ? content.key_facts : [];
      return [section.title, content.current_summary, ...facts].filter(Boolean).join(' ');
    })
    .join(' ');

  const found = extractCatalogKeywords(text)
    .slice(0, KEYWORD_LIMIT)
    .map((k) => k.word);

  if (found.length > 0) return found;

  return [...new Set(sections.map((s) => s.title).filter(Boolean))].slice(0, KEYWORD_LIMIT);
}

function normalizeIssue(section) {
  const content = section.content && typeof section.content === 'object' ? section.content : {};
  const importanceScore = Number(content.importance_score ?? 0);
  const level = getLevelFromScore(importanceScore);
  const firstCitation = section.citations?.[0];

  return {
    id: section.id,
    level,
    category: content.category || '미분류',
    title: section.title,
    summary: content.current_summary || section.title,
    sourceIsDoc: Boolean(firstCitation?.source_url),
    sourceLabel: firstCitation?.source_name || firstCitation?.document_title || '출처 없음',
    sourceUrl: firstCitation?.source_url || '#',
    sourceTitle:
      firstCitation?.document_title ||
      firstCitation?.quoted_text ||
      section.title,
    wikiId: null,
    wikiTitle: null,
  };
}

function normalizeArchiveItem(report, issues, todayDate) {
  const level = getOverallLevel(issues);
  const overview = buildOverview(issues);

  return {
    date: report.date,
    label: formatDateLabel(report.date),
    day: report.date === todayDate ? '오늘' : '',
    title: report.title,
    summary: overview,
    issues: issues.length,
    wiki: 0,
    level,
    old: false,
  };
}

function normalizeHistoryArchiveItem(item, todayDate) {
  const date = item.date || '';

  return {
    reportId: item.report_id,
    date,
    label: formatDateLabel(date),
    day: date === todayDate ? '\uC624\uB298' : '',
    title: item.title || '\uC77C\uC77C \uC0B0\uC5C5 \uB3D9\uD5A5 \uBCF4\uACE0\uC11C',
    summary: '',
    issues: Number(item.issue_count ?? 0),
    wiki: null,
    level: null,
    old: false,
    version: Number(item.version ?? 1),
    status: item.status || 'completed',
    completedAt: item.completed_at || null,
    hasPdf: Boolean(item.has_pdf),
    hasDocx: Boolean(item.has_docx),
    hasPptx: Boolean(item.has_pptx),
  };
}

async function loadReportArchive(limit = HISTORY_ARCHIVE_LIMIT) {
  const safeLimit = Math.min(100, Math.max(1, Number(limit) || HISTORY_ARCHIVE_LIMIT));
  if (!reportArchiveCache.has(safeLimit)) {
    reportArchiveCache.set(
      safeLimit,
      fetchDailyReportHistoryApi(safeLimit).catch((error) => {
        reportArchiveCache.delete(safeLimit);
        throw error;
      }),
    );
  }

  return reportArchiveCache.get(safeLimit);
}

function buildOverview(issues) {
  if (!issues.length) {
    return '아직 생성된 리포트 본문이 없습니다.';
  }

  return issues
    .slice(0, 2)
    .map((issue) => issue.summary)
    .join(' ')
    .trim();
}

function buildPendingReportView(date = getTodayKSTDate()) {
  const label = formatDateLabel(date);
  const title = '일일 동향 보고서 생성 대기';
  const summary = '아직 생성된 리포트가 없습니다. Word/PDF/PPT 버튼을 누르면 리포트를 생성한 뒤 다운로드합니다.';
  const archiveItem = {
    date,
    label,
    day: date === getTodayKSTDate() ? '오늘' : '',
    title,
    summary,
    issues: 0,
    wiki: 0,
    level: 'mid',
    old: false,
  };

  return {
    raw: null,
    issues: [],
    summary: {
      date: label,
      statusLabel: '생성 대기',
      kpis: [],
      totalLabel: '전체 0건',
      categories: [{ name: '전체', count: 0 }],
      keywords: ['리포트 생성 대기'],
    },
    archive: [archiveItem],
    today: {
      label: `${label} - 생성 대기`,
      date,
      archiveItem,
    },
    detail: {
      date,
      label,
      day: archiveItem.day,
      title,
      summary,
      level: archiveItem.level,
      issueCount: 0,
      wikiCount: 0,
      overview: summary,
      issues: [],
    },
  };
}


async function fetchDailyReportOrGenerate(date, generateOnMissing = false) {
  try {
    return await fetchDailyReportApi(date);
  } catch (error) {
    if (error?.status !== 404) {
      throw error;
    }

    if (!generateOnMissing) {
      return null;
    }

    await ensureDailyReportGenerated(date);
    return fetchDailyReportApi(date);
  }
}

async function loadDailyReport(date = getTodayKSTDate(), { generateOnMissing = false } = {}) {
  if (!reportCache.has(date)) {
    reportCache.set(
      date,
      fetchDailyReportOrGenerate(date, generateOnMissing).catch((error) => {
        reportCache.delete(date);
        throw error;
      }),
    );
  }

  return reportCache.get(date);
}

async function buildReportView(date = getTodayKSTDate(), { generateOnMissing = false } = {}) {
  const report = await loadDailyReport(date, { generateOnMissing });
  if (!report) {
    return buildPendingReportView(date);
  }

  const issues = (report.sections || []).map(normalizeIssue);
  const archiveItem = normalizeArchiveItem(report, issues, getTodayKSTDate());

  return {
    raw: report,
    issues,
    summary: {
      date: formatDateLabel(report.date),
      statusLabel: report.status === 'completed' ? '생성 완료' : report.status,
      kpis: [],
      totalLabel: `전체 ${issues.length}건`,
      categories: [
        { name: '전체', count: issues.length },
        ...Array.from(
          issues.reduce((map, issue) => {
            map.set(issue.category, (map.get(issue.category) || 0) + 1);
            return map;
          }, new Map()),
        ).map(([name, count]) => ({ name, count })),
      ],
      keywords: pickKeywords(report.sections || []),
    },
    archive: [archiveItem],
    today: {
      label: `${formatDateLabel(report.date)} - 생성 완료 - 이슈 ${issues.length}건`,
      date: report.date,
      archiveItem,
    },
    detail: {
      date: report.date,
      label: formatDateLabel(report.date),
      day: archiveItem.day,
      title: report.title,
      summary: archiveItem.summary,
      level: archiveItem.level,
      issueCount: issues.length,
      wikiCount: 0,
      overview: archiveItem.summary,
      issues,
    },
  };
}

export async function fetchReportSummary(date) {
  try {
    const view = await buildReportView(date, { generateOnMissing: false });
    return view.summary;
  } catch (error) {
    if (isAuthError(error)) return MOCK_REPORT_SUMMARY;
    throw error;
  }
}

export async function fetchReportIssues(date) {
  const view = await buildReportView(date, { generateOnMissing: true });
  return view.issues;
}

export async function fetchReportArchive(_date, limit = HISTORY_ARCHIVE_LIMIT) {
  try {
    const history = await loadReportArchive(limit);
    const todayDate = getTodayKSTDate();
    return (Array.isArray(history) ? history : []).map((item) =>
      normalizeHistoryArchiveItem(item, todayDate),
    );
  } catch (error) {
    if (isAuthError(error)) return MOCK_REPORT_ARCHIVE;
    throw error;
  }
}

export async function fetchTodayReport(date) {
  try {
    const view = await buildReportView(date, { generateOnMissing: false });
    return view.today;
  } catch (error) {
    if (isAuthError(error)) return MOCK_REPORT_TODAY;
    throw error;
  }
}

export async function fetchReportDetail(date) {
  if (!date) return null;
  try {
    const view = await buildReportView(date, { generateOnMissing: false });
    return view.detail;
  } catch (error) {
    if (error?.status === 404) return null;
    if (isAuthError(error)) return mockDetail(date);
    throw error;
  }
}

const DOWNLOAD_EXTENSIONS = {
  word: 'docx',
  doc: 'docx',
  docx: 'docx',
  pdf: 'pdf',
  ppt: 'pptx',
  pptx: 'pptx',
};

function buildFallbackDownloadName(date, format) {
  const extension = DOWNLOAD_EXTENSIONS[format] || format || 'file';
  return `daily-report-${date}.${extension}`;
}

async function ensureDailyReportGenerated(date) {
  if (!reportGenerationCache.has(date)) {
    reportGenerationCache.set(
      date,
      generateDailyReportApi(date).finally(() => {
        reportGenerationCache.delete(date);
      }),
    );
  }

  const generatedReport = await reportGenerationCache.get(date);
  reportCache.delete(date);
  return generatedReport;
}

function saveBlobAsFile(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export async function downloadReport(date, format) {
  try {
    const { blob, filename } = await downloadDailyReportApi(date, format);
    saveBlobAsFile(blob, filename || buildFallbackDownloadName(date, format));
    return { date, format, ok: true, generated: false };
  } catch (error) {
    if (error?.status !== 404) {
      return {
        date,
        format,
        ok: false,
        status: error?.status,
        reason: error?.detail || error?.message || 'download failed',
      };
    }

    try {
      await ensureDailyReportGenerated(date);
      const { blob, filename } = await downloadDailyReportApi(date, format);
      saveBlobAsFile(blob, filename || buildFallbackDownloadName(date, format));
      return { date, format, ok: true, generated: true };
    } catch (generationError) {
      return {
        date,
        format,
        ok: false,
        status: generationError?.status,
        reason: generationError?.detail || generationError?.message || 'report generation failed',
      };
    }
  }
}

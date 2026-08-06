import {
  downloadDailyReport as downloadDailyReportApi,
  fetchDailyReport as fetchDailyReportApi,
  generateDailyReport as generateDailyReportApi,
} from '../api/report';

const reportCache = new Map();
const reportGenerationCache = new Map();

const LEVEL_ORDER = { low: 1, mid: 2, high: 3 };
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

function pickKeywords(sections) {
  const values = [];
  for (const section of sections) {
    const facts = Array.isArray(section.content?.key_facts) ? section.content.key_facts : [];
    for (const fact of facts) {
      if (!fact) continue;
      values.push(String(fact).trim());
      if (values.length >= 6) return values;
    }
  }

  for (const section of sections) {
    if (section.title) values.push(section.title);
    if (values.length >= 6) break;
  }

  return [...new Set(values)].slice(0, 6);
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
      label: `${label} - 리포트 생성 대기`,
      date,
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
      label: `${formatDateLabel(report.date)} - 일일 동향 보고서 - 이슈 ${issues.length}건`,
      date: report.date,
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
  const view = await buildReportView(date, { generateOnMissing: true });
  return view.summary;
}

export async function fetchReportIssues(date) {
  const view = await buildReportView(date, { generateOnMissing: true });
  return view.issues;
}

export async function fetchReportArchive(date) {
  const view = await buildReportView(date, { generateOnMissing: true });
  return view.archive;
}

export async function fetchTodayReport(date) {
  const view = await buildReportView(date, { generateOnMissing: true });
  return view.today;
}

export async function fetchReportDetail(date) {
  if (!date) return null;
  try {
    const view = await buildReportView(date, { generateOnMissing: false });
    return view.detail;
  } catch (error) {
    if (error?.status === 404) return null;
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

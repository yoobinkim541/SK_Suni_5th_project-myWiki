// 대시보드 API 호출부.
//
// 화면 컴포넌트는 이 파일만 봅니다. 나머지 항목을 실제 fetch로 바꿀 때도
// pages/DashboardPage.jsx는 손댈 필요가 없습니다.
//
// 항목별 연동 현황 (2026-08-07 확인):
//   [LIVE] kpiSummary   GET /dashboard/summary -> src/api/dashboard_router.py
//                       수집 문서·생성 보고서·위키 문서·평균 신뢰도 4종
//   [LIVE] trend        GET /dashboard/trend   -> src/api/dashboard_router.py
//                       최근 7일 일별 수집·채택 (KST 기준)
//   [LIVE] news         GET /dashboard/news    -> src/api/dashboard_router.py
//                       문서 단위로 접은 뒤 발행일 내림차순
//   [LIVE] keywords     GET /dashboard/keywords -> src/api/dashboard_router.py
//                       제목에 등장한 낱말 상위 8개 (최근 7일)
//   [목업] issues       백엔드 없음 — summary·level이 분석 산출물이라 조회만으로는
//                       못 만듭니다. 공시 기반이어야 하는데 /dashboard/news 경로에는
//                       공시가 거의 안 들어옵니다(별도 조회 필요, 이환희 협의 사항).
//
// 목업 항목은 백엔드가 생기기 전까지 지우지 않습니다 — 지우면 화면이 빕니다.
// MOCK_NEWS·MOCK_KEYWORDS는 VITE_USE_MOCK 분기에서 계속 쓰므로 남겨 둡니다.
//
// categoryPreview는 이 파일에서 뺐습니다. #92(대시보드 개편)로 DashboardPage가
// CategoryPreview를 렌더링하지 않게 됐는데 fetchDashboard()가 값을 계속 반환하고
// 있어서, 화면에 없는 항목이 "아직 연동할 게 남은 것"처럼 목록에 잡혔습니다.
// 컴포넌트(components/dashboard/CategoryPreview.jsx)와 목업
// (data/mockDashboard.js MOCK_CATEGORY_PREVIEW)은 되살릴 때를 위해 남겨뒀습니다.
// 되살린다면 지금은 /categories/stats가 같은 값을 이미 내려주므로 목업이 아니라
// 그쪽에 붙이면 됩니다.
//
// ⚠ VITE_USE_MOCK은 전역 스위치입니다. 'false'로 두면 이 파일뿐 아니라
//   agentApi·wikiApi·settingsApi도 함께 실백엔드로 붙습니다.

import {
  fetchDashboardKeywords,
  fetchDashboardNews,
  fetchDashboardSummary,
  fetchDashboardTrend,
} from '../api/dashboard';
import {
  MOCK_NEWS,
  MOCK_ISSUES,
  MOCK_TREND,
  MOCK_KEYWORDS,
  MOCK_KPI_SUMMARY,
} from '../data/mockDashboard';

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false';

// 목업을 Promise로 감싸 반환합니다. 화면 쪽 코드가 실연동 후에도 그대로 동작하게
// 하려는 장치라, 실제 백엔드가 생기면 이 함수가 아니라 각 fetch* 함수 안을 바꿉니다.
const delay = (value) => Promise.resolve(value);

// 대시보드는 App.jsx가 세션을 확인(authChecked=true)한 뒤에만 그려지지만, 그 시점에도
// Supabase 클라이언트 내부 세션 복원이 완전히 끝나 있다는 보장은 없다 — 실사용에서
// 로그인된 사용자의 첫 로드에서 apiFetch가 토큰 없이 나가 "missing bearer token"(401)이
// 나는 게 콘솔에 확인됐다(2026-08-09). 네트워크가 느릴 때 나는 "Failed to fetch"도 같은
// 증상(반응이 없다가 대시보드만 비어 보임)이라 같이 묶어서 처리한다.
// 세션은 보통 1~2초 안에 복원되므로, 실패하면 한 번만 짧게 기다렸다가 재시도한다 —
// 그래도 실패하면(진짜 로그인 안 된 상태 등) 기존처럼 실패로 처리한다(무한 재시도 안 함).
async function withRetry(fn) {
  try {
    return await fn();
  } catch {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    return fn();
  }
}

// 발행 시각 -> '12분 전' 같은 상대 시간. 백엔드는 ISO 그대로 주고 여기서 만듭니다 —
// 서버 시각과 보는 사람의 시각이 다를 수 있어서, 서버가 미리 계산하면 어긋납니다.
// 하루가 넘으면 상대 표기가 오히려 안 읽혀서 날짜로 바꿉니다.
function toRelativeTime(iso) {
  if (!iso) return '';
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return '';

  const minutes = Math.floor((Date.now() - then.getTime()) / 60000);
  if (minutes < 1) return '방금 전';
  if (minutes < 60) return `${minutes}분 전`;
  if (minutes < 60 * 24) return `${Math.floor(minutes / 60)}시간 전`;
  return `${then.getMonth() + 1}.${then.getDate()}`;
}

// 백엔드 DashboardNewsItemOut -> 뉴스 카드가 기대하는 shape.
//
// tags에 ?? []를 거는 이유: DashboardPage가 n.tags.map()을 가드 없이 부릅니다.
// 백엔드도 항상 배열을 주지만, 여기서 한 번 더 막아야 화면이 안 죽습니다.
function toNewsItem(item) {
  return {
    title: item.title,
    quote: item.quote || '',
    category: item.category,
    tags: item.tags ?? [],
    isDoc: item.is_doc,
    sourceLabel: item.source_label,
    sourceUrl: item.source_url,
    time: toRelativeTime(item.published_at),
  };
}

// [LIVE] VITE_USE_MOCK !== 'false' 일 때만 목업입니다.
export function fetchNews() {
  if (USE_MOCK) return delay(MOCK_NEWS);
  return fetchDashboardNews().then((res) => (res.items ?? []).map(toNewsItem));
}

// [목업] 백엔드 없음
export function fetchIssues() {
  // isSample을 여기서 붙입니다. 목업/실데이터를 아는 것은 이 계층이고,
  // 화면(IssueList)은 플래그만 보고 표시를 정합니다.
  //
  // 목업의 sourceUrl이 개별 원문이 아니라 도메인 루트라(https://dart.fss.or.kr)
  // 그대로 링크로 걸면 눌렀을 때 언론사·DART 홈페이지로 갑니다. 실제로 그렇게
  // 신고가 들어왔습니다. 백엔드가 붙기 전까지는 링크로 만들지 않습니다.
  return delay(MOCK_ISSUES.map((issue) => ({ ...issue, isSample: true })));
}

// 백엔드 TrendDayOut -> TrendChart가 기대하는 shape.
//
// date는 'YYYY-MM-DD'로 오는데 차트 x축은 폭이 좁아 'MM.DD'만 쓴다. 문자열을
// 잘라 쓰는 이유는 new Date()로 파싱하면 브라우저 타임존에 따라 하루가 밀려서다 —
// 백엔드가 이미 KST 기준으로 잘라 보낸 날짜라 여기서 다시 해석하면 안 된다.
//
// news/disclosure는 차트가 안 쓰지만 그대로 넘긴다. 나중에 계열을 나눠 그릴 때
// 서비스 계약을 다시 바꾸지 않아도 되게 한다.
function toTrendDay(day) {
  return {
    date: String(day.date).slice(5).replace('-', '.'),
    collected: day.collected,
    adopted: day.adopted,
    news: day.news,
    disclosure: day.disclosure,
  };
}

// [LIVE] VITE_USE_MOCK !== 'false' 일 때만 목업입니다.
export function fetchTrend() {
  if (USE_MOCK) return delay(MOCK_TREND);
  return fetchDashboardTrend().then((res) => (res.days ?? []).map(toTrendDay));
}

// [LIVE] VITE_USE_MOCK !== 'false' 일 때만 목업입니다.
//
// 칩과 뉴스 카드의 tags는 백엔드에서 같은 키워드 사전을 씁니다. 칩을 눌렀을 때
// 뉴스가 좁혀지는 게 텍스트 매칭(newsMatchesInterest)이라, 사전이 갈리면
// 칩을 눌러도 걸리는 카드가 없어 빈 화면이 됩니다. 둘은 같이 실데이터로 붙입니다.
export function fetchKeywords() {
  if (USE_MOCK) return delay(MOCK_KEYWORDS);
  return fetchDashboardKeywords().then((res) => res.keywords ?? []);
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
// kpiSummary·trend가 실데이터이고 나머지는 목업인 혼합 상태입니다 — 항목별로 하나씩 교체합니다.
//
// 목업 항목은 fetch* 함수를 거치지 않고 상수를 그대로 씁니다.
//
// ⚠ 원래는 실연동된 넷을 Promise.all로 동시에 불렀는데, 실제 로그인 세션 콘솔에서 직접
// 확인해보니(2026-08-09) api.mywiki.pe.kr에 4개를 동시에 쏘면 상당수가 "Failed to fetch"로
// 죽는다 — 같은 요청을 하나씩 순서대로 보내면 15/15 전부 성공하고, 2개씩 동시에 보내도
// 12/12 성공하는데 4개를 한 번에 보내면 5라운드 중 2라운드가 4개 전부 실패했다. Cloudflare
// Tunnel(cloudflared)이나 백엔드 쪽에 동시 연결 상한이 있는 것으로 보이는데, 그 값을 직접
// 조정할 권한/접근이 없어서(VM 설정) 프론트에서 애초에 그 상한을 안 건드리도록 순서대로
// 호출한다. 각자 1.5초 응답이라 넷을 순서대로 불러도 체감상 크게 느리지 않다(기존에도
// KPI/추이만 실데이터였을 때부터 이미 이 정도 지연은 있었다).
//
// 그래도 각자 실패하면 서로, 그리고 목업 항목을 물고 들어가지 않게 개별 try/catch로 갈라둔다.
// KPI 실패는 카드에 "—"를 채우고, 추이 실패는 목업으로 메우지 않고 빈 배열을
// 돌려줍니다(차트는 "표시할 추이 데이터가 없습니다"를 그립니다) — 목업으로 덮으면
// 백엔드가 죽은 걸 정상 화면처럼 보이게 만듭니다.
export async function fetchDashboard() {
  const kpiSummary = await withRetry(fetchKpiSummary).catch((err) => {
    console.error('[dashboardApi] KPI 조회 실패(재시도 후에도 실패 — 게스트이거나 인증 만료) — KPI만 빈 상태로 둡니다:', err);
    return {
      collectedDocs: { value: '—', desc: '' },
      generatedReports: { value: '—', desc: '' },
      wikiDocs: { value: '—', desc: '' },
      avgConfidence: { value: '—', desc: '' },
    };
  });
  const trend = await withRetry(fetchTrend).catch((err) => {
    console.error('[dashboardApi] 추이 조회 실패(재시도 후에도 실패) — 차트만 빈 상태로 둡니다:', err);
    return [];
  });
  const news = await withRetry(fetchNews).catch((err) => {
    console.error('[dashboardApi] 뉴스 조회 실패(재시도 후에도 실패) — 뉴스만 빈 상태로 둡니다:', err);
    return [];
  });
  const keywords = await withRetry(fetchKeywords).catch((err) => {
    console.error('[dashboardApi] 키워드 조회 실패(재시도 후에도 실패) — 칩만 빈 상태로 둡니다:', err);
    return [];
  });
  return {
    news,
    issues: MOCK_ISSUES,
    trend,
    keywords,
    kpiSummary,
  };
}

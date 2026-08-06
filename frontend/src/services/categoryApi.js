// 카테고리 현황 API 호출부.
//
// 항목별 연동 현황 (2026-08-06):
//   [LIVE] fetchCategories()       GET /categories/stats -> src/api/category_router.py
//                                  카드 + 원그래프 키워드 + 관련 뉴스가 한 응답에 들어온다
//   [LIVE] fetchCategorySummary()  같은 응답을 나눠 쓴다 (KPI 4장 중 2장은 아래 참고)
//
// ⚠ 관련 뉴스의 인용문(quote)은 대체로 빈칸입니다. 인용문은 분석 4단계 중
//   중요도 단계 산출물인데 그 단계가 하루쯤 뒤처져서, 최신순으로 뽑는 이 목록에는
//   아직 인용문이 없습니다. 스케줄러 타임아웃(P1)이 풀리면 채워집니다.
//
// ⚠ VITE_USE_MOCK은 전역 스위치입니다. 'false'로 두면 이 파일뿐 아니라
//   dashboardApi·agentApi·wikiApi·settingsApi도 함께 실백엔드로 붙습니다.

import { fetchCategoryStats } from '../api/category';
import { MOCK_CATEGORIES, MOCK_CATEGORY_KEYWORDS, MOCK_SUMMARY } from '../data/mockCategory';
import { MOCK_NEWS } from '../data/mockDashboard';

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false';

const delay = (value) => Promise.resolve(value);

// 한 화면에서 fetchCategories()와 fetchCategorySummary()를 Promise.all로 동시에 부른다.
// 같은 응답을 두 번 받지 않도록 진행 중인 요청을 공유한다. CategoryPage가 마운트될
// 때마다 새로 만들어야 하므로 결과가 아니라 "진행 중 Promise"만 잠시 붙들어 둔다.
let inflight = null;

function loadStats() {
  if (!inflight) {
    inflight = fetchCategoryStats().finally(() => {
      inflight = null;
    });
  }
  return inflight;
}

// 백엔드 CategoryStatOut -> 화면이 기대하는 shape.
// id 슬러그는 그대로 둔다 — 원그래프 탭 선택 상태의 키로 쓰인다.
function toCategory(row) {
  return {
    id: row.id,
    name: row.name,
    count: row.count,
    topIssue: row.top_issue,
    tags: row.tags ?? [],
    level: row.level,
    // 원그래프 오른쪽 — KeywordPie가 [{word, count}]를 그대로 먹는다
    keywords: row.keywords ?? [],
    // 관련 뉴스 모달
    recentDocuments: (row.recent_documents ?? []).map((d) => ({
      title: d.title,
      quote: d.quote,
      sourceLabel: d.source_label,
      sourceUrl: d.source_url,
      publishedAt: d.published_at,
    })),
  };
}

// 목업도 실데이터와 같은 shape로 맞춘다. 그래야 CategoryKeywordChart·CategoryRow가
// data/를 직접 import하지 않고 categories prop 하나만 보면 된다.
function toMockCategory(c) {
  return {
    ...c,
    keywords: MOCK_CATEGORY_KEYWORDS[c.id] ?? [],
    recentDocuments: MOCK_NEWS.filter((n) => n.category === c.name).map((n) => ({
      title: n.title,
      quote: n.quote,
      sourceLabel: n.sourceLabel,
      sourceUrl: n.sourceUrl,
      // 목업은 '1시간 전' 같은 완성 문자열이라 ISO가 없다. 화면이 publishedAt이
      // 없으면 그대로 time을 쓰도록 두 값을 다 넘긴다.
      publishedAt: null,
      time: n.time,
    })),
  };
}

export function fetchCategories() {
  if (USE_MOCK) return delay(MOCK_CATEGORIES.map(toMockCategory));
  return loadStats().then((stats) => stats.categories.map(toCategory));
}

// KpiCard 4장. CategoryDetail이 {value, desc} 중첩 구조를 그대로 읽으므로
// 네 칸을 항상 채운다 — 한 칸이라도 비면 화면이 빈 카드로 남는다.
//
// [LIVE] 최다 분류 / 평균 신뢰도
// [목업] 증가 폭 최대 / 신규 이슈 분류
//   -> 둘 다 "전일 대비" 개념인데 카테고리별 일별 스냅샷이 DB에 없다.
//      만들려면 어제 구간을 다시 집계해야 해서 이번 범위에서 뺐다.
function toSummary(stats) {
  const categories = stats.categories ?? [];
  const top = categories.reduce(
    (best, c) => (best === null || c.count > best.count ? c : best),
    null
  );
  const total = stats.total_documents ?? 0;
  const percent = top && total > 0 ? Math.round((top.count / total) * 100) : 0;

  return {
    totalLabel: `전체 ${total}건 · ${categories.length}개 분류`,
    topCategory: top
      ? { value: top.name, desc: `${percent}% · ${top.count}건` }
      : { value: '-', desc: '분류된 문서 없음' },
    maxIncrease: MOCK_SUMMARY.maxIncrease, // [목업]
    newCategory: MOCK_SUMMARY.newCategory, // [목업]
    avgConfidence: { value: overallLevelLabel(categories), desc: '체크리스트 기준' },
  };
}

// 카드의 level(high/mid/low)을 한글 라벨로. 문서 수로 가중평균해서 전체 경향을 낸다.
const LEVEL_SCORE = { high: 2, mid: 1, low: 0 };
const LEVEL_LABEL = ['낮음', '보통', '높음'];

function overallLevelLabel(categories) {
  const scored = categories.filter((c) => c.count > 0 && c.level in LEVEL_SCORE);
  if (scored.length === 0) return '데이터 없음';
  const totalCount = scored.reduce((sum, c) => sum + c.count, 0);
  const weighted = scored.reduce((sum, c) => sum + LEVEL_SCORE[c.level] * c.count, 0);
  return LEVEL_LABEL[Math.round(weighted / totalCount)];
}

export function fetchCategorySummary() {
  if (USE_MOCK) return delay(MOCK_SUMMARY);
  return loadStats().then(toSummary);
}

// fetchNewsByCategory는 없앴습니다. 관련 뉴스가 카테고리 객체의 recentDocuments로
// 함께 오므로 화면당 요청이 1+6건에서 1건으로 줄었습니다.

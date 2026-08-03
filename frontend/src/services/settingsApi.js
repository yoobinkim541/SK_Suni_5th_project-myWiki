// 설정 화면 데이터 호출부.
// USE_MOCK=true면 아래 상수를 그대로 돌려주고, false면 백엔드를 호출합니다.
//
// 수집 소스 목록은 DB의 sources 테이블에 있어서 프론트가 직접 읽을 수 없습니다.
// (배치는 SERVICE_ROLE_KEY로 RLS를 우회하지만 프론트는 그럴 수 없음)
// 조회 엔드포인트가 열리면 fetchCollectSources() 몸통만 교체하면 됩니다.

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false';

// scripts/register_sources.py 기준 (2026-08-03 확인).
// ⚠ 초기 등록 스크립트를 근거로 한 값이라, 이후 소스가 추가되면 실제와 어긋납니다.
//   화면에 "N개 매체"처럼 단정적인 숫자를 쓰지 않는 이유입니다.
const COLLECT_SOURCES = [
  { provider: 'naver', label: '네이버 검색 API', count: 4 },
  { provider: 'gnews', label: 'GNews', count: 3 },
  { provider: 'google_rss', label: '구글 뉴스 RSS', count: 1 },
  { provider: 'opendart', label: 'OpenDART', count: null }, // 공시 — 등록 위치 미확인
];

/**
 * 수집 소스 목록.
 * @returns {Promise<Array<{provider, label, count}>>}
 */
export async function fetchCollectSources() {
  if (USE_MOCK) return COLLECT_SOURCES;

  // TODO: 백엔드에 소스 조회 엔드포인트가 없습니다.
  // GET /api/sources 가 열리면 아래 주석을 해제하고 위 상수 반환을 제거합니다.
  // const rows = await settingsApi.fetchSources();
  // return groupByProvider(rows);
  return COLLECT_SOURCES;
}

/** 화면 상단 요약 문구 — "네이버 검색 API · GNews · 구글 뉴스 RSS · OpenDART" */
export function formatSourceSummary(sources) {
  return sources.map((s) => s.label).join(' · ');
}

/** 값 칸 문구 — "4종 연결됨" */
export function formatSourceCount(sources) {
  return `${sources.length}종 연결됨`;
}
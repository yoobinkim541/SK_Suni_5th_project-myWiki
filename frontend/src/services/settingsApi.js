// 설정 화면 데이터 호출부.
// USE_MOCK=true면 아래 상수를 그대로 돌려주고, false면 백엔드를 호출합니다.
//
// 수집 소스 목록은 DB의 sources 테이블에 있어서 프론트가 직접 읽을 수 없습니다.
// (배치는 SERVICE_ROLE_KEY로 RLS를 우회하지만 프론트는 그럴 수 없음)
// 조회 엔드포인트가 열리면 fetchCollectSources() 몸통만 교체하면 됩니다.

import * as workspaceSettingsApi from '../api/workspaceSettings';

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

// SettingsPage.jsx의 <select> 값(문자열) <-> 백엔드 workspace_settings 값(숫자) 매핑.
// 허용값은 src/settings/service.py의 WIKI_UPDATE_CYCLE_MINUTES_CHOICES와 1:1로 맞춰뒀다.
const WIKI_CYCLE_TO_MINUTES = { '30m': 30, '1h': 60, '3h': 180, '6h': 360, '12h': 720, '24h': 1440 };
const MINUTES_TO_WIKI_CYCLE = Object.fromEntries(
  Object.entries(WIKI_CYCLE_TO_MINUTES).map(([label, minutes]) => [minutes, label])
);

// 데이터(수집·분석) 갱신 주기 — DATA_REFRESH_CYCLE_MINUTES_CHOICES와 1:1로 맞춤.
// 2시간(2h)이 위키 주기엔 없는 선택지라 여기만 따로 둔다.
const DATA_CYCLE_TO_MINUTES = { '30m': 30, '1h': 60, '2h': 120, '3h': 180, '6h': 360, '12h': 720, '24h': 1440 };
const MINUTES_TO_DATA_CYCLE = Object.fromEntries(
  Object.entries(DATA_CYCLE_TO_MINUTES).map(([label, minutes]) => [minutes, label])
);

// chat_retention_days: null이면 "영구 보관". CHAT_RETENTION_DAYS_CHOICES=(7,30,90)과 맞춤.
const CHAT_KEEP_TO_DAYS = { 7: 7, 30: 30, 90: 90 };

function daysToChatKeep(days) {
  if (days == null) return 'forever';
  return CHAT_KEEP_TO_DAYS[days] != null ? String(days) : '90';
}

/**
 * 워크스페이스 설정 조회 — SettingsPage.jsx의 초기값으로 쓴다.
 * 목업 모드에서는 null을 돌려주고, 호출부가 localStorage 값을 그대로 쓰게 둔다.
 * @returns {Promise<{wikiCycle: string, chatKeep: string} | null>}
 */
export async function fetchWorkspaceSettings() {
  if (USE_MOCK) return null;
  const data = await workspaceSettingsApi.fetchWorkspaceSettings();
  return {
    wikiCycle: MINUTES_TO_WIKI_CYCLE[data.wiki_update_cycle_minutes] || '6h',
    dataCycle: MINUTES_TO_DATA_CYCLE[data.data_refresh_cycle_minutes] || '2h',
    chatKeep: daysToChatKeep(data.chat_retention_days),
  };
}

/** Wiki 업데이트 주기 저장. wikiCycle은 <select>의 값('30m'|'1h'|...)을 그대로 받는다. */
export async function updateWikiCycle(wikiCycle) {
  if (USE_MOCK) return;
  const minutes = WIKI_CYCLE_TO_MINUTES[wikiCycle];
  if (!minutes) return;
  await workspaceSettingsApi.updateWorkspaceSettings({ wiki_update_cycle_minutes: minutes });
}

/** 데이터(수집·분석) 갱신 주기 저장. dataCycle은 <select>의 값('30m'|'1h'|'2h'|...)을 그대로 받는다. */
export async function updateDataRefreshCycle(dataCycle) {
  if (USE_MOCK) return;
  const minutes = DATA_CYCLE_TO_MINUTES[dataCycle];
  if (!minutes) return;
  await workspaceSettingsApi.updateWorkspaceSettings({ data_refresh_cycle_minutes: minutes });
}

/** 대화 보관 기간 저장. chatKeep은 <select>의 값('7'|'30'|'90'|'forever')을 그대로 받는다. */
export async function updateChatRetention(chatKeep) {
  if (USE_MOCK) return;
  const days = chatKeep === 'forever' ? null : Number(chatKeep);
  await workspaceSettingsApi.updateWorkspaceSettings({ chat_retention_days: days });
}
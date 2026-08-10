// 위키 API 호출부.
// USE_MOCK=true면 data/mockWiki.js를 그대로 돌려주고, false면 api/wiki.js를 호출합니다.
// 백엔드 응답 shape과 화면(WikiPage.jsx/WikiCard.jsx)이 기대하는 shape이 달라서
// 아래 어댑터로 변환합니다 — services/agentApi.js와 같은 패턴입니다.

import * as wikiApi from '../api/wiki';
import { WIKI_PAGE_TYPE_LABELS } from '../api/wiki';
import { MOCK_WIKI_DOCS, MOCK_WIKI_TREE, WIKI_SOURCES, WIKI_ALIAS, DEFAULT_WIKI_DOC } from '../data/mockWiki';
import { WIKI_KEYWORD_CATALOG, groupKeywordCatalog, findDocsWithKeyword } from '../data/wikiKeywords';
import { WIKI_KEYWORD_LINKS } from '../data/mockWiki';

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false';

// 게스트(비로그인)는 토큰이 없어 실백엔드 요청이 401(missing bearer token)로 실패한다.
// 그 경우엔 에러를 화면에 그대로 흘려보내는 대신 목업으로 대체해 둘러볼 수 있게 한다.
function isAuthError(error) {
  return error?.status === 401;
}

// 출처 원문 정의(공시/뉴스 등) 조회 — CitationTag.jsx, AgentPage.jsx가 그대로 씁니다.
// 위키 화면 자체는 이제 실제 문서 출처(document_title/canonical_url)를 직접 쓰므로
// 이 조회를 거치지 않습니다.
// key가 없을 수 있어(백엔드 citations가 출처 종류를 안 주는 경로) null을 그대로 돌려줍니다 —
// 호출부에서 반드시 널 체크를 해야 합니다.
export function getSource(key) {
  if (!key) return null;
  return WIKI_SOURCES[key] ?? null;
}

// agentApi.js(에이전트 "근거 원문" 카드)도 같은 포맷/기준을 써야 해서 export한다.
export function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}.${mm}.${dd}`;
}

// document_analysis_results/ranking.py의 신뢰도 구간(<40 낮음, <70 보통, 그 외 높음)과
// 동일한 기준으로 라벨링합니다 — 백엔드가 이미 쓰는 임계값과 어긋나지 않게.
export function reliabilityLabel(score) {
  if (score < 40) return '낮음';
  if (score < 70) return '보통';
  return '높음';
}

// 백엔드 WikiPageSummaryOut[] -> 좌측 트리 {group, items:[{id, title}]}[]
export function toTree(pages) {
  const groups = new Map();
  for (const page of pages) {
    const group = WIKI_PAGE_TYPE_LABELS[page.page_type] || page.page_type;
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push({ id: page.slug, title: page.title });
  }
  return Array.from(groups, ([group, items]) => ({ group, items }));
}

// 백엔드 WikiPageContentOut -> WikiCard.jsx가 기대하는 doc shape.
//
// 대응이 안 되는 필드는 만들어내지 않고 빈 값/생략으로 남깁니다:
//  - zones: markdown이 raw 텍스트 한 덩어리라 "개요/쟁점" 구역을 나눌 근거가 없습니다.
//    heading 파싱 규칙이 정해지기 전까지는 본문 전체를 zone 하나(markdown 필드)로 보여주고,
//    WikiCard.jsx가 react-markdown으로 렌더링합니다.
//  - meta의 "평균 신뢰도"는 근거 문서 중 하나라도 점수가 있을 때만 넣습니다.
function toDoc(content) {
  const sources = content.sources.map((s, i) => ({
    citationOrder: s.citation_order ?? i + 1,
    title: s.document_title || `근거 문서 #${s.citation_order ?? i + 1}`,
    sourceName: s.source_name,
    url: s.canonical_url,
    date: formatDate(s.published_at),
    reliabilityScore: s.reliability_score,
  }));

  const meta = [`근거 문서 ${sources.length}건`];
  const scored = sources.filter((s) => s.reliabilityScore != null).map((s) => s.reliabilityScore);
  if (scored.length > 0) {
    const avg = scored.reduce((sum, v) => sum + v, 0) / scored.length;
    meta.push(`평균 신뢰도 ${reliabilityLabel(avg)}`);
  }
  meta.push(`최근 버전 ${formatDate(content.created_at)}`);

  return {
    id: content.slug,
    title: content.title,
    category: WIKI_PAGE_TYPE_LABELS[content.page_type] || content.page_type,
    updated: formatDate(content.published_at),
    meta,
    zones: [{ title: '본문', markdown: content.markdown }],
    timeline: content.versions.map((v, i) => ({
      date: formatDate(v.created_at),
      text: `버전 ${v.version_no}`,
      desc: v.change_summary || '변경 사유 없음',
      isNew: i === 0,
    })),
    sourceCount: sources.length,
    sources,
    // related_pages: 같은 원문을 근거로 인용하는 다른 위키(공유 근거 기반, 조회 시점 계산).
    links: (content.related_pages || []).map((p) => ({
      id: p.slug,
      title: p.title,
      desc: ` · 공유 근거 ${p.shared_source_count}건 · ${WIKI_PAGE_TYPE_LABELS[p.page_type] || p.page_type}`,
    })),
  };
}

// GET /wiki/pages는 한 번에 최대 200건(limit<=200)만 준다 — 트리는 전체가 보여야 하므로
// 페이지를 다 받을 때까지 반복 조회한다(대시보드 KPI가 이미 겪은 것과 같은 truncation 버그,
// src/dashboard/service.py의 _fetch_all() 패턴과 동일).
const WIKI_TREE_PAGE_SIZE = 200;

async function fetchAllWikiPages() {
  const all = [];
  let offset = 0;
  for (;;) {
    const batch = await wikiApi.fetchWikiPages({ limit: WIKI_TREE_PAGE_SIZE, offset });
    all.push(...batch);
    if (batch.length < WIKI_TREE_PAGE_SIZE) break;
    offset += WIKI_TREE_PAGE_SIZE;
  }
  return all;
}

/** WikiPage 좌측 트리 전체. */
export async function fetchWikiTree() {
  if (USE_MOCK) return MOCK_WIKI_TREE;
  try {
    const pages = await fetchAllWikiPages();
    return toTree(pages);
  } catch (error) {
    if (isAuthError(error)) return MOCK_WIKI_TREE;
    throw error;
  }
}

/** 문서 하나(본문 + 출처 + 변경이력). 게시된 페이지가 없으면 null. */
export async function fetchWikiDoc(slug) {
  if (USE_MOCK) return MOCK_WIKI_DOCS[slug] || MOCK_WIKI_DOCS[DEFAULT_WIKI_DOC];
  try {
    const content = await wikiApi.fetchWikiPage(slug);
    return content ? toDoc(content) : null;
  } catch (error) {
    if (isAuthError(error)) return MOCK_WIKI_DOCS[slug] || MOCK_WIKI_DOCS[DEFAULT_WIKI_DOC];
    throw error;
  }
}

/**
 * 연동 키워드 카탈로그(분류별). WikiKeywordBar가 그리는 칩 목록의 데이터 소스.
 * 목업 모드에서는 고정 상수를 그대로, 실제 모드에서는 GET /wiki/keywords 응답을
 * 이 파일과 같은 {cat, words} 모양으로 묶어서 돌려줍니다.
 * @returns {Promise<{cat: string, words: string[]}[]>}
 */
export async function fetchWikiKeywordCatalog() {
  if (USE_MOCK) return WIKI_KEYWORD_CATALOG;
  try {
    const flat = await wikiApi.fetchWikiKeywordCatalog();
    return groupKeywordCatalog(flat);
  } catch (error) {
    if (isAuthError(error)) return WIKI_KEYWORD_CATALOG;
    throw error;
  }
}

/**
 * getDocCoreKeywords()가 카탈로그와 함께 합칠 "본문 단어 클릭 → 공시·IR 원문/뉴스기사
 * 모달" 대상 단어 목록. WIKI_KEYWORD_LINKS는 목업 전용 데이터라, 실제 백엔드 모드에서는
 * 빈 배열을 돌려준다 — 백엔드 122개 사전에 없는 단어가 칩으로 떴다가 클릭 시
 * GET /wiki/pages?keyword=가 빈 결과만 주는 막다른 상황을 막는다.
 * @returns {string[]}
 */
export function getKeywordLinkWords() {
  return USE_MOCK ? Object.keys(WIKI_KEYWORD_LINKS) : [];
}

/**
 * 이 키워드가 태깅된 위키 문서 목록 — WikiKeywordDocsModal용.
 * 목업 모드에서는 본문 등장 횟수를 세고(findDocsWithKeyword), 실제 모드에서는
 * GET /wiki/pages?keyword=로 실제 태깅된 페이지를 가져옵니다. 실제 모드는 본문 등장
 * 횟수를 알 수 없으므로 count는 null로 둡니다(없는 값을 지어내지 않음) —
 * WikiKeywordDocsModal이 count가 없으면 등장 횟수 문구를 생략합니다.
 * @returns {Promise<{ id: string, title: string, group: string, count: number|null }[]>}
 */
export async function fetchDocsWithKeyword(word, tree) {
  if (!word) return [];
  if (USE_MOCK) return findDocsWithKeyword(word, tree);
  try {
    const pages = await wikiApi.fetchWikiPages({ keyword: word });
    return pages.map((p) => ({
      id: p.slug,
      title: p.title,
      group: WIKI_PAGE_TYPE_LABELS[p.page_type] || p.page_type,
      count: null,
    }));
  } catch (error) {
    if (isAuthError(error)) return findDocsWithKeyword(word, tree);
    throw error;
  }
}

// 대시보드·리포트의 "관련 위키" 링크 이름을 문서 slug로 바꿉니다.
// 실제 데이터는 WIKI_ALIAS(목업 전용 이름 매핑) 대상이 아니므로, 목업 모드에서만 적용합니다.
export function resolveWikiId(nameOrId) {
  if (!USE_MOCK) return nameOrId || null;
  if (!nameOrId) return DEFAULT_WIKI_DOC;
  if (MOCK_WIKI_DOCS[nameOrId]) return nameOrId;
  return WIKI_ALIAS[nameOrId] || DEFAULT_WIKI_DOC;
}

// 위키 API 호출부.
// USE_MOCK=true면 data/mockWiki.js를 그대로 돌려주고, false면 api/wiki.js를 호출합니다.
// 백엔드 응답 shape과 화면(WikiPage.jsx/WikiCard.jsx)이 기대하는 shape이 달라서
// 아래 어댑터로 변환합니다 — services/agentApi.js와 같은 패턴입니다.

import * as wikiApi from '../api/wiki';
import { WIKI_PAGE_TYPE_LABELS } from '../api/wiki';
import { MOCK_WIKI_DOCS, MOCK_WIKI_TREE, WIKI_SOURCES, WIKI_ALIAS, DEFAULT_WIKI_DOC } from '../data/mockWiki';

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false';

// 출처 원문 정의(공시/뉴스 등) 조회 — CitationTag.jsx, AgentPage.jsx가 그대로 씁니다.
// 위키 화면 자체는 이제 실제 문서 출처(document_title/canonical_url)를 직접 쓰므로
// 이 조회를 거치지 않습니다.
// key가 없을 수 있어(백엔드 citations가 출처 종류를 안 주는 경로) null을 그대로 돌려줍니다 —
// 호출부에서 반드시 널 체크를 해야 합니다.
export function getSource(key) {
  if (!key) return null;
  return WIKI_SOURCES[key] ?? null;
}

function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}.${mm}.${dd}`;
}

// document_analysis_results/ranking.py의 신뢰도 구간(<40 낮음, <70 보통, 그 외 높음)과
// 동일한 기준으로 라벨링합니다 — 백엔드가 이미 쓰는 임계값과 어긋나지 않게.
function reliabilityLabel(score) {
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
//    heading 파싱 규칙이 정해지기 전까지는 본문 전체를 zone 하나로 보여줍니다.
//  - links(연결된 문서): wiki_pages 간 링크를 표현하는 테이블이 없습니다. 빈 배열.
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
    zones: [{ title: '본문', paragraphs: [[content.markdown]] }],
    timeline: content.versions.map((v, i) => ({
      date: formatDate(v.created_at),
      text: `버전 ${v.version_no}`,
      desc: v.change_summary || '변경 사유 없음',
      isNew: i === 0,
    })),
    sourceCount: sources.length,
    sources,
    // TODO: 위키 간 상호 링크 테이블이 생기면 채운다. 그 전까지는 빈 배열.
    links: [],
  };
}

/** WikiPage 좌측 트리 전체. */
export async function fetchWikiTree() {
  if (USE_MOCK) return MOCK_WIKI_TREE;
  const pages = await wikiApi.fetchWikiPages();
  return toTree(pages);
}

/** 문서 하나(본문 + 출처 + 변경이력). 게시된 페이지가 없으면 null. */
export async function fetchWikiDoc(slug) {
  if (USE_MOCK) return MOCK_WIKI_DOCS[slug] || MOCK_WIKI_DOCS[DEFAULT_WIKI_DOC];
  const content = await wikiApi.fetchWikiPage(slug);
  return content ? toDoc(content) : null;
}

// 대시보드·리포트의 "관련 위키" 링크 이름을 문서 slug로 바꿉니다.
// 실제 데이터는 WIKI_ALIAS(목업 전용 이름 매핑) 대상이 아니므로, 목업 모드에서만 적용합니다.
export function resolveWikiId(nameOrId) {
  if (!USE_MOCK) return nameOrId || null;
  if (!nameOrId) return DEFAULT_WIKI_DOC;
  if (MOCK_WIKI_DOCS[nameOrId]) return nameOrId;
  return WIKI_ALIAS[nameOrId] || DEFAULT_WIKI_DOC;
}

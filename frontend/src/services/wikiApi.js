// 위키 API 호출부.
// USE_MOCK=true면 data/mockWiki.js를 그대로 돌려주고, false면 api/wiki.js를 호출합니다.
//
// 백엔드(wiki_pages)와 화면이 기대하는 shape이 달라서 아래 어댑터로 변환합니다.
// 화면에 있지만 백엔드에 대응 데이터가 없는 항목은 비워 둡니다 —
// 없는 값을 지어내면 근거 없는 내용을 표시하게 되므로 그렇게 하지 않습니다.

import * as wikiApi from '../api/wiki';
import {
  MOCK_WIKI_DOCS,
  MOCK_WIKI_TREE,
  WIKI_SOURCES,
  WIKI_ALIAS,
  DEFAULT_WIKI_DOC,
  MOCK_AGENT_PANES,
  MOCK_AGENT_REPLY,
} from '../data/mockWiki';

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false';

const delay = (value) => Promise.resolve(value);

// ---------- 분류 매핑 ----------
// 2026-08-03 팀 확인: 위키의 page_type과 대시보드·리포트의 6종 카테고리는 별개 축입니다.
//  · 6종 카테고리 = "이 뉴스가 어떤 주제 영역인가" (document_analysis_results.primary_category)
//  · page_type    = "이 위키 페이지가 어떤 종류의 개체를 다루는가" (wiki_pages.page_type)
// 위키 페이지 하나가 여러 카테고리의 뉴스를 인용하므로 카테고리를 강제로 매기지 않습니다.
// ⚠ 트리 그룹 라벨을 바꾸려면 이 두 상수만 고치면 됩니다.
const PAGE_TYPE_LABEL = {
  industry: '산업',
  company: '기업',
  technology: '기술',
  issue: '이슈',
  term: '용어',
};
const PAGE_TYPE_ORDER = ['industry', 'company', 'technology', 'issue', 'term'];

// ---------- 변환 함수 ----------

function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const yy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yy}.${mm}.${dd}`;
}

// markdown 한 덩어리 → 화면의 zones[{title, body}]
// 백엔드는 본문을 통째로 주고 "개요 / 쟁점" 같은 구획을 나눠 주지 않습니다.
// `##` heading을 기준으로만 자르고, heading이 없으면 통짜 한 구획으로 둡니다.
function toZones(markdown) {
  if (!markdown) return [];
  const parts = markdown.split(/^##\s+/m);
  const head = parts.shift()?.trim();
  const zones = [];
  if (head) zones.push({ title: '개요', body: head });
  for (const part of parts) {
    const nl = part.indexOf('\n');
    if (nl === -1) {
      zones.push({ title: part.trim(), body: '' });
    } else {
      zones.push({ title: part.slice(0, nl).trim(), body: part.slice(nl + 1).trim() });
    }
  }
  return zones.length ? zones : [{ title: '개요', body: markdown }];
}

// citations[] → 화면 sources[{key, date}]
// 주의: 백엔드는 document_version_id만 주고 출처 종류(공시/뉴스)나 발행일을 알려주지 않습니다.
// key를 임의로 채우면 잘못된 출처명이 표시되므로 null로 둡니다.
// (documents 조인이 백엔드에 추가되면 여기서 실제 key/date를 채웁니다.)
function toSources(citations = []) {
  return citations.map((c, i) => ({
    key: null,
    date: '',
    no: c.citation_order ?? i + 1,
    documentVersionId: c.document_version_id,
    quotedText: c.quoted_text ?? '',
  }));
}

// 신뢰도 점수 → 라벨 밴드 (0~1 소수 대신 높음/보통/낮음)
function toConfidenceLabel(score) {
  if (typeof score !== 'number') return null;
  if (score >= 0.8) return '높음';
  if (score >= 0.5) return '보통';
  return '낮음';
}

// 백엔드 위키 페이지 → 화면 문서 하나
function toViewDoc(page) {
  const meta = [];
  const conf = toConfidenceLabel(page.confidence_score);
  if (conf) meta.push({ label: '신뢰도', value: conf });
  if (page.version_no) meta.push({ label: '버전', value: `v${page.version_no}` });
  if (page.validation_status) meta.push({ label: '검증', value: page.validation_status });

  const sources = toSources(page.sources);

  return {
    id: page.slug,
    title: page.title,
    category: PAGE_TYPE_LABEL[page.page_type] ?? page.page_type ?? '',
    updated: formatDate(page.published_at),
    meta,
    zones: toZones(page.markdown),
    sourceCount: sources.length,
    sources,
    // 위키 간 링크 테이블이 백엔드에 없습니다. 빈 배열이면 화면에서 섹션을 숨깁니다.
    links: [],
    timeline: (page.versions ?? []).map((v) => ({
      version: `v${v.version_no}`,
      date: formatDate(v.created_at),
      summary: v.change_summary ?? '',
    })),
  };
}

// ---------- 화면에서 쓰는 함수 ----------

/** 좌측 문서 트리. [{ group, items:[docId], titles:{docId: title} }] */
export async function fetchWikiTree() {
  if (USE_MOCK) return MOCK_WIKI_TREE;

  const pages = await wikiApi.fetchWikiPages({ limit: 200 });
  const byType = {};
  for (const p of pages) {
    (byType[p.page_type] ??= []).push(p);
  }
  const types = PAGE_TYPE_ORDER.filter((t) => byType[t]).concat(
    Object.keys(byType).filter((t) => !PAGE_TYPE_ORDER.includes(t))
  );
  return types.map((type) => ({
    group: PAGE_TYPE_LABEL[type] ?? type,
    items: byType[type].map((p) => p.slug),
    // 트리에 제목을 같이 실어 보냅니다 — 화면이 문서 전체를 미리 받지 않아도 되게.
    titles: Object.fromEntries(byType[type].map((p) => [p.slug, p.title])),
  }));
}

/** 문서 하나. 목업 모드에서도 비동기로 통일합니다. */
export async function fetchWikiDoc(id) {
  if (USE_MOCK) {
    return MOCK_WIKI_DOCS[id] || MOCK_WIKI_DOCS[DEFAULT_WIKI_DOC];
  }

  const page = await wikiApi.fetchWikiPage(id);
  const doc = toViewDoc(page);

  // 변경 이력은 별도 호출입니다. 실패해도 본문은 보여줍니다.
  if (!doc.timeline.length && page.page_id) {
    try {
      const versions = await wikiApi.fetchWikiVersions(page.page_id);
      doc.timeline = versions.map((v) => ({
        version: `v${v.version_no}`,
        date: formatDate(v.created_at),
        summary: v.change_summary ?? '',
      }));
    } catch {
      /* 이력 없이 진행 */
    }
  }
  return doc;
}

/** 대시보드·리포트의 "관련 위키" 링크 이름을 문서 id로 바꿉니다. */
export function resolveWikiId(nameOrId) {
  if (!nameOrId) return DEFAULT_WIKI_DOC;
  if (MOCK_WIKI_DOCS[nameOrId]) return nameOrId;
  return WIKI_ALIAS[nameOrId] || nameOrId || DEFAULT_WIKI_DOC;
}

/**
 * 출처 메타. key가 없으면(백엔드가 출처 종류를 안 줄 때) null을 돌려주므로
 * 호출부에서 반드시 널 체크를 해야 합니다.
 */
export function getSource(key) {
  if (!key) return null;
  return WIKI_SOURCES[key] ?? null;
}

// ---------- 에이전트 (services/agentApi.js로 이관됨) ----------
// 아래 두 함수는 이전 구조에서 남은 것으로, 현재 AgentPage는 agentApi를 씁니다.
// 다른 화면이 참조하고 있을 수 있어 남겨 둡니다.

export function fetchAgentPanes() {
  return delay(MOCK_AGENT_PANES);
}

export function askAgent() {
  return delay(MOCK_AGENT_REPLY);
}

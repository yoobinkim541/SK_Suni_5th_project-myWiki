// [LIVE] src/api/wiki_router.py 실제 연결 — 2026-07-30 구현 완료.
// WikiPage.jsx가 지금 쓰는 목업(TREE, SOURCES, LINKED_DOCS, TIMELINE)을 이 함수들로 교체한다.
import { apiFetch } from './client';

// wiki_pages.page_type(DB CHECK 제약 8종)만 실제로 존재하는 분류값이다.
// 2026-08-04: supply_chain/policy/market 추가 — 리포트 6종 카테고리와 1:1로 맞춰졌다
// (제품·기술→technology, 경쟁사→company, 고객·수요산업→industry, 공급망·생산→supply_chain,
//  정책·규제→policy, 시장·경영→market).
export const WIKI_PAGE_TYPE_LABELS = {
  industry: '산업',
  company: '기업',
  technology: '제품·기술',
  supply_chain: '공급망·생산',
  policy: '정책·규제',
  market: '시장·경영',
  issue: '이슈',
  term: '용어',
};

/**
 * WikiPage 좌측 트리 목록. keyword를 주면 그 키워드가 태깅된 페이지만 돌아온다
 * (연동 키워드 바에서 칩을 눌렀을 때 쓴다 — WikiKeywordDocsModal).
 * @returns {Promise<{id, slug, title, page_type, status, parent_page_id, published_at}[]>}
 * 트리로 그룹핑하려면 프론트에서 page_type 기준으로 묶는다:
 *   const pages = await fetchWikiPages();
 *   const groups = Object.groupBy(pages, p => p.page_type); // 또는 reduce로 동일하게
 */
export function fetchWikiPages({ pageType, q, keyword, limit = 50, offset = 0 } = {}) {
  const params = new URLSearchParams();
  if (pageType) params.set('page_type', pageType);
  if (q) params.set('q', q);
  if (keyword) params.set('keyword', keyword);
  params.set('limit', String(limit));
  params.set('offset', String(offset));
  return apiFetch(`/wiki/pages?${params}`);
}

/**
 * 연동 키워드 카탈로그 전체 — 실사용 여부와 무관한 고정 사전(word, category).
 * WikiKeywordBar가 본문 키워드 하이라이트·칩 목록을 그릴 때 쓴다.
 * @returns {Promise<{word: string, category: string}[]>}
 */
export function fetchWikiKeywordCatalog() {
  return apiFetch('/wiki/keywords');
}

/**
 * WikiPage 본문(.doc 영역) — 게시·승인·검증된 버전만 반환된다(없으면 null).
 * @returns {Promise<{
 *   page_id, slug, title, page_type, published_at, version_id, version_no,
 *   markdown, change_summary, confidence_score, validation_status, review_status,
 *   generated_by, generator_model, created_at,
 *   sources: {document_version_id, citation_order, claim_text, support_type, source_start_line, source_end_line}[],
 *   versions: {id, version_no, change_summary, created_at}[],
 *   related_pages: {page_id, slug, title, page_type, shared_source_count}[],
 * } | null>}
 *
 * related_pages(연결된 문서): 별도 관계 테이블 없이, 같은 원문(document_version_id)을
 * 근거로 인용하는 다른 위키를 조회 시점에 계산해서 공유 건수 내림차순 상위 5개만 준다.
 *
 * 주의(아직 없는 항목 — 화면 목업엔 있지만 스키마/API에 대응 없음):
 *  - 근거 출처 라벨("공시 원문 · 07.21" 같은 것): sources[]는 document_version_id만 줌.
 *    문서 제목·날짜를 붙이려면 documents/document_versions 조인이 필요 — collectors 파트 확인 필요.
 *  - markdown은 raw 텍스트 하나. 화면의 "개요/쟁점" 같은 zone 나누기는 프론트에서
 *    마크다운 렌더러 + heading 파싱으로 처리하거나, 작성 규칙(## 개요, ## 쟁점)을 정해야 함.
 */
export function fetchWikiPage(slug) {
  return apiFetch(`/wiki/pages/${encodeURIComponent(slug)}`);
}

/**
 * WikiPage "변경 이력" 타임라인.
 * @returns {Promise<{id, version_no, change_summary, created_at}[]>}
 * TIMELINE 목업의 isNew 플래그는 없음 — versions[0](최신)을 프론트에서 isNew로 표시하면 된다.
 */
export function fetchWikiVersions(pageId) {
  return apiFetch(`/wiki/pages/${encodeURIComponent(pageId)}/versions`);
}

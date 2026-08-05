// [LIVE] GET /categories/stats — src/api/category_router.py / src/categories/service.py
//
// 2026-08-05 정정 — 이 파일에 있던 두 서술이 모두 사실과 달랐다.
//   "page_type 5종"                        -> 실제 8종
//   "카테고리 현황 화면은 메모리/파운드리/장비" -> 실제로는 아래 6종
// data/mockCategory.js는 처음부터 6종을 쓰고 있었다. '파운드리'는 카테고리가 아니라
// mockOnboarding.js의 키워드 사전과 목업 본문에만 등장하는 단어다.
//
// 확정된 분류 (팀 확인 완료, 2026-08-05):
//   제품·기술 / 경쟁사 / 고객·수요산업 / 공급망·생산 / 정책·규제 / 시장·경영
//
// 이 6종은 세 곳이 이미 같은 값을 쓴다:
//   document_analysis_results.primary_category  (문서 438건에 채워져 있음)
//   data/mockOnboarding.js INTEREST_KEYWORD_GROUPS  (선호조사 키워드 사전)
//   data/mockCategory.js MOCK_CATEGORIES            (이 화면의 목업)
//
// 백엔드는 primary_category를 집계한다 — 스키마 변경도 분류 로직 신설도 없었다.
// 필드별 산출: count=분류 건수 / top_issue=importance_score 최상위 문서 제목 /
// tags=제목에서 키워드 사전 매칭 상위 3개 / level=reliability_score 평균
import { apiFetch } from './client';

/**
 * 카테고리 현황 집계 (최근 7일). 백엔드는 snake_case로 내려주고,
 * CategoryCard가 기대하는 camelCase 변환은 services/categoryApi.js가 한다.
 *
 * level은 'high' | 'mid' | 'low' 세 값만 온다 — 백엔드 스키마에서 Literal로 막아뒀다.
 * id는 'product-tech' 같은 슬러그이고, CategoryKeywordChart가 원그래프 데이터를
 * 찾는 키로도 쓰므로 프론트에서 바꾸면 안 된다.
 *
 * @returns {Promise<{
 *   total_documents: number,
 *   categories: {id: string, name: string, count: number,
 *                top_issue: string, tags: string[], level: 'high'|'mid'|'low'}[]
 * }>}
 */
export function fetchCategoryStats() {
  return apiFetch('/categories/stats');
}

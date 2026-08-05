// [백엔드 미구현] 분류 체계는 확정됐고, 남은 건 백엔드 엔드포인트 하나뿐이다.
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
// 즉 프론트는 손댈 게 없고, primary_category를 집계하는 API만 만들면 실연동된다.
//
// 필요한 엔드포인트: GET /categories/stats
//   집계원  document_analysis_results.primary_category (+ documents 조인)
//   스키마 변경 불필요. 분류 로직 신설도 불필요 — 이미 분류돼 있다.
import { apiFetch } from './client';

/**
 * 카테고리 현황 집계. MOCK_CATEGORIES와 같은 shape로 돌려받아야 화면이 그대로 동작한다.
 * @returns {Promise<{id: string, name: string, count: number,
 *                    topIssue: string, tags: string[], level: string}[]>}
 */
export function fetchCategoryStats() {
  return apiFetch('/categories/stats'); // 백엔드 구현 전까지 호출 시 404
}

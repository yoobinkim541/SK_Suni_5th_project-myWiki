// [설계 미정 · 백엔드 불가] CategoryPage.jsx의 카테고리(메모리/파운드리/장비)는
// DB 어느 테이블에도 대응하는 컬럼이 없다. wiki_pages.page_type(5종: industry/company/
// technology/issue/term)과도 다른 분류체계이고, WikiPage.jsx 트리 그룹(제품·기술/경쟁사/...)
// 과도 다르다 — 3곳(카테고리 현황/위키 트리/리포트 분류)이 서로 다른 카테고리 이름을 쓰고 있다.
//
// 이 함수를 실제로 쓰려면 먼저 팀에서:
//   1) 카테고리 분류 기준을 하나로 통일할지(예: page_type 5종 재사용) 정하고,
//   2) 통일 안 한다면 어느 테이블에 카테고리 컬럼/테이블을 추가할지 정해야 함.
// 그 전까지는 이 함수를 호출해도 백엔드가 없어 항상 실패한다 — 자리만 잡아둔 상태.
import { apiFetch } from './client';

/** @returns {Promise<{name: string, count: number, percent: number}[]>} */
export function fetchCategoryStats() {
  return apiFetch('/categories/stats'); // 분류 기준 확정 후 백엔드 담당 정해서 구현
}

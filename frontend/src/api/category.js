// [설계 미정 · 백엔드 불가] CategoryPage.jsx의 카테고리(메모리/파운드리/장비)는
// DB 어느 테이블에도 대응하는 컬럼이 없다. 자리만 잡아둔 상태이고, 호출하면 백엔드가
// 없어 항상 실패한다.
//
// 2026-08-05 재확인 — 이 주석에 있던 "page_type 5종"은 낡은 정보였다. 실제 현황:
//   analysis 분류        6종  제품·기술 / 경쟁사 / 고객·수요산업 / 공급망·생산 / 정책·규제 / 시장·경영
//   wiki_pages.page_type 8종  industry / company / technology / supply_chain /
//                             policy / market / issue / term  (api/wiki.js WIKI_PAGE_TYPE_LABELS)
//   카테고리 현황 화면    3종  메모리 / 파운드리 / 장비
//
// 즉 "3곳이 제각각"이 아니라 앞의 두 곳은 6개가 서로 대응하고, **이 화면의 3종만
// 동떨어져 있다.** 실질 안건은 "카테고리 현황을 어디에 맞출 것인가" 하나다.
//
// 팀 결정이 필요한 선택지:
//   ① page_type 8종 재사용 — 백엔드 API 1개만 추가하면 된다. 스키마 변경 없음 (가장 작다)
//   ② 메모리/파운드리/장비 유지 — 분류 컬럼·테이블 신설(SQL) + 분류 로직 신설이 따라온다
//   ③ 화면 보류 — MVP 범위에서 빼고 목업 유지
// 결정 전까지 services/categoryApi.js와 data/mockCategory.js를 건드리지 않는다.
import { apiFetch } from './client';

/** @returns {Promise<{name: string, count: number, percent: number}[]>} */
export function fetchCategoryStats() {
  return apiFetch('/categories/stats'); // 분류 기준 확정 후 백엔드 담당 정해서 구현
}

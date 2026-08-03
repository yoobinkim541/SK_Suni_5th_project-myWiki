// 카테고리 현황 API 호출부. 지금은 data/mockCategory.js를 그대로 돌려줍니다.

import { MOCK_CATEGORIES, MOCK_SUMMARY } from '../data/mockCategory';
import { MOCK_NEWS } from '../data/mockDashboard';

const delay = (value) => Promise.resolve(value);

export function fetchCategories() {
  return delay(MOCK_CATEGORIES);
}

export function fetchCategorySummary() {
  return delay(MOCK_SUMMARY);
}

// 카드의 "N건"과 관련 뉴스 모달이 항상 같은 소스를 보게 하려고 뉴스에서 필터링합니다.
export function fetchNewsByCategory(categoryName) {
  return delay(MOCK_NEWS.filter((n) => n.category === categoryName));
}

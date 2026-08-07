// Date -> '2026.08.06 목요일'
//
// 대시보드와 카테고리 현황 헤더가 같은 자리에 같은 형식으로 오늘 날짜를 씁니다.
// 두 화면이 각자 문자열을 만들면 한쪽만 고쳐져 서로 다른 날짜가 뜨기 쉬워서
// 여기 한 곳에 둡니다.
//
// relativeTime.js와 같은 이유로 백엔드가 아니라 화면에서 만듭니다 — 렌더 시점의
// 관심사라, 응답이 캐시되거나 탭이 자정을 넘겨 열려 있으면 서버가 만든 문자열은
// 틀린 채로 굳습니다.

const WEEKDAYS = ['일요일', '월요일', '화요일', '수요일', '목요일', '금요일', '토요일'];

const pad = (n) => String(n).padStart(2, '0');

/**
 * @param {Date} [date]  기본값은 지금. 테스트에서 시각을 고정할 때만 넘깁니다
 * @returns {string} '2026.08.06 목요일'. 값이 이상하면 빈 문자열
 */
export function formatKoreanDate(date = new Date()) {
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) return '';
  return `${date.getFullYear()}.${pad(date.getMonth() + 1)}.${pad(date.getDate())} ${
    WEEKDAYS[date.getDay()]
  }`;
}

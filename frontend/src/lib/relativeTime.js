// ISO 시각 -> '3분 전' / '2시간 전' / '3일 전'
//
// 백엔드가 아니라 여기서 만드는 이유: 상대시각은 렌더 시점의 관심사입니다.
// 백엔드가 '1시간 전'을 만들어 보내면 응답이 캐시되거나 탭이 오래 열려 있을 때
// 그 문자열이 틀린 채로 굳습니다. 백엔드는 published_at을 ISO로 주고,
// 화면이 매번 지금 기준으로 계산합니다.

const MINUTE = 60 * 1000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/**
 * @param {string|null|undefined} iso  ISO 8601 문자열
 * @param {Date} [now]  테스트에서 시각을 고정할 때만 넘깁니다
 * @returns {string} 표시용 문자열. 값이 없거나 파싱이 안 되면 빈 문자열
 */
export function formatRelative(iso, now = new Date()) {
  if (!iso) return '';
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return '';

  const diff = now.getTime() - then.getTime();
  // 발행 시각이 미래로 잡힌 문서가 간혹 있습니다(타임존 오기재 등). '방금'으로 뭉갭니다.
  if (diff < MINUTE) return '방금';
  if (diff < HOUR) return `${Math.floor(diff / MINUTE)}분 전`;
  if (diff < DAY) return `${Math.floor(diff / HOUR)}시간 전`;
  if (diff < 7 * DAY) return `${Math.floor(diff / DAY)}일 전`;

  // 일주일이 넘으면 상대시각이 오히려 안 읽힙니다. 날짜로 보여줍니다.
  return `${then.getFullYear()}.${String(then.getMonth() + 1).padStart(2, '0')}.${String(
    then.getDate()
  ).padStart(2, '0')}`;
}

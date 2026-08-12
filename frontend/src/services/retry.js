// 조회 재시도 — 대시보드·카테고리 공용.
//
// 왜 필요한가, 그리고 무엇을 못 하는가 (2026-08-12 실측)
//
// 백엔드가 Supabase에 붙을 때 HTTP/2 연결이 끊겨 500이 튄다.
//   RemoteProtocolError: <ConnectionTerminated error_code:1, last_stream_id:463>
// 한 연결에 스트림이 쌓이면 Supabase 앞단이 GOAWAY로 정리하는데, 그 순간 진행 중이던
// 요청이 죽는다.
//
// ⚠ 원인은 요청 '횟수'가 아니라 '동시성'이다. 인증을 우회해 실제 DB 경로로 잰 값:
//     동시 1개(순차) 실패  0%      동시 3개 실패 42%
//     동시 2개      실패 17%      동시 6개 실패 58%
//   순차로 부르면 실패가 아예 없다.
//
// ⚠ 그래서 이 재시도는 해결책이 아니라 보험이다. 6개를 동시에 쏘면서 재시도까지
//   걸어봤더니 실패율이 33% -> 39%로 오히려 나빠졌다 — 재시도가 동시성을 더 키우기
//   때문이다. **진짜 해결은 (1) 순차 호출 유지와 (2) 백엔드의 Supabase 클라이언트
//   수정이다**(src/analysis/repository.py get_supabase — 요청마다 create_client를
//   새로 부르고 HTTP/2 연결이 재사용된다).
//
// 이 파일이 실제로 건지는 경우는 좁다. 대시보드는 이미 순차로 부르지만 AppShell의
// profile/members/workspace 조회가 같은 시점에 나가서 동시성이 2~4로 뜬다. 그때
// 튀는 단발성 실패를 600ms 뒤 재시도로 건진다.
//
// 백엔드가 고쳐지면 MAX_ATTEMPTS를 1로 되돌려도 된다.
//
// 재시도해도 소용없는 것은 즉시 포기한다. 401은 게스트이거나 세션 만료라 몇 번을
// 더 불러도 같고, 각 서비스가 그때 목업으로 대체하는 경로를 갖고 있어서 빨리
// 실패하는 편이 화면이 빨리 뜬다.

const MAX_ATTEMPTS = 3;

// 지수 백오프. 끊긴 연결은 새로 붙으면 대체로 바로 성공해서 첫 대기는 짧게 둔다.
const BACKOFF_MS = [600, 1500];

// 이 상태 코드는 다시 불러도 결과가 같다 — 인증·권한·없는 리소스.
const NO_RETRY_STATUS = new Set([400, 401, 403, 404, 422]);

function shouldRetry(error) {
  // ApiError가 아니면 네트워크 계층 실패(TypeError: Failed to fetch)다. 재시도 대상.
  if (typeof error?.status !== 'number') return true;
  return !NO_RETRY_STATUS.has(error.status);
}

/**
 * fn을 최대 3회까지 시도한다. 마지막 시도까지 실패하면 마지막 에러를 그대로 던진다.
 *
 * 에러를 삼키지 않는 것이 중요하다 — 호출부가 401을 보고 목업으로 대체하거나
 * 화면에 사유를 띄우기 때문에, 여기서 뭉개면 그 분기가 죽는다.
 */
export async function withRetry(fn, { label = '' } = {}) {
  let lastError;
  for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt += 1) {
    try {
      return await fn();
    } catch (error) {
      lastError = error;
      if (!shouldRetry(error) || attempt === MAX_ATTEMPTS - 1) break;
      // 몇 번째 시도에서 살아났는지 콘솔에 남긴다. 백엔드 연결 문제가 계속되는지
      // 판단하는 유일한 단서라 조용히 넘기지 않는다.
      console.warn(
        `[retry] ${label || 'request'} 실패 (${attempt + 1}/${MAX_ATTEMPTS}) — 재시도합니다:`,
        error?.message ?? error
      );
      await new Promise((resolve) => setTimeout(resolve, BACKOFF_MS[attempt]));
    }
  }
  throw lastError;
}

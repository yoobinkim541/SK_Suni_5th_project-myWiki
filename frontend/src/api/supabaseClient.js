// Supabase Auth 전용 클라이언트 — 세션/토큰 관리만 여기서 하고,
// 실제 애플리케이션 테이블(wiki_pages 등)은 프론트에서 절대 직접 쿼리하지 않는다.
// (docs/architecture/mywiki-erd.md 6절)
//
// 필요 env: VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY (.env.local)
//
// 키가 아직 없는 상태(목업 모드)에서도 앱이 뜨도록, 클라이언트를 처음 쓸 때
// 만듭니다. import 시점에 createClient를 부르면 빈 값일 때 앱 전체가 죽습니다.
import { createClient } from '@supabase/supabase-js';

const url = import.meta.env.VITE_SUPABASE_URL;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

let client = null;

function getClient() {
  if (!url || !anonKey) {
    throw new Error(
      'Supabase 환경변수가 없습니다. .env.local에 VITE_SUPABASE_URL과 VITE_SUPABASE_ANON_KEY를 설정하세요.'
    );
  }
  // detectSessionInUrl: true가 기본값이라 원래도 켜져 있지만(supabase-js v2), OAuth 콜백
  // (구글 로그인 등)이 돌아왔을 때 주소창의 access_token/refresh_token 해시를 자동으로
  // 파싱·세션 저장하는 핵심 옵션이라 향후 라이브러리 기본값이 바뀌어도 깨지지 않게 명시한다.
  if (!client) client = createClient(url, anonKey, { auth: { detectSessionInUrl: true } });
  return client;
}

export const supabase = {
  auth: {
    getSession: (...args) => getClient().auth.getSession(...args),
    signInWithOAuth: (...args) => getClient().auth.signInWithOAuth(...args),
    signOut: (...args) => getClient().auth.signOut(...args),
    onAuthStateChange: (...args) => getClient().auth.onAuthStateChange(...args),
  },
};

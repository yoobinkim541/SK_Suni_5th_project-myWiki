// [LIVE] Supabase Auth 자체는 바로 연결 가능 — src/api/auth.py가 이 세션의 JWT를 검증한다.
// LoginScreen.jsx의 handleLogin 주석("실제 연동 시: supabase.auth.signInWithOAuth")을 그대로 구현.
import { supabase } from './supabaseClient';

/**
 * provider: 'google' | 'github' | 'custom:naver'
 *   — EntryFlow.jsx · ProfilePanel.jsx의 OAUTH_PROVIDERS.key와 맞춤.
 *     'custom:naver'는 Supabase Custom Providers(OIDC)에 등록한 Provider Identifier다.
 *
 * redirectTo를 도메인 하드코딩 대신 window.location.origin으로 두면 로컬(5173)과 배포
 * 양쪽에서 그대로 동작한다. 콜백은 토큰을 URL 해시로 실어 오고 supabaseClient.js의
 * detectSessionInUrl이 이를 세션으로 바꾸므로, 전용 콜백 라우트 없이 루트로 돌려보내면 된다.
 * (단 Supabase Authentication → URL Configuration → Redirect URLs 에 해당 origin이 등록돼 있어야 한다)
 */
export function signInWithProvider(provider) {
  return supabase.auth.signInWithOAuth({
    provider,
    options: { redirectTo: `${window.location.origin}/` },
  });
}

export function signOut() {
  return supabase.auth.signOut();
}

export async function getCurrentSession() {
  const { data } = await supabase.auth.getSession();
  return data.session;
}

// [설계 필요] SurveyScreen.jsx는 지금 선호도(keyword/role/age)를 localStorage에만 저장한다.
// "계정에 저장됩니다"라는 화면 문구대로 서버에 남기려면 profiles 테이블에
// 저장할 컬럼이 없다(현재 profiles: id, display_name, department, created_at, updated_at).
// prefs jsonb 컬럼 추가 여부는 스키마 변경이라 팀 확인 후 진행 — 그 전까지는
// SurveyScreen의 localStorage 저장 방식을 그대로 두는 게 맞다(임의로 만들지 않음).

// OAuth 콜백 직후 세션인지(=방금 가입한 계정인지) 판단한다.
// EntryFlow 진입 시점에 선호조사(3단계)를 보여줄지, 곧장 대시보드로 보낼지 가르는 데 쓴다.
// 판단할 정보가 없으면 신규로 본다(최악의 경우 이미 온보딩한 사용자가 한 번 더 보는 정도라 안전).
const NEW_ACCOUNT_WINDOW_MS = 5 * 60 * 1000; // 5분

export function isNewAccount(session) {
  const createdAt = session?.user?.created_at;
  const lastSignInAt = session?.user?.last_sign_in_at;
  if (!createdAt || !lastSignInAt) return true;
  const diffMs = Math.abs(new Date(lastSignInAt).getTime() - new Date(createdAt).getTime());
  return diffMs <= NEW_ACCOUNT_WINDOW_MS;
}

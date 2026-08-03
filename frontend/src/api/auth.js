// [LIVE] Supabase Auth 자체는 바로 연결 가능 — src/api/auth.py가 이 세션의 JWT를 검증한다.
// LoginScreen.jsx의 handleLogin 주석("실제 연동 시: supabase.auth.signInWithOAuth")을 그대로 구현.
import { supabase } from './supabaseClient';

/** provider: 'google' | 'github' | 'kakao' — LoginScreen.jsx OAUTH_PROVIDERS.key와 맞춤 */
export function signInWithProvider(provider) {
  return supabase.auth.signInWithOAuth({ provider });
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

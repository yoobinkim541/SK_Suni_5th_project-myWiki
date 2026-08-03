// Supabase Auth 전용 클라이언트 — 세션/토큰 관리만 여기서 하고,
// 실제 애플리케이션 테이블(wiki_pages 등)은 프론트에서 절대 직접 쿼리하지 않는다.
// (docs/architecture/mywiki-erd.md 6절: "프론트엔드는 애플리케이션 테이블에 직접 접근하지 않는다")
//
// 필요 패키지: npm i @supabase/supabase-js
// 필요 env: VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY (.env.local)
import { createClient } from '@supabase/supabase-js';

const url = import.meta.env.VITE_SUPABASE_URL;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

export const supabase = createClient(url, anonKey);

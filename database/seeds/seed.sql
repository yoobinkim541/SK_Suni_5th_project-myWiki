-- ============================================================
-- myWiki 시드 데이터 (MVP 초기 실행용, 1회만 실행)
-- 실행 위치: Supabase SQL Editor (프로젝트 uhzjshqmnlahhvqzygkp)
--
-- 실행 후 workspaces.id 를 복사해 .env 의 WORKSPACE_ID 에 등록한다.
-- SERVICE_ROLE_KEY 를 사용하므로 RLS 우회 상태로 직접 삽입된다.
-- ============================================================

-- 1. workspace 생성
INSERT INTO workspaces (name, slug)
VALUES ('myWiki', 'mywiki')
ON CONFLICT DO NOTHING;

-- 2. 삽입된 id 확인 (배치 .env 에 등록할 값)
SELECT id, name, slug FROM workspaces WHERE slug = 'mywiki';

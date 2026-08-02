-- ============================================================
-- chat_sessions.visibility 추가
-- "내 에이전트"(private)와 "팀 공유 에이전트"(team, workspace 멤버 전원 조회 가능)를
-- 구분하기 위한 컬럼. 2026-08-02
-- ============================================================

ALTER TABLE public.chat_sessions
    ADD COLUMN IF NOT EXISTS visibility VARCHAR(10) NOT NULL DEFAULT 'private';

ALTER TABLE public.chat_sessions
    ADD CONSTRAINT IF NOT EXISTS chat_sessions_visibility_check
    CHECK (visibility IN ('private', 'team'));

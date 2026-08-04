-- 2026-08-04 설계 변경으로 "워크스페이스당 팀 세션 1개" 가정이 폐기됐다
-- (docs/superpowers/specs/2026-08-04-agent-session-sharing-design.md).
-- 팀 세션은 이제 여러 개일 수 있고, 공유할 때마다 사용자가 대상을 고르거나 새로 만든다
-- (ShareToTeamRequest.target_session_id). 20260803010000에서 걸어둔 유니크 인덱스가
-- 남아있으면 두 번째 팀 세션 생성 시 duplicate key로 500이 나므로 지운다.

DROP INDEX IF EXISTS uq_chat_sessions_team_per_workspace;

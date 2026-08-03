-- get_or_create_team_session()이 "팀 공유 세션은 워크스페이스당 하나"를 가정하지만
-- 동시 요청 시 둘 다 기존 세션을 못 찾고 각자 새로 만들 수 있다(레이스 컨디션).
-- 부분 유니크 인덱스로 DB 레벨에서 막는다.

DROP INDEX IF EXISTS uq_chat_sessions_team_per_workspace;

CREATE UNIQUE INDEX uq_chat_sessions_team_per_workspace
ON public.chat_sessions (workspace_id)
WHERE visibility = 'team';

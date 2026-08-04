CREATE TABLE IF NOT EXISTS public.chat_session_participants (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES public.chat_sessions(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

ALTER TABLE public.chat_session_participants
DROP CONSTRAINT IF EXISTS uq_chat_session_participants_session_user;

ALTER TABLE public.chat_session_participants
ADD CONSTRAINT uq_chat_session_participants_session_user UNIQUE (session_id, user_id);

-- 이 테이블이 생기기 전에는 team 세션을 워크스페이스 멤버 누구나 볼 수 있었다.
-- 참여자 기반 접근 제어로 바뀌면서 기존 team 세션이 갑자기 아무에게도 안 보이지
-- 않도록, 최소한 생성자는 계속 볼 수 있도록 백필한다.
INSERT INTO public.chat_session_participants (session_id, user_id)
SELECT id, user_id FROM public.chat_sessions WHERE visibility = 'team'
ON CONFLICT (session_id, user_id) DO NOTHING;

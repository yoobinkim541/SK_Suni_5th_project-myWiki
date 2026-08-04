-- 팀 공유 대화에서 각 질문을 누가 보냈는지 표시하기 위한 작성자 컬럼.
-- 과거 행은 작성자 불명으로 남긴다(nullable).
ALTER TABLE public.chat_messages
  ADD COLUMN user_id uuid REFERENCES public.profiles(id);

-- 프로필 사진 전용. profiles.avatar_object_key는 avatars 버킷 안의 object_key만
-- 저장한다(예: "{user_id}/avatar.jpg") — 다른 버킷들과 동일하게 프론트는 이 값을
-- 직접 못 보고, 백엔드가 GET /profile/avatar에서 바이트를 스트리밍한다.

ALTER TABLE public.profiles
  ADD COLUMN IF NOT EXISTS avatar_object_key text;

INSERT INTO storage.buckets (id, name, public)
VALUES ('avatars', 'avatars', false)
ON CONFLICT (id) DO NOTHING;

-- 다른 버킷들은 workspace_id가 경로 첫 세그먼트라 is_workspace_member()로 걸렀지만,
-- 아바타는 워크스페이스 공유 콘텐츠가 아니라 개인 소유물이라 경로 첫 세그먼트를
-- user_id로 두고 auth.uid() 본인 소유만 허용한다.
DROP POLICY IF EXISTS avatars_bucket_select_own ON storage.objects;
CREATE POLICY avatars_bucket_select_own ON storage.objects FOR SELECT
  TO authenticated
  USING (
    bucket_id = 'avatars'
    AND (storage.foldername(name))[1] = auth.uid()::text
  );

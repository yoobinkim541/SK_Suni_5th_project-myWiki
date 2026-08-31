-- 프로필 아바타 Storage 객체 경로를 저장한다.
-- 기존 백엔드의 멤버/팀 조회 및 아바타 API와 신규 DB 스키마를 맞춘다.
ALTER TABLE public.profiles
  ADD COLUMN IF NOT EXISTS avatar_object_key text;


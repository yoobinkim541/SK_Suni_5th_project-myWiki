-- 리포트 산출물 전용 Storage 버킷.
-- 기존 버킷(raw/processed/wiki)과 같은 비공개 정책이며, object_key 는 다른 파트와 동일하게
-- 버킷명을 접두사로 포함한다: reports/{workspace_id}/{report_id}/{artifact_type}/v{n}.md

INSERT INTO storage.buckets (id, name, public)
VALUES ('reports', 'reports', false)
ON CONFLICT (id) DO NOTHING;

-- 워크스페이스 멤버는 자기 워크스페이스 경로의 객체만 읽을 수 있다.
-- 경로 첫 세그먼트가 workspace_id 라는 규칙에 의존한다.
DROP POLICY IF EXISTS reports_bucket_select_member ON storage.objects;
CREATE POLICY reports_bucket_select_member ON storage.objects FOR SELECT
  TO authenticated
  USING (
    bucket_id = 'reports'
    AND is_workspace_member(((storage.foldername(name))[1])::uuid)
  );

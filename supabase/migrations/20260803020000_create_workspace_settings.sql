CREATE TABLE IF NOT EXISTS public.workspace_settings (
  workspace_id uuid PRIMARY KEY REFERENCES public.workspaces(id) ON DELETE CASCADE,
  wiki_update_cycle_minutes int NOT NULL DEFAULT 360,
  chat_retention_days int,
  last_wiki_refresh_at timestamptz,
  updated_by uuid REFERENCES public.profiles(id),
  updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.workspace_settings
DROP CONSTRAINT IF EXISTS workspace_settings_wiki_update_cycle_minutes_check;

ALTER TABLE public.workspace_settings
ADD CONSTRAINT workspace_settings_wiki_update_cycle_minutes_check
CHECK (wiki_update_cycle_minutes IN (30, 60, 180, 360, 720, 1440));

ALTER TABLE public.workspace_settings
DROP CONSTRAINT IF EXISTS workspace_settings_chat_retention_days_check;

ALTER TABLE public.workspace_settings
ADD CONSTRAINT workspace_settings_chat_retention_days_check
CHECK (chat_retention_days IN (7, 30, 90) OR chat_retention_days IS NULL);

DROP TRIGGER IF EXISTS trg_workspace_settings_updated_at ON public.workspace_settings;

CREATE TRIGGER trg_workspace_settings_updated_at
BEFORE UPDATE ON public.workspace_settings
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.workspace_settings ENABLE ROW LEVEL SECURITY;

-- 팀 공유 설정 조회 — 배치 스크립트는 SERVICE_ROLE_KEY(RLS 우회)로 돌고,
-- 여기서는 API를 통한 일반 사용자 조회만 대상으로 한다. 다른 workspace_id 스코프
-- 테이블(예: wiki_pages)과 동일한 "같은 workspace 소속이면 읽기 가능" 정책.
DROP POLICY IF EXISTS workspace_settings_select ON public.workspace_settings;

CREATE POLICY workspace_settings_select ON public.workspace_settings
FOR SELECT
USING (
  EXISTS (
    SELECT 1 FROM public.workspace_members
    WHERE workspace_members.workspace_id = workspace_settings.workspace_id
      AND workspace_members.user_id = auth.uid()
  )
);

-- 기존 팀 워크스페이스에 초기 행 삽입(mock 기본값과 맞춤: 대화 보관 90일).
INSERT INTO public.workspace_settings (workspace_id, wiki_update_cycle_minutes, chat_retention_days)
SELECT id, 360, 90 FROM public.workspaces WHERE slug = 'mywiki'
ON CONFLICT (workspace_id) DO NOTHING;

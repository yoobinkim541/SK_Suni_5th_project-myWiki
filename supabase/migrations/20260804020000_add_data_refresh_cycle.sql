-- 수집·분석 주기를 wiki_update_cycle_minutes와 같은 방식(주기 길이)으로 사용자가
-- 설정할 수 있게 한다. 지금까지 scheduled-collection.yml/scheduled-analysis.yml은
-- 고정 2시간 cron이었다 — 이 컬럼을 실제로 게이트(scripts/refresh_data_scheduled.py)가
-- 참고하게 된다.
--
-- 선택지는 wiki_update_cycle_minutes(30/60/180/360/720/1440)에 120분(2시간)을 추가한
-- 7종 — 지금 실제 수집 주기(2시간)를 정확히 표현하려고 추가함. 기본값도 120.

ALTER TABLE public.workspace_settings
ADD COLUMN IF NOT EXISTS data_refresh_cycle_minutes int NOT NULL DEFAULT 120;

ALTER TABLE public.workspace_settings
ADD COLUMN IF NOT EXISTS last_data_refresh_at timestamptz;

ALTER TABLE public.workspace_settings
DROP CONSTRAINT IF EXISTS workspace_settings_data_refresh_cycle_minutes_check;

ALTER TABLE public.workspace_settings
ADD CONSTRAINT workspace_settings_data_refresh_cycle_minutes_check
CHECK (data_refresh_cycle_minutes IN (30, 60, 120, 180, 360, 720, 1440));

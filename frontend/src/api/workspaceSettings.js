// [LIVE] src/api/settings_router.py 실제 연결.
// 워크스페이스 설정(Wiki 업데이트 주기, 대화 보관 기간) 조회·수정 — workspace_settings 테이블.
// 다크모드/글자크기처럼 이 브라우저에만 저장되는 값은 api/settings.js(localStorage)를
// 그대로 쓴다. 이 파일은 서버에 저장되는 워크스페이스 공용 설정만 다룬다.
import { apiFetch } from './client';

/**
 * @returns {Promise<{
 *   workspace_id, wiki_update_cycle_minutes: 30|60|180|360|720|1440,
 *   chat_retention_days: number|null, last_wiki_refresh_at: string|null, updated_at: string,
 * }>}
 */
export function fetchWorkspaceSettings() {
  return apiFetch('/settings');
}

/**
 * 넘기지 않은 필드는 그대로 둔다. chat_retention_days에 null을 명시적으로 넘기면
 * "영구 보관"으로 저장된다(settings_router.py가 필드 존재 여부로 구분).
 * @param {{wiki_update_cycle_minutes?: 30|60|180|360|720|1440, chat_retention_days?: number|null}} patch
 */
export function updateWorkspaceSettings(patch) {
  return apiFetch('/settings', { method: 'PATCH', body: patch });
}

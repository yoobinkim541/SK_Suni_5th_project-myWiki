// [LIVE] src/api/main.py의 프로필 편집 엔드포인트 연결 — 설정 화면 "계정" 섹션의
// 이름/프로필 사진 편집용.
import { apiFetch, apiFetchBlob, apiFetchUpload } from './client';

/**
 * 내 프로필(이름 + 아바타 존재 여부).
 * @returns {Promise<{id: string, display_name: string|null, has_avatar: boolean}>}
 */
export function fetchProfile() {
  return apiFetch('/profile');
}

/**
 * 이름을 바꾼다.
 * @returns {Promise<{id: string, display_name: string|null, has_avatar: boolean}>}
 */
export function updateProfile(displayName) {
  return apiFetch('/profile', { method: 'PATCH', body: { display_name: displayName } });
}

/**
 * 프로필 사진 바이트를 인증 헤더와 함께 내려받는다(비공개 버킷이라 <img src>로 직접
 * 못 부른다 — apiFetchBlob으로 받아 Object URL을 만들어 써야 한다).
 * @returns {Promise<{blob: Blob, contentType: string}>}
 */
export function fetchAvatarBlob() {
  return apiFetchBlob('/profile/avatar');
}

/**
 * 프로필 사진을 업로드한다(jpeg/png/webp/gif, 최대 3MB — 서버가 검증).
 * @returns {Promise<{id: string, display_name: string|null, has_avatar: boolean}>}
 */
export function uploadAvatar(file) {
  const formData = new FormData();
  formData.append('file', file);
  return apiFetchUpload('/profile/avatar', formData);
}

/** 프로필 사진을 지운다. */
export function deleteAvatar() {
  return apiFetch('/profile/avatar', { method: 'DELETE' });
}

/**
 * 다른 워크스페이스 멤버의 프로필 사진 바이트 — 상단바·팀 로스터가 각 멤버의
 * has_avatar가 true일 때만 부른다(false면 조회할 필요가 없다 — 항상 404이므로).
 * @returns {Promise<{blob: Blob, contentType: string}>}
 */
export function fetchMemberAvatarBlob(userId) {
  return apiFetchBlob(`/workspace/members/${userId}/avatar`);
}

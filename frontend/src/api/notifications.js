// [LIVE] src/api/notifications_router.py 실제 연결.
// 위키 발행 브라우저 푸시 알림 — 구독 저장/해지만 다룬다(발송은 백엔드가 배치 종료 시 직접 함).
import { apiFetch } from './client';

/**
 * @param {{endpoint: string, keys: {p256dh: string, auth: string}}} subscription
 */
export function subscribeToPush(subscription) {
  return apiFetch('/notifications/subscribe', { method: 'POST', body: subscription });
}

/** @param {string} endpoint */
export function unsubscribeFromPush(endpoint) {
  return apiFetch(`/notifications/subscribe?endpoint=${encodeURIComponent(endpoint)}`, {
    method: 'DELETE',
  });
}

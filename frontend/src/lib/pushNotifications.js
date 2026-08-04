// 위키 발행 브라우저 푸시 알림 — 권한 요청 → 서비스워커 등록 → 구독 → 백엔드 저장까지 감싼다.
// App.jsx의 notiWiki 토글이 이 두 함수(enable/disable)만 호출하면 된다.
import { subscribeToPush, unsubscribeFromPush } from '../api/notifications';

const VAPID_PUBLIC_KEY = import.meta.env.VITE_VAPID_PUBLIC_KEY;

// PushManager.subscribe()의 applicationServerKey는 Uint8Array를 요구한다 —
// 백엔드가 주는 base64url 공개키 문자열을 여기서 변환한다(표준 변환 로직).
function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; i += 1) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

function assertSupported() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    throw new Error('이 브라우저는 푸시 알림을 지원하지 않습니다.');
  }
  if (!VAPID_PUBLIC_KEY) {
    throw new Error('푸시 알림이 아직 설정되지 않았습니다.');
  }
}

/** 현재 이 브라우저의 활성 구독(없으면 null). 서비스워커가 아직 등록 전이면 등록만 하고 구독은 안 만든다. */
export async function getActivePushSubscription() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return null;
  const registration = await navigator.serviceWorker.getRegistration();
  if (!registration) return null;
  return registration.pushManager.getSubscription();
}

export async function enableWikiPushNotifications() {
  assertSupported();

  const permission = await Notification.requestPermission();
  if (permission !== 'granted') {
    throw new Error('알림 권한이 거부되었습니다.');
  }

  // register()는 서비스워커가 "설치 중"이기만 해도 곧장 resolve된다 — pushManager.subscribe()는
  // "활성화(active)"된 워커를 요구해서, register() 결과를 바로 쓰면 브라우저에 따라
  // "no active Service Worker" 에러가 난다. serviceWorker.ready로 활성화까지 기다린다.
  await navigator.serviceWorker.register('/sw.js');
  const registration = await navigator.serviceWorker.ready;
  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY),
  });

  const json = subscription.toJSON();
  await subscribeToPush({ endpoint: json.endpoint, keys: json.keys });
}

export async function disableWikiPushNotifications() {
  const subscription = await getActivePushSubscription();
  if (!subscription) return;
  await unsubscribeFromPush(subscription.endpoint).catch(() => {
    // 서버에서 이미 지워졌어도 로컬 구독 해지는 계속 진행한다.
  });
  await subscription.unsubscribe();
}

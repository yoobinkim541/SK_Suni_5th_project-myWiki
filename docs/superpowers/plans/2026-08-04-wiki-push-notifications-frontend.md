# 위키 발행 브라우저 푸시 알림 — 프론트엔드 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 설정 화면의 "Wiki 업데이트 알림" 토글을 실제 브라우저 푸시 구독/해지에 연결한다.

**Architecture:** 서비스워커(`sw.js`)가 `push` 이벤트를 받아 OS 알림을 띄우고, `lib/pushNotifications.js`가 권한 요청 → 서비스워커 등록 → `pushManager.subscribe()` → 백엔드 저장까지의 흐름을 감싼다. `App.jsx`의 `notiWiki` 토글 핸들러 하나가 이 흐름을 켜고 끈다.

**Tech Stack:** 표준 Web Push API(`Notification`/`PushManager`/Service Worker), `develop-frontend` 브랜치 기준. 백엔드는 별도 계획서(`2026-08-04-wiki-push-notifications-backend.md`) — `POST/DELETE /notifications/subscribe` 엔드포인트를 그대로 가정한다.

## Global Constraints

- 딥링크 없음 — 알림 클릭 시 사이트 루트만 열거나 포커스한다(URL 라우팅이 없는 SPA라서) — 설계 §2.
- 새 아이콘 자산·manifest.json을 만들지 않는다 — 설계 §5.1, §9.
- `notiWiki` 토글은 실제 구독 상태를 반영해야 한다(하드코딩된 `true` 금지).
- 브라우저 미지원·권한 거부 시 명확한 한글 에러로 실패하고 토글은 켜진 채로 남지 않는다.

---

## Task 1: 서비스워커

**Files:**
- Create: `frontend/public/sw.js`

**Interfaces:**
- Produces: `push`/`notificationclick` 이벤트 핸들러가 등록된 서비스워커 파일 — Task 3(`pushNotifications.js`)이 `navigator.serviceWorker.register('/sw.js')`로 이 파일을 등록한다.

- [ ] **Step 1: 서비스워커 작성**

Write to `frontend/public/sw.js`:

```js
// 위키 발행 브라우저 푸시 알림 서비스워커.
// 딥링크는 안 함(이 앱은 URL 라우팅이 없는 SPA) — 알림 클릭 시 열려있는 탭을 포커스하거나
// 없으면 사이트 루트를 새로 연다.

self.addEventListener('push', (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = {};
  }
  const title = payload.title || 'myWiki';
  const body = payload.body || '';

  event.waitUntil(self.registration.showNotification(title, { body }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if ('focus' in client) return client.focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow('/');
    })
  );
});
```

- [ ] **Step 2: 정적 파일로 서빙되는지 확인**

Run: `cd frontend && npm run build && ls dist/sw.js`
Expected: `dist/sw.js` 존재(Vite는 `public/` 아래 파일을 빌드 결과에 그대로 복사한다).

- [ ] **Step 3: 커밋**

```bash
git add frontend/public/sw.js
git commit -m "Feat: 위키 발행 알림 서비스워커(sw.js) 추가"
```

---

## Task 2: 백엔드 구독 API 호출부

**Files:**
- Create: `frontend/src/api/notifications.js`

**Interfaces:**
- Consumes: `apiFetch`(`../api/client`, 기존 — `POST/DELETE /notifications/subscribe` 백엔드 계획서 Task 4와 계약이 같아야 함).
- Produces: `subscribeToPush({endpoint, keys: {p256dh, auth}}): Promise<void>`, `unsubscribeFromPush(endpoint: string): Promise<void>` — Task 3(`pushNotifications.js`)이 이 두 함수를 쓴다.

- [ ] **Step 1: 작성**

Write to `frontend/src/api/notifications.js`:

```js
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
```

- [ ] **Step 2: 빌드 확인**

Run: `cd frontend && npm run build`
Expected: `✓ built`, 에러 없음.

- [ ] **Step 3: 커밋**

```bash
git add frontend/src/api/notifications.js
git commit -m "Feat: 푸시 구독 API 호출부(subscribeToPush/unsubscribeFromPush) 추가"
```

---

## Task 3: 브라우저 구독 오케스트레이션

**Files:**
- Create: `frontend/src/lib/pushNotifications.js`
- Modify: `frontend/.env.example`

**Interfaces:**
- Consumes: `subscribeToPush`/`unsubscribeFromPush`(Task 2), `VITE_VAPID_PUBLIC_KEY`(환경변수).
- Produces: `enableWikiPushNotifications(): Promise<void>`(실패 시 한글 메시지로 reject), `disableWikiPushNotifications(): Promise<void>`, `getActivePushSubscription(): Promise<PushSubscription|null>` — Task 4(`App.jsx`)가 이 세 함수를 쓴다.

- [ ] **Step 1: 작성**

`frontend/.env.example`에 한 줄 추가(파일 맨 아래):

```
VITE_VAPID_PUBLIC_KEY=
```

Write to `frontend/src/lib/pushNotifications.js`:

```js
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

  const registration = await navigator.serviceWorker.register('/sw.js');
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
```

- [ ] **Step 2: 빌드 확인**

Run: `cd frontend && npm run build`
Expected: `✓ built`, 에러 없음.

- [ ] **Step 3: 커밋**

```bash
git add frontend/src/lib/pushNotifications.js frontend/.env.example
git commit -m "Feat: 푸시 알림 구독 오케스트레이션(enable/disableWikiPushNotifications) 추가"
```

---

## Task 4: App.jsx 연결

**Files:**
- Modify: `frontend/src/App.jsx`

**Interfaces:**
- Consumes: `enableWikiPushNotifications`/`disableWikiPushNotifications`/`getActivePushSubscription`(Task 3).
- Produces: 이 태스크가 마지막 — `notiWiki` 토글이 실제 구독 상태를 반영하고 켜고 끌 때 실제로 구독/해지한다.

- [ ] **Step 1: import 추가**

`frontend/src/App.jsx` 상단에서 아래 줄을 찾는다:

```js
import { signInWithProvider, signOut, getCurrentSession, isNewAccount } from './api/auth';
```

바로 아래에 추가:

```js
import {
  enableWikiPushNotifications,
  disableWikiPushNotifications,
  getActivePushSubscription,
} from './lib/pushNotifications';
```

- [ ] **Step 2: 마운트 시 실제 구독 상태로 `notiWiki` 초기화**

아래 블록을 찾는다(PWA 설치 프롬프트 useEffect 바로 다음, 세션 동기화 useEffect 앞):

```js
  useEffect(() => {
    function handleBeforeInstall(e) {
```

이 useEffect 블록이 끝나는 `}, []);` 바로 다음 줄에 새 useEffect를 추가:

```js

  // notiWiki 토글의 실제 상태 — 지금까지는 하드코딩된 true였는데, 실제 구독이
  // 없으면(권한 거부됐거나 애초에 켠 적 없으면) 거짓말을 하고 있었던 셈이라 실제로 확인한다.
  useEffect(() => {
    let alive = true;
    getActivePushSubscription()
      .then((subscription) => {
        if (alive) setNotiWiki(!!subscription);
      })
      .catch(() => {
        if (alive) setNotiWiki(false);
      });
    return () => {
      alive = false;
    };
  }, []);
```

- [ ] **Step 3: 토글 핸들러 추가**

`handleLogout` 함수 바로 다음(빈 줄 하나 두고)에 추가:

```js

  // Wiki 업데이트 알림 토글 — 켤 때 실패하면(권한 거부·브라우저 미지원 등) 토글을 다시
  // 끔 상태로 되돌리고 이유를 알려준다. 끌 때는 실패해도 화면상 토글은 그대로 꺼둔다.
  async function handleToggleNotiWiki(next) {
    if (next) {
      try {
        await enableWikiPushNotifications();
        setNotiWiki(true);
      } catch (err) {
        setNotiWiki(false);
        alert(err.message || '알림을 켜지 못했습니다.');
      }
    } else {
      setNotiWiki(false);
      disableWikiPushNotifications().catch(() => {});
    }
  }
```

- [ ] **Step 4: `SettingsPanel`/`SettingsPage`에 새 핸들러 연결**

`SettingsPage`에 내려주는 곳을 찾는다:

```js
            notiWiki={notiWiki}
            onToggleNotiWiki={setNotiWiki}
```

(이 파일에 두 군데 있다 — `<SettingsPage ...>` 안 1곳, `<SettingsPanel ...>` 안 1곳. **둘 다** 아래로 교체)

```js
            notiWiki={notiWiki}
            onToggleNotiWiki={handleToggleNotiWiki}
```

`<SettingsPanel ...>` 쪽은 들여쓰기가 다르다(6칸):

```js
        notiWiki={notiWiki}
        onToggleNotiWiki={setNotiWiki}
```

아래로 교체:

```js
        notiWiki={notiWiki}
        onToggleNotiWiki={handleToggleNotiWiki}
```

- [ ] **Step 5: 빌드 확인**

Run: `cd frontend && npm run build`
Expected: `✓ built`, 에러 없음.

- [ ] **Step 6: 수동 QA**

`frontend/.env.local`에 `VITE_VAPID_PUBLIC_KEY`(백엔드 계획서 Task 6에서 생성한 공개키)까지 채워서 dev 서버로 확인:

- 설정 화면에서 "Wiki 업데이트 알림" 토글 클릭 → 브라우저 알림 권한 프롬프트 → 허용 → 콘솔 에러 없음, 네트워크 탭에서 `POST /notifications/subscribe` 확인(백엔드가 배포 전이면 실패해도 됨 — 요청이 나가는지만 확인)
- 토글 다시 끄기 → `DELETE /notifications/subscribe` 확인
- 새로고침 → 토글이 방금 상태(켜짐/꺼짐)를 그대로 유지하는지 확인
- `frontend/.env.local`은 확인 후 삭제(커밋 대상 아님)

- [ ] **Step 7: 커밋**

```bash
git add frontend/src/App.jsx
git commit -m "Feat: Wiki 업데이트 알림 토글을 실제 푸시 구독에 연결"
```

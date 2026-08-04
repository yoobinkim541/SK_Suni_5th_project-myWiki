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

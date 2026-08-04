# 위키 발행 브라우저 푸시 알림 설계

> 기준일: 2026-08-04
> 담당: 김유빈 (Wiki·지식베이스 + DB 전체 담당)
> 대상 파일: `frontend/public/sw.js`(신규), `frontend/src/lib/pushNotifications.js`(신규), `frontend/src/api/notifications.js`(신규), `frontend/src/App.jsx`, `supabase/migrations/`(신규), `src/notifications/`(신규 패키지), `src/api/notifications_router.py`(신규), `src/api/main.py`, `src/wiki/generation.py`, `requirements.txt`

---

## 1. 목적

설정 화면(`SettingsPage.jsx`/`SettingsPanel.jsx`)의 "Wiki 업데이트 알림" 토글은 지금 순수 UI 상태(`notiWiki`, 기본 `true`)만 갖고 있고 저장도, 실제 알림 발송도 없다. 이 설계는 그 토글을 실제 브라우저 푸시 알림(OS 알림)에 연결해서, 위키 문서가 새로 발행되면(자동 승인·발행 정책은 [[wiki-publish-pipeline-gap]] 참고) 구독한 사용자에게 알림이 가도록 한다.

## 2. 핵심 원칙

- **표준 Web Push만 쓴다.** 유료 서비스(Firebase, OneSignal 등) 없이 VAPID 키 기반 표준 Web Push API로 구현한다.
- **배치 단위로 한 번만 알린다.** 한 번의 위키 갱신 배치(`generate_wiki_drafts_for_sections`)에서 여러 문서가 발행될 수 있는데, 문서마다 알림을 보내면 스팸이 된다 — 배치가 끝난 뒤 "N건 발행" 알림 하나만 보낸다.
- **딥링크는 안 한다.** 이 앱은 URL 라우팅이 없는 SPA(`view` state로만 화면 전환)라서, 알림을 클릭하면 사이트 루트만 열거나 포커스한다. 특정 위키 문서로 바로 이동시키려면 별도 라우팅 설계가 필요해서 범위 밖으로 둔다.
- **시크릿은 내가 직접 등록하지 않는다.** VAPID 키 쌍은 내가 생성해서 전달하지만, GitHub Actions 시크릿·오라클 VM `.env`·Vercel 환경변수 등록은 배포 설정 변경이라 사용자가 직접 한다(PR #27 때 시크릿 등록과 동일한 경계).
- **실패해도 발행 자체를 막지 않는다.** 알림 발송 실패(만료된 구독 등)는 로그만 남기고 위키 발행 흐름에 영향을 주지 않는다 — 기존 `generate_wiki_drafts_for_sections`의 섹션별 try/except 격리 패턴과 동일한 원칙.

## 3. 데이터 모델

새 테이블 `push_subscriptions` — 브라우저/기기 하나당 구독 하나. 기존 `workspace_settings` 마이그레이션과 동일한 RLS 패턴을 따른다.

```sql
CREATE TABLE IF NOT EXISTS public.push_subscriptions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  endpoint text NOT NULL,
  p256dh text NOT NULL,
  auth text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, endpoint)
);

ALTER TABLE public.push_subscriptions ENABLE ROW LEVEL SECURITY;

CREATE POLICY push_subscriptions_own ON public.push_subscriptions
FOR ALL
USING (user_id = auth.uid())
WITH CHECK (user_id = auth.uid());
```

- `UNIQUE (user_id, endpoint)`: 같은 브라우저에서 토글을 껐다 켜도 중복 행이 안 쌓인다(upsert).
- 백엔드는 SERVICE_ROLE_KEY로 RLS를 우회하고 `workspace_id`/`user_id`로 직접 필터링한다(기존 `src/api/db.py` 전체와 동일한 접근 방식) — 위 정책은 혹시 모를 클라이언트 직접 접근에 대한 방어 계층일 뿐, 실제 조회·발송 경로는 이 정책을 안 거친다.

## 4. 백엔드

### 4.1 새 패키지 `src/notifications/`

`src/settings/service.py`와 같은 단일 파일 패턴:

```python
# src/notifications/service.py
def save_subscription(workspace_id, user_id, endpoint, p256dh, auth_key, *, supabase=None) -> None: ...
def delete_subscription(user_id, endpoint, *, supabase=None) -> None: ...
def send_wiki_notification(workspace_id, published_count, *, supabase=None) -> None:
    """workspace_id 구독자 전원에게 웹 푸시 발송. 만료된 구독(404/410)은 그 자리에서 삭제."""
```

`send_wiki_notification`은 `pywebpush.webpush()`로 구독마다 개별 발송하고, 구독 하나가 실패해도 나머지는 계속 보낸다(반복문 안에서 try/except). `VAPID_PRIVATE_KEY`/`VAPID_CLAIMS_SUB`(연락처, `mailto:sunnycmywiki@gmail.com`)는 환경변수로 읽는다.

### 4.2 REST 엔드포인트 (`src/api/notifications_router.py`)

`settings_router.py`와 같은 인증 패턴(`get_current_user` + `_require_workspace`).

- `POST /notifications/subscribe` — body `{endpoint, keys: {p256dh, auth}}` → `save_subscription()` 호출, 204 반환.
- `DELETE /notifications/subscribe?endpoint=...` — `delete_subscription()` 호출, 204 반환.

`src/api/main.py`에 `app.include_router(notifications_router)` 한 줄 추가.

### 4.3 발송 트리거 (`src/wiki/generation.py`)

`generate_wiki_drafts_for_sections()` 끝에서, 이번 배치에서 실제로 발행된 문서 수를 센다. `error_message`는 "이슈는 성공했는데 주제 단계에서 예외가 났다" 케이스에도 채워지는 필드라(코드상 `error_message=topic_error`) 성공 판정 기준으로 쓰면 안 된다 — 대신 각 페이지 아이디의 존재 여부로 판단한다:

- 이슈 페이지: `result.issue_page_id`가 빈 문자열이 아니면 1건(이슈 페이지는 항상 무조건 발행되므로 — §5 [[wiki-publish-pipeline-gap]]. `issue_page_id=""`는 이슈 생성 자체가 예외로 실패했을 때만 나온다).
- 주제 페이지: `result.topic_page_id`가 `None`이 아니면 1건 추가(`skip`이거나 실패하면 `None`).

합계가 1건 이상이면 `send_wiki_notification(workspace_id, count)`을 한 번 호출한다. 발송 자체가 예외를 던져도 `generate_wiki_drafts_for_sections()`의 반환값(리포트 파이프라인이 쓰는 `results`)에는 영향 없게 try/except로 감싼다.

## 5. 프론트엔드

### 5.1 서비스워커 (`frontend/public/sw.js`)

`push` 이벤트를 받아 `self.registration.showNotification(title, {body})`로 OS 알림을 띄우고, `notificationclick`에서 열려있는 탭을 포커스하거나(없으면) 사이트 루트를 새로 연다. 아이콘 자산은 새로 안 만든다(브라우저 기본 아이콘 사용 — 범위 밖).

### 5.2 구독 관리 (`frontend/src/lib/pushNotifications.js`)

- `enableWikiPushNotifications()`: 브라우저 지원 확인 → `Notification.requestPermission()` → 서비스워커 등록 → `pushManager.subscribe({userVisibleOnly: true, applicationServerKey: VITE_VAPID_PUBLIC_KEY})` → 결과를 `api/notifications.js`로 백엔드에 저장. 각 단계 실패 시 명확한 한글 에러 메시지로 reject.
- `disableWikiPushNotifications()`: 등록된 구독을 찾아 백엔드에서 삭제 요청 후 `subscription.unsubscribe()`.

### 5.3 App.jsx 연결

- 마운트 시 `navigator.serviceWorker.getRegistration()` → `pushManager.getSubscription()`으로 실제 구독 여부를 읽어서 `notiWiki` 초기값을 정한다(지금처럼 무조건 `true`가 아니라 실제 상태 반영 — 안 그러면 토글이 거짓말을 하게 됨).
- `onToggleNotiWiki`를 `setNotiWiki` 직통 대신 `handleToggleNotiWiki(next)`로 바꿔서, 켤 때 `enableWikiPushNotifications()`가 실패하면(권한 거부 등) 토글을 다시 끔 상태로 되돌리고 이유를 알려준다.
- 이 핸들러 하나를 `SettingsPanel`(상단바 드롭다운)과 `SettingsPage`(설정 화면) 양쪽에 그대로 내려준다 — 지금도 두 곳이 같은 `notiWiki`/`onToggleNotiWiki`를 공유하는 구조라 변경 지점은 App.jsx 한 곳뿐이다.

## 6. 시크릿·환경변수 (사용자가 직접 등록)

내가 VAPID 키 쌍을 생성해서 전달하면, 다음을 등록해야 발송이 실제로 동작한다:

| 값 | 위치 |
|---|---|
| `VAPID_PRIVATE_KEY` | GitHub Actions 저장소 시크릿 + 오라클 VM 백엔드 `.env`(배포 파이프라인이 이미 SUPABASE_* 를 이렇게 주입하는 것과 동일) |
| `VITE_VAPID_PUBLIC_KEY` | Vercel 프로젝트 환경변수(프론트 빌드 타임) |

등록 전까지는 구독 저장까지는 되지만(공개키만 있으면 `pushManager.subscribe()`는 성공) 실제 발송(`webpush()`)이 서버에서 실패한다 — 이 경우도 위 4.1의 try/except로 로그만 남고 조용히 실패한다.

## 7. 에러 처리

- 브라우저가 Push API 미지원(구형 Safari 등) → `enableWikiPushNotifications()`가 즉시 reject, 토글 안 켜짐 + 안내 메시지.
- 알림 권한 거부 → 동일하게 토글 안 켜짐 + 안내 메시지.
- 만료/취소된 구독으로 발송 시 404/410 → 그 구독 행 자동 삭제(다음부터 발송 대상에서 빠짐).
- 그 외 발송 실패(네트워크 등) → 로그만, 구독 유지(일시적 실패일 수 있으므로 지우지 않음).

## 8. 테스트 계획

프론트는 자동 테스트 프레임워크가 없어 수동 QA로 대체(이 저장소 기존 컨벤션):

- 설정에서 토글 켜기 → 브라우저 알림 권한 프롬프트 → 허용 → 네트워크 탭에서 `POST /notifications/subscribe` 확인
- 토글 끄기 → `DELETE /notifications/subscribe` 확인
- 새로고침 후 토글이 실제 구독 상태를 반영하는지 확인
- 백엔드: `pytest`로 `save_subscription`/`delete_subscription`/`send_wiki_notification`(fake webpush 클라이언트로 만료 구독 삭제 로직까지) 단위 테스트, `generate_wiki_drafts_for_sections`가 발행 건수를 세어 알림을 한 번만 호출하는지 monkeypatch로 확인(기존 `tests/test_wiki_generation.py` 패턴 재사용)
- `npm run build` / `pytest tests/` 전체 통과

## 9. 이번 설계에 포함하지 않는 것

- 특정 위키 문서로 딥링크(URL 라우팅 자체가 없음)
- 일일 리포트 알림(notiReport) — 요청 범위 밖
- PWA manifest.json 추가(기존에 반쯤 있던 `beforeinstallprompt` 처리와는 별개 — 이미 있던 미완성 기능이라 이번엔 안 건드림)
- 알림 아이콘 등 브랜드 자산 제작
- iOS Safari 홈 화면 설치 강제·안내

# 랜딩 → 인증 → 온보딩 진입 플로우 설계

> 기준일: 2026-08-04
> 담당: 김유빈 (Wiki·지식베이스 + DB 전체 담당, 이번 세션에서 프론트 진입 플로우까지 확장)
> 대상 파일: `frontend/src/pages/EntryFlow.jsx`(신규), `frontend/src/App.jsx`, `frontend/src/data/mockOnboarding.js`
> 변경 없음: `frontend/src/pages/OnboardingPage.jsx`(그대로 재사용), `frontend/src/api/auth.js`, `frontend/src/api/supabaseClient.js`, 백엔드 전체

---

## 1. 목적

현재 `App.jsx`는 로그인 여부와 무관하게 `localStorage['mywiki-interests']`가 없으면 무조건 선호 조사(OnboardingPage) 화면부터 보여주고, 로그인은 상단바 프로필 드롭다운에서 언제든 할 수 있는 부가 기능처럼 취급된다. 이번 설계는 원본 시안에 있었지만 미구현 상태로 남아있던 4단계 진입 흐름(랜딩 → 사람확인 → 로그인/회원가입 → 선호조사 → 대시보드)을 완성한다:

- 첫 방문자는 랜딩 페이지를 먼저 본다(현재는 곧바로 선호조사 화면이 뜸).
- 기존 계정으로 로그인하면 선호조사를 건너뛰고 바로 대시보드로 간다(현재는 신규/기존 구분이 없음).
- 신규 계정은 회원가입(=OAuth) 후 선호조사를 거쳐 대시보드로 간다.
- 로그인 없이 "건너뛰기"를 선택하면 대시보드는 보이지만 다른 메뉴는 클릭 시 로그인을 유도한다(현재는 이런 게스트 개념 자체가 없음).

## 2. 핵심 원칙

- **기존 CSS를 그대로 쓴다.** `globals.css`에 이미 원본 시안의 랜딩(`.landing-*`)·사람확인(`.ob-check`, `.ob-gate-note`)·로그인(`.ob-login`, `.pp-oauth`) 스타일이 다 있다 — 지금까지 아무 컴포넌트도 안 썼을 뿐이다. 새 CSS를 만들지 않는다.
- **OnboardingPage.jsx는 수정하지 않는다.** 이미 선호조사(3단계) 역할을 완전히 구현하고 있다 — `EntryFlow`가 적절한 시점에 그대로 렌더링만 한다.
- **OAuth 리다이렉트로 상태가 날아가는 걸 전제로 설계한다.** `signInWithOAuth`는 전체 페이지 이동이라 리다이렉트 복귀 시 React 상태가 초기화된다. "로그인 버튼을 눌렀었다"를 따로 기억하지 않고, 매번 세션 유무 + 로컬 기록 + 계정 생성 시각만으로 어느 화면을 보여줄지 판단한다(멱등).
- **서버 스키마를 바꾸지 않는다.** 신규/기존 판단과 관심사 저장 전부 클라이언트에서 이미 갖고 있는 정보(Supabase 세션의 `created_at`/`last_sign_in_at`, `localStorage`)로 처리한다. `profiles.prefs` 컬럼 추가는 여전히 범위 밖(기존에 이미 알려진 제약, [[wiki-frontend-boundary]] 참고).

## 3. 화면 구성과 라우팅 로직

### 3.1 앱 부팅 시 어느 화면을 보여줄지 결정하는 규칙

`App.jsx`가 mount 시 `getCurrentSession()`으로 세션을 먼저 확인한다(기존 PR #31 로직 그대로). 세션 확인이 끝난 뒤(비동기라 짧은 "확인 중" 순간이 있음 — 기존 앱 로고/빈 화면으로 자연스럽게 처리, 별도 스피너 불필요) 아래 순서로 판단:

```
1. session이 있고 authed === true:
   a. localStorage['mywiki-interests']가 있다  →  대시보드로 (일반 앱 화면)
   b. 없다  →  session.user.created_at과 session.user.last_sign_in_at 비교
        - 5분 이내로 가깝다 (방금 가입)  →  EntryFlow를 "선호조사" 단계부터 시작
        - 5분보다 차이난다 (다른 기기의 기존 계정)  →  대시보드로
2. session이 없고 guestMode === true (이번 앱 실행 중 "건너뛰기"를 눌렀음)  →  대시보드(게스트)
3. 그 외 (세션도 없고 게스트도 아님)  →  EntryFlow를 "랜딩" 단계부터 시작
```

`guestMode`는 `App.jsx`의 평범한 `useState(false)` — 새로고침하면 자연히 초기화되므로 "게스트 상태는 저장 안 함(매번 랜딩부터)" 요구사항을 별도 코드 없이 만족한다.

5분이라는 기준은 임의값이지만, 목적이 "OAuth 콜백 직후인가"를 가리는 것뿐이라 넉넉하게 잡아도 안전하다(길어도 신규 사용자가 선호조사를 한 번 더 보는 정도이지, 오작동은 아님).

### 3.2 EntryFlow.jsx (신규 컴포넌트)

`App.jsx`가 위 3가지 케이스 중 "EntryFlow가 필요함" 판단이 서면 렌더링한다. 내부적으로 자체 `step` state(`'landing' | 'gate' | 'login' | 'survey'`)를 갖고, 진입 시 초기 step을 props로 받는다(`initialStep`: 대부분 `'landing'`, 신규 가입 직후 리다이렉트 복귀 케이스만 `'survey'`).

| step | 재사용 CSS | 내용 | 다음 |
|---|---|---|---|
| `landing` | `.ob-screen.ob-landing`, `.landing-*`, `.lf-card` | 브랜드/헤드라인/기능 카드 4개, 버튼 3개: 로그인 · 회원가입 · 건너뛰기 | 로그인/회원가입 → `gate`(intent 저장), 건너뛰기 → `onComplete('guest')` |
| `gate` | `.ob-card`, `.ob-steps`, `.ob-check`, `.ob-gate-note` | "사람 확인" 클릭 → 체크 애니메이션 → 확인 완료 텍스트 → 다음 버튼 활성화 | `login` |
| `login` | `.ob-card`, `.ob-login`, `.pp-oauth` | Google/GitHub 버튼(카카오는 비활성 — PR #31과 동일 이유). intent에 따라 문구만 다름("로그인해주세요" / "가입하고 시작하기") | 클릭 시 `signInWithProvider()` 호출 → 페이지 이탈(OAuth) |
| `survey` | (없음, `OnboardingPage` 그대로 렌더) | 기존 `OnboardingPage`를 `onComplete`만 연결해서 그대로 사용 | 완료/건너뛰기 → `onComplete('authed')` |

`onComplete(mode)`는 `App.jsx`로 한 번만 호출되는 콜백 — `mode==='guest'`면 `guestMode=true`, `mode==='authed'`면 그냥 일반 앱 화면으로 전환(이미 세션이 있으므로 추가 처리 불필요).

### 3.3 게스트 모드 내비게이션 제한

`App.jsx`의 `navigateTo(key, payload)`에 가드 추가:

```js
function navigateTo(key, payload) {
  if (guestMode && key !== 'dash') {
    setProfileOpen(true);  // 대시보드 외 메뉴 클릭 → 로그인 유도(프로필 드롭다운 오픈)
    return;
  }
  // 기존 로직 그대로
}
```

`ProfilePanel`은 이미 비로그인 상태에서 OAuth 버튼을 보여주므로 추가 UI 없이 그대로 재사용된다. SideNav/BottomNav 메뉴 항목 자체는 그대로 다 보인다(요구사항: "보이되 클릭 시 로그인 유도").

게스트가 이 드롭다운에서 실제로 로그인하면(기존 PR #31 경로 그대로, `EntryFlow`를 거치지 않음) OAuth 리다이렉트 후 앱이 재부팅되고, 이때는 세션이 있으므로 3.1의 케이스 1로 바로 들어간다 — `guestMode`는 자연히 의미를 잃는다(재부팅 시 `false`로 리셋되고, 세션이 있으니 애초에 안 쓰임).

### 3.4 로그아웃

`handleLogout()`이 `signOut()` 호출 후 `guestMode`도 함께 초기화하고 다음 렌더에서 세션이 없어지므로 자연히 위 3.1의 케이스 3(랜딩)으로 돌아간다 — 별도 분기 불필요, `authed`가 `false`가 되는 순간 App.jsx의 최상위 조건이 알아서 EntryFlow를 다시 보여준다.

## 4. 랜딩 페이지 카피 (초안)

기존 톤(`"myWiki — 반도체 동향 모니터링"`)에 맞춘 초안 — 구현 시 그대로 쓰되 필요하면 조정 가능:

- 브랜드: `myWiki`
- 헤드라인: `"반도체 업계 동향, 놓치지 않고 한눈에"`
- 서브: `"뉴스 수집부터 신뢰도 검증, 위키 정리, 리포트까지 — 반도체 도메인 뉴스를 자동으로 정리해드립니다."`
- 기능 카드 4개(`.lf-card`, 아이콘은 이모지로 대체):
  1. 📡 자동 수집 — "네이버·GNews·전자공시 등 여러 소스에서 반도체 뉴스를 자동 수집합니다"
  2. ✅ 신뢰도 검증 — "출처·근거를 따져 신뢰도 등급을 매기고 낮은 신뢰도는 걸러냅니다"
  3. 📖 위키 자동 정리 — "이슈·기업·기술별로 위키 문서를 자동 생성·갱신합니다"
  4. 🤖 AI 에이전트 — "위키 근거를 바탕으로 질문에 답하고, 답변을 위키에 저장할 수 있습니다"
- CTA: "로그인" / "회원가입" / "건너뛰고 둘러보기"

## 5. 에러 처리

- `getCurrentSession()` 실패(네트워크 등) → 세션 없음으로 간주, 랜딩부터 시작(기존 앱도 이미 이런 폴백 없이 안전한 기본값으로 처리하는 패턴).
- OAuth 리다이렉트 실패/취소 → Supabase가 원래 페이지로 세션 없이 돌려보냄 → 위 3.1 규칙에 따라 다시 랜딩. 별도 에러 화면 불필요.
- 신규/기존 판단에 쓰는 `session.user.created_at`/`last_sign_in_at`이 없는 예외 케이스 → 신규로 간주(선호조사 보여주는 쪽이 안전한 기본값 — 최악의 경우 이미 완료한 사용자가 한 번 더 보는 정도).

## 6. 테스트 계획

프론트는 이 저장소에 컴포넌트 테스트 프레임워크가 없어서(Vite + 수동 QA 패턴, 기존 PR들과 동일) 아래는 수동 확인 항목으로 대체:

- 세션 없음 + 게스트 아님 → 랜딩 노출
- 랜딩에서 건너뛰기 → 대시보드, 다른 메뉴 클릭 시 프로필 드롭다운 오픈(화면 전환 안 됨)
- (실제 로그인 계정으로) 로그인 → 이미 `mywiki-interests` 있으면 대시보드 직행
- `localStorage` 초기화 후 기존 계정으로 재로그인 → 계정이 오래됐으면(생성 5분 초과) 대시보드 직행, 선호조사 안 뜸
- 로그아웃 → 랜딩으로 복귀
- `npm run build` 통과

`session.user.created_at`/`last_sign_in_at` 비교 로직 자체는 순수 함수로 분리해서(예: `isNewAccount(session)`) 로직만이라도 짧은 단위 검증(수동 콘솔 확인 또는 간단한 스크립트)으로 확인한다.

## 7. 이번 설계에 포함하지 않는 것

- `profiles.prefs` 서버 저장(스키마 변경 필요, 팀 확인 후 별도 설계)
- 카카오 로그인(Supabase provider 비활성 상태, PR #31에서 이미 제외)
- 실제 사람 확인(캡챠) 로직 — `.ob-check`는 원본 시안 그대로 순수 UI
- 이메일/비밀번호 로그인 — OAuth(Google/GitHub)만

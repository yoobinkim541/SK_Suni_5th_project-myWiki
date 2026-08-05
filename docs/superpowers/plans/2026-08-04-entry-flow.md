# 랜딩→인증→온보딩 진입 플로우 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 첫 방문자는 랜딩 페이지부터 보고, 기존 계정 로그인은 바로 대시보드로, 신규 가입은 선호조사를 거쳐 대시보드로, "건너뛰기"는 대시보드만 제한적으로 볼 수 있게 진입 흐름을 완성한다.

**Architecture:** 새 컴포넌트 `EntryFlow.jsx`가 랜딩·사람확인·로그인 3단계를 내부 state로 관리하고, 기존 `OnboardingPage.jsx`(선호조사)를 그대로 재사용한다. `App.jsx`는 Supabase 세션 + `localStorage['mywiki-interests']` + 계정 생성 시각을 조합해 어느 단계부터 보여줄지 매 부팅 시 재계산한다(OAuth 리다이렉트로 상태가 날아가는 걸 전제로 멱등하게 설계).

**Tech Stack:** React 18 (Vite), 기존 CSS(`globals.css`)의 `.landing-*`/`.ob-*`/`.pp-oauth` 클래스 재사용. 새 CSS 없음. 테스트 프레임워크 없음(이 저장소 프론트 전체가 `npm run build` + 수동 QA로 검증하는 기존 컨벤션 — Task별 검증도 이 방식을 따른다).

## Global Constraints

- 새 CSS를 추가하지 않는다 — `globals.css`에 이미 있는 `.landing-*`, `.ob-*`, `.pp-oauth` 클래스만 쓴다.
- `OnboardingPage.jsx`는 수정하지 않는다 — `EntryFlow`가 그대로 렌더링만 한다.
- 서버(백엔드/DB) 변경 없음 — 전부 프론트 전용, `develop-frontend` 기준.
- 신규/기존 판단은 `session.user.created_at`/`last_sign_in_at`로만 하고, 정보가 없으면 신규로 간주한다(안전한 기본값).
- 게스트 모드(`guestMode`)는 새로고침 시 초기화된다(별도 저장 로직을 만들지 않는 것 자체가 요구사항).

---

## Task 1: 랜딩 화면 콘텐츠 데이터 추가

**Files:**
- Modify: `frontend/src/data/mockOnboarding.js`

**Interfaces:**
- Produces: `LANDING_FEATURES: {icon: string, title: string, desc: string}[]` (export) — Task 3(`EntryFlow.jsx`)이 이 배열을 순회해서 `.lf-card` 4개를 렌더링한다.

- [ ] **Step 1: `LANDING_FEATURES` 배열 추가**

`frontend/src/data/mockOnboarding.js` 맨 위(`ONBOARDING_STEPS` 선언 앞)에 추가:

```js
// 랜딩 페이지(0단계) 기능 소개 카드 4개 — globals.css의 .landing-features/.lf-card 그대로 씀.
export const LANDING_FEATURES = [
  { icon: '📡', title: '자동 수집', desc: '네이버·GNews·전자공시 등 여러 소스에서 반도체 뉴스를 자동 수집합니다' },
  { icon: '✅', title: '신뢰도 검증', desc: '출처·근거를 따져 신뢰도 등급을 매기고 낮은 신뢰도는 걸러냅니다' },
  { icon: '📖', title: '위키 자동 정리', desc: '이슈·기업·기술별로 위키 문서를 자동 생성·갱신합니다' },
  { icon: '🤖', title: 'AI 에이전트', desc: '위키 근거를 바탕으로 질문에 답하고, 답변을 위키에 저장할 수 있습니다' },
];
```

- [ ] **Step 2: 문법 확인**

Run: `cd frontend && node -e "require('esbuild')" 2>/dev/null; node --input-type=module -e "import('./src/data/mockOnboarding.js').then(m => console.log(m.LANDING_FEATURES.length))"`

이 저장소엔 별도 JS 유닛 테스트가 없으므로, import가 되고 길이가 `4`로 찍히면 통과. (Vite 프로젝트라 브라우저 환경 API를 쓰는 다른 export까지 같이 로드되면 실패할 수 있음 — 그 경우 Step 4의 `npm run build`로 대체 확인해도 됨.)
Expected: `4` 출력 (또는 실패 시 Step 4로 대체 확인)

- [ ] **Step 3: 커밋**

```bash
git add frontend/src/data/mockOnboarding.js
git commit -m "Feat: 랜딩 페이지 기능 소개 카드 데이터 추가"
```

---

## Task 2: 신규/기존 계정 판단 헬퍼 추가

**Files:**
- Modify: `frontend/src/api/auth.js`

**Interfaces:**
- Produces: `isNewAccount(session): boolean` (export) — Task 4(`App.jsx`)가 로그인 직후 선호조사를 보여줄지 판단할 때 쓴다. `session`은 Supabase `session` 객체(`session.user.created_at`, `session.user.last_sign_in_at` 문자열 필드를 읽음).

- [ ] **Step 1: 임시 검증 스크립트 작성**

`frontend/src/api/auth.js`를 고치기 전에, 기대 동작을 먼저 스크립트로 적어둔다(이 저장소엔 JS 테스트 러너가 없어서 임시 스크립트로 대체 — 커밋 대상 아님).

Write to `frontend/.tmp-isNewAccount-check.mjs`:

```js
function isNewAccount(session) {
  const createdAt = session?.user?.created_at;
  const lastSignInAt = session?.user?.last_sign_in_at;
  if (!createdAt || !lastSignInAt) return true;
  const diffMs = Math.abs(new Date(lastSignInAt).getTime() - new Date(createdAt).getTime());
  return diffMs <= 5 * 60 * 1000;
}

const cases = [
  ['정보 없음 -> 신규 취급', { user: {} }, true],
  ['방금 가입(같은 시각) -> 신규', { user: { created_at: '2026-08-04T00:00:00Z', last_sign_in_at: '2026-08-04T00:00:00Z' } }, true],
  ['방금 가입(2분 차이) -> 신규', { user: { created_at: '2026-08-04T00:00:00Z', last_sign_in_at: '2026-08-04T00:02:00Z' } }, true],
  ['오래된 계정(1년 전 가입) -> 기존', { user: { created_at: '2025-08-04T00:00:00Z', last_sign_in_at: '2026-08-04T00:00:00Z' } }, false],
  ['session 자체가 null -> 신규 취급', null, true],
];

let failed = 0;
for (const [label, session, expected] of cases) {
  const actual = isNewAccount(session);
  const ok = actual === expected;
  if (!ok) failed++;
  console.log(`${ok ? 'PASS' : 'FAIL'} - ${label} (expected ${expected}, got ${actual})`);
}
process.exit(failed > 0 ? 1 : 0);
```

- [ ] **Step 2: 스크립트 실행해서 로직 확정**

Run: `node frontend/.tmp-isNewAccount-check.mjs`
Expected: 5개 케이스 전부 `PASS`, exit code 0.

- [ ] **Step 3: 검증된 로직을 `api/auth.js`로 옮기기**

`frontend/src/api/auth.js` 맨 아래(파일 끝)에 추가:

```js

// OAuth 콜백 직후 세션인지(=방금 가입한 계정인지) 판단한다.
// EntryFlow 진입 시점에 선호조사(3단계)를 보여줄지, 곧장 대시보드로 보낼지 가르는 데 쓴다.
// 판단할 정보가 없으면 신규로 본다(최악의 경우 이미 온보딩한 사용자가 한 번 더 보는 정도라 안전).
const NEW_ACCOUNT_WINDOW_MS = 5 * 60 * 1000; // 5분

export function isNewAccount(session) {
  const createdAt = session?.user?.created_at;
  const lastSignInAt = session?.user?.last_sign_in_at;
  if (!createdAt || !lastSignInAt) return true;
  const diffMs = Math.abs(new Date(lastSignInAt).getTime() - new Date(createdAt).getTime());
  return diffMs <= NEW_ACCOUNT_WINDOW_MS;
}
```

- [ ] **Step 4: 임시 스크립트 삭제**

```bash
rm frontend/.tmp-isNewAccount-check.mjs
```

- [ ] **Step 5: 빌드 확인 + 커밋**

Run: `cd frontend && npm run build`
Expected: `✓ built` 로 종료, 에러 없음.

```bash
git add frontend/src/api/auth.js
git commit -m "Feat: 세션 기준 신규/기존 계정 판단 헬퍼(isNewAccount) 추가"
```

---

## Task 3: EntryFlow 컴포넌트 (랜딩·사람확인·로그인)

**Files:**
- Create: `frontend/src/pages/EntryFlow.jsx`

**Interfaces:**
- Consumes: `signInWithProvider(provider)` (from `../api/auth`, 기존 함수, PR #31에서 이미 구현됨), `LANDING_FEATURES` (from `../data/mockOnboarding`, Task 1), `OnboardingPage` (from `./OnboardingPage`, 기존 컴포넌트, 수정 없음).
- Produces: `EntryFlow({ initialStep: 'landing' | 'survey', onSurveyComplete: (result) => void, onGuestSkip: () => void })` (default export) — Task 4(`App.jsx`)가 이 컴포넌트를 렌더링한다. `onSurveyComplete`는 `OnboardingPage`의 `onComplete`와 동일한 시그니처(`result: {keywords: string[], role: string|null, age: string|null}`)로 그대로 전달됨.

- [ ] **Step 1: 컴포넌트 뼈대 + landing 단계 작성**

Write to `frontend/src/pages/EntryFlow.jsx`:

```jsx
// 진입 플로우 — 랜딩(0) → 사람확인(1) → 로그인(2) → 선호조사(3, OnboardingPage 재사용) → 대시보드(4).
//
// App.jsx가 세션·localStorage·계정 생성 시각을 보고 이 컴포넌트를 어느 단계(initialStep)로
// 띄울지 결정한다(자세한 판단 규칙은 docs/superpowers/specs/2026-08-04-entry-flow-design.md 3.1절).
// initialStep이 'survey'면 사람확인/로그인 없이 곧장 OnboardingPage를 보여준다 —
// 이미 로그인된 세션이 있는 상태(OAuth 콜백 복귀 직후)이기 때문.
//
// OAuth 로그인 버튼을 누르면 signInWithProvider가 페이지를 통째로 이동시킨다(리다이렉트).
// 그래서 이 컴포넌트는 "로그인 진행 중" 상태를 따로 저장하지 않는다 — 리다이렉트 복귀 후엔
// App.jsx가 세션 유무로 처음부터 다시 판단하므로 중간 상태를 기억할 필요가 없다.
//
// CSS는 전부 globals.css에 이미 있던 원본 시안 클래스를 그대로 쓴다(.landing-*, .ob-*, .pp-oauth) —
// 지금까지 아무 컴포넌트도 쓰지 않고 있던 것들이다.

import { useState } from 'react';
import { signInWithProvider } from '../api/auth';
import { LANDING_FEATURES } from '../data/mockOnboarding';
import OnboardingPage from './OnboardingPage';

// ProfilePanel.jsx의 OAUTH_PROVIDERS와 동일 — 카카오는 Supabase provider 비활성 상태라 제외(PR #31과 동일 이유).
const OAUTH_PROVIDERS = [
  { key: 'google', label: 'Google로 계속하기', ic: 'G' },
  { key: 'github', label: 'GitHub로 계속하기', ic: 'Gh' },
];

const ENTRY_STEPS_LABELS = ['1 · 사람 확인', '2 · 로그인', '3 · 선호 조사', '4 · 대시보드'];

function StepsBar({ activeIndex }) {
  return (
    <div className="ob-steps">
      {ENTRY_STEPS_LABELS.map((label, i) => (
        <span
          key={label}
          className={`ob-step${i < activeIndex ? ' done' : i === activeIndex ? ' on' : ''}`}
        >
          {label}
        </span>
      ))}
    </div>
  );
}

export default function EntryFlow({ initialStep, onSurveyComplete, onGuestSkip }) {
  const [step, setStep] = useState(initialStep);
  const [intent, setIntent] = useState('login'); // 'login' | 'signup' — 로그인 화면 문구만 다르게 씀
  const [gateChecking, setGateChecking] = useState(false);
  const [gateChecked, setGateChecked] = useState(false);

  // 이미 세션이 있는 상태(신규 가입 직후)로 진입한 경우 — 사람확인/로그인 없이 곧장 선호조사.
  if (step === 'survey') {
    return <OnboardingPage onComplete={onSurveyComplete} />;
  }

  function startAuth(nextIntent) {
    setIntent(nextIntent);
    setStep('gate');
  }

  function handleGateCheck() {
    if (gateChecking || gateChecked) return;
    setGateChecking(true);
    // 실제 검증 로직 없음(순수 UI) — globals.css의 .ob-check 스핀 애니메이션 길이(0.7s)에 맞춤.
    setTimeout(() => {
      setGateChecking(false);
      setGateChecked(true);
    }, 700);
  }

  return (
    <div className="ob-stage">
      {step === 'landing' && (
        <div className="ob-screen ob-landing on">
          <div className="landing-inner">
            <div className="landing-brand">myWiki</div>
            <h1>
              반도체 업계 동향,
              <br />
              놓치지 않고 한눈에
            </h1>
            <p className="landing-sub">
              뉴스 수집부터 신뢰도 검증, 위키 정리, 리포트까지 — 반도체 도메인 뉴스를 자동으로
              정리해드립니다.
            </p>
            <div className="landing-features">
              {LANDING_FEATURES.map((f) => (
                <div className="lf-card" key={f.title}>
                  <div className="lf-ic">{f.icon}</div>
                  <div className="lf-t">{f.title}</div>
                  <div className="lf-d">{f.desc}</div>
                </div>
              ))}
            </div>
            <button type="button" className="landing-cta" onClick={() => startAuth('login')}>
              로그인
            </button>{' '}
            <button type="button" className="landing-cta" onClick={() => startAuth('signup')}>
              회원가입
            </button>
            <div style={{ marginTop: 16 }}>
              <button type="button" className="ob-skip" onClick={onGuestSkip}>
                건너뛰고 둘러보기
              </button>
            </div>
          </div>
        </div>
      )}

      {step === 'gate' && (
        <div className="ob-screen on">
          <div className="ob-card">
            <div className="ob-logo">
              <div className="ob-eb">MYWIKI</div>
              <div className="ob-nm">myWiki</div>
            </div>
            <StepsBar activeIndex={0} />
            <div className="ob-h">사람인지 확인해주세요</div>
            <div className="ob-sub">아래 체크박스를 눌러 진행해주세요.</div>
            <button
              type="button"
              className={`ob-check${gateChecking ? ' checking' : ''}${gateChecked ? ' checked' : ''}`}
              onClick={handleGateCheck}
            >
              <span className="box" />
              <span className="ob-check-l">저는 사람입니다</span>
              <span className="ob-check-badge">확인</span>
            </button>
            <div className={`ob-gate-note${gateChecked ? ' ok' : ''}`}>
              {gateChecked ? '확인되었습니다.' : ''}
            </div>
            <div className="ob-actions">
              <button type="button" className="ob-skip" onClick={() => setStep('landing')}>
                이전
              </button>
              <button
                type="button"
                className="ob-next"
                disabled={!gateChecked}
                onClick={() => setStep('login')}
              >
                다음
              </button>
            </div>
          </div>
        </div>
      )}

      {step === 'login' && (
        <div className="ob-screen on">
          <div className="ob-card ob-login">
            <div className="ob-logo">
              <div className="ob-eb">MYWIKI</div>
              <div className="ob-nm">myWiki</div>
            </div>
            <StepsBar activeIndex={1} />
            <div className="ob-h">{intent === 'signup' ? '가입하고 시작하기' : '로그인해주세요'}</div>
            <div className="ob-sub">
              계정으로 계속하면 관심 키워드·위키·리포트를 이어서 볼 수 있습니다.
            </div>
            {OAUTH_PROVIDERS.map((p) => (
              <button
                key={p.key}
                type="button"
                className={`pp-oauth ${p.key}`}
                onClick={() => signInWithProvider(p.key)}
              >
                <span className="ic">{p.ic}</span>
                {p.label}
              </button>
            ))}
            <div className="ob-actions">
              <button type="button" className="ob-skip" onClick={() => setStep('gate')}>
                이전
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: 빌드 확인**

Run: `cd frontend && npm run build`
Expected: `✓ built` 로 종료, 에러 없음(아직 `App.jsx`에서 안 쓰고 있어도 빌드는 통과해야 함 — dead code 상태라도 문법 오류가 없어야 함).

- [ ] **Step 3: 커밋**

```bash
git add frontend/src/pages/EntryFlow.jsx
git commit -m "Feat: EntryFlow 컴포넌트 추가 — 랜딩·사람확인·로그인 3단계 + 선호조사(OnboardingPage) 연결"
```

---

## Task 4: App.jsx에 EntryFlow 연결

**Files:**
- Modify: `frontend/src/App.jsx`

**Interfaces:**
- Consumes: `EntryFlow` (Task 3), `isNewAccount` (Task 2, from `./api/auth`).
- Produces: 이 태스크가 마지막 — 이후 태스크 없음. 최종 사용자 동작(랜딩/게스트/로그인/로그아웃)이 여기서 확정된다.

- [ ] **Step 1: import 교체**

`frontend/src/App.jsx` 상단 import 블록에서 `import OnboardingPage from './pages/OnboardingPage';` 줄을 찾아 아래로 교체:

```js
import EntryFlow from './pages/EntryFlow';
```

`import { signInWithProvider, signOut, getCurrentSession } from './api/auth';` 줄을 아래로 교체(`isNewAccount` 추가):

```js
import { signInWithProvider, signOut, getCurrentSession, isNewAccount } from './api/auth';
```

- [ ] **Step 2: state 추가**

`const [authed, setAuthed] = useState(false);` 바로 아래에 추가:

```js
  const [authChecked, setAuthChecked] = useState(false);
  const [guestMode, setGuestMode] = useState(false);
  const [entryStep, setEntryStep] = useState(null); // 'landing' | 'survey' | null(=일반 앱 화면)
```

- [ ] **Step 3: 세션 동기화 useEffect 교체**

기존(PR #31에서 추가된) 아래 블록을 찾는다:

```js
  useEffect(() => {
    getCurrentSession().then((session) => {
      setAuthed(!!session);
      setProfile(session?.user ?? null);
    });
    const { data: subscription } = supabase.auth.onAuthStateChange((_event, session) => {
      setAuthed(!!session);
      setProfile(session?.user ?? null);
    });
    return () => subscription?.subscription?.unsubscribe();
  }, []);
```

아래로 통째로 교체:

```js
  // 실제 Supabase 세션 동기화 + 어느 화면(entryStep)부터 시작할지 결정.
  // determineEntryStep은 매 세션 변화(최초 로드·OAuth 콜백 복귀·로그아웃)마다 다시 계산한다 —
  // "로그인 진행 중이었다" 같은 중간 상태를 따로 안 들고 있어도 항상 같은 결론에 도달한다.
  useEffect(() => {
    function determineEntryStep(session) {
      if (!session) {
        setEntryStep('landing');
        return;
      }
      const existingPrefs = readPrefs();
      if (existingPrefs !== null) {
        setPrefs(existingPrefs);
        setEntryStep(null);
        return;
      }
      if (isNewAccount(session)) {
        setEntryStep('survey');
        return;
      }
      // 기존 계정인데 이 기기엔 관심사 기록이 없음(다른 기기로 처음 로그인) — 빈 기본값으로 대시보드 진입.
      // "설정 > 관심사 다시 고르기"로 나중에 채우면 됨.
      setPrefs({ keywords: [], role: null, age: null });
      setEntryStep(null);
    }
    function applySession(session) {
      setAuthed(!!session);
      setProfile(session?.user ?? null);
      determineEntryStep(session);
    }
    getCurrentSession()
      .then((session) => {
        applySession(session);
      })
      .catch(() => {
        // 세션 조회 실패(네트워크 등) — 세션 없음으로 간주하고 랜딩부터 보여준다.
        applySession(null);
      })
      .finally(() => {
        setAuthChecked(true);
      });
    const { data: subscription } = supabase.auth.onAuthStateChange((_event, session) => {
      applySession(session);
    });
    return () => subscription?.subscription?.unsubscribe();
  }, []);
```

- [ ] **Step 4: `handleOnboardingComplete`에 `setEntryStep(null)` 추가**

기존:

```js
  function handleOnboardingComplete(result) {
    const value = {
      keywords: Array.isArray(result?.keywords) ? result.keywords : [],
      role: result?.role ?? null,
      age: result?.age ?? null,
    };
    setPrefs(value);
    try {
      localStorage.setItem(INTERESTS_KEY, JSON.stringify(value));
    } catch {
      // 저장 실패해도 이번 세션 동안은 상태로 유지됩니다.
    }
    setView('dash');
  }
```

`setView('dash');` 바로 다음 줄에 추가(함수 닫는 중괄호 앞):

```js
    setEntryStep(null);
```

- [ ] **Step 5: `navigateTo`에 게스트 가드 추가**

기존:

```js
  function navigateTo(key, payload) {
    setView(key);
    if (key === 'wiki' && payload) setWikiDocId(payload);
    setDrawerOpen(false);
    setSheetOpen(false);
  }
```

아래로 교체:

```js
  function navigateTo(key, payload) {
    if (guestMode && key !== 'dash') {
      // 게스트는 대시보드 외 메뉴를 못 본다 — 화면 전환 대신 로그인 유도(프로필 드롭다운 오픈).
      setProfileOpen(true);
      return;
    }
    setView(key);
    if (key === 'wiki' && payload) setWikiDocId(payload);
    setDrawerOpen(false);
    setSheetOpen(false);
  }
```

- [ ] **Step 6: `handleLogout`에 `guestMode` 초기화 추가**

기존:

```js
  function handleLogout() {
    setProfileOpen(false);
    signOut();
  }
```

아래로 교체:

```js
  function handleLogout() {
    setProfileOpen(false);
    setGuestMode(false);
    signOut();
  }
```

- [ ] **Step 7: 최상위 렌더 분기 교체**

기존:

```js
  // 첫 진입 — 선호 조사 화면. 앱 뼈대(상단바/내비)를 띄우지 않고 이 화면만 보여줍니다.
  if (prefs === null) {
    return <OnboardingPage onComplete={handleOnboardingComplete} />;
  }
```

아래로 교체:

```js
  // 세션 확인이 끝나기 전엔 아무것도 그리지 않는다(로그인된 사용자가 잠깐 랜딩으로
  // 잘못 보이는 걸 막기 위함 — 확인은 보통 수백ms 안에 끝나서 별도 스피너 없이도 자연스럽다).
  if (!authChecked) {
    return null;
  }

  // 신규 계정 로그인 직후 — 사람확인/로그인 없이 곧장 선호조사.
  if (entryStep === 'survey') {
    return (
      <EntryFlow
        initialStep="survey"
        onSurveyComplete={handleOnboardingComplete}
        onGuestSkip={() => {}}
      />
    );
  }

  // 첫 방문(세션 없음, 게스트도 아님) — 랜딩부터.
  if (entryStep === 'landing' && !guestMode) {
    return (
      <EntryFlow
        initialStep="landing"
        onSurveyComplete={handleOnboardingComplete}
        onGuestSkip={() => {
          setGuestMode(true);
          setPrefs({ keywords: [], role: null, age: null });
        }}
      />
    );
  }
```

- [ ] **Step 8: 로컬 dev 서버로 4가지 경로 수동 확인**

`.claude/launch.json`이 없다면 만들고(`{"version":"0.0.1","configurations":[{"name":"frontend-dev","runtimeExecutable":"npm","runtimeArgs":["--prefix","frontend","run","dev"],"port":5173}]}`), `frontend/.env.local`에 `VITE_USE_MOCK=false`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`(anon key는 공개 키라 Supabase 대시보드 또는 MCP `get_publishable_keys`로 확인 가능), `VITE_API_BASE_URL`을 채운 뒤 dev 서버를 띄워서 브라우저로 직접 확인한다(로그인 완료까지는 실제 계정이 필요해서 여기선 랜딩/게스트 경로 위주로 확인):

- 브라우저 `localStorage`를 비우고 새로고침 → 랜딩 화면(브랜드/헤드라인/기능 카드 4개/버튼 3개) 노출 확인
- "건너뛰고 둘러보기" 클릭 → 대시보드 진입, 사이드바에서 "위키" 등 클릭 → 화면 전환 없이 프로필 드롭다운이 열리는지 확인
- "로그인"/"회원가입" 클릭 → 사람확인(체크박스 클릭 → 0.7초 후 체크됨 → 다음 버튼 활성화) → 로그인 화면(Google/GitHub 버튼, "이전" 버튼으로 사람확인으로 돌아가는지)까지 확인. 실제 OAuth 리다이렉트(계정 로그인 완료)는 배포 후 실사용자 계정으로 확인(로컬은 CORS로 백엔드 응답을 못 받으므로 이 두 화면의 UI 동작까지만 확인).
- 완료 후 `frontend/.env.local`은 삭제(커밋 대상 아님, `.gitignore`에 이미 포함).

- [ ] **Step 9: 빌드 확인**

Run: `cd frontend && npm run build`
Expected: `✓ built` 로 종료, 에러 없음.

- [ ] **Step 10: 커밋**

```bash
git add frontend/src/App.jsx
git commit -m "Feat: App.jsx에 EntryFlow 연결 — 랜딩/게스트/신규가입 온보딩/로그아웃 라우팅"
```

---

## Task 5: PR 생성

**Files:** 없음(문서화·PR 작업)

- [ ] **Step 1: 중복 브랜치/PR 확인**

Run: `gh pr list --state open`
Expected: 이 기능과 겹치는 열린 PR이 없어야 함(있다면 진행 전에 사용자에게 보고).

- [ ] **Step 2: origin/develop-frontend 기준으로 최신인지 확인 후 push**

```bash
git fetch origin
git log --oneline origin/develop-frontend..HEAD
git push -u origin feature/entry-flow-landing-auth
```

- [ ] **Step 3: PR 생성**

`gh pr create --base develop-frontend --head feature/entry-flow-landing-auth`로, 협업 규칙(`collaboration_rule.md`)의 PR 템플릿(작업 내용/변경 이유/테스트 결과/참고 사항/관련 Issue)에 맞춰 본문을 작성한다. 이 세션에서 설계 논의부터 진행한 내용(원본 시안 CSS 재사용, 신규/기존 판단 방식, 게스트 모드 동작)을 요약해서 담는다.


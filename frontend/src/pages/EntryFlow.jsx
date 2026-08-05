// 진입 플로우 — 랜딩(0) → 사람확인(1) → 로그인(2) → 선호조사(3, OnboardingPage 재사용) → 대시보드(4).
// 랜딩의 "건너뛰고 둘러보기"는 미리보기(preview) 화면만 보여주고 이 플로우 안에서 끝난다 —
// 실제 데이터가 연동된 메인 대시보드는 로그인해야만 볼 수 있다(App.jsx는 guestMode를 두지 않는다).
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
// .ob-perks/.ob-switch-intent/.ob-linklike 세 개만 이번에 globals.css 끝에 새로 추가했다.

import { useState } from 'react';
import { signInWithProvider } from '../api/auth';
import { LANDING_FEATURES } from '../data/mockOnboarding';
import OnboardingPage from './OnboardingPage';

// ProfilePanel.jsx의 OAUTH_PROVIDERS와 동일하게 유지한다(둘 중 하나만 고치면 화면마다 버튼이 달라진다).
// 카카오는 Supabase provider 비활성 상태라 제외. 네이버는 Custom Providers(OIDC)라
// key가 'naver'가 아니라 대시보드의 Provider Identifier인 'custom:naver'다.
const OAUTH_PROVIDERS = [
  { key: 'google', label: 'Google로 계속하기', ic: 'G' },
  { key: 'github', label: 'GitHub로 계속하기', ic: 'Gh' },
  { key: 'custom:naver', label: '네이버로 계속하기', ic: 'N' },
];

// 로그인/회원가입 화면 — OAuth 버튼은 같지만 위 안내문과 혜택 목록을 다르게 보여준다.
const AUTH_COPY = {
  login: {
    heading: '로그인해주세요',
    sub: '계정으로 계속하면 관심 키워드·위키·리포트를 이어서 볼 수 있습니다.',
    perks: null,
  },
  signup: {
    heading: '가입하고 무료로 시작하기',
    sub: '몇 초면 가입이 끝나요. 아래 계정 중 하나로 바로 시작할 수 있습니다.',
    perks: [
      '관심 키워드 기반 맞춤 뉴스·이슈 알림',
      '자동 생성되는 위키 문서와 일일 동향 리포트',
      'AI 에이전트에게 근거를 물어보고 답변을 위키에 저장',
    ],
  },
};

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

export default function EntryFlow({ initialStep, onSurveyComplete }) {
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
              <button type="button" className="ob-skip" onClick={() => setStep('preview')}>
                건너뛰고 둘러보기
              </button>
            </div>
          </div>
        </div>
      )}

      {step === 'preview' && (
        <div className="ob-screen on">
          <div className="ob-card">
            <div className="ob-logo">
              <div className="ob-eb">MYWIKI</div>
              <div className="ob-nm">myWiki</div>
            </div>
            <div className="ob-h">둘러보기는 여기까지예요</div>
            <div className="ob-sub">
              실제 데이터가 연동된 메인 대시보드·위키·리포트는 로그인 후에 볼 수 있습니다.
              아래는 로그인하면 만나게 될 화면들입니다.
            </div>
            <div className="landing-features">
              {LANDING_FEATURES.map((f) => (
                <div className="lf-card" key={f.title}>
                  <div className="lf-ic">{f.icon}</div>
                  <div className="lf-t">{f.title}</div>
                  <div className="lf-d">{f.desc}</div>
                </div>
              ))}
            </div>
            <div className="ob-actions">
              <button type="button" className="ob-skip" onClick={() => setStep('landing')}>
                이전
              </button>
              <button type="button" className="ob-next" onClick={() => startAuth('signup')}>
                회원가입하고 시작하기
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
            <div className="ob-h">{AUTH_COPY[intent].heading}</div>
            <div className="ob-sub">{AUTH_COPY[intent].sub}</div>
            {AUTH_COPY[intent].perks && (
              <ul className="ob-perks">
                {AUTH_COPY[intent].perks.map((perk) => (
                  <li key={perk}>{perk}</li>
                ))}
              </ul>
            )}
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
            <div className="ob-switch-intent">
              {intent === 'signup' ? (
                <>
                  이미 계정이 있으신가요?{' '}
                  <button type="button" className="ob-linklike" onClick={() => setIntent('login')}>
                    로그인
                  </button>
                </>
              ) : (
                <>
                  아직 계정이 없으신가요?{' '}
                  <button type="button" className="ob-linklike" onClick={() => setIntent('signup')}>
                    회원가입
                  </button>
                </>
              )}
            </div>
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

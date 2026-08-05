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
// 네이버는 Supabase 기본 provider가 아니라 Custom Providers(OIDC)로 등록했다.
// 그래서 key가 'naver'가 아니라 대시보드의 Provider Identifier인 'custom:naver'다.
const OAUTH_PROVIDERS = [
  { key: 'google', label: 'Google로 계속하기', ic: 'G' },
  { key: 'github', label: 'GitHub로 계속하기', ic: 'Gh' },
  { key: 'custom:naver', label: '네이버로 계속하기', ic: 'N' },
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

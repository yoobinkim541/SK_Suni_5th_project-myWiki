// 진입 플로우 — 랜딩(0) → 사람확인(1) → 로그인(2) → 선호조사(3, OnboardingPage 재사용) → 대시보드(4).
// 로그인/회원가입 화면의 "건너뛰기"를 누르면 App.jsx의 onGuestSkip이 호출돼 실데이터가
// 붙은 진짜 메인 대시보드로 곧장 들어간다(게스트 모드) — 대시보드 말고 다른 메뉴로 가려고
// 하면 App.jsx가 화면 전환 대신 프로필 드롭다운(우측 상단, Google·GitHub·네이버 로그인)을
// 열어서 로그인을 유도한다.
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
// CSS는 대부분 globals.css에 이미 있던 원본 시안 클래스를 그대로 쓴다(.ob-*, .pp-oauth) —
// 랜딩(0단계)만 마케팅 사이트 스타일(상단 네비 + 좌측 헤드라인/CTA + 우측 브랜드 비주얼)로
// 다시 짜면서 .landing-nav-*/.landing-hero-*/.landing-mock-* 클래스를 새로 추가했다.
// "무료로 시작하기"는 "시작하기"로 이름만 바꾸고 동작은 그대로 startAuth('signup') —
// 눌러도 곧장 대시보드로 가는 게 아니라 기존 흐름대로 사람 확인(gate)부터 순서대로 나온다.
// ⚠ 우측 비주얼: 처음엔 KPI 숫자·사이드바 항목 같은 가짜 대시보드 데이터를 미니어처로
// 재현했는데("이상하다"는 피드백) — 실제 값도 아닌 걸 화면처럼 보여주는 게 오해를 줄 수
// 있어서, 지금은 숫자·라벨 없이 로고 + 브랜드 컬러 도형 + 지식 축적화 그래프 느낌의 점
// 패턴만 남긴 순수 디자인 구성으로 바꿨다(실제 데이터/화면 캡처 아님).

import { useState } from 'react';
import { signInWithProvider } from '../api/auth';
import OnboardingPage from './OnboardingPage';
import logo from '../assets/logo.png';
import logoDark from '../assets/logo-dark.png';

// 우측 화면 시안 전용 — 실제 SideNav.jsx의 NAV_ITEMS와 같은 라벨(장식용, 아이콘은 생략).
const MOCK_SIDE_ITEMS = ['대시보드', '일일 리포트', '카테고리 현황', '위키', '에이전트', '설정'];
const MOCK_KPIS = [
  { label: '수집 문서', value: '312' },
  { label: '생성 보고서', value: '18' },
  { label: '위키 문서', value: '124' },
  { label: '평균 신뢰도', value: '보통' },
];
// 지식 축적화 그래프 미니어처 — KnowledgeGraph.jsx와 같은 6방향 배치 + 실제 카테고리 이름.
const MOCK_GRAPH_NODES = [
  { deg: 0, label: '제품' },
  { deg: 60, label: '경쟁사' },
  { deg: 120, label: '고객' },
  { deg: 180, label: '공급망' },
  { deg: 240, label: '정책' },
  { deg: 300, label: '시장' },
];

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
    <div className={`ob-stage${step === 'landing' ? ' ob-stage-landing' : ''}`}>
      {step === 'landing' && (
        <div className="ob-screen ob-landing on">
          <header className="landing-nav">
            <div className="landing-nav-logo">myWiki</div>
            <div className="landing-nav-auth">
              <button type="button" className="landing-nav-login" onClick={() => startAuth('login')}>
                로그인
              </button>
              <button type="button" className="landing-nav-signup" onClick={() => startAuth('signup')}>
                회원가입
              </button>
            </div>
          </header>

          <div className="landing-hero">
            <div className="landing-hero-left">
              <h1>
                반도체 업계 동향,
                <br />
                <em>놓치지 않고</em> 한눈에
              </h1>
              <p className="landing-sub">
                뉴스 수집부터 신뢰도 검증, 위키 정리, 리포트까지 — 반도체 도메인 뉴스를 자동으로
                정리해드립니다.
              </p>
              <div className="landing-hero-cta">
                <button type="button" className="landing-cta" onClick={() => startAuth('signup')}>
                  시작하기
                </button>
                <button type="button" className="ob-skip landing-cta-skip" onClick={onGuestSkip}>
                  건너뛰고 둘러보기
                </button>
              </div>
            </div>

            <div className="landing-hero-right">
              {/* 실제 메인 대시보드 화면 구성(사이드바 메뉴 + KPI + 지식 축적화 그래프)을
                  그대로 축소 재현한 화면 시안 — 우리 사이트가 뭘 보여주는지 한눈에 전달하려는
                  목적이라, 숫자·라벨은 실제 화면과 같은 자리에 예시로 채워 넣었다(실데이터
                  스크린샷은 아님). 오른쪽 아래에 겹쳐진 카드는 "산업 동향 분석" 그래프 미니어처. */}
              <div className="landing-mock" aria-hidden="true">
                <div className="landing-mock-titlebar">
                  <span className="lm-dot lm-dot-r" />
                  <span className="lm-dot lm-dot-y" />
                  <span className="lm-dot lm-dot-g" />
                  <span className="landing-mock-titlebar-t">메인 대시보드</span>
                </div>
                <div className="landing-mock-body">
                  <div className="landing-mock-side">
                    <div className="lm-side-brand">
                      <img src={logo} alt="" className="logo-light" />
                      <img src={logoDark} alt="" className="logo-dark" />
                    </div>
                    {MOCK_SIDE_ITEMS.map((label, i) => (
                      <span key={label} className={`lm-side-item${i === 0 ? ' on' : ''}`}>
                        {label}
                      </span>
                    ))}
                  </div>
                  <div className="landing-mock-main">
                    <div className="lm-kpi-row">
                      {MOCK_KPIS.map((k) => (
                        <div className="lm-kpi" key={k.label}>
                          <span>{k.label}</span>
                          <b>{k.value}</b>
                        </div>
                      ))}
                    </div>
                    <div className="lm-graph">
                      <span className="lm-graph-label">지식 축적화</span>
                      <div className="lm-graph-canvas">
                        <span className="lm-hub" />
                        {MOCK_GRAPH_NODES.map((node) => (
                          <span
                            key={node.deg}
                            className="lm-node-wrap"
                            style={{ transform: `rotate(${node.deg}deg) translate(52px)` }}
                          >
                            <span className="lm-node" style={{ transform: `rotate(${-node.deg}deg)` }}>
                              {node.label}
                            </span>
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div className="landing-mock-chart">
                <div className="lmc-h">산업 동향 분석</div>
                <svg className="lmc-svg" viewBox="0 0 160 56" preserveAspectRatio="none">
                  <polyline
                    points="0,40 22,30 44,34 66,18 88,24 110,10 132,16 160,4"
                    fill="none" stroke="var(--green)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"
                  />
                </svg>
              </div>
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
              <button type="button" className="ob-skip" onClick={onGuestSkip}>
                건너뛰기
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

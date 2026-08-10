import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import './styles/globals.css';
// ⚠ CSS 안의 다크모드 규칙이 `:root[data-theme="dark"]{...}` 형태라서(문서 <html> 기준),
//   App.jsx가 <html>에 data-theme을 설정하도록 고쳐놨습니다. 이 파일은 전역 CSS를 한 번만
//   import하면 되는 구조라 그대로 두면 됩니다 — 여기서 따로 수정할 건 없었어요.
//
// Tailwind는 globals.css *뒤에* 불러옵니다 — preflight(리셋)는 껐지만(tailwind.config.js),
// 새로 작성하는 컴포넌트가 반응형 유틸리티 클래스(sm:/md:/lg: 등)로 기존 스타일을 자연스럽게
// 덮어쓸 수 있으려면 로드 순서상 뒤에 와야 합니다. 기존 컴포넌트는 지금 당장 아무 영향 없습니다.
import './styles/tailwind.css';

// 개발 중 로그인 없이 특정 화면만 빨리 확인하고 싶을 때 쓰는 우회 경로.
// import.meta.env.DEV로 감싸서 프로덕션 빌드(vite build)에는 이 코드 자체가 포함되지 않는다.
// 사용법: 로컬 dev 서버에서 http://localhost:5173/?previewOnboarding=1 또는 ?previewDashboard=1,
// ?previewAgent=1 로 접속.
let DevEntry = App;
const devPreview = new URLSearchParams(location.search).get('previewOnboarding')
  ? 'onboarding'
  : new URLSearchParams(location.search).has('previewDashboard')
  ? 'dashboard'
  : new URLSearchParams(location.search).has('previewAgent')
  ? 'agent'
  : null;
if (import.meta.env.DEV && devPreview === 'onboarding') {
  const { default: OnboardingPage } = await import('./pages/OnboardingPage');
  DevEntry = () => (
    <OnboardingPage onComplete={(r) => console.log('[dev preview] onComplete', r)} />
  );
} else if (import.meta.env.DEV && devPreview === 'dashboard') {
  const { default: DashboardPage } = await import('./pages/DashboardPage');
  DevEntry = () => <DashboardPage interests={[]} />;
} else if (import.meta.env.DEV && devPreview === 'agent') {
  // 실 로그인/백엔드 없이 AgentPage만 확인 — myProfile.display_name을 profile의
  // user_metadata.full_name과 일부러 다르게 줘서, 배너/작성자 표시가 어느 쪽을
  // 우선하는지(실제 프로필이 우선해야 함) 눈으로 바로 구분할 수 있게 한다.
  const { default: AgentPage } = await import('./pages/AgentPage');
  DevEntry = () => (
    <AgentPage
      profile={{ id: 'dev-user', email: 'dev@example.com', user_metadata: { full_name: '(구)OAuth 이름' } }}
      myProfile={{ id: 'dev-user', display_name: '(신)수정된 이름', has_avatar: false }}
    />
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <DevEntry />
    </BrowserRouter>
  </React.StrictMode>
);

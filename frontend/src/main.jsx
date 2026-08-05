import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles/globals.css';
// ⚠ CSS 안의 다크모드 규칙이 `:root[data-theme="dark"]{...}` 형태라서(문서 <html> 기준),
//   App.jsx가 <html>에 data-theme을 설정하도록 고쳐놨습니다. 이 파일은 전역 CSS를 한 번만
//   import하면 되는 구조라 그대로 두면 됩니다 — 여기서 따로 수정할 건 없었어요.

// 개발 중 로그인 없이 선호조사(OnboardingPage) 화면만 빨리 확인하고 싶을 때 쓰는 우회 경로.
// import.meta.env.DEV로 감싸서 프로덕션 빌드(vite build)에는 이 코드 자체가 포함되지 않는다.
// 사용법: 로컬 dev 서버에서 http://localhost:5173/?previewOnboarding=1 로 접속.
let DevEntry = App;
if (import.meta.env.DEV && new URLSearchParams(location.search).has('previewOnboarding')) {
  const { default: OnboardingPage } = await import('./pages/OnboardingPage');
  DevEntry = () => (
    <OnboardingPage onComplete={(r) => console.log('[dev preview] onComplete', r)} />
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <DevEntry />
  </React.StrictMode>
);

import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles/globals.css';
// ⚠ CSS 안의 다크모드 규칙이 `:root[data-theme="dark"]{...}` 형태라서(문서 <html> 기준),
//   App.jsx가 <html>에 data-theme을 설정하도록 고쳐놨습니다. 이 파일은 전역 CSS를 한 번만
//   import하면 되는 구조라 그대로 두면 됩니다 — 여기서 따로 수정할 건 없었어요.

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

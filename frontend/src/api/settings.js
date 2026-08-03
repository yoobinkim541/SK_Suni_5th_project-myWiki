// SettingsPage.jsx 자체 문구대로("이 브라우저에만 저장됩니다") 다크모드/글자크기는
// 서버 API가 아니라 localStorage로만 다룬다 — 백엔드 연결 대상이 아님, 여기 정리만 해둠.
// App.jsx의 dark/fontSize useState를 이 함수들로 감싸면 새로고침해도 유지된다.
const KEY = 'mywiki-settings';

export function loadSettings() {
  try {
    return JSON.parse(localStorage.getItem(KEY)) ?? { dark: false, fontSize: 'm' };
  } catch {
    return { dark: false, fontSize: 'm' };
  }
}

export function saveSettings(settings) {
  try {
    localStorage.setItem(KEY, JSON.stringify(settings));
  } catch {
    /* noop — 저장 실패해도 화면 동작에는 지장 없음 */
  }
}

// [대기 · 미정] "데이터·파이프라인 / 앱·소스" 섹션(SettingsPage.jsx TODO)은
// 백엔드 API 명세가 아직 없음 — 무엇을 보여줄지부터 정해야 함(수집 소스 목록? 연동 상태?).

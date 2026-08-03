// 공통 컴포넌트 6/6 — 켜고 끄는 스위치 (다크모드, 알림 등에서 재사용)
//
// 확인 결과 .switch 클래스는 다크모드/알림 토글 등에서 이미 쓰이고 있어서
// 고칠 게 없었습니다. 그대로 쓰시면 됩니다.

export default function ToggleSwitch({ checked, onChange }) {
  return (
    <button
      className={`switch${checked ? ' on' : ''}`}
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
    >
      <i></i>
    </button>
  );
}

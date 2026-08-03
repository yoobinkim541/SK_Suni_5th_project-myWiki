// 설정 페이지 전용 — 한 줄(.set-row) = 왼쪽 라벨/설명 + 오른쪽 컨트롤
// 오른쪽 컨트롤이 토글/세그먼트/입력창/버튼/고정값 등 종류가 다 달라서
// 그냥 children으로 받습니다. (예: <SettingsRow label="다크 모드" desc="...">
//   <ToggleSwitch .../></SettingsRow>)

export default function SettingsRow({ label, desc, children }) {
  return (
    <div className="set-row">
      <div className="tx">
        <div className="nm">{label}</div>
        <div className="ds">{desc}</div>
      </div>
      {children}
    </div>
  );
}

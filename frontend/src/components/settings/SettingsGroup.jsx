// 설정 페이지 전용 — 섹션 하나(제목 + 카드). 시안 마크업: .set-lb 다음에 .set-card
// 안에 SettingsRow 여러 개가 들어가는 구조를 그대로 컴포넌트로 뺐습니다.
// (예: <SettingsGroup title="계정 설정"><SettingsRow .../><SettingsRow .../></SettingsGroup>)

export default function SettingsGroup({ title, children }) {
  return (
    <>
      <div className="set-lb">{title}</div>
      <div className="set-card">{children}</div>
    </>
  );
}

// 공통 컴포넌트 4/6 — 설정 드롭다운 패널 (톱니바퀴 눌렀을 때 나오는 것)
// PC/모바일 공용. 화면 하나짜리 설정 페이지(v-settings)와는 다른 컴포넌트입니다.
//
// .settings-panel/.sp-row 클래스는 이미 시안에 정의돼 있고, 여기서 쓰는
// ToggleSwitch/SegmentedControl도 문제 없어서 그대로 씁니다.
//
// ⚠ 알림 토글 추가: 다크모드·글자크기만 있던 자리에 "알림" 그룹을 더했습니다.
//   상단바에서 바로 알림을 켜고 끌 수 있게 하려는 용도입니다. 이 토글은 SettingsPage.jsx의
//   "알림" 섹션과 같은 state(App.jsx에서 내려주는 notiReport/notiWiki)를 공유합니다 —
//   여기서 꺼도 설정 페이지에서 다시 켜져 있는 식으로 어긋나지 않습니다.

import ToggleSwitch from './ToggleSwitch';
import SegmentedControl from './SegmentedControl';

export default function SettingsPanel({
  isOpen,
  dark,
  onToggleDark,
  fontSize,
  onFontSizeChange,
  notiReport,
  onToggleNotiReport,
  notiWiki,
  onToggleNotiWiki,
}) {
  return (
    <div className={`settings-panel${isOpen ? ' open' : ''}`}>
      <h4>화면</h4>
      <div className="sp-row">
        <span>다크 모드</span>
        <ToggleSwitch checked={dark} onChange={onToggleDark} />
      </div>
      <div className="sp-row">
        <span>글자 크기</span>
        <SegmentedControl
          options={[
            { value: 's', label: '작게' },
            { value: 'm', label: '기본' },
            { value: 'l', label: '크게' },
          ]}
          value={fontSize}
          onChange={onFontSizeChange}
        />
      </div>
      <h4>알림</h4>
      <div className="sp-row">
        <span>일일 리포트 생성 알림</span>
        <ToggleSwitch checked={notiReport} onChange={onToggleNotiReport} />
      </div>
      <div className="sp-row">
        <span>Wiki 업데이트 알림</span>
        <ToggleSwitch checked={notiWiki} onChange={onToggleNotiWiki} />
      </div>
      <div className="sp-row sp-sub">이 기기의 브라우저에만 저장됩니다. · myWiki v0.4</div>
    </div>
  );
}

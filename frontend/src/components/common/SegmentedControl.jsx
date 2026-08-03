// 공통 컴포넌트 (SettingsPanel 안에서 쓰는 "작게/기본/크게" 같은 버튼 그룹)
//
// 확인 결과 .sp-seg 클래스는 이미 시안에 정의돼 있어서 고칠 게 없었습니다. 그대로 쓰시면 됩니다.

export default function SegmentedControl({ options, value, onChange }) {
  return (
    <div className="sp-seg">
      {options.map((opt) => (
        <button
          key={opt.value}
          className={value === opt.value ? 'on' : ''}
          onClick={() => onChange(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

// 공용 로고 아이콘 — PC 상단바/사이드바, 모바일 상단바/드로어 네 곳이 전부 이 컴포넌트를 씁니다.
// 래스터 이미지가 아니라 SVG라, 다크모드 전환 시 별도 필터 없이 var(--green) 하나로
// 라이트(#175243 짙은 그린) → 다크(#5cbf9a 민트 그린)로 그대로 따라갑니다.
// 안쪽 3줄 + 짧은 포인트 줄은 var(--panel)로 뚫어내서, 테마가 바뀌어도 아이콘 배경색과
// 항상 대비되는 색으로 자동 반전됩니다(라이트: 흰 줄 위 짙은 그린 / 다크: 짙은 줄 위 민트 그린).

export default function LogoMark({ className = '' }) {
  return (
    <svg
      className={`logo-mark${className ? ` ${className}` : ''}`}
      viewBox="0 0 28 28"
      aria-hidden="true"
    >
      <rect x="5" y="9" width="15" height="17" rx="4" fill="var(--green)" opacity="0.45" />
      <rect x="9" y="4" width="15" height="17" rx="4" fill="var(--green)" />
      <rect x="13" y="9" width="7" height="2" rx="1" fill="var(--panel)" />
      <rect x="13" y="13" width="7" height="2" rx="1" fill="var(--panel)" />
      <rect x="13" y="17" width="7" height="2" rx="1" fill="var(--panel)" />
      <rect x="13" y="21" width="3.5" height="2" rx="1" fill="#e8c46c" />
    </svg>
  );
}

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
      {/* 왼쪽: 접힌 모서리 문서 + 가로줄 3개 */}
      <path
        d="M4 3.5C4 2.67 4.67 2 5.5 2H13l4 4v16.5c0 .83-.67 1.5-1.5 1.5h-11
           c-.83 0-1.5-.67-1.5-1.5v-19z"
        fill="var(--green)"
      />
      <path d="M13 2 17 6h-3.3c-.39 0-.7-.31-.7-.7V2z" fill="var(--panel)" opacity="0.55" />
      <rect x="6.5" y="11" width="8" height="1.8" rx="0.9" fill="var(--panel)" />
      <rect x="6.5" y="15" width="8" height="1.8" rx="0.9" fill="var(--panel)" />
      <rect x="6.5" y="19" width="5.5" height="1.8" rx="0.9" fill="var(--panel)" />

      {/* 오른쪽: 노드 네트워크(그래프) 아이콘 — 허브(짙은 그린) + 리프 3개(진한 1 · 연한 민트 2) */}
      <g stroke="var(--green)" strokeWidth="1.4" fill="none">
        <line x1="16.5" y1="14" x2="20.5" y2="8" />
        <line x1="16.5" y1="14" x2="24" y2="12.5" />
        <line x1="16.5" y1="14" x2="14" y2="20.5" />
      </g>
      <circle cx="20.5" cy="8" r="1.9" fill="var(--green)" />
      <circle cx="16.5" cy="14" r="2.3" fill="var(--green)" />
      <circle cx="24" cy="12.5" r="2" fill="#6fa79d" />
      <circle cx="14" cy="20.5" r="2" fill="#6fa79d" />
    </svg>
  );
}

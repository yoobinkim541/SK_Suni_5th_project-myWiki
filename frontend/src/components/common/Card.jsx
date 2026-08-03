// 공통 컴포넌트 5/6 — 흰 배경 카드 틀
// 대시보드 KPI, 카테고리 목록 등 거의 모든 화면에서 이 위에 내용을 얹습니다.
//
// ⚠ 수정한 부분: className을 "cd"에서 "panel-card"로 바꿨습니다.
//   시안 CSS에서 ".cd"는 이미 카테고리 현황 카드 전용 클래스로 쓰이고 있고
//   (배지+대표 이슈+태그+신뢰도 구조를 가정한 아주 구체적인 스타일이라
//   여기서 재사용하면 자식 마크업이 안 맞아서 이상하게 깨져 보입니다),
//   실제로 시안에는 "어디서나 쓰는 흰 카드 틀" 클래스가 따로 없었어서
//   .set-card(설정 페이지 카드)와 같은 스타일로 .panel-card를 새로 만들어 매핑했습니다.

export default function Card({ children, className = '' }) {
  return <div className={`panel-card ${className}`.trim()}>{children}</div>;
}

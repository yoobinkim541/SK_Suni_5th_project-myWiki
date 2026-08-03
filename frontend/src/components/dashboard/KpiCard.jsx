// 대시보드/카테고리 현황 공용 — KPI 숫자 카드
// 시안 마크업: <div><div class="k">라벨</div><div class="v[ txt]">값</div><div class="d">보조 텍스트</div></div>
// value가 "312" 같은 숫자가 아니라 "보통", "제품·기술" 같은 텍스트 값이면 isText로 .v txt 클래스를 붙입니다.
// desc 안에서 강조하고 싶은 부분은 호출하는 쪽에서 <b>+48</b> 처럼 JSX로 바로 넣으면 됩니다.
//
// 확인차 메모: "평균 신뢰도" KPI(값 "보통")는 색상 없이 기본 텍스트색으로 표시하기로 확정했습니다.
// 즉 이 컴포넌트에는 색상(tone) prop을 따로 두지 않습니다 — 그대로 쓰면 원하는 대로(검은 글자) 렌더링됩니다.
// (반대로 색을 넣고 싶은 값이 생기면 그때 tone?: 'hi'|'mid'|'low' 같은 prop을 추가해 className에
//  `lvl ${tone}`을 붙이는 방식으로 확장하면 되는데, 지금은 필요 없습니다.)
export default function KpiCard({ label, value, desc, isText = false }) {
  return (
    <div>
      <div className="k">{label}</div>
      <div className={`v${isText ? ' txt' : ''}`}>{value}</div>
      {desc && <div className="d">{desc}</div>}
    </div>
  );
}

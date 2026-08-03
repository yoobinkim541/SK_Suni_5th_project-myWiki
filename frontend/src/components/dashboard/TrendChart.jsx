// 대시보드 전용 — "산업 동향 분석" 추이 차트
// 막대 = 일별 수집 문서 수, 선 = 일별 정제 후 채택 건수.
// data가 없으면 data/mockDashboard.js의 MOCK_TREND(최근 7일)를 기본값으로 씁니다.
// 차트 자체는 시안의 SVG 구조(.grid/.bars/.area/.line/.dots/.yl/.xl/.now)를 그대로 유지하고,
// 좌표만 data 배열로부터 계산합니다. 실제 값 연동 시 data prop만 갈아끼우면 됩니다.
//
// 반응형 참고: 이 차트는 이 파일에서 바꿀 게 없습니다.
// 시안 CSS가 `.chart svg{ width:100%; height:auto; }`로 이미 처리하고 있어서
// viewBox 비율(730:212)을 유지한 채 부모 폭에 맞춰 자동으로 축소됩니다.
// 범례(.chart-legend)도 flex-wrap:wrap이라 좁은 화면에서 알아서 줄바꿈됩니다.
// → 모바일 대응을 위해 이 컴포넌트에서 별도로 분기할 내용은 없습니다.

import { MOCK_TREND } from '../../data/mockDashboard';

const CHART_W = 730;
const CHART_H = 212;
const PLOT_LEFT = 44;
const PLOT_RIGHT = 712;
const PLOT_TOP = 16;
const PLOT_BOTTOM = 176;
const BAR_W = 24;

export default function TrendChart({ data = MOCK_TREND }) {
  const maxVal = 320;
  const yTicks = [320, 240, 160, 80, 0];

  const step = (PLOT_RIGHT - PLOT_LEFT - BAR_W) / Math.max(data.length - 1, 1);
  const barX = (i) => PLOT_LEFT + i * step;
  const barY = (v) => PLOT_BOTTOM - (v / maxVal) * (PLOT_BOTTOM - PLOT_TOP - 20);
  const lineX = (i) => barX(i) + BAR_W / 2;
  const lineY = (v) => PLOT_TOP + 8 + (1 - v / 100) * 40;

  const linePoints = data.map((d, i) => `${lineX(i)},${lineY(d.adopted)}`).join(' ');
  const areaPoints = `M${lineX(0)},${lineY(data[0].adopted)} ` +
    data.slice(1).map((d, i) => `L${lineX(i + 1)},${lineY(d.adopted)}`).join(' ') +
    ` L${lineX(data.length - 1)},${PLOT_BOTTOM} L${lineX(0)},${PLOT_BOTTOM} Z`;

  const today = data[data.length - 1];
  const avgCollected = Math.round(data.reduce((s, d) => s + d.collected, 0) / data.length);
  const avgAdoptRate = Math.round((data.reduce((s, d) => s + d.adopted / d.collected, 0) / data.length) * 100);

  return (
    <div className="chart">
      <svg viewBox={`0 0 ${CHART_W} ${CHART_H}`} role="img" aria-label="최근 수집 및 채택 건수 추이">
        <g className="grid">
          {yTicks.slice(0, -1).map((t) => (
            <line key={t} x1={PLOT_LEFT} y1={barY(t)} x2={PLOT_RIGHT} y2={barY(t)} />
          ))}
          <line className="ax" x1={PLOT_LEFT} y1={PLOT_BOTTOM} x2={PLOT_RIGHT} y2={PLOT_BOTTOM} />
        </g>
        {yTicks.map((t) => (
          <text key={t} className="yl" x={PLOT_LEFT - 8} y={barY(t) + 4}>{t}</text>
        ))}
        <g className="bars">
          {data.map((d, i) => (
            <rect
              key={d.date}
              className={i === data.length - 1 ? 'now' : undefined}
              x={barX(i)}
              y={barY(d.collected)}
              width={BAR_W}
              height={PLOT_BOTTOM - barY(d.collected)}
            />
          ))}
        </g>
        <path className="area" d={areaPoints} />
        <polyline className="line" points={linePoints} />
        <g className="dots">
          {data.slice(0, -1).map((d, i) => (
            <circle key={d.date} cx={lineX(i)} cy={lineY(d.adopted)} r="2.6" />
          ))}
        </g>
        <circle className="now-dot" cx={lineX(data.length - 1)} cy={lineY(today.adopted)} r="4" />
        <text className="now" x={lineX(data.length - 1)} y={lineY(today.adopted) - 9}>{today.collected}</text>
        {data.map((d, i) => (
          <text key={d.date} className="xl" x={lineX(i)} y={PLOT_BOTTOM + 22}>{d.date}</text>
        ))}
      </svg>
      <div className="chart-legend">
        <span><span className="mk"></span>수집 문서</span>
        <span><span className="mk bar"></span>정제 후 채택</span>
        <span>7일 평균 <b>{avgCollected}건</b></span>
        <span>평균 채택률 <b>{avgAdoptRate}%</b></span>
        <span>오늘 <b>{today.collected}건 수집 · {today.adopted}건 채택</b></span>
      </div>
    </div>
  );
}

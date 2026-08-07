// 대시보드 전용 — "산업 동향 분석" 추이 차트
// 막대 = 일별 수집 문서 수, 선 = 일별 정제 후 채택 건수.
//
// 데이터는 services/dashboardApi.js의 fetchTrend()가 넘겨줍니다.
// data/mockDashboard.js를 직접 import하지 않습니다 — 목업/실데이터 분기는
// services 한 곳에만 둡니다(레이어 규칙). data가 비면 빈 상태를 그립니다.
//
// 두 계열은 **같은 y축**을 씁니다. 예전에는 막대가 0~320 고정, 선이 0~100 별도
// 축이라 같은 그림 안에서 서로 다른 눈금을 읽어야 했고, 수집이 320을 넘으면
// 막대가 플롯 위로 뚫고 나갔습니다.
//
// ⚠ 오늘 채택 건수는 대체로 0에 가깝게 보입니다. 분석 배치가 수집보다 하루쯤
//   뒤처져서 생기는 결과이지 차트 버그가 아닙니다.
//
// 반응형 참고: 시안 CSS가 `.chart svg{ width:100%; height:auto; }`로 처리하므로
// viewBox 비율(730:212)을 유지한 채 부모 폭에 맞춰 자동으로 축소됩니다.
// 범례(.chart-legend)도 flex-wrap:wrap이라 좁은 화면에서 알아서 줄바꿈됩니다.

const CHART_W = 730;
const CHART_H = 212;
const PLOT_LEFT = 44;
const PLOT_RIGHT = 712;
const PLOT_TOP = 16;
const PLOT_BOTTOM = 176;
const BAR_W = 24;

// y축 눈금 개수(0 포함 5개 = 4구간). 상한을 4로 나눠 떨어지게 잡아야 눈금이 정수가 된다.
const TICK_STEPS = 4;

// 눈금 간격 후보(×10^n). 상한이 아니라 **간격**을 고르고 거기에 TICK_STEPS를 곱한다.
// 상한만 1·2·5×10^n으로 잡으면 135건일 때 상한이 200으로 튀어 막대가 플롯의 2/3까지밖에
// 안 차서 추이가 납작해 보인다. 간격을 고르면 160으로 잡혀 세로 공간을 제대로 쓴다.
const NICE_STEPS = [1, 2, 2.5, 4, 5, 10];

/**
 * 데이터 최대값을 담으면서 눈금이 읽기 좋은 y축 상한.
 * 실데이터가 하루 86~135건이면 상한이 100/160으로 잡히고 눈금은 25·40 단위가 된다.
 */
function niceCeiling(value) {
  if (!Number.isFinite(value) || value <= 0) return TICK_STEPS;
  const rawStep = value / TICK_STEPS;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const normalized = rawStep / magnitude;
  const step = NICE_STEPS.find((candidate) => candidate >= normalized) ?? 10;
  // 상한이 TICK_STEPS보다 작으면 눈금 간격이 1 미만이 돼 반올림 후 라벨이 겹친다
  // (최대 1건일 때 '1,1,1,0,0'). 눈금은 최소 1씩 벌린다.
  return Math.max(TICK_STEPS, step * magnitude * TICK_STEPS);
}

export default function TrendChart({ data = [] }) {
  // 데이터가 없으면 아래 좌표 계산이 data[0]을 읽다 터진다. 빈 상태로 빠진다.
  if (data.length === 0) {
    return (
      <div className="chart">
        <p className="chart-empty">표시할 추이 데이터가 없습니다.</p>
      </div>
    );
  }

  // 두 계열이 같은 축을 쓰므로 상한도 둘을 함께 보고 정한다.
  const peak = Math.max(...data.map((d) => Math.max(d.collected, d.adopted)));
  const maxVal = niceCeiling(peak);
  const yTicks = Array.from(
    { length: TICK_STEPS + 1 },
    (_, i) => (maxVal / TICK_STEPS) * (TICK_STEPS - i)
  );

  const step = (PLOT_RIGHT - PLOT_LEFT - BAR_W) / Math.max(data.length - 1, 1);
  const barX = (i) => PLOT_LEFT + i * step;
  // 막대와 선이 공유하는 단 하나의 y 변환.
  const scaleY = (v) => PLOT_BOTTOM - (v / maxVal) * (PLOT_BOTTOM - PLOT_TOP);
  const lineX = (i) => barX(i) + BAR_W / 2;

  const linePoints = data.map((d, i) => `${lineX(i)},${scaleY(d.adopted)}`).join(' ');
  const areaPoints =
    `M${lineX(0)},${scaleY(data[0].adopted)} ` +
    data.slice(1).map((d, i) => `L${lineX(i + 1)},${scaleY(d.adopted)}`).join(' ') +
    ` L${lineX(data.length - 1)},${PLOT_BOTTOM} L${lineX(0)},${PLOT_BOTTOM} Z`;

  const today = data[data.length - 1];
  const totalCollected = data.reduce((s, d) => s + d.collected, 0);
  const totalAdopted = data.reduce((s, d) => s + d.adopted, 0);
  const avgCollected = Math.round(totalCollected / data.length);
  // 하루씩 비율을 내서 평균 내면 수집 0건인 날에 0으로 나눠 NaN이 된다.
  // 실데이터에는 수집이 없는 날이 실제로 있다. 총합끼리 나눈다.
  const avgAdoptRate = totalCollected > 0 ? Math.round((totalAdopted / totalCollected) * 100) : 0;

  return (
    <div className="chart">
      <svg viewBox={`0 0 ${CHART_W} ${CHART_H}`} role="img" aria-label="최근 수집 및 채택 건수 추이">
        {/* TailAdmin 스타일 area 채우기 — 위는 진하고 아래로 갈수록 투명해진다.
            fill 자체는 globals.css의 .chart .area가 이 id를 가리켜서 적용한다
            (CSS가 presentation attribute보다 우선하므로 여기 attribute만으론 안 먹는다). */}
        <defs>
          <linearGradient id="trend-area-gradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#86AABD" stopOpacity="0.6" />
            <stop offset="100%" stopColor="#86AABD" stopOpacity="0.04" />
          </linearGradient>
        </defs>
        <g className="grid">
          {yTicks.slice(0, -1).map((t) => (
            <line key={t} x1={PLOT_LEFT} y1={scaleY(t)} x2={PLOT_RIGHT} y2={scaleY(t)} />
          ))}
          <line className="ax" x1={PLOT_LEFT} y1={PLOT_BOTTOM} x2={PLOT_RIGHT} y2={PLOT_BOTTOM} />
        </g>
        {yTicks.map((t) => (
          <text key={t} className="yl" x={PLOT_LEFT - 8} y={scaleY(t) + 4}>{Math.round(t)}</text>
        ))}
        <g className="bars">
          {data.map((d, i) => (
            <rect
              key={d.date}
              className={i === data.length - 1 ? 'now' : undefined}
              x={barX(i)}
              y={scaleY(d.collected)}
              width={BAR_W}
              height={PLOT_BOTTOM - scaleY(d.collected)}
            />
          ))}
        </g>
        <path className="area" d={areaPoints} />
        <polyline className="line" points={linePoints} />
        <g className="dots">
          {data.slice(0, -1).map((d, i) => (
            <circle key={d.date} cx={lineX(i)} cy={scaleY(d.adopted)} r="2.6" />
          ))}
        </g>
        <circle className="now-dot" cx={lineX(data.length - 1)} cy={scaleY(today.adopted)} r="4" />
        {/* 오늘 수집 건수는 막대 위에 붙인다. 예전에는 채택 선의 마지막 점 위에
            collected를 찍어서, 선을 가리키며 막대 값을 읽게 만들고 있었다. */}
        <text className="now" x={lineX(data.length - 1)} y={scaleY(today.collected) - 6}>
          {today.collected}
        </text>
        {data.map((d, i) => (
          <text key={d.date} className="xl" x={lineX(i)} y={PLOT_BOTTOM + 22}>{d.date}</text>
        ))}
      </svg>
      <div className="chart-legend">
        {/* .mk는 초록 선(2px), .mk.bar는 회색 사각형이다. 막대가 수집·선이 채택이므로
            예전 배치는 두 마커가 서로 반대 계열을 가리키고 있었다. */}
        <span><span className="mk bar"></span>수집 문서</span>
        <span><span className="mk"></span>정제 후 채택</span>
        <span>7일 평균 <b>{avgCollected}건</b></span>
        <span>평균 채택률 <b>{avgAdoptRate}%</b></span>
        <span>오늘 <b>{today.collected}건 수집 · {today.adopted}건 채택</b></span>
      </div>
    </div>
  );
}

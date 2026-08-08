// 대시보드 전용 — "산업 동향 분석" 최근 7일 뉴스 기사 수 추이 (꺾은선 + 영역)
//
// 데이터는 services/dashboardApi.js의 fetchTrend()가 넘겨줍니다.
// data/mockDashboard.js를 직접 import하지 않습니다 — 목업/실데이터 분기는
// services 한 곳에만 둡니다(레이어 규칙). data가 비면 빈 상태를 그립니다.
//
// ⚠ [2026-08-08] 막대(수집 문서) + 선(정제 후 채택) 이중 계열 구성을 걷어내고,
//   "최근 7일 뉴스 기사 수" 하나만 보여주는 단일 꺾은선 + 옅은 영역 채우기로 바꿨습니다.
//   막대를 없앤 건 디자인 방향 때문이지 데이터가 사라진 게 아닙니다 — d.collected(=기사 수)를
//   선으로 그리고, d.adopted(채택 건수)는 그대로 계산해서 하단 범례 텍스트로만 보여줍니다.
//   (그래프 계산에 쓰는 원본 데이터/필드는 그대로입니다. 시각화 방식만 바뀌었습니다.)
//
// 애니메이션: 마운트 시가 아니라 "화면에 스크롤돼 들어오는 시점"에 한 번만 —
// 이 차트는 대시보드 아래쪽(지식 축적화 그래프보다 한참 아래)에 있어서 마운트 시점엔
// 대개 뷰포트 밖이다. 그래서 IntersectionObserver로 실제로 보이기 시작할 때 .in 클래스를
// 붙이고(아래 useEffect), CSS 애니메이션은 그 클래스가 붙기 전까진 시작 상태(선 안 그려짐/
// 영역·점 투명)로 멈춰 있는다(globals.css `.chart-plot.in ...`). 한 번 보이면 다시 스크롤을
// 왔다갔다 해도 재생하지 않는다(observer를 그 시점에 끊는다) — loop 없이 딱 한 번만.
// stroke-dashoffset으로 선이 왼쪽에서 오른쪽으로 그려지고, 영역이 뒤이어 옅게 페이드인,
// 마지막으로 각 점이 선이 도착하는 타이밍에 맞춰 순서대로 나타난다.
// prefers-reduced-motion이면 전역 규칙(globals.css)이 모든 애니메이션 지속시간을
// 사실상 0으로 만들어 (보이자마자) 즉시 완성된 상태로 보인다.
//
// 반응형 참고: 시안 CSS가 `.chart svg{ width:100%; height:auto; }`로 처리하므로
// viewBox 비율(730:212)을 유지한 채 부모 폭에 맞춰 자동으로 축소됩니다.
// 범례(.chart-legend)도 flex-wrap:wrap이라 좁은 화면에서 알아서 줄바꿈됩니다.

import { useEffect, useRef, useState } from 'react';

const CHART_W = 730;
const CHART_H = 212;
const PLOT_LEFT = 44;
const PLOT_RIGHT = 712;
const PLOT_TOP = 16;
const PLOT_BOTTOM = 176;

// y축 눈금 개수(0 포함 5개 = 4구간). 상한을 4로 나눠 떨어지게 잡아야 눈금이 정수가 된다.
const TICK_STEPS = 4;

// 눈금 간격 후보(×10^n). 상한이 아니라 **간격**을 고르고 거기에 TICK_STEPS를 곱한다.
// 상한만 1·2·5×10^n으로 잡으면 135건일 때 상한이 200으로 튀어 선이 플롯의 2/3까지밖에
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

// date는 "MM.DD" 문자열(services/dashboardApi.js toTrendDay 참고). 툴팁 표시용으로만
// "8월 5일" 형태로 바꾼다 — 원본 필드/포맷 자체는 건드리지 않는다.
function formatTipDate(mmdd) {
  const [mm, dd] = mmdd.split('.').map(Number);
  if (!mm || !dd) return mmdd;
  return `${mm}월 ${dd}일`;
}

export default function TrendChart({ data = [] }) {
  const [hoverIdx, setHoverIdx] = useState(null);
  const [inView, setInView] = useState(false);
  const plotRef = useRef(null);

  useEffect(() => {
    const el = plotRef.current;
    if (!el) return;
    let done = false;
    function reveal() {
      if (done) return;
      done = true;
      setInView(true);
      cleanup();
    }
    // IntersectionObserver가 기본 경로다. 다만 이것만 믿지는 않는다 — 탭이 백그라운드거나
    // 컴포지팅이 지연되는 환경(KnowledgeGraph.jsx 쪽 기존 주석 참고)에서는 콜백 자체가
    // 아예 안 불릴 수 있다. 그래서 스크롤/리사이즈 때마다 실제 위치(getBoundingClientRect)를
    // 직접 확인하는 보강 경로를 같이 둔다 — 레이아웃 계산은 컴포지팅과 무관하게 항상
    // 동작하므로 더 안정적이다. 둘 중 뭐가 먼저 감지하든 한 번만 reveal되고 끝난다.
    function checkPosition() {
      const rect = el.getBoundingClientRect();
      const vh = window.innerHeight || document.documentElement.clientHeight;
      if (rect.top < vh * 0.85 && rect.bottom > 0) reveal();
    }
    let observer = null;
    if (typeof IntersectionObserver !== 'undefined') {
      observer = new IntersectionObserver(
        ([entry]) => {
          if (entry.isIntersecting) reveal();
        },
        { threshold: 0.3 }
      );
      observer.observe(el);
    }
    window.addEventListener('scroll', checkPosition, { passive: true });
    window.addEventListener('resize', checkPosition);
    checkPosition(); // 마운트 시점에 이미 화면 안이면(뷰포트가 큰 화면 등) 바로 확인한다.
    function cleanup() {
      observer?.disconnect();
      window.removeEventListener('scroll', checkPosition);
      window.removeEventListener('resize', checkPosition);
    }
    return cleanup;
  }, []);

  // 데이터가 없으면 아래 좌표 계산이 data[0]을 읽다 터진다. 빈 상태로 빠진다.
  if (data.length === 0) {
    return (
      <div className="chart">
        <p className="chart-empty">표시할 추이 데이터가 없습니다.</p>
      </div>
    );
  }

  const peak = Math.max(...data.map((d) => d.collected));
  const maxVal = niceCeiling(peak);
  const yTicks = Array.from(
    { length: TICK_STEPS + 1 },
    (_, i) => (maxVal / TICK_STEPS) * (TICK_STEPS - i)
  );

  const step = (PLOT_RIGHT - PLOT_LEFT) / Math.max(data.length - 1, 1);
  const pointX = (i) => PLOT_LEFT + i * step;
  const scaleY = (v) => PLOT_BOTTOM - (v / maxVal) * (PLOT_BOTTOM - PLOT_TOP);

  const linePoints = data.map((d, i) => `${pointX(i)},${scaleY(d.collected)}`).join(' ');
  const areaPoints =
    `M${pointX(0)},${scaleY(data[0].collected)} ` +
    data.slice(1).map((d, i) => `L${pointX(i + 1)},${scaleY(d.collected)}`).join(' ') +
    ` L${pointX(data.length - 1)},${PLOT_BOTTOM} L${pointX(0)},${PLOT_BOTTOM} Z`;

  const today = data[data.length - 1];
  const totalCollected = data.reduce((s, d) => s + d.collected, 0);
  const totalAdopted = data.reduce((s, d) => s + d.adopted, 0);
  const avgCollected = Math.round(totalCollected / data.length);
  // 하루씩 비율을 내서 평균 내면 수집 0건인 날에 0으로 나눠 NaN이 된다.
  // 실데이터에는 수집이 없는 날이 실제로 있다. 총합끼리 나눈다.
  const avgAdoptRate = totalCollected > 0 ? Math.round((totalAdopted / totalCollected) * 100) : 0;

  return (
    <div className="chart">
      <div className={`chart-plot${inView ? ' in' : ''}`} ref={plotRef}>
        <svg viewBox={`0 0 ${CHART_W} ${CHART_H}`} role="img" aria-label="최근 7일 뉴스 기사 수 추이">
          <defs>
            {/* 아주 옅은 블루 영역 채우기 — 위쪽만 살짝 진하고 아래로 갈수록 거의 안 보이게. */}
            <linearGradient id="trend-area-gradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#DCEBF0" stopOpacity="0.6" />
              <stop offset="100%" stopColor="#DCEBF0" stopOpacity="0.05" />
            </linearGradient>
          </defs>
          {/* 축/그리드/라벨은 애니메이션 없이 처음부터 표시 — 선이 그려지기 전에 기준선이 먼저 보여야 한다. */}
          <g className="grid">
            {yTicks.slice(0, -1).map((t) => (
              <line key={t} x1={PLOT_LEFT} y1={scaleY(t)} x2={PLOT_RIGHT} y2={scaleY(t)} />
            ))}
            <line className="ax" x1={PLOT_LEFT} y1={PLOT_BOTTOM} x2={PLOT_RIGHT} y2={PLOT_BOTTOM} />
          </g>
          {yTicks.map((t) => (
            <text key={t} className="yl" x={PLOT_LEFT - 8} y={scaleY(t) + 4}>{Math.round(t)}</text>
          ))}
          <path className="area" d={areaPoints} />
          <polyline className="line" points={linePoints} />
          <g className="dots">
            {data.map((d, i) => (
              <circle
                key={d.date}
                className={i === data.length - 1 ? 'now-dot' : undefined}
                cx={pointX(i)}
                cy={scaleY(d.collected)}
                r={i === data.length - 1 ? 4 : 2.8}
                style={{ animationDelay: `${0.15 + (i / Math.max(data.length - 1, 1)) * 1.1}s` }}
              />
            ))}
          </g>
          {/* 실제 hover/포커스 히트 영역 — 점보다 넉넉하게 잡아야 마우스로 정확히 맞추기 쉽다.
              점 자체(위 .dots)는 순수 표시용이라 애니메이션 지연을 그대로 두고, 히트 영역은
              항상 그 자리에 존재해야 하므로 별도 그룹으로 뺀다(안 그러면 페이드인 되기 전엔
              hover가 안 먹는다). */}
          <g>
            {data.map((d, i) => (
              <circle
                key={d.date}
                cx={pointX(i)}
                cy={scaleY(d.collected)}
                r="12"
                className="hit"
                tabIndex={0}
                role="img"
                aria-label={`${formatTipDate(d.date)} 뉴스 ${d.collected}건`}
                onMouseEnter={() => setHoverIdx(i)}
                onMouseLeave={() => setHoverIdx((prev) => (prev === i ? null : prev))}
                onFocus={() => setHoverIdx(i)}
                onBlur={() => setHoverIdx((prev) => (prev === i ? null : prev))}
              />
            ))}
          </g>
          {data.map((d, i) => (
            <text key={d.date} className="xl" x={pointX(i)} y={PLOT_BOTTOM + 22}>{d.date}</text>
          ))}
        </svg>
        {hoverIdx !== null && (
          <div
            className="chart-tip"
            style={{
              left: `${(pointX(hoverIdx) / CHART_W) * 100}%`,
              top: `${(scaleY(data[hoverIdx].collected) / CHART_H) * 100}%`,
            }}
          >
            <b>{formatTipDate(data[hoverIdx].date)}</b>
            <span>뉴스 {data[hoverIdx].collected}건</span>
          </div>
        )}
      </div>
      <div className="chart-legend">
        <span><span className="mk"></span>뉴스 기사 수</span>
        <span>7일 평균 <b>{avgCollected}건</b></span>
        <span>평균 채택률 <b>{avgAdoptRate}%</b></span>
        <span>오늘 <b>{today.collected}건 수집 · {today.adopted}건 채택</b></span>
      </div>
    </div>
  );
}

// 카테고리 현황 전용 — 원그래프(도넛) 한 개 (수정사항 6)
//
// 외부 차트 라이브러리 없이 SVG path로 직접 그립니다.
// (기존 TrendChart도 같은 방식이라 의존성을 늘리지 않으려고 맞췄습니다.)
//
// props
//  · items   : [{ word, count }] — 조각 목록. count 합계로 비율을 계산합니다.
//  · title   : 도넛 가운데 위쪽에 들어갈 짧은 라벨
//  · total   : 가운데 큰 숫자. 안 넘기면 count 합계를 씁니다.
//  · onSlice : 조각/범례를 클릭했을 때 호출(선택 연동용). 없으면 클릭 비활성.
//  · activeWord : 강조할 조각 이름
//
// 반응형: svg에 viewBox만 주고 CSS(.pie svg{width:100%;height:auto})가 폭을 맞춥니다.

const PALETTE = ['#86AABD', '#6B93A8', '#A2C0CE', '#587C8F', '#BFD5DE', '#4A6A7A'];

const R_OUT = 68;
const R_IN = 40;
const CX = 84;
const CY = 84;

function polar(cx, cy, r, angleDeg) {
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
}

function arcPath(startAngle, endAngle) {
  // 조각이 사실상 100%면 path 두 개로 나눠 그려야 하지만,
  // 실무상 카테고리가 1개만 남는 경우는 없어서 원 하나로 대체합니다.
  const large = endAngle - startAngle > 180 ? 1 : 0;
  const [x1, y1] = polar(CX, CY, R_OUT, startAngle);
  const [x2, y2] = polar(CX, CY, R_OUT, endAngle);
  const [x3, y3] = polar(CX, CY, R_IN, endAngle);
  const [x4, y4] = polar(CX, CY, R_IN, startAngle);
  return [
    `M${x1.toFixed(2)},${y1.toFixed(2)}`,
    `A${R_OUT},${R_OUT} 0 ${large} 1 ${x2.toFixed(2)},${y2.toFixed(2)}`,
    `L${x3.toFixed(2)},${y3.toFixed(2)}`,
    `A${R_IN},${R_IN} 0 ${large} 0 ${x4.toFixed(2)},${y4.toFixed(2)}`,
    'Z',
  ].join(' ');
}

export default function KeywordPie({ items = [], title, total, onSlice, activeWord }) {
  const sum = items.reduce((s, i) => s + i.count, 0);

  if (!sum) {
    return <div className="pie-empty">표시할 키워드가 없습니다.</div>;
  }

  let cursor = 0;
  const slices = items.map((item, idx) => {
    const share = item.count / sum;
    const start = cursor * 360;
    cursor += share;
    const end = cursor * 360;
    return {
      ...item,
      share,
      color: PALETTE[idx % PALETTE.length],
      d: arcPath(start, Math.min(end, 359.99)),
    };
  });

  return (
    <div className="pie">
      <svg viewBox="0 0 168 168" role="img" aria-label={`${title || '키워드'} 비중 원그래프`}>
        {slices.map((s) => (
          <path
            key={s.word}
            className={`sl${activeWord === s.word ? ' on' : ''}${onSlice ? ' clickable' : ''}`}
            d={s.d}
            fill={s.color}
            onClick={onSlice ? () => onSlice(s.word) : undefined}
          >
            <title>{`${s.word} · ${s.count}건 (${Math.round(s.share * 100)}%)`}</title>
          </path>
        ))}
        <text className="pie-ct" x={CX} y={CY - 4}>{total ?? sum}</text>
        <text className="pie-cl" x={CX} y={CY + 13}>{title || '건'}</text>
      </svg>

      <ul className="pie-legend">
        {slices.map((s) => (
          <li
            key={s.word}
            className={`${activeWord === s.word ? 'on ' : ''}${onSlice ? 'clickable' : ''}`.trim()}
            onClick={onSlice ? () => onSlice(s.word) : undefined}
          >
            <span className="sw" style={{ background: s.color }}></span>
            <span className="w">{s.word}</span>
            <span className="v">{s.count}건</span>
            <span className="p">{Math.round(s.share * 100)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

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
//
// ⚠ [2026-08-10] 애니메이션:
//  · 진입 시 도넛 전체가 12시 방향에서 시작해 시계방향으로 한 바퀴 쓸려가며 그려진다
//    (SVG <mask> 위에 얹은 도넛 두께짜리 원형 stroke를 stroke-dashoffset으로 감아서
//    구현 — 조각별 색은 그대로, "가려진 영역"만 시계방향으로 넓어진다). 예전엔 조각마다
//    scale+fade로 따로 튀어나오는 방식이었는데, 방향이 뚜렷하지 않다는 피드백으로
//    이 방식으로 바꿨다. 0.9s, 한 번만 재생(반복 없음).
//  · hover 시 그 조각만 살짝(4%) 확대 + 밝기 증가, 나머지는 그대로.
//  · hover 중엔 중앙 숫자/라벨이 그 조각 값으로 바뀌고, 벗어나면 원래 합계로 돌아온다.
//  · 원그래프 전체가 계속 회전/pulse하는 애니메이션은 없다(진입 시 한 번뿐).

import { useId, useState } from 'react';

// 진한 색 → 밝은 색 순. 비중이 큰 조각일수록 앞쪽(진한 색)을 씁니다.
const PALETTE = ['#347FA3', '#4B94B5', '#63A9C4', '#86AABD', '#A7CBD8', '#C8E0E7'];

const R_OUT = 68;
const R_IN = 40;
const CX = 84;
const CY = 84;
// 마스크용 원형 stroke — 도넛 두께(R_OUT-R_IN)와 정확히 겹치도록 반지름을 중간값으로,
// 굵기를 도넛 두께만큼 잡는다. 이 원의 stroke-dashoffset을 0→둘레로 감아서(=시계방향
// 스윕) 도넛이 12시에서부터 한 바퀴 그려지는 것처럼 보이게 한다.
const SWEEP_R = (R_OUT + R_IN) / 2;
const SWEEP_CIRC = 2 * Math.PI * SWEEP_R;

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
  const [hoverWord, setHoverWord] = useState(null);
  // 같은 페이지에 원그래프가 두 개(전체 분류 / 선택한 분류 내부) 동시에 떠서, mask id가
  // 겹치면 한쪽 스윕이 다른 쪽 마스크를 가리키는 사고가 난다 — 인스턴스마다 고유하게.
  const maskId = useId();
  const sum = items.reduce((s, i) => s + i.count, 0);

  if (!sum) {
    return <div className="pie-empty">표시할 키워드가 없습니다.</div>;
  }

  // 비중이 큰 조각일수록 진한 색을 쓰도록, count 내림차순 순위로 팔레트를 배정합니다.
  // (조각이 그려지는 순서·위치는 items 원래 순서를 그대로 따릅니다)
  const rankByIndex = items
    .map((item, idx) => idx)
    .sort((a, b) => items[b].count - items[a].count);
  const colorByIndex = {};
  rankByIndex.forEach((origIdx, rank) => {
    colorByIndex[origIdx] = PALETTE[rank % PALETTE.length];
  });

  let cursor = 0;
  const slices = items.map((item, idx) => {
    const share = item.count / sum;
    const start = cursor * 360;
    cursor += share;
    const end = cursor * 360;
    return {
      ...item,
      share,
      color: colorByIndex[idx],
      d: arcPath(start, Math.min(end, 359.99)),
    };
  });

  const hovered = hoverWord ? slices.find((s) => s.word === hoverWord) : null;
  const centerValue = hovered ? hovered.count : total ?? sum;
  const centerLabel = hovered ? hovered.word : title || '건';

  return (
    <div className="pie">
      <svg viewBox="0 0 168 168" role="img" aria-label={`${title || '키워드'} 비중 원그래프`}>
        <defs>
          <mask id={maskId} maskUnits="userSpaceOnUse" x="0" y="0" width="168" height="168">
            {/* 검정 배경 = 전부 가림, 흰 stroke가 지나간 자리만 보인다. */}
            <rect x="0" y="0" width="168" height="168" fill="black" />
            <circle
              className="pie-sweep"
              cx={CX} cy={CY} r={SWEEP_R}
              fill="none" stroke="#fff" strokeWidth={R_OUT - R_IN + 1}
              strokeDasharray={SWEEP_CIRC}
              strokeDashoffset={SWEEP_CIRC}
              transform={`rotate(-90 ${CX} ${CY})`}
            />
          </mask>
        </defs>
        <g mask={`url(#${maskId})`}>
          {slices.map((s) => (
            <path
              key={s.word}
              className={`sl${activeWord === s.word ? ' on' : ''}${hoverWord === s.word ? ' hover' : ''}${onSlice ? ' clickable' : ''}`}
              d={s.d}
              fill={s.color}
              onClick={onSlice ? () => onSlice(s.word) : undefined}
              onMouseEnter={() => setHoverWord(s.word)}
              onMouseLeave={() => setHoverWord((prev) => (prev === s.word ? null : prev))}
            >
              <title>{`${s.word} · ${s.count}건 (${Math.round(s.share * 100)}%)`}</title>
            </path>
          ))}
        </g>
        <text key={`ct-${centerValue}`} className="pie-ct" x={CX} y={CY - 4}>{centerValue}</text>
        <text key={`cl-${centerLabel}`} className="pie-cl" x={CX} y={CY + 13}>{centerLabel}</text>
      </svg>

      <ul className="pie-legend">
        {slices.map((s) => (
          <li
            key={s.word}
            className={`${activeWord === s.word ? 'on ' : ''}${hoverWord === s.word ? 'hover ' : ''}${onSlice ? 'clickable' : ''}`.trim()}
            onClick={onSlice ? () => onSlice(s.word) : undefined}
            onMouseEnter={() => setHoverWord(s.word)}
            onMouseLeave={() => setHoverWord((prev) => (prev === s.word ? null : prev))}
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

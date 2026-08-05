// 대시보드 전용 — "지식 축적화" 네트워크 그래프
//
// "최근 현황"과 "산업 동향 분석" 사이에 들어가는 장식용 시각화입니다. 실데이터를 그리는
// 컴포넌트가 아니라, myWiki가 6개 카테고리·수백 개 키워드를 계속 축적하고 서로 연결하고
// 있다는 걸 보여주는 정적 다이어그램입니다 — 그래서 데이터는 mockOnboarding.js의
// INTEREST_KEYWORD_GROUPS(선호조사 키워드 사전)를 그대로 재사용합니다. 카테고리 6개 순서가
// 온보딩 키워드 사전과 동일해서, 두 화면에서 같은 분류 체계를 보여준다는 일관성도 생깁니다.
//
// 노드 구성: 허브(myWiki) → 카테고리 원 6개(서로 인접한 원끼리도 선으로 연결) → 카테고리마다
// 키워드 리프 10개(그중 5개에 라벨). 리프끼리 잇는 대각선("웹" 스타일)은 넣지 않습니다 —
// 선이 너무 빽빽해서 오히려 안 보기 좋았고, 가지 길이가 리프마다 다른(LEAF_JITTER) 깔끔한
// 방사형 트리 쪽이 더 잘 읽힙니다. 카테고리 원끼리의 연결선(고리)만 다시 추가했습니다.
// 중앙 허브는 TopBar.jsx와 동일한 로고 이미지(logo.png/logo-dark.png, 라이트/다크 자동 전환)만
// 둡니다 — 아이콘·별도 텍스트 없이 로고 자체(이미지 안에 이미 "myWiki" 워드마크 포함)만.
// 로고는 SVG 안에 직접 넣는 것보다 <img>로 얹는 쪽이 다크모드 전환에 더 간단해서, 허브 자리만
// wrapper를 relative로 두고 절대 위치로 겹칩니다(CX/CY가 viewBox 정중앙이라 50%/50%로 항상 맞습니다).
//
// 애니메이션: 마운트 직후(다음 틱) 허브 → 카테고리 → 리프 순으로 스태거드 페이드인 +
// 스케일업. 허브는 항상 은은하게 펄스, 리프 점들은 각자 다른 딜레이로 계속 둥둥 떠다닙니다.
// 3D 느낌을 위해 그래프 전체가 얕은 원근감(perspective)을 두고 계속 좌우로 살짝 흔들리듯
// 기울어지고(rotateX/rotateY sway), 원 노드는 방사형 그라디언트로 광원이 있는 듯한 입체감을 냅니다.
// prefers-reduced-motion이면 즉시 전부 보이고 흔들림·부유 애니메이션은 꺼집니다(globals.css).
// ⚠ 스크롤 진입 시점(IntersectionObserver)이 아니라 마운트 시점에 트리거합니다 — 대시보드
// 최상단 KPI 바로 아래라 로드되자마자 화면에 보이는 경우가 대부분이고, 스크롤 트리거는
// 탭이 백그라운드거나 컴포지팅이 지연되는 환경에서 아예 안 켜지는 문제가 있었습니다.

import { useEffect, useState } from 'react';
import { INTEREST_KEYWORD_GROUPS } from '../../data/mockOnboarding';
import logo from '../../assets/logo.png';
import logoDark from '../../assets/logo-dark.png';

const CX = 500;
// viewBox 높이(780)의 정확히 절반 — 12시 방향 카테고리(제품·기술)의 리프가 위쪽 여백 부족으로
// 잘리던 문제가 있어서, CY를 낮추는 대신 viewBox 자체를 키워 상하 여백을 넉넉히 확보했다.
const CY = 390;
const HUB_R = 62;
// 카테고리 원과 리프 점의 크기 차이가 너무 크다는 피드백을 반영해 카테고리는 살짝 줄이고
// 리프 점(특히 라벨 붙은 것)은 키워서 격차를 좁혔다.
const CATEGORY_R = 218; // 허브 중심에서 카테고리 노드까지 거리
const CATEGORY_NODE_R = 44;
const LEAF_R_BASE = 320; // 허브 중심에서 리프(키워드 점)까지 기본 거리
// 카테고리 하나당 리프 10개 — 각도 퍼짐 + 반지름을 살짝씩 어긋나게 해서 가지 길이가 다양해 보이게 함.
const LEAF_ANGLES = [-42, -32, -22, -12, -3, 6, 15, 25, 35, 45];
const LEAF_JITTER = [0, 22, 6, 30, 14, 0, 24, 8, 32, 12];
// 라벨을 붙일 리프 인덱스 — 10개 중 5개(퍼짐 양 끝은 피해서 텍스트가 잘리지 않게 함).
const LABELED_LEAF_INDEXES = new Set([1, 3, 4, 6, 8]);

function toXY(angleDeg, radius) {
  const rad = (angleDeg * Math.PI) / 180;
  return { x: CX + radius * Math.sin(rad), y: CY - radius * Math.cos(rad) };
}

const CATEGORIES = INTEREST_KEYWORD_GROUPS.map((g, i) => {
  const angle = i * 60; // 12시 방향(제품·기술)부터 시계방향 60도씩
  const pos = toXY(angle, CATEGORY_R);
  const leaves = g.keywords.slice(0, LEAF_ANGLES.length).map((word, li) => {
    const leafAngle = angle + LEAF_ANGLES[li];
    const leafPos = toXY(leafAngle, LEAF_R_BASE + LEAF_JITTER[li]);
    return { word, labeled: LABELED_LEAF_INDEXES.has(li), floatDelay: (i * 10 + li) % 7, ...leafPos };
  });
  const parts = g.category.split('·');
  return { name: g.category, nameLines: parts, angle, ...pos, leaves };
});

export default function KnowledgeGraph() {
  const [inView, setInView] = useState(false);

  useEffect(() => {
    // 다음 틱에 클래스를 붙여야 CSS transition이 "0 → 1"로 실제 발생한다
    // (마운트와 동시에 in 클래스가 있으면 transition 없이 곧장 최종 상태로 그려진다).
    // rAF는 탭이 백그라운드거나 페인트가 지연되는 환경에서 아예 안 불릴 수 있어
    // setTimeout(0)을 쓴다 — 이건 렌더링 파이프라인과 무관하게 항상 실행된다.
    const id = setTimeout(() => setInView(true), 0);
    return () => clearTimeout(id);
  }, []);

  return (
    <div
      className={`kg-wrap relative mx-auto w-full max-w-full overflow-hidden rounded-2xl px-2 pt-4 pb-2 sm:px-4 sm:pt-6 md:px-6${
        inView ? ' in' : ''
      }`}
    >
      <svg
        className="kg-svg block h-auto w-full max-h-[420px] sm:max-h-[480px] lg:max-h-[560px]"
        viewBox="0 0 1000 780"
        role="img"
        aria-label="myWiki 지식 축적 네트워크 — 6개 카테고리와 키워드"
      >
        <defs>
          <radialGradient id="kgNodeGrad" cx="35%" cy="28%" r="75%">
            <stop offset="0%" stopColor="var(--green-soft, #4fc491)" />
            <stop offset="100%" stopColor="var(--green)" />
          </radialGradient>
        </defs>

        {/* 카테고리 원끼리 서로 연결(바깥 테두리 고리) */}
        {CATEGORIES.map((c, i) => {
          const next = CATEGORIES[(i + 1) % CATEGORIES.length];
          return (
            <line
              key={`ring-${c.name}`}
              className="kg-line kg-line-ring"
              x1={c.x} y1={c.y} x2={next.x} y2={next.y}
              style={{ transitionDelay: `${260 + i * 70}ms` }}
            />
          );
        })}
        {/* 허브 → 카테고리 연결선 */}
        {CATEGORIES.map((c, i) => (
          <line
            key={`hl-${c.name}`}
            className="kg-line kg-line-main"
            x1={CX} y1={CY} x2={c.x} y2={c.y}
            style={{ transitionDelay: `${140 + i * 70}ms` }}
          />
        ))}
        {/* 카테고리 → 리프 스포크선 */}
        {CATEGORIES.map((c) =>
          c.leaves.map((leaf, li) => (
            <line
              key={`ll-${c.name}-${leaf.word}`}
              className="kg-line kg-line-leaf"
              x1={c.x} y1={c.y} x2={leaf.x} y2={leaf.y}
              style={{ transitionDelay: `${420 + li * 35}ms` }}
            />
          ))
        )}

        {/* 리프(키워드) 점 */}
        {CATEGORIES.map((c) =>
          c.leaves.map((leaf, li) => (
            <g
              key={`leaf-${c.name}-${leaf.word}`}
              className="kg-leaf"
              style={{
                transitionDelay: `${480 + li * 35}ms`,
                '--kg-float-delay': `${leaf.floatDelay * 0.35}s`,
              }}
            >
              <circle cx={leaf.x} cy={leaf.y} r={leaf.labeled ? 6.5 : 4.5} className="kg-leaf-dot" />
              {leaf.labeled && (
                <text
                  x={leaf.x + (leaf.x >= CX ? 11 : -11)}
                  y={leaf.y + 4}
                  textAnchor={leaf.x >= CX ? 'start' : 'end'}
                  className="kg-leaf-label"
                >
                  {leaf.word}
                </text>
              )}
            </g>
          ))
        )}
        {/* 카테고리 노드 — 원, 방사형 그라디언트 + 그림자로 입체감 */}
        {CATEGORIES.map((c, i) => (
          <g key={c.name} className="kg-cat" style={{ transitionDelay: `${180 + i * 70}ms` }}>
            <circle cx={c.x} cy={c.y + 5} r={CATEGORY_NODE_R} className="kg-cat-circle-shadow" />
            <circle cx={c.x} cy={c.y} r={CATEGORY_NODE_R} className="kg-cat-circle" />
            {c.nameLines.length > 1 ? (
              <>
                <text x={c.x} y={c.y - 6} textAnchor="middle" className="kg-cat-label">
                  {c.nameLines[0]}·
                </text>
                <text x={c.x} y={c.y + 14} textAnchor="middle" className="kg-cat-label">
                  {c.nameLines[1]}
                </text>
              </>
            ) : (
              <text x={c.x} y={c.y + 4} textAnchor="middle" className="kg-cat-label">
                {c.name}
              </text>
            )}
          </g>
        ))}
        {/* 허브 배경(원+글로우) — 로고는 아래 HTML 오버레이가 담당 */}
        <g className="kg-hub">
          <circle cx={CX} cy={CY} r={HUB_R + 24} className="kg-hub-glow" />
          <circle cx={CX} cy={CY} r={HUB_R} className="kg-hub-circle" />
        </g>
      </svg>

      {/* 허브 로고 오버레이 — viewBox 정중앙(CX=500/1000, CY=390/780 → 50%/50%)에 항상 겹친다 */}
      <div className="pointer-events-none absolute left-1/2 top-1/2 flex -translate-x-1/2 -translate-y-1/2 items-center justify-center">
        <img src={logo} alt="myWiki" className="kg-hub-logo-img logo-light h-10 w-auto sm:h-12" />
        <img src={logoDark} alt="myWiki" className="kg-hub-logo-img logo-dark h-10 w-auto sm:h-12" />
      </div>
    </div>
  );
}

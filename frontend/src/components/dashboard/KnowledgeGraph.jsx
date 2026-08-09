// 대시보드 전용 — "지식 축적화" 네트워크 그래프
//
// 대시보드에 들어오자마자(파이프라인 바 바로 아래) 바로 보이는 장식용 시각화입니다.
// 실데이터를 그리는 컴포넌트가 아니라, myWiki가 6개 카테고리·수백 개 키워드를 계속
// 축적하고 있다는 걸 보여주는 정적 다이어그램입니다 — 그래서 데이터는 mockOnboarding.js의
// INTEREST_KEYWORD_GROUPS(선호조사 키워드 사전)를 그대로 재사용합니다. 카테고리 6개 순서가
// 온보딩 키워드 사전과 동일해서, 두 화면에서 같은 분류 체계를 보여준다는 일관성도 생깁니다.
//
// 노드 구성: 중앙 허브(그라디언트 글로우 + myWiki 로고 이미지) → 카테고리 원 6개(서로
// 인접한 원끼리 고리로 연결) → 카테고리마다 키워드 리프 10개(그중 5개에 라벨).
// ⚠ 허브 ↔ 카테고리를 잇는 선 6개는 일부러 안 그립니다 — 허브 자체(그라디언트 + 로고)는
// 그대로 두되, 다 같은 중심점에서 뻗어나가는 선이 있으면 지저분해 보인다는 피드백이 있었습니다.
// 카테고리 → 리프 스포크선은 진하게(stroke-opacity .85, globals.css)로 잘 보이게 했습니다.
//
// 애니메이션: 마운트 직후(다음 틱) 카테고리 → 리프 순으로 스태거드 페이드인 + 스케일업,
// 허브는 항상 은은하게 펄스. 리프 점들은 각자 다른 딜레이로 계속 둥둥 떠다닙니다.
// prefers-reduced-motion이면 즉시 전부 보이고 펄스·부유 애니메이션은 꺼집니다(globals.css).
// ⚠ 스크롤 진입 시점(IntersectionObserver)이 아니라 마운트 시점에 트리거합니다 — 대시보드
// 최상단이라 로드되자마자 화면에 보이는 경우가 대부분이고, 스크롤 트리거는 탭이 백그라운드
// 이거나 컴포지팅이 지연되는 환경에서 아예 안 켜지는 문제가 있었습니다.

import { useEffect, useState } from 'react';
import { INTEREST_KEYWORD_GROUPS } from '../../data/mockOnboarding';
import myWikiLogoFull from '../../assets/mywiki-logo-full.png';

const CX = 500;
const CY = 340; // viewBox 높이(680)의 정확히 절반
const HUB_R = 110;
const CATEGORY_R = 218; // 중심에서 카테고리 노드까지 거리(가로 기준 — Y_SQUASH 적용 전)
const CATEGORY_NODE_R = 44;
const LEAF_R_BASE = 320; // 중심에서 리프(키워드 점)까지 기본 거리(가로 기준 — Y_SQUASH 적용 전)
// 타원형 배치 — 화면은 세로보다 가로가 훨씬 넓은데 예전엔 완전한 원형(가로=세로 반지름)으로
// 배치해서, 가로는 여유가 남아도는데 세로는 위/아래 끝 리프가 viewBox 밖으로 살짝
// 잘렸다. toXY의 Y좌표에만 이 배수를 곱해 세로 반지름을 줄인다 — 각 카테고리·리프의
// 각도/개수/연결 관계 등 데이터는 전혀 안 건드리고, 화면에 투영되는 좌표만 눌러
// 타원으로 만든다(노드 자체는 원의 r=CATEGORY_NODE_R을 그대로 쓰므로 동그란 모양은 유지된다).
const Y_SQUASH = 0.72;
// 카테고리 하나당 리프 13개 — 각도 퍼짐 + 반지름을 어긋나게 해서 가지 길이가 다양해 보이게
// 함. 라벨 있는 가지(아래 LABELED_LEAF_INDEXES)는 텍스트가 잘리지 않도록 반지름을 크게
// 안 건드리고, 라벨 없는 "빈 가지"는 반지름을 훨씬 크게 들쭉날쭉하게 벌려서 전체 윤곽이
// 매끈한 원이 아니라 나뭇가지처럼 삐죽삐죽하게 뻗어나가 보이게 한다(직선으로 뻗기만 하면
// 되고, 끝까지 둥글게 모일 필요는 없다).
// 가지 수를 13개에서 11개로 줄여(-42/+62 양 끝단 제거) 더 정돈되어 보이게 함.
const LEAF_ANGLES = [-32, -22, -12, -3, 6, 15, 25, 35, 45, -52, 53];
// ⚠ 리프 각도는 카테고리 각도(0/60/120/180/240/300)에 그대로 더해지기 때문에, 어떤 카테고리는
// 특정 리프의 최종 각도가 0°/180°(정확히 위/아래)에 가까워진다 — Y_SQUASH 덕분에 그 방향
// 반지름이 실제로는 370*0.72≈266px까지만 나가므로(CY=340 기준 위/아래 모두 70px 이상 여유),
// 예전 완전 원형일 때보다 여유가 넉넉해졌다. 그래도 최대치는 370(기본 반지름+지터 합)선에서
// 그대로 묶어 둔다.
const LEAF_JITTER = [22, 40, 30, 14, 48, 24, 34, 32, 44, 50, 18];
// 라벨을 붙일 리프 인덱스 — 10개 중 5개(퍼짐 양 끝은 피해서 텍스트가 잘리지 않게 함).
const LABELED_LEAF_INDEXES = new Set([1, 3, 4, 6, 8]);

function toXY(angleDeg, radius) {
  const rad = (angleDeg * Math.PI) / 180;
  return { x: CX + radius * Math.sin(rad), y: CY - radius * Math.cos(rad) * Y_SQUASH };
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
      className={`kg-wrap relative mx-auto w-full max-w-full rounded-2xl px-1 pt-1 pb-2 sm:px-4 sm:pt-2 md:px-6${
        inView ? ' in' : ''
      }`}
    >
      <svg
        className="kg-svg block h-auto w-full max-h-[380px] sm:max-h-[480px] lg:max-h-[580px]"
        viewBox="0 0 1000 680"
        role="img"
        aria-label="myWiki 지식 축적 네트워크 — 6개 카테고리와 키워드"
      >
        <defs>
          <radialGradient id="kgHubGrad" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#6FC0A5" stopOpacity=".34" />
            <stop offset="65%" stopColor="#4C9A83" stopOpacity=".16" />
            <stop offset="100%" stopColor="#4C9A83" stopOpacity="0" />
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
              style={{ transitionDelay: `${140 + i * 70}ms` }}
            />
          );
        })}
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
                // 노드가 리프(점)+라벨을 함께 담고 있어서 transform-box:fill-box 기본값을 쓰면
                // 텍스트 라벨 쪽으로 무게중심이 쏠려 scale/pulse 때 점이 제자리에서 벗어나
                // "좌우로 움직이는" 것처럼 보인다. 점의 실제 좌표로 원점을 못박아 고정한다.
                transformOrigin: `${leaf.x}px ${leaf.y}px`,
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
        {/* 카테고리 노드 — 원, 단색 매트 채움(그라디언트·그림자 없음) */}
        {CATEGORIES.map((c, i) => (
          <g
            key={c.name}
            className="kg-cat"
            style={{
              transitionDelay: `${180 + i * 70}ms`,
              // 원 + 텍스트를 함께 담은 그룹이라 fill-box 기본 중심은 원의 실제 중심과 다르다
              // (라벨이 위/아래로 치우쳐 있어서). 펄스가 위치를 흔드는 것처럼 보이지 않도록
              // 원의 진짜 좌표를 transform-origin으로 못박는다.
              transformOrigin: `${c.x}px ${c.y}px`,
              // 진입 스케일-인 트랜지션(.5s)이 다 끝난 뒤에야 펄스가 시작되게 딜레이를 겹치지
              // 않게 잡는다 — 그래야 애니메이션이 진입 효과를 도중에 가로채 뚝 끊기지 않는다.
              animationDelay: `${700 + i * 220}ms`,
            }}
          >
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

        {/* 허브 배경(그라디언트 글로우) — 로고는 아래 HTML 오버레이가 담당 */}
        <g className="kg-hub">
          <circle cx={CX} cy={CY} r={HUB_R + 24} className="kg-hub-glow" />
          <circle cx={CX} cy={CY} r={HUB_R + 10} className="kg-hub-grad" />
        </g>
      </svg>

      {/* 허브 로고 오버레이 — viewBox 정중앙(CX=500/1000, CY=340/680 → 50%/50%)에 항상 겹친다.
          로고는 SVG 안에 직접 넣는 것보다 <img>로 얹는 쪽이 다크모드 전환에 더 간단하다. */}
      <div className="kg-hub-overlay pointer-events-none absolute left-1/2 top-1/2 flex -translate-x-1/2 -translate-y-1/2 flex-col items-center justify-center gap-1">
        <img
          src={myWikiLogoFull}
          alt="my Wiki"
          className="kg-hub-logo-full"
        />
      </div>
    </div>
  );
}

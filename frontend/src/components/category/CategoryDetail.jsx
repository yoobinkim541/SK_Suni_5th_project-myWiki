// 카테고리 현황 페이지 전체 조립 (#v-cat)
// 헤더(.ph) + "오늘의 분류 요약" KPI 4개 + "수집 키워드 분포"(원그래프) + "분류별 상세" 카드 그리드.
//
// ⚠ 수정사항 6) "우리 키워드 중심으로 내부에 어떤 키워드가 있는지"를 보여주는
//   원그래프 섹션(CategoryKeywordChart)을 KPI 바로 아래에 추가했습니다.
//   숫자 카드(KPI) → 비중 그림(원그래프) → 개별 카드(상세) 순으로 점점 좁아지는 구성입니다.
//
// 반응형 참고: `.kpi`가 1020px 이하에서 2열로 바뀌는 것도 CSS가 처리하므로
// 이 컴포넌트/자식 컴포넌트에서 화면 폭 분기를 할 일은 없습니다.

import KpiCard from '../dashboard/KpiCard';
import CategoryRow from './CategoryRow';
import CategoryKeywordChart from './CategoryKeywordChart';
import { formatKoreanDate } from '../../lib/formatDate';

// 목업을 기본값으로 두지 않는다. 실연동 후 summary/categories가 undefined로 들어오면
// 목업이 조용히 fallback돼서, 실데이터가 안 오는 상황을 정상처럼 보이게 만든다.
// 데이터를 채우는 책임은 CategoryPage에 있다.
export default function CategoryDetail({
  // 기본값을 '2026.07.24 금요일'로 박아놓고 CategoryPage가 이 prop을 안 넘겨서,
  // 화면에 고정된 과거 날짜가 그대로 떠 있었다. 기본 인자는 렌더마다 다시 평가되므로
  // 탭을 자정 넘겨 열어둬도 날짜가 따라간다.
  date = formatKoreanDate(),
  // [목업] '일 배치 정상'은 실제와 반대다 — 수집·분석 배치가 매 회차 timeout으로
  // 잘리고 있다(P1). 배치 상태를 실데이터로 바꾸려면 그게 먼저 풀려야 해서,
  // 이번에는 날짜만 고치고 이 라벨은 목업으로 남겨둔다.
  statusLabel = '반도체 도메인 · 일 배치 정상',
  summary,
  categories = [],
}) {
  const s = summary;

  return (
    <section className="view on" id="v-cat"
      data-pri="P1"
      data-cap="카테고리 현황. 6개 분류의 비중·증감·대표 키워드·대표 이슈를 한 화면에 모아 수집 키워드 조정의 근거로 쓴다."
    >
      <div className="ph">
        <h2>카테고리 현황</h2>
        <span className="dt">{date}</span>
        <span className="st">{statusLabel}</span>
      </div>

      <section className="sec">
        <div className="sh">
          <span className="t">오늘의 분류 요약</span>
          <span className="s">{s?.totalLabel}</span>
          <span className="r">전일 대비 변화 포함</span>
        </div>
        {/* 옵셔널 체이닝 — 한 칸이라도 비면 페이지 전체가 흰 화면이 되던 자리다.
            값을 채우는 책임은 services/categoryApi.js에 있고, 여기선 크래시만 막는다. */}
        <div className="kpi">
          <KpiCard label="최다 분류" value={s?.topCategory?.value} isText desc={s?.topCategory?.desc} />
          <KpiCard label="증가 폭 최대" value={s?.maxIncrease?.value} isText desc={s?.maxIncrease?.desc} />
          <KpiCard label="신규 이슈 분류" value={s?.newCategory?.value} isText desc={s?.newCategory?.desc} />
          {/* 평균 신뢰도는 색상 없이 기본 텍스트색으로 표시 (KpiCard 기본값 그대로) */}
          <KpiCard label="평균 신뢰도" value={s?.avgConfidence?.value} isText desc={s?.avgConfidence?.desc} />
        </div>
      </section>

      <CategoryKeywordChart categories={categories} />

      <CategoryRow categories={categories} />
    </section>
  );
}

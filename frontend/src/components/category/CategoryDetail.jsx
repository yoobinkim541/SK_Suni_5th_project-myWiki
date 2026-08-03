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
import { MOCK_CATEGORIES, MOCK_SUMMARY } from '../../data/mockCategory';

export default function CategoryDetail({
  date = '2026.07.24 금요일',
  statusLabel = '반도체 도메인 · 일 배치 정상',
  summary = MOCK_SUMMARY,
  categories = MOCK_CATEGORIES,
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
          <span className="s">{s.totalLabel}</span>
          <span className="r">전일 대비 변화 포함</span>
        </div>
        <div className="kpi">
          <KpiCard label="최다 분류" value={s.topCategory.value} isText desc={s.topCategory.desc} />
          <KpiCard label="증가 폭 최대" value={s.maxIncrease.value} isText desc={s.maxIncrease.desc} />
          <KpiCard label="신규 이슈 분류" value={s.newCategory.value} isText desc={s.newCategory.desc} />
          {/* 평균 신뢰도는 색상 없이 기본 텍스트색으로 표시 (KpiCard 기본값 그대로) */}
          <KpiCard label="평균 신뢰도" value={s.avgConfidence.value} isText desc={s.avgConfidence.desc} />
        </div>
      </section>

      <CategoryKeywordChart categories={categories} />

      <CategoryRow categories={categories} />
    </section>
  );
}

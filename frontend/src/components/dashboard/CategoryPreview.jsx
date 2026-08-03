// 메인 대시보드 전용 — "카테고리 현황" 미리보기 카드 (.catrow 목록)
// ⚠ 카테고리 현황 페이지의 카드(.cd)와는 다른, 대시보드 하단 좌측에 들어가는 "간단 목록"입니다.
//   시안에서 진행률 막대(.trk)를 완전히 제거하고 "대표 이슈 한 줄 + 신뢰도 : 높음" 텍스트만
//   보여주는 구성으로 바뀌어서, CategoryProgressBar는 여기서 쓰지 않습니다.
//   (카테고리 현황 페이지의 CategoryCard도 마찬가지로 진행률 막대를 더 이상 쓰지 않습니다 —
//    아래 category/CategoryCard.jsx 참고. CategoryProgressBar.jsx 자체는 현재 화면 어디에서도
//    안 쓰이는 상태라, 남겨두더라도 실제로 import하는 곳은 없습니다.)
//
// 마크업: .sh(제목+전체보기) 다음에 .catrow 목록. 오른쪽 "오늘의 키워드" 컬럼은 형제 컴포넌트라
// 이 파일 범위 밖입니다(부모에서 .split 안에 나란히 배치).
//
// 반응형 참고: 부모의 `.split`이 1020px 이하에서 grid-template-columns:1fr로 바뀌면서
// 이 컴포넌트와 "오늘의 키워드" 컬럼이 자동으로 세로 스택됩니다. 이 컴포넌트 내부는 그대로 두면 됩니다.

const LEVEL_LABEL = { high: '높음', mid: '보통', low: '낮음' };
const LEVEL_CLASS = { high: 'hi', mid: 'mid', low: 'low' };

export default function CategoryPreview({ categories, onViewAll }) {
  return (
    <div>
      <div className="sh">
        <span className="t">카테고리 현황</span>
        <span className="r">
          <a
            data-v="cat"
            href="#"
            onClick={(e) => {
              if (onViewAll) {
                e.preventDefault();
                onViewAll();
              }
            }}
          >
            전체 보기 →
          </a>
        </span>
      </div>
      <div>
        {categories.map((c) => (
          <div className="catrow" key={c.id}>
            <div className="nm">
              {c.name}
              <span className="issue">{c.issueTitle}</span>
              <span className="cnt">{c.count}건</span>
            </div>
            <div className={`pc ${LEVEL_CLASS[c.level] || ''}`}>신뢰도 : {LEVEL_LABEL[c.level]}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// 목업 데이터는 data/mockDashboard.js의 MOCK_CATEGORY_PREVIEW를 씁니다.
// (예: import { MOCK_CATEGORY_PREVIEW } from '../../data/mockDashboard';)

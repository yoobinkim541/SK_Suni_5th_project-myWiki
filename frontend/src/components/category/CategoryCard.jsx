// 카테고리 현황 페이지 전용 — 개별 카테고리 카드 (.cd)
// 시안 최신 버전: 진행률 막대(.trk), 인용문(.quote), 출처 링크가 전부 빠지고
//   배지(카테고리명) + 대표 이슈 한 줄 + 키워드 태그 + 신뢰도 텍스트만 남은 "간단 카드" 구성입니다.
//   → 카테고리별로 "기사가 몇 건인지 / 어떤 키워드가 많은지 / 신뢰도가 어느 정도인지"만
//     한눈에 보이면 되고, 나머지 정보는 대시보드 "최근 산업 이슈"·위키에서 확인하는 구조입니다.
//
// 배지 색상은 카테고리별로 다르지 않고 전부 동일합니다(초록 배경 + 흰 글자, .badge 클래스가 처리) —
// 그래서 이 컴포넌트에는 iconColorClass 같은 prop이 없습니다.
//
// ⚠ 수정한 부분: 카드를 눌렀을 때(또는 Tab으로 포커스 후 Enter/Space) 그 카테고리의
//   관련 뉴스 모달이 열리도록 onClick을 받게 했습니다. 실제로 여는 동작(모달 상태 관리)은
//   부모인 CategoryRow.jsx에서 하고, 이 컴포넌트는 그냥 클릭됐다는 것만 부모에 알립니다.

const LEVEL_LABEL = { high: '높음', mid: '보통', low: '낮음' };
const LEVEL_CLASS = { high: 'hi', mid: 'mid', low: 'low' };

export default function CategoryCard({ name, count, topIssue, tags = [], level, onClick }) {
  return (
    <div
      className="cd"
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onClick?.();
        }
      }}
    >
      <div className="hd">
        <span className="badge">{name}</span>
        <span className="hd-count"><b>{count}</b>건</span>
      </div>
      <div className="top-issue">{topIssue}</div>
      {tags.length > 0 && (
        <div className="tags">
          {tags.map((t) => (
            <span className="tag" key={t}>{t}</span>
          ))}
        </div>
      )}
      <div className="cat-foot">
        <span className={`trust ${LEVEL_CLASS[level] || ''}`}>신뢰도 : {LEVEL_LABEL[level]}</span>
      </div>
    </div>
  );
}

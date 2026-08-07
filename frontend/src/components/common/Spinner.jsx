// 공통 로딩 스피너 — 콘텐츠 영역 정가운데에서 빙글빙글
export default function Spinner({ label = '불러오는 중' }) {
  return (
    <div className="spinner-wrap" role="status" aria-live="polite">
      <div className="spinner" />
      {label && <div className="spinner-label">{label}</div>}
    </div>
  );
}
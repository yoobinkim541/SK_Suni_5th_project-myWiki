// 카테고리 카드 클릭 시 뜨는 "관련 뉴스" 모달
// 시안 HTML의 .mw-modal/.mw-scrim(리포트 상세 모달과 같은 틀)을 그대로 재사용합니다.
//
// ⚠ 수정한 부분: 기사 목록을 담는 div에 id="catNewsRows"를 붙였습니다.
//   시안 CSS가 `#catNewsRows{max-height:...; overflow-y:auto}`로 목록만 따로 스크롤되게
//   되어 있는데, 이 id가 없으면 그 스타일이 안 먹어서 카테고리에 기사가 많을 때
//   모달이 화면 밖으로 넘쳐버립니다. 이제 기사가 몇 건이든 목록 안에서 스크롤됩니다.
//
// ⚠ 지금 여기 뜨는 건수·날짜·시간은 전부 data/mockDashboard.js의 정적인 목업 텍스트입니다.
//   "5건"이나 "12분 전" 같은 값이 자동으로 바뀌는 게 아니라, 지금 이 컴포넌트가 받는
//   newsItems 배열이 바뀔 때만 화면이 바뀝니다. 지금은 그 배열이 하드코딩된 목업이라
//   실제로 뉴스가 새로 들어와도 화면엔 반영되지 않고, 백엔드 API로 뉴스 목록을 fetch해서
//   이 배열 자리를 채우게 되면 그때부터 "실시간"이 됩니다(정확히는 API를 다시 부를 때마다
//   최신값으로 갱신 — 진짜 실시간 push가 되려면 폴링이나 웹소켓 같은 별도 처리가 더 필요해요).
//   시간 표시도 마찬가지로 지금은 "12분 전" 같은 문자열을 그대로 박아둔 것뿐이라,
//   실제 연동 시에는 서버가 내려주는 타임스탬프를 상대시간으로 변환하는 로직이 따로 필요합니다.

import { useEffect } from 'react';

export default function CategoryNewsModal({ category, newsItems = [], onClose }) {
  useEffect(() => {
    if (!category) return;
    function handleKey(e) {
      if (e.key === 'Escape') onClose?.();
    }
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [category, onClose]);

  if (!category) return null;

  return (
    <>
      <div className="mw-scrim open" onClick={onClose}></div>
      <div className="mw-modal open" role="dialog" aria-modal="true" aria-label="카테고리 관련 뉴스">
        <div className="mw-hd">
          <div>
            <div className="eb">CATEGORY · {newsItems.length}건</div>
            <h3>{category.name}</h3>
          </div>
          <button className="mw-x" onClick={onClose} aria-label="닫기">✕</button>
        </div>
        <div className="mw-body">
          <div className="mw-lb">관련 뉴스</div>
          <div id="catNewsRows">
            {newsItems.length === 0 ? (
              <div className="cat-news-item"><p>관련 뉴스가 없습니다.</p></div>
            ) : (
              newsItems.map((n) => (
                <article className="cat-news-item" key={n.title}>
                  <h4>{n.title}</h4>
                  <p>{n.quote}</p>
                  <div className="meta">
                    <a className="s" href={n.sourceUrl} target="_blank" rel="noopener">{n.sourceLabel}</a>
                    <span>{n.time}</span>
                  </div>
                </article>
              ))
            )}
          </div>
        </div>
      </div>
    </>
  );
}

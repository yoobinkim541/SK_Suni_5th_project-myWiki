// 카테고리 카드 클릭 시 뜨는 "관련 뉴스" 모달
// 시안 HTML의 .mw-modal/.mw-scrim(리포트 상세 모달과 같은 틀)을 그대로 재사용합니다.
//
// ⚠ 수정한 부분: 기사 목록을 담는 div에 id="catNewsRows"를 붙였습니다.
//   시안 CSS가 `#catNewsRows{max-height:...; overflow-y:auto}`로 목록만 따로 스크롤되게
//   되어 있는데, 이 id가 없으면 그 스타일이 안 먹어서 카테고리에 기사가 많을 때
//   모달이 화면 밖으로 넘쳐버립니다. 이제 기사가 몇 건이든 목록 안에서 스크롤됩니다.
//
// 목록은 GET /categories/stats의 recent_documents에서 옵니다(분류당 최신 5건).
// 시각은 서버가 ISO로 주고 formatRelative가 렌더 시점에 '2시간 전'으로 바꿉니다 —
// 서버가 문자열을 만들면 탭을 오래 열어뒀을 때 그 값이 틀린 채로 굳습니다.
//
// ⚠ 인용문(quote)은 대체로 빈칸입니다. 인용문은 분석 4단계 중 중요도 단계 산출물인데
//   그 단계가 하루쯤 뒤처져서, 최신순으로 뽑는 이 목록에는 아직 없습니다.
//   스케줄러 타임아웃(P1)이 풀리면 채워집니다.

import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { formatRelative } from '../../lib/relativeTime';

export default function CategoryNewsModal({ category, newsItems = [], onClose }) {
  useEffect(() => {
    if (!category) return;
    function handleKey(e) {
      if (e.key === 'Escape') onClose?.();
    }
    document.addEventListener('keydown', handleKey);
    // 모달이 떠 있는 동안 배경 스크롤을 잠근다(아래 createPortal과 짝 — 자세한 이유는
    // InterestsModal.jsx의 같은 주석 참고).
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', handleKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [category, onClose]);

  if (!category) return null;

  return createPortal(
    <>
      <div className="mw-scrim open" onClick={onClose}></div>
      <div className="mw-modal open" role="dialog" aria-modal="true" aria-label="카테고리 관련 뉴스">
        <div className="mw-hd">
          <div>
            {/* '최근'을 붙인다. 카드는 분류 전체 건수(예: 45건)를 보여주는데 여기는
                최신 몇 건만 담기므로, 숫자만 쓰면 분류가 줄어든 것처럼 읽힌다. */}
            <div className="eb">CATEGORY · 최근 {newsItems.length}건</div>
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
                // 제목이 같은 기사가 여러 매체로 재배포되는 일이 있어 key는 URL로 잡는다.
                <article className="cat-news-item" key={n.sourceUrl || n.title}>
                  <h4>{n.title}</h4>
                  {n.quote ? <p>{n.quote}</p> : null}
                  <div className="meta">
                    <a className="s" href={n.sourceUrl} target="_blank" rel="noopener">{n.sourceLabel}</a>
                    {/* 목업은 '12분 전' 완성 문자열(time), 실데이터는 ISO(publishedAt) */}
                    <span>{n.publishedAt ? formatRelative(n.publishedAt) : n.time}</span>
                  </div>
                </article>
              ))
            )}
          </div>
        </div>
      </div>
    </>,
    document.body
  );
}

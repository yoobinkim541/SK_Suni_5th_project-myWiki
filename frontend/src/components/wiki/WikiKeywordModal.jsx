// 위키 본문 키워드를 눌렀을 때 뜨는 "연동 원문" 모달 (수정사항 4)
//
// 한 키워드에 엮인 근거를 두 덩어리로 나눠 보여줍니다.
//  · 공시·IR 원문 : 검증 가능한 1차 자료 (DART / IR 페이지)
//  · 관련 뉴스기사 : 보도 기반 2차 자료
// 둘 다 새 탭으로 원문에 바로 나갑니다.
//
// 모달 틀(.mw-modal / .mw-scrim)은 카테고리 뉴스 모달과 같은 시안 클래스를 재사용합니다.

import { useEffect } from 'react';
import { createPortal } from 'react-dom';

export default function WikiKeywordModal({ word, entry, onClose }) {
  useEffect(() => {
    if (!word) return;
    function handleKey(e) {
      if (e.key === 'Escape') onClose?.();
    }
    document.addEventListener('keydown', handleKey);
    // 모달이 떠 있는 동안 배경 스크롤을 잠가서 뒤 화면이 같이 움직이지 않게 한다
    // (.view/.main 조상에 걸린 애니메이션·필터가 fixed 모달의 containing block이
    //  돼버리는 문제의 근본 해결은 아래 createPortal이 하지만, 스크롤 잠금도 같이 걸어야
    //  모달이 열려 있는 동안 뒤 페이지가 안 움직인다는 기대에 맞는다).
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', handleKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [word, onClose]);

  if (!word || !entry) return null;

  const docs = entry.docs || [];
  const news = entry.news || [];

  return createPortal(
    <>
      <div className="mw-scrim open" onClick={onClose}></div>
      <div className="mw-modal open" role="dialog" aria-modal="true" aria-label={`${word} 연동 원문`}>
        <div className="mw-hd">
          <div>
            <div className="eb">KEYWORD · 원문 {docs.length}건 · 뉴스 {news.length}건</div>
            <h3>{word}</h3>
          </div>
          <button className="mw-x" onClick={onClose} aria-label="닫기">✕</button>
        </div>

        <div className="mw-body">
          {entry.desc && <p className="kwm-desc">{entry.desc}</p>}

          <div className="mw-lb">공시 · IR 원문</div>
          <div className="kwm-list">
            {docs.length === 0 ? (
              <div className="kwm-empty">이 키워드로 확인된 공시·IR 원문이 아직 없습니다. 아래 보도 기반 서술만 있습니다.</div>
            ) : (
              docs.map((d) => (
                <a className="kwm-item doc" key={d.label + d.date} href={d.url} target="_blank" rel="noopener">
                  <span className="ic" aria-hidden="true">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14" />
                    </svg>
                  </span>
                  <span className="tx">
                    <b>{d.label}</b>
                    <span className="s">{d.source} · {d.date}</span>
                  </span>
                </a>
              ))
            )}
          </div>

          <div className="mw-lb">관련 뉴스기사</div>
          <div className="kwm-list">
            {news.length === 0 ? (
              <div className="kwm-empty">연동된 뉴스기사가 없습니다.</div>
            ) : (
              news.map((n) => (
                <a className="kwm-item" key={n.title} href={n.url} target="_blank" rel="noopener">
                  <span className="ic" aria-hidden="true">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M7 17 17 7M9 7h8v8" />
                    </svg>
                  </span>
                  <span className="tx">
                    <b>{n.title}</b>
                    <span className="s">{n.source} · {n.time}</span>
                  </span>
                </a>
              ))
            )}
          </div>
        </div>
      </div>
    </>,
    document.body
  );
}

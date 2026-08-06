// 좌측 키워드 패널의 키워드를 눌렀을 때 뜨는 "이 키워드가 들어간 문서" 목록 모달
//
// 본문 안 키워드(.wiki-kw)를 누를 때 뜨는 WikiKeywordModal과 역할이 다릅니다.
//   본문 키워드  = 그 단어에 엮인 공시·IR 원문 / 뉴스기사   (WikiKeywordModal)
//   좌측 키워드  = 그 단어가 등장하는 위키 문서 목록        (이 파일)
//
// 문서를 누르면 모달을 닫고 그 문서로 이동합니다.
// 모달 틀(.mw-modal / .mw-scrim)은 기존 모달과 같은 시안 클래스를 재사용합니다.

import { useEffect } from 'react';

export default function WikiKeywordDocsModal({ word, docs, category, onSelect, onClose }) {
  useEffect(() => {
    if (!word) return;
    function handleKey(e) {
      if (e.key === 'Escape') onClose?.();
    }
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [word, onClose]);

  if (!word) return null;

  const rows = docs || [];

  return (
    <>
      <div className="mw-scrim open" onClick={onClose}></div>
      <div className="mw-modal open" role="dialog" aria-modal="true" aria-label={`${word} 관련 문서`}>
        <div className="mw-hd">
          <div>
            <div className="eb">
              KEYWORD{category ? ` · ${category}` : ''} · 문서 {rows.length}건
            </div>
            <h3>{word}</h3>
          </div>
          <button className="mw-x" onClick={onClose} aria-label="닫기">✕</button>
        </div>

        <div className="mw-body">
          <div className="mw-lb">이 키워드가 등장하는 문서</div>
          <div className="kwm-list">
            {rows.length === 0 ? (
              // 축적된 문서에서 근거를 못 찾은 경우 — 추측으로 채우지 않습니다.
              <div className="kwm-empty">
                이 키워드가 등장하는 위키 문서를 찾지 못했습니다.
              </div>
            ) : (
              rows.map((d) => (
                <button
                  type="button" className="kwm-item kwd-item" key={d.id}
                  onClick={() => { onSelect?.(d.id); onClose?.(); }}
                >
                  <span className="ic" aria-hidden="true">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M6 3h9l4 4v14H6z" />
                      <path d="M14 3v5h5" />
                    </svg>
                  </span>
                  <span className="tx">
                    <b>{d.title}</b>
                    <span className="s">{d.group} · 본문 {d.count}회 등장</span>
                  </span>
                </button>
              ))
            )}
          </div>
        </div>
      </div>
    </>
  );
}

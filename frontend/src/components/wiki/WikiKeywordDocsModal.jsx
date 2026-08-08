// 좌측 키워드 패널의 키워드를 눌렀을 때 뜨는 "이 키워드로 태깅된 문서" 목록 모달
//
// 본문 안 키워드(.wiki-kw)를 누를 때 뜨는 WikiKeywordModal과 역할이 다릅니다.
//   본문 키워드  = 그 단어에 엮인 공시·IR 원문 / 뉴스기사   (WikiKeywordModal)
//   좌측 키워드  = 그 단어로 태깅된 위키 문서 목록          (이 파일)
//
// 문서를 누르면 모달을 닫고 그 문서로 이동합니다.
// 모달 틀(.mw-modal / .mw-scrim)은 기존 모달과 같은 시안 클래스를 재사용합니다.
//
// docs: null이면 "아직 조회 중"(WikiPage.jsx가 GET /wiki/pages?keyword=를 부르는 동안),
// 빈 배열이면 "조회 끝났고 결과 없음" — 이 둘을 구분해야 로딩 중에 "찾지 못했습니다"가
// 잘못 뜨지 않습니다. error가 있으면 조회 실패를 그대로 보여줍니다(빈 결과로 둔갑시키지 않음).

import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import Spinner from '../common/Spinner';

export default function WikiKeywordDocsModal({ word, docs, category, error, onSelect, onClose }) {
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

  if (!word) return null;

  const loading = docs === null;
  const rows = docs || [];

  return createPortal(
    <>
      <div className="mw-scrim open" onClick={onClose}></div>
      <div className="mw-modal open" role="dialog" aria-modal="true" aria-label={`${word} 관련 문서`}>
        <div className="mw-hd">
          <div>
            <div className="eb">
              KEYWORD{category ? ` · ${category}` : ''}{!loading && !error ? ` · 문서 ${rows.length}건` : ''}
            </div>
            <h3>{word}</h3>
          </div>
          <button className="mw-x" onClick={onClose} aria-label="닫기">✕</button>
        </div>

        <div className="mw-body">
          <div className="mw-lb">이 키워드로 태깅된 문서</div>
          <div className="kwm-list">
            {loading ? (
              <Spinner label="문서를 찾는 중" />
            ) : error ? (
              <div className="kwm-empty">문서 목록을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</div>
            ) : rows.length === 0 ? (
              // 축적된 문서에서 근거를 못 찾은 경우 — 추측으로 채우지 않습니다.
              <div className="kwm-empty">
                이 키워드로 태깅된 위키 문서를 찾지 못했습니다.
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
                    <span className="s">{d.group}{d.count != null ? ` · 본문 ${d.count}회 등장` : ''}</span>
                  </span>
                </button>
              ))
            )}
          </div>
        </div>
      </div>
    </>,
    document.body
  );
}

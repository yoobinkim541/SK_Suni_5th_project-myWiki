// "팀에 공유" 클릭 시 뜨는 팀 세션 선택 모달.
//
// 백엔드는 팀 세션이 여러 개일 수 있다(공유할 때마다 골라야 함 — get_or_create_team_session의
// "가장 오래된 세션으로 암묵적 병합" 방식은 폐기됨, 2026-08-04 설계 변경).
// 이미 로드돼 있는 팀 pane의 conversations를 그대로 보여주고, "+ 새 공유 대화 만들어서 공유"를
// 고르면 target_session_id 없이 호출해 백엔드가 새로 만들게 한다.
//
// 모달 틀(.mw-scrim/.mw-modal/.mw-hd/.mw-body/.mw-lb)은 WikiKeywordModal.jsx/
// ReportDetailModal.jsx와 같은 시안 클래스를 재사용한다.

import { useEffect } from 'react';
import { createPortal } from 'react-dom';

export default function ShareToTeamModal({ open, teamConversations, sharing, onSelect, onClose }) {
  useEffect(() => {
    if (!open) return;
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
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <>
      <div className="mw-scrim open" onClick={onClose}></div>
      <div className="mw-modal open" role="dialog" aria-modal="true" aria-label="팀에 공유">
        <div className="mw-hd">
          <div>
            <div className="eb">SHARE</div>
            <h3>어느 팀 공유 대화에 보낼까요?</h3>
          </div>
          <button className="mw-x" onClick={onClose} aria-label="닫기">✕</button>
        </div>

        <div className="mw-body">
          <div className="mw-lb">기존 공유 대화</div>
          <div className="kwm-list">
            {teamConversations.length === 0 ? (
              <div className="kwm-empty">아직 팀 공유 대화가 없습니다. 아래에서 새로 만들어 공유하세요.</div>
            ) : (
              teamConversations.map((c) => (
                <button
                  key={c.id}
                  className="ag-conv"
                  disabled={sharing}
                  onClick={() => onSelect(c.id)}
                >
                  {c.title}<span className="d">{c.meta}</span>
                </button>
              ))
            )}
          </div>

          <div className="mw-lb">새로 만들기</div>
          <button className="ag-conv new" disabled={sharing} onClick={() => onSelect(undefined)}>
            + 새 공유 대화 만들어서 공유
          </button>
        </div>
      </div>
    </>,
    document.body
  );
}

// 오너 전용 "세션 전체 보기"에서 세션 하나를 고르면 뜨는 읽기 전용 대화 열람 모달.
//
// AgentPage를 재사용하지 않고 새로 만든다 — AgentPage는 입력창/재생성/공유/삭제 등
// 액션이 많아서 읽기 전용으로 억지로 끄는 것보다 새로 만드는 게 더 단순하고 안전하다.
// 각주 클릭 이동 같은 인터랙션 없이 role+content만 마크다운으로 보여준다
// (오너가 내용을 확인하는 용도로 충분 — 클릭해서 원문으로 이동할 필요는 없음).
//
// 모달 틀은 ParticipantsModal.jsx와 같은 시안 클래스를 재사용한다.

import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import ReactMarkdown from 'react-markdown';

export default function AdminSessionViewModal({ open, title, messages, loading, error, onClose }) {
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
      <div className="mw-modal open" role="dialog" aria-modal="true" aria-label="세션 열람">
        <div className="mw-hd">
          <div>
            <div className="eb">SESSION VIEW</div>
            <h3>{title || '대화 내용'}</h3>
          </div>
          <button className="mw-x" onClick={onClose} aria-label="닫기">✕</button>
        </div>

        <div className="mw-body">
          {error && <div className="kwm-empty">{error}</div>}
          {loading && <div className="kwm-empty">불러오는 중…</div>}
          {!loading && !error && (messages ?? []).length === 0 && (
            <div className="kwm-empty">메시지가 없습니다.</div>
          )}
          {!loading && (messages ?? []).map((m) => (
            <div key={m.id} className="set-row" style={{ display: 'block', padding: '10px 0' }}>
              <div className="ds" style={{ marginBottom: 4 }}>
                {m.role === 'user' ? '질문' : '답변'}
              </div>
              <div className="vl">
                <ReactMarkdown>{m.content}</ReactMarkdown>
              </div>
            </div>
          ))}
        </div>
      </div>
    </>,
    document.body
  );
}

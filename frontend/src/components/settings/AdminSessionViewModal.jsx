// 오너 전용 "세션 전체 보기"에서 세션 하나를 고르면 뜨는 읽기 전용 대화 열람 모달.
//
// AgentPage를 재사용하지 않고 새로 만든다 — AgentPage는 입력창/재생성/공유/삭제 등
// 액션이 많아서 읽기 전용으로 억지로 끄는 것보다 새로 만드는 게 더 단순하고 안전하다.
// 각주 클릭 이동 같은 인터랙션 없이 role+content만 마크다운으로 보여준다
// (오너가 내용을 확인하는 용도로 충분 — 클릭해서 원문으로 이동할 필요는 없음).
//
// 모달 틀은 ParticipantsModal.jsx와 같은 시안 클래스를 재사용한다.

import { useEffect } from 'react';
import ReactMarkdown from 'react-markdown';

export default function AdminSessionViewModal({ open, title, messages, loading, error, onClose }) {
  useEffect(() => {
    if (!open) return;
    function handleKey(e) {
      if (e.key === 'Escape') onClose?.();
    }
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
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
    </>
  );
}

// 팀 공유 대화의 참여자 관리 모달.
//
// 팀 세션은 이제 워크스페이스 전체가 아니라 chat_session_participants에 있는
// 참여자만 볼 수 있다(2026-08-05 참여자 관리 기능). 여기서 현재 참여자 목록을 보고,
// 아직 안 들어온 워크스페이스 멤버를 추가하거나, 참여자를 뺄 수 있다.
//
// 현재 참여자는 아바타+이름 칩에 x 아이콘(.pt-chip), 추가 후보는 아바타+이름 행에
// + 아이콘(.pt-row)으로 표시한다 — .au/.avs와 같은 초록 원 이니셜 아바타 패턴을 재사용.
//
// 권한(다른 사람 빼기는 세션 생성자만)은 백엔드가 최종 검증한다 — 여기서는 버튼을
// 다 보여주고, 거부되면 에러 메시지로 안내한다(굳이 프론트에서 먼저 숨기지 않음 —
// "왜 안 보이지" 보다 "이건 못 함"이 더 명확하다).
//
// 모달 틀은 WikiKeywordModal.jsx/ReportDetailModal.jsx와 같은 시안 클래스를 재사용한다.

import { useEffect } from 'react';

function initialOf(nameOrId) {
  return (nameOrId || '?').charAt(0).toUpperCase();
}

export default function ParticipantsModal({
  open,
  participants,
  workspaceMembers,
  loading,
  error,
  busyUserId,
  onAdd,
  onRemove,
  onClose,
}) {
  useEffect(() => {
    if (!open) return;
    function handleKey(e) {
      if (e.key === 'Escape') onClose?.();
    }
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [open, onClose]);

  if (!open) return null;

  const participantIds = new Set((participants ?? []).map((p) => p.user_id));
  const addable = (workspaceMembers ?? []).filter((m) => !participantIds.has(m.user_id));

  return (
    <>
      <div className="mw-scrim open" onClick={onClose}></div>
      <div className="mw-modal open" role="dialog" aria-modal="true" aria-label="참여자 관리">
        <div className="mw-hd">
          <div>
            <div className="eb">PARTICIPANTS</div>
            <h3>참여자 관리</h3>
          </div>
          <button className="mw-x" onClick={onClose} aria-label="닫기">✕</button>
        </div>

        <div className="mw-body">
          {error && <div className="kwm-empty">{error}</div>}

          <div className="mw-lb">현재 참여자{participants ? `(${participants.length})` : ''}</div>
          {loading && !participants ? (
            <div className="kwm-empty">불러오는 중…</div>
          ) : participants.length === 0 ? (
            <div className="kwm-empty">참여자가 없습니다.</div>
          ) : (
            <div className="pt-chips">
              {participants.map((p) => (
                <span className="pt-chip" key={p.user_id}>
                  <i className="av">{initialOf(p.display_name || p.user_id)}</i>
                  <span className="nm">{p.display_name || p.user_id}</span>
                  <span
                    role="button"
                    tabIndex={0}
                    className="x"
                    aria-label={`${p.display_name || p.user_id} 빼기`}
                    style={{ opacity: busyUserId === p.user_id ? 0.4 : 1 }}
                    onClick={() => busyUserId !== p.user_id && onRemove(p.user_id)}
                    onKeyDown={(e) => e.key === 'Enter' && busyUserId !== p.user_id && onRemove(p.user_id)}
                  >
                    ✕
                  </span>
                </span>
              ))}
            </div>
          )}

          <div className="mw-lb">추가하기</div>
          {loading && !workspaceMembers ? (
            <div className="kwm-empty">불러오는 중…</div>
          ) : addable.length === 0 ? (
            <div className="kwm-empty">추가할 수 있는 워크스페이스 멤버가 없습니다.</div>
          ) : (
            <div className="pt-list">
              {addable.map((m) => (
                <div className="pt-row" key={m.user_id}>
                  <i className="av">{initialOf(m.display_name || m.user_id)}</i>
                  <span className="nm">
                    {m.display_name || m.user_id}
                    {m.email && <span className="d"> ({m.email})</span>}
                  </span>
                  <span
                    role="button"
                    tabIndex={0}
                    className="add"
                    aria-label={`${m.display_name || m.user_id} 추가`}
                    style={{ opacity: busyUserId === m.user_id ? 0.4 : 1 }}
                    onClick={() => busyUserId !== m.user_id && onAdd(m.user_id)}
                    onKeyDown={(e) => e.key === 'Enter' && busyUserId !== m.user_id && onAdd(m.user_id)}
                  >
                    +
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

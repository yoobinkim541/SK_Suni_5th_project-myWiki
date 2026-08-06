// 팀 공유 대화의 참여자 관리 모달.
//
// 팀 세션은 이제 워크스페이스 전체가 아니라 chat_session_participants에 있는
// 참여자만 볼 수 있다(2026-08-05 참여자 관리 기능). 여기서 현재 참여자 목록을 보고,
// 아직 안 들어온 워크스페이스 멤버를 추가하거나, 참여자를 뺄 수 있다.
//
// 현재 참여자는 아바타+이름 칩에 x 아이콘(.pt-chip), 추가 후보는 아바타+이름 행에
// + 아이콘(.pt-row)으로 표시한다 — .au/.avs와 같은 초록 원 이니셜 아바타 패턴을 재사용.
//
// ⚠ 2026-08-05 변경: 역할별로 버튼을 숨긴다.
//   이전에는 버튼을 다 보여주고 백엔드가 거부하면 에러로 안내하는 방식이었으나,
//   팀 요구사항이 권한 구조를 화면에 드러내는 쪽으로 정해져 역할 기반 제어로 바꿨다.
//   · 세션 초대 → 관리자·팀장·팀원
//   · 세션에서 제외 → 관리자·팀장 (본인 탈퇴는 누구나)
//   · 게스트는 아무것도 못 함
//   실제 차단은 여전히 백엔드가 한다 — 버튼을 숨겨도 API 직접 호출은 막지 못하므로
//   서버 권한 체크가 반드시 함께 있어야 한다.
//
// 모달 틀은 WikiKeywordModal.jsx/ReportDetailModal.jsx와 같은 시안 클래스를 재사용한다.

import { useEffect } from 'react';
import {
  roleLabel,
  roleClass,
  canInviteToSession,
  canRemoveFromSession,
} from '../../constants/roles';

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
  myRole,
  myUserId,
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
  const mayInvite = canInviteToSession(myRole);

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
              {participants.map((p) => {
                const isSelf = p.user_id === myUserId;
                const mayRemove = canRemoveFromSession(myRole, { isSelf });
                const name = p.display_name || p.user_id;
                return (
                  <span className="pt-chip" key={p.user_id}>
                    <i className="av">{initialOf(name)}</i>
                    <span className="nm">{name}</span>
                    {p.role && (
                      <span className={`pt-role ${roleClass(p.role)}`}>{roleLabel(p.role)}</span>
                    )}
                    {mayRemove && (
                      <span
                        role="button"
                        tabIndex={0}
                        className="x"
                        aria-label={isSelf ? '대화에서 나가기' : `${name} 빼기`}
                        title={isSelf ? '대화에서 나가기' : `${name} 빼기`}
                        style={{ opacity: busyUserId === p.user_id ? 0.4 : 1 }}
                        onClick={() => busyUserId !== p.user_id && onRemove(p.user_id)}
                        onKeyDown={(e) => e.key === 'Enter' && busyUserId !== p.user_id && onRemove(p.user_id)}
                      >
                        ✕
                      </span>
                    )}
                  </span>
                );
              })}
            </div>
          )}

          {/* 초대 권한이 없으면(게스트) 추가 영역 자체를 숨긴다. */}
          {mayInvite && (
            <>
              <div className="mw-lb">추가하기</div>
              {loading && !workspaceMembers ? (
                <div className="kwm-empty">불러오는 중…</div>
              ) : addable.length === 0 ? (
                <div className="kwm-empty">추가할 수 있는 워크스페이스 멤버가 없습니다.</div>
              ) : (
                <div className="pt-list">
                  {addable.map((m) => {
                    const name = m.display_name || m.user_id;
                    return (
                      <div className="pt-row" key={m.user_id}>
                        <i className="av">{initialOf(name)}</i>
                        <span className="nm">
                          {name}
                          {m.email && <span className="d"> ({m.email})</span>}
                        </span>
                        {m.role && (
                          <span className={`pt-role ${roleClass(m.role)}`}>{roleLabel(m.role)}</span>
                        )}
                        <span
                          role="button"
                          tabIndex={0}
                          className="add"
                          aria-label={`${name} 추가`}
                          style={{ opacity: busyUserId === m.user_id ? 0.4 : 1 }}
                          onClick={() => busyUserId !== m.user_id && onAdd(m.user_id)}
                          onKeyDown={(e) => e.key === 'Enter' && busyUserId !== m.user_id && onAdd(m.user_id)}
                        >
                          +
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </>
          )}

          {!mayInvite && (
            <div className="kwm-empty">참여자를 추가할 권한이 없습니다.</div>
          )}
        </div>
      </div>
    </>
  );
}

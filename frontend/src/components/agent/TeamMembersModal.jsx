// 에이전트 페이지 "팀 공유 에이전트" 배너를 누르면 뜨는, 워크스페이스 전체 구성원
// 명단 모달 — 읽기 전용이다(추가/제외는 대화별 ParticipantsModal, 팀 배치는
// SettingsPage의 TeamPanel이 각자 담당한다. 여기는 "이 워크스페이스에 누가 있는지"만
// 보여준다).
//
// 모달 틀·pt-chips 시안 클래스는 ParticipantsModal.jsx와 같은 것을 재사용한다.

import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { roleLabel, roleClass } from '../../constants/roles';
import MemberAvatar from '../common/MemberAvatar';

export default function TeamMembersModal({ open, members, loading, error, onClose }) {
  useEffect(() => {
    if (!open) return;
    function handleKey(e) {
      if (e.key === 'Escape') onClose?.();
    }
    document.addEventListener('keydown', handleKey);
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
      <div className="mw-modal open" role="dialog" aria-modal="true" aria-label="팀 구성원">
        <div className="mw-hd">
          <div>
            <div className="eb">TEAM</div>
            <h3>팀 구성원{members ? `(${members.length})` : ''}</h3>
          </div>
          <button className="mw-x" onClick={onClose} aria-label="닫기">✕</button>
        </div>

        <div className="mw-body">
          {error && <div className="kwm-empty">{error}</div>}
          {!error && loading && !members ? (
            <div className="kwm-empty">불러오는 중…</div>
          ) : !error && (members ?? []).length === 0 ? (
            <div className="kwm-empty">구성원이 없습니다.</div>
          ) : !error && (
            <div className="pt-chips">
              {members.map((m) => {
                const name = m.display_name || m.user_id;
                return (
                  <span className="pt-chip" key={m.user_id}>
                    <MemberAvatar userId={m.user_id} hasAvatar={m.has_avatar} name={name} size={22} />
                    <span className="nm">{name}</span>
                    {m.role && (
                      <span className={`pt-role ${roleClass(m.role)}`}>{roleLabel(m.role)}</span>
                    )}
                  </span>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </>,
    document.body
  );
}

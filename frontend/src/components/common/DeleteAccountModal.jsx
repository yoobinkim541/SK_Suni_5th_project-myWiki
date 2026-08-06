// 회원 탈퇴(계정 삭제) 확인 모달.
//
// 되돌릴 수 없는 동작이라 두 단계로 막는다:
//  1) 무엇이 사라지는지 명시
//  2) "탈퇴"를 직접 입력해야 버튼이 활성화
//
// [2026-08-06] 백엔드가 profiles를 하드 삭제하지 않고 소프트 삭제(deleted_at)로 바뀌어서,
// 내가 만든 팀 공유 대화는 탈퇴 후에도 다른 참여자 화면에 그대로 남는다 — 아래 안내 문구는
// 그래서 "삭제되는 항목"에서 팀 공유 대화를 빼고 "개인 대화/계정 자체"만 남겼다.
//
// 모달 틀은 ParticipantsModal / ReportDetailModal과 같은 시안 클래스를 재사용한다.

import { useEffect, useState } from 'react';

const CONFIRM_WORD = '탈퇴';

export default function DeleteAccountModal({ open, busy, error, onConfirm, onClose }) {
  const [typed, setTyped] = useState('');

  useEffect(() => {
    if (open) setTyped('');
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function handleKey(e) {
      if (e.key === 'Escape' && !busy) onClose?.();
    }
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [open, busy, onClose]);

  if (!open) return null;

  const ready = typed.trim() === CONFIRM_WORD && !busy;

  return (
    <>
      <div className="mw-scrim open" onClick={() => !busy && onClose?.()}></div>
      <div className="mw-modal open" role="dialog" aria-modal="true" aria-label="회원 탈퇴">
        <div className="mw-hd">
          <div>
            <div className="eb">DELETE ACCOUNT</div>
            <h3>회원 탈퇴</h3>
          </div>
          <button className="mw-x" onClick={() => !busy && onClose?.()} aria-label="닫기">✕</button>
        </div>

        <div className="mw-body">
          <div className="da-warn">
            탈퇴하면 되돌릴 수 없습니다. 아래 항목이 모두 삭제됩니다.
          </div>

          <ul className="da-list">
            <li>계정 로그인 — 이 계정으로 다시 로그인할 수 없게 됩니다</li>
            <li>내 개인 에이전트 대화 전체 — 더 이상 접근할 수 없습니다</li>
            <li>소속 팀에서의 멤버 자격</li>
          </ul>
          <div className="da-note">
            내가 만든 팀 공유 대화는 지워지지 않고, 다른 참여자에게 그대로 남습니다.
          </div>

          <div className="mw-lb">계속하려면 "{CONFIRM_WORD}"를 입력하세요</div>
          <input
            className="fld da-input"
            type="text"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder={CONFIRM_WORD}
            aria-label="탈퇴 확인 문구 입력"
            disabled={busy}
          />

          {error && <div className="kwm-empty">{error}</div>}

          <div className="da-actions">
            <button className="dlbtn" onClick={onClose} disabled={busy}>
              취소
            </button>
            <button className="dlbtn danger" onClick={onConfirm} disabled={!ready}>
              {busy ? '처리 중…' : '탈퇴하기'}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

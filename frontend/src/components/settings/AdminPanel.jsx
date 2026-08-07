// 설정 화면의 "관리" 섹션 — 오너에게만 렌더링된다(SettingsPage.jsx에서 myRole 체크 후 렌더).
// 3개 하위 블록: 팀원 목록(역할 변경/방출), 팀 세션 전체 보기, 개인 세션 전체 보기.
//
// 방출은 회원 탈퇴 모달(DeleteAccountModal)과 달리 확인 문구 입력까지는 요구하지 않는다 —
// 대상이 본인이 아니라 타인이라 그 정도로 무겁게 막을 필요는 없고, 버튼 2단계 확인
// (한 번 누르면 "정말 방출?"로 바뀌고 다시 눌러야 실행) 정도면 충분하다는 설계 결정.

import { useEffect, useState } from 'react';
import SettingsGroup from './SettingsGroup';
import SettingsRow from './SettingsRow';
import AdminSessionViewModal from './AdminSessionViewModal';
import { roleLabel, roleClass } from '../../constants/roles';
import { listWorkspaceMembers } from '../../services/agentApi';
import {
  removeWorkspaceMember,
  updateWorkspaceMemberRole,
  listWorkspaceSessions,
  getWorkspaceSessionMessages,
} from '../../api/admin';

const ASSIGNABLE_ROLES = ['admin', 'editor', 'viewer'];

function MemberRow({ member, onRemove, onChangeRole, busy }) {
  const [confirmingRemove, setConfirmingRemove] = useState(false);

  useEffect(() => {
    if (!confirmingRemove) return;
    const t = window.setTimeout(() => setConfirmingRemove(false), 3000);
    return () => window.clearTimeout(t);
  }, [confirmingRemove]);

  return (
    <SettingsRow label={member.display_name || member.user_id} desc={member.email || ''}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <span className={`pt-role ${roleClass(member.role)}`}>{roleLabel(member.role)}</span>
        <select
          className="fld"
          value={member.role || ''}
          disabled={busy}
          onChange={(e) => onChangeRole(member.user_id, e.target.value)}
        >
          {ASSIGNABLE_ROLES.map((r) => (
            <option key={r} value={r}>{roleLabel(r)}</option>
          ))}
        </select>
        <button
          className="dlbtn danger"
          disabled={busy}
          onClick={() => {
            if (!confirmingRemove) {
              setConfirmingRemove(true);
              return;
            }
            setConfirmingRemove(false);
            onRemove(member.user_id);
          }}
        >
          {confirmingRemove ? '정말 방출?' : '방출'}
        </button>
      </div>
    </SettingsRow>
  );
}

function SessionListBlock({ title, visibility, onOpenSession }) {
  const [sessions, setSessions] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    listWorkspaceSessions(visibility)
      .then((rows) => alive && setSessions(rows))
      .catch((e) => alive && setError(e.message || '세션 목록을 불러오지 못했습니다.'));
    return () => { alive = false; };
  }, [visibility]);

  return (
    <SettingsGroup title={title}>
      {error && <SettingsRow label="오류" desc={error}><div /></SettingsRow>}
      {!error && sessions === null && (
        <SettingsRow label="불러오는 중…" desc=""><div /></SettingsRow>
      )}
      {!error && sessions !== null && sessions.length === 0 && (
        <SettingsRow label="세션이 없습니다" desc=""><div /></SettingsRow>
      )}
      {!error && (sessions ?? []).map((s) => (
        <SettingsRow key={s.id} label={s.title || '(제목 없음)'} desc={`작성자: ${s.owner_name || '알 수 없음'}`}>
          <button className="dlbtn" onClick={() => onOpenSession(s)}>보기</button>
        </SettingsRow>
      ))}
    </SettingsGroup>
  );
}

export default function AdminPanel() {
  const [members, setMembers] = useState(null);
  const [membersError, setMembersError] = useState(null);
  const [busyUserId, setBusyUserId] = useState(null);

  const [viewingSession, setViewingSession] = useState(null);
  const [sessionMessages, setSessionMessages] = useState(null);
  const [sessionMessagesLoading, setSessionMessagesLoading] = useState(false);
  const [sessionMessagesError, setSessionMessagesError] = useState(null);

  function loadMembers() {
    listWorkspaceMembers()
      .then((rows) => setMembers(rows))
      .catch((e) => setMembersError(e.message || '멤버 목록을 불러오지 못했습니다.'));
  }

  useEffect(() => {
    loadMembers();
  }, []);

  async function handleRemove(userId) {
    setBusyUserId(userId);
    try {
      await removeWorkspaceMember(userId);
      loadMembers();
    } catch (e) {
      setMembersError(e.message || '방출에 실패했습니다.');
    } finally {
      setBusyUserId(null);
    }
  }

  async function handleChangeRole(userId, role) {
    setBusyUserId(userId);
    try {
      await updateWorkspaceMemberRole(userId, role);
      loadMembers();
    } catch (e) {
      setMembersError(e.message || '역할 변경에 실패했습니다.');
    } finally {
      setBusyUserId(null);
    }
  }

  function openSession(session) {
    setViewingSession(session);
    setSessionMessages(null);
    setSessionMessagesError(null);
    setSessionMessagesLoading(true);
    getWorkspaceSessionMessages(session.id)
      .then((rows) => setSessionMessages(rows))
      .catch((e) => setSessionMessagesError(e.message || '대화 내용을 불러오지 못했습니다.'))
      .finally(() => setSessionMessagesLoading(false));
  }

  return (
    <>
      <SettingsGroup title="관리">
        {membersError && <SettingsRow label="오류" desc={membersError}><div /></SettingsRow>}
        {!membersError && members === null && (
          <SettingsRow label="불러오는 중…" desc=""><div /></SettingsRow>
        )}
        {!membersError && (members ?? []).map((m) => (
          <MemberRow
            key={m.user_id}
            member={m}
            busy={busyUserId === m.user_id}
            onRemove={handleRemove}
            onChangeRole={handleChangeRole}
          />
        ))}
      </SettingsGroup>

      <SessionListBlock title="팀 세션 전체 보기" visibility="team" onOpenSession={openSession} />
      <SessionListBlock title="개인 세션 전체 보기" visibility="private" onOpenSession={openSession} />

      <AdminSessionViewModal
        open={viewingSession !== null}
        title={viewingSession?.title}
        messages={sessionMessages}
        loading={sessionMessagesLoading}
        error={sessionMessagesError}
        onClose={() => setViewingSession(null)}
      />
    </>
  );
}

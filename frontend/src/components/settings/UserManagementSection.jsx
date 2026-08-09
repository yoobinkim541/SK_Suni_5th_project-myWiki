// AdminPanel.jsx("관리" 섹션, 오너 전용)의 "사용자" 탭 — 예전엔 역할 변경(관리 섹션)과
// 팀 배치(전체 사용자 배치, 구 TeamAdminSection)가 같은 12명을 두 번 나눠서 보여줬다.
// 한 사람당 한 행에 역할 변경 + 팀 배치 + 방출을 모두 모아 중복을 없앤다.
//
// 데이터 소스 3개를 합친다 — listWorkspaceMembers()(email 포함, 동명이인 구분용)를
// 기준으로 listAllUsersWithTeam()의 team_id/team_name을 user_id로 붙인다. listTeams()는
// 팀 배치 드롭다운 선택지(인원 0명인 빈 팀도 포함)로 따로 쓴다.
//
// 방출은 회원 탈퇴 모달과 달리 확인 문구 입력까지는 요구하지 않는다 — 대상이 본인이
// 아니라 타인이라 그 정도로 무겁게 막을 필요는 없고, 버튼 2단계 확인(한 번 누르면
// "정말 방출?"로 바뀌고 다시 눌러야 실행) 정도면 충분하다는 기존 설계 결정을 유지한다.

import { useEffect, useState } from 'react';
import SettingsRow from './SettingsRow';
import { roleLabel, roleClass } from '../../constants/roles';
import { listWorkspaceMembers } from '../../services/agentApi';
import { removeWorkspaceMember, updateWorkspaceMemberRole } from '../../api/admin';
import { listAllUsersWithTeam, listTeams, assignUserTeam } from '../../api/teams';

const ASSIGNABLE_ROLES = ['admin', 'editor', 'viewer'];
const UNASSIGNED = '__unassigned__';

function UserRow({ user, teams, onRemove, onChangeRole, onAssignTeam, busy }) {
  const [confirmingRemove, setConfirmingRemove] = useState(false);

  useEffect(() => {
    if (!confirmingRemove) return;
    const t = window.setTimeout(() => setConfirmingRemove(false), 3000);
    return () => window.clearTimeout(t);
  }, [confirmingRemove]);

  return (
    <SettingsRow label={user.display_name || user.user_id} desc={user.email || ''}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <span className={`pt-role ${roleClass(user.role)}`}>{roleLabel(user.role)}</span>
        <select
          className="fld"
          value={user.role || ''}
          disabled={busy}
          onChange={(e) => onChangeRole(user.user_id, e.target.value)}
        >
          {ASSIGNABLE_ROLES.map((r) => (
            <option key={r} value={r}>{roleLabel(r)}</option>
          ))}
        </select>
        <select
          className="fld"
          value={user.team_id || UNASSIGNED}
          disabled={busy}
          onChange={(e) => onAssignTeam(user.user_id, e.target.value)}
        >
          <option value={UNASSIGNED}>미배치</option>
          {teams.map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
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
            onRemove(user.user_id);
          }}
        >
          {confirmingRemove ? '정말 방출?' : '방출'}
        </button>
      </div>
    </SettingsRow>
  );
}

export default function UserManagementSection() {
  const [users, setUsers] = useState(null);
  const [teams, setTeams] = useState([]);
  const [error, setError] = useState(null);
  const [busyUserId, setBusyUserId] = useState(null);

  function load() {
    setError(null);
    Promise.all([listWorkspaceMembers(), listAllUsersWithTeam(), listTeams()])
      .then(([members, usersWithTeam, teamRows]) => {
        const teamInfoByUserId = new Map(
          usersWithTeam.map((u) => [u.user_id, { team_id: u.team_id, team_name: u.team_name }])
        );
        setUsers(members.map((m) => ({ ...m, ...(teamInfoByUserId.get(m.user_id) ?? {}) })));
        setTeams(teamRows);
      })
      .catch((e) => setError(e.message || '사용자 목록을 불러오지 못했습니다.'));
  }

  useEffect(() => { load(); }, []);

  async function handleRemove(userId) {
    setBusyUserId(userId);
    try {
      await removeWorkspaceMember(userId);
      load();
    } catch (e) {
      setError(e.message || '방출에 실패했습니다.');
    } finally {
      setBusyUserId(null);
    }
  }

  async function handleChangeRole(userId, role) {
    setBusyUserId(userId);
    try {
      await updateWorkspaceMemberRole(userId, role);
      load();
    } catch (e) {
      setError(e.message || '역할 변경에 실패했습니다.');
    } finally {
      setBusyUserId(null);
    }
  }

  async function handleAssignTeam(userId, teamId) {
    setBusyUserId(userId);
    try {
      await assignUserTeam(userId, teamId === UNASSIGNED ? null : teamId);
      load();
    } catch (e) {
      setError(e.message || '팀 배치 변경에 실패했습니다.');
    } finally {
      setBusyUserId(null);
    }
  }

  return (
    <>
      {error && <SettingsRow label="오류" desc={error}><div /></SettingsRow>}
      {!error && users === null && (
        <SettingsRow label="불러오는 중…" desc=""><div /></SettingsRow>
      )}
      {(users ?? []).map((u) => (
        // 오너 본인 행은 방출/역할변경 대상이 될 수 없다(백엔드도 400으로 거부).
        // 워크스페이스당 오너는 항상 1명뿐이고 이 패널은 오너에게만 렌더링되므로,
        // role === 'owner'인 행이 곧 "나"다 — 읽기 전용으로 표시하고 컨트롤을 뺀다.
        u.role === 'owner' ? (
          <SettingsRow key={u.user_id} label={`${u.display_name || u.user_id} (나)`} desc={u.email || ''}>
            <span className={`pt-role ${roleClass(u.role)}`}>{roleLabel(u.role)}</span>
          </SettingsRow>
        ) : (
          <UserRow
            key={u.user_id}
            user={u}
            teams={teams}
            busy={busyUserId === u.user_id}
            onRemove={handleRemove}
            onChangeRole={handleChangeRole}
            onAssignTeam={handleAssignTeam}
          />
        )
      ))}
    </>
  );
}

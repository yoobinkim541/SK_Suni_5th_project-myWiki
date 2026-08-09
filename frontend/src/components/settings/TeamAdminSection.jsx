// AdminPanel.jsx("관리" 섹션, 오너 전용)의 하위 블록 — 팀 생성/삭제 + 전체 사용자의
// 팀 배치를 관리자가 임의로 바꾼다. TeamPanel.jsx(팀장/팀원의 "내 팀" 초대/영입/제외)와
// 달리 자기 팀 범위 제한이 없다 — 오너는 아무나 아무 팀으로 옮길 수 있다.

import { useEffect, useState } from 'react';
import SettingsGroup from './SettingsGroup';
import SettingsRow from './SettingsRow';
import { roleLabel, roleClass } from '../../constants/roles';
import { listTeams, listAllUsersWithTeam, createTeam, deleteTeam, assignUserTeam } from '../../api/teams';

const UNASSIGNED = '__unassigned__';

export default function TeamAdminSection() {
  const [teams, setTeams] = useState(null);
  const [users, setUsers] = useState(null);
  const [error, setError] = useState(null);
  const [busyUserId, setBusyUserId] = useState(null);
  const [newTeamName, setNewTeamName] = useState('');
  const [creating, setCreating] = useState(false);
  const [confirmingDeleteId, setConfirmingDeleteId] = useState(null);

  function load() {
    setError(null);
    Promise.all([listTeams(), listAllUsersWithTeam()])
      .then(([teamRows, userRows]) => { setTeams(teamRows); setUsers(userRows); })
      .catch((e) => setError(e.message || '팀 배치 정보를 불러오지 못했습니다.'));
  }

  useEffect(() => { load(); }, []);

  useEffect(() => {
    if (confirmingDeleteId === null) return;
    const t = window.setTimeout(() => setConfirmingDeleteId(null), 3000);
    return () => window.clearTimeout(t);
  }, [confirmingDeleteId]);

  async function handleCreateTeam() {
    const name = newTeamName.trim();
    if (!name) return;
    setCreating(true);
    setError(null);
    try {
      await createTeam(name);
      setNewTeamName('');
      load();
    } catch (e) {
      setError(e.message || '팀 생성에 실패했습니다.');
    } finally {
      setCreating(false);
    }
  }

  async function handleDeleteTeam(teamId) {
    setError(null);
    try {
      await deleteTeam(teamId);
      load();
    } catch (e) {
      setError(e.message || '팀 삭제에 실패했습니다. 소속 인원이 있으면 먼저 배치를 비워야 합니다.');
    }
  }

  async function handleAssign(userId, teamId) {
    setBusyUserId(userId);
    setError(null);
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
      <SettingsGroup title="팀 배치 관리">
        {error && <SettingsRow label="오류" desc={error}><div /></SettingsRow>}

        <SettingsRow label="새 팀 만들기" desc="팀 이름은 워크스페이스 안에서 중복될 수 없습니다">
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              className="fld"
              value={newTeamName}
              placeholder="예: A팀"
              disabled={creating}
              onChange={(e) => setNewTeamName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleCreateTeam()}
            />
            <button className="dlbtn" disabled={creating || !newTeamName.trim()} onClick={handleCreateTeam}>
              만들기
            </button>
          </div>
        </SettingsRow>

        {teams === null && <SettingsRow label="불러오는 중…" desc=""><div /></SettingsRow>}
        {teams !== null && teams.map((t) => (
          <SettingsRow key={t.id} label={t.name} desc={`팀원 ${t.member_count}명`}>
            <button
              className="dlbtn danger"
              onClick={() => {
                if (confirmingDeleteId !== t.id) { setConfirmingDeleteId(t.id); return; }
                setConfirmingDeleteId(null);
                handleDeleteTeam(t.id);
              }}
            >
              {confirmingDeleteId === t.id ? '정말 삭제?' : '삭제'}
            </button>
          </SettingsRow>
        ))}
      </SettingsGroup>

      <SettingsGroup title="전체 사용자 배치">
        {users === null && <SettingsRow label="불러오는 중…" desc=""><div /></SettingsRow>}
        {users !== null && users.map((u) => (
          <SettingsRow key={u.user_id} label={u.display_name || u.user_id} desc="">
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              {u.role && <span className={`pt-role ${roleClass(u.role)}`}>{roleLabel(u.role)}</span>}
              <select
                className="fld"
                value={u.team_id || UNASSIGNED}
                disabled={busyUserId === u.user_id || teams === null}
                onChange={(e) => handleAssign(u.user_id, e.target.value)}
              >
                <option value={UNASSIGNED}>미배치</option>
                {(teams ?? []).map((t) => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
            </div>
          </SettingsRow>
        ))}
      </SettingsGroup>
    </>
  );
}

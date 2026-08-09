// AdminPanel.jsx("관리" 섹션, 오너 전용)의 "팀" 탭 — 팀 생성/삭제만 담당한다.
// 사용자별 팀 배치는 UserManagementSection.jsx("사용자" 탭)로 옮겨 중복을 없앴다
// (예전 이름 TeamAdminSection에는 "전체 사용자 배치" 목록도 같이 있었다).

import { useEffect, useState } from 'react';
import SettingsRow from './SettingsRow';
import { listTeams, createTeam, deleteTeam } from '../../api/teams';

export default function TeamCrudSection() {
  const [teams, setTeams] = useState(null);
  const [error, setError] = useState(null);
  const [newTeamName, setNewTeamName] = useState('');
  const [creating, setCreating] = useState(false);
  const [confirmingDeleteId, setConfirmingDeleteId] = useState(null);

  function load() {
    setError(null);
    listTeams()
      .then(setTeams)
      .catch((e) => setError(e.message || '팀 목록을 불러오지 못했습니다.'));
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

  return (
    <>
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
      {teams !== null && teams.length === 0 && (
        <SettingsRow label="아직 생성된 팀이 없습니다" desc=""><div /></SettingsRow>
      )}
      {(teams ?? []).map((t) => (
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
    </>
  );
}

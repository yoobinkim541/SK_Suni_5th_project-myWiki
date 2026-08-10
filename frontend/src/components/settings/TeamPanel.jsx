// 설정 화면의 "소속 팀" 섹션 — 관리자/팀장/팀원 전원에게 노출된다(GET /teams,
// GET /teams/{id}/members는 워크스페이스 멤버 누구나 조회 가능한 엔드포인트).
//
// 백엔드에 "내 팀"을 바로 알려주는 엔드포인트가 없어서(팀 수가 적은 소규모
// 워크스페이스라는 전제), 팀 목록 + 팀별 멤버 명단을 모두 불러온 뒤 내 user_id가
// 들어있는 팀을 프론트에서 찾는다. 팀이 몇 개 안 되므로 이 정도 병렬 조회는
// 백엔드에 team_id 조회 엔드포인트를 새로 추가하는 것보다 단순하다.
//
// 초대/영입 후보 목록·액션 버튼은 ParticipantsModal.jsx(세션 참여자 관리)와 같은
// pt-chips/pt-list/pt-row 시안 클래스를 그대로 재사용한다.

import { useEffect, useState } from 'react';
import SettingsGroup from './SettingsGroup';
import SettingsRow from './SettingsRow';
import { roleLabel, roleClass, canInviteToTeam, canRecruitToTeam, canRemoveFromTeam } from '../../constants/roles';
import { listTeams, listTeamMembers, inviteTeamMember, recruitTeamMember, removeTeamMember } from '../../api/teams';
import { listWorkspaceMembers } from '../../services/agentApi';
import MemberAvatar from '../common/MemberAvatar';

export default function TeamPanel({ myRole, myUserId }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busyUserId, setBusyUserId] = useState(null);

  const [teams, setTeams] = useState([]);
  const [membersByTeamId, setMembersByTeamId] = useState({});
  const [workspaceMembers, setWorkspaceMembers] = useState([]);

  function load() {
    setLoading(true);
    setError(null);
    listTeams()
      .then(async (teamRows) => {
        const memberLists = await Promise.all(teamRows.map((t) => listTeamMembers(t.id)));
        const byId = {};
        teamRows.forEach((t, i) => { byId[t.id] = memberLists[i]; });
        return Promise.all([teamRows, byId, listWorkspaceMembers()]);
      })
      .then(([teamRows, byId, allMembers]) => {
        setTeams(teamRows);
        setMembersByTeamId(byId);
        setWorkspaceMembers(allMembers ?? []);
      })
      .catch((e) => setError(e.message || '팀 정보를 불러오지 못했습니다.'))
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(); }, []);

  // 내 user_id가 들어있는 팀을 찾는다 — 없으면 미배치.
  const myTeam = teams.find((t) => (membersByTeamId[t.id] ?? []).some((m) => m.user_id === myUserId)) ?? null;
  const myTeamMembers = myTeam ? membersByTeamId[myTeam.id] ?? [] : [];

  // 어느 팀에도 없는 workspace 멤버(초대 후보).
  const assignedIds = new Set(Object.values(membersByTeamId).flat().map((m) => m.user_id));
  const unassignedCandidates = workspaceMembers.filter((m) => !assignedIds.has(m.user_id));

  // 다른 팀 소속인 workspace 멤버(영입 후보) — 소속 팀 id/이름을 같이 보여준다.
  const teamIdByMemberId = {};
  const teamNameByMemberId = {};
  teams.forEach((t) => {
    (membersByTeamId[t.id] ?? []).forEach((m) => {
      teamIdByMemberId[m.user_id] = t.id;
      teamNameByMemberId[m.user_id] = t.name;
    });
  });
  const otherTeamCandidates = myTeam
    ? workspaceMembers.filter((m) => assignedIds.has(m.user_id) && teamIdByMemberId[m.user_id] !== myTeam.id)
    : [];

  async function runAction(userId, action) {
    setBusyUserId(userId);
    setError(null);
    try {
      await action();
      load();
    } catch (e) {
      setError(e.message || '작업에 실패했습니다.');
      setBusyUserId(null);
    }
  }

  const handleInvite = (userId) => runAction(userId, () => inviteTeamMember(myTeam.id, userId));
  const handleRecruit = (userId) => runAction(userId, () => recruitTeamMember(myTeam.id, userId));
  const handleRemove = (userId) => runAction(userId, () => removeTeamMember(myTeam.id, userId));

  return (
    <SettingsGroup title="소속 팀">
      {error && <SettingsRow label="오류" desc={error}><div /></SettingsRow>}
      {!error && loading && (
        <SettingsRow label="불러오는 중…" desc=""><div /></SettingsRow>
      )}
      {!error && !loading && !myTeam && (
        <SettingsRow label="미배치" desc="아직 소속된 팀이 없습니다. 관리자에게 배치를 요청하세요.">
          <div />
        </SettingsRow>
      )}

      {!error && !loading && myTeam && (
        <>
          <SettingsRow label={myTeam.name} desc={`팀원 ${myTeamMembers.length}명`}>
            <div />
          </SettingsRow>

          <div className="pt-chips">
            {myTeamMembers.map((m) => {
              const name = m.display_name || m.user_id;
              const isSelf = m.user_id === myUserId;
              const mayRemove = canRemoveFromTeam(myRole) && !isSelf;
              return (
                <span className="pt-chip" key={m.user_id}>
                  <MemberAvatar userId={m.user_id} hasAvatar={m.has_avatar} name={name} size={22} />
                  <span className="nm">{name}{isSelf ? ' (나)' : ''}</span>
                  {m.role && <span className={`pt-role ${roleClass(m.role)}`}>{roleLabel(m.role)}</span>}
                  {mayRemove && (
                    <span
                      role="button"
                      tabIndex={0}
                      className="x"
                      aria-label={`${name} 팀에서 제외`}
                      title={`${name} 팀에서 제외`}
                      style={{ opacity: busyUserId === m.user_id ? 0.4 : 1 }}
                      onClick={() => busyUserId !== m.user_id && handleRemove(m.user_id)}
                      onKeyDown={(e) => e.key === 'Enter' && busyUserId !== m.user_id && handleRemove(m.user_id)}
                    >
                      ✕
                    </span>
                  )}
                </span>
              );
            })}
          </div>

          {canInviteToTeam(myRole) && (
            <>
              <div className="mw-lb">초대하기 (미배치 사용자)</div>
              {unassignedCandidates.length === 0 ? (
                <div className="kwm-empty">초대할 수 있는 미배치 사용자가 없습니다.</div>
              ) : (
                <div className="pt-list">
                  {unassignedCandidates.map((m) => {
                    const name = m.display_name || m.user_id;
                    return (
                      <div className="pt-row" key={m.user_id}>
                        <MemberAvatar userId={m.user_id} hasAvatar={m.has_avatar} name={name} size={24} />
                        <span className="nm">{name}</span>
                        <span
                          role="button"
                          tabIndex={0}
                          className="add"
                          aria-label={`${name} 초대`}
                          style={{ opacity: busyUserId === m.user_id ? 0.4 : 1 }}
                          onClick={() => busyUserId !== m.user_id && handleInvite(m.user_id)}
                          onKeyDown={(e) => e.key === 'Enter' && busyUserId !== m.user_id && handleInvite(m.user_id)}
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

          {canRecruitToTeam(myRole) && (
            <>
              <div className="mw-lb">영입하기 (다른 팀 소속)</div>
              {otherTeamCandidates.length === 0 ? (
                <div className="kwm-empty">영입할 수 있는 다른 팀 소속 사용자가 없습니다.</div>
              ) : (
                <div className="pt-list">
                  {otherTeamCandidates.map((m) => {
                    const name = m.display_name || m.user_id;
                    return (
                      <div className="pt-row" key={m.user_id}>
                        <MemberAvatar userId={m.user_id} hasAvatar={m.has_avatar} name={name} size={24} />
                        <span className="nm">{name} <span className="d">({teamNameByMemberId[m.user_id]})</span></span>
                        <span
                          role="button"
                          tabIndex={0}
                          className="add"
                          aria-label={`${name} 영입`}
                          style={{ opacity: busyUserId === m.user_id ? 0.4 : 1 }}
                          onClick={() => busyUserId !== m.user_id && handleRecruit(m.user_id)}
                          onKeyDown={(e) => e.key === 'Enter' && busyUserId !== m.user_id && handleRecruit(m.user_id)}
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
        </>
      )}
    </SettingsGroup>
  );
}

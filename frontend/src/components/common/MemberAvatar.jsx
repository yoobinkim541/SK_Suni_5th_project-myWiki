// 워크스페이스 멤버 한 명의 아바타 — 사진이 있으면 <img>, 없으면 이니셜 원(.av).
// TeamPanel.jsx에 있던 걸 공용으로 뺐다 — ParticipantsModal/AgentPage의 팀 배너도
// 같은 useAvatarUrl(GET /workspace/members/{id}/avatar) 패턴을 그대로 써야 해서다.
import useAvatarUrl from '../../hooks/useAvatarUrl';

function initialOf(nameOrId) {
  return (nameOrId || '?').charAt(0).toUpperCase();
}

export default function MemberAvatar({ userId, hasAvatar, name, size }) {
  const avatarUrl = useAvatarUrl(userId, hasAvatar);
  if (avatarUrl) {
    return (
      <img
        src={avatarUrl}
        alt=""
        style={{ width: size, height: size, borderRadius: '50%', objectFit: 'cover', flex: 'none' }}
      />
    );
  }
  return <i className="av">{initialOf(name)}</i>;
}

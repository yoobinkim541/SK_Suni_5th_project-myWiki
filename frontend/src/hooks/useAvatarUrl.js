// 워크스페이스 멤버 프로필 사진 조회 공통 훅 — TeamPanel/UserManagementSection처럼
// 여러 사람의 사진을 나란히 보여주는 화면에서 쓴다. hasAvatar가 false인 사람은
// 애초에 조회하지 않는다(항상 404이므로 헛수고).
//
// "내 사진"(App.jsx의 상단바·프로필 패널)은 이 훅을 쓰지 않는다 — 방금 올린 사진을
// 바로 반영해야 해서 hasAvatar가 true→true로 안 바뀌어도 다시 받아와야 하는데,
// 이 훅은 [userId, hasAvatar]가 바뀔 때만 다시 조회하기 때문이다. App.jsx는 자체
// loadMyProfile()에서 매번 명시적으로 다시 받아온다.

import { useEffect, useState } from 'react';
import { fetchMemberAvatarBlob } from '../api/profile';

export default function useAvatarUrl(userId, hasAvatar) {
  const [avatarUrl, setAvatarUrl] = useState(null);

  useEffect(() => {
    if (!hasAvatar || !userId) {
      setAvatarUrl(null);
      return;
    }
    let alive = true;
    let objectUrl = null;
    fetchMemberAvatarBlob(userId)
      .then(({ blob }) => {
        if (!alive) return;
        objectUrl = URL.createObjectURL(blob);
        setAvatarUrl(objectUrl);
      })
      .catch(() => alive && setAvatarUrl(null));
    return () => {
      alive = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [userId, hasAvatar]);

  return avatarUrl;
}

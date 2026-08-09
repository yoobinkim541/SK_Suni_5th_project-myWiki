// 설정 화면 "계정" 섹션의 "프로필"(사진)·"이름" 행 — 예전엔 OAuth 로그인 이름을
// 그대로 보여주기만 하는 읽기전용이었다. 이제 앱 자체 profiles.display_name/
// avatar_object_key를 편집할 수 있다.
//
// ⚠ profile/avatarUrl은 App.jsx가 소유한다(상단바·프로필 패널과 같은 값을 공유해야
// 하므로) — 이 컴포넌트가 직접 조회하지 않는다. 저장/업로드/삭제에 성공하면
// onProfileChange()로 App.jsx에게 다시 불러오라고 알린다 — 안 그러면 여기서는
// 바뀐 이름·사진이 보여도 상단바는 예전 값 그대로 남는다(이 기능을 처음 만들 때
// 실제로 겪은 문제).

import { useEffect, useRef, useState } from 'react';
import SettingsRow from './SettingsRow';
import { updateProfile, uploadAvatar, deleteAvatar } from '../../api/profile';

function initialOf(name) {
  return (name || '?').charAt(0).toUpperCase();
}

export default function ProfileFields({ profile, avatarUrl, onProfileChange }) {
  const [error, setError] = useState(null);
  const [nameInput, setNameInput] = useState(profile?.display_name || '');
  const [savingName, setSavingName] = useState(false);
  const [nameSaved, setNameSaved] = useState(false);
  const [avatarBusy, setAvatarBusy] = useState(false);
  const fileInputRef = useRef(null);

  // App.jsx에서 새로 받아온 profile로 입력창 기본값을 맞춘다 — 단, 사용자가 지금
  // 타이핑 중인 값을 덮어쓰지 않도록 저장 중(savingName)이 아닐 때만 동기화한다.
  useEffect(() => {
    if (!savingName) setNameInput(profile?.display_name || '');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile?.display_name]);

  async function handleSaveName() {
    const trimmed = nameInput.trim();
    if (!trimmed || trimmed === profile?.display_name) return;
    setSavingName(true);
    setError(null);
    try {
      await updateProfile(trimmed);
      onProfileChange?.();
      setNameSaved(true);
      window.setTimeout(() => setNameSaved(false), 2000);
    } catch (e) {
      setError(e.message || '이름 저장에 실패했습니다.');
    } finally {
      setSavingName(false);
    }
  }

  async function handleFileChange(e) {
    const file = e.target.files?.[0];
    e.target.value = ''; // 같은 파일을 다시 골라도 change가 다시 일어나게 초기화
    if (!file) return;
    setAvatarBusy(true);
    setError(null);
    try {
      await uploadAvatar(file);
      onProfileChange?.();
    } catch (err) {
      setError(err.message || '프로필 사진 업로드에 실패했습니다.');
    } finally {
      setAvatarBusy(false);
    }
  }

  async function handleRemoveAvatar() {
    setAvatarBusy(true);
    setError(null);
    try {
      await deleteAvatar();
      onProfileChange?.();
    } catch (err) {
      setError(err.message || '프로필 사진 삭제에 실패했습니다.');
    } finally {
      setAvatarBusy(false);
    }
  }

  return (
    <>
      {error && <SettingsRow label="오류" desc={error}><div /></SettingsRow>}

      <SettingsRow label="프로필" desc="에이전트 답변·리포트에 표시되는 프로필입니다">
        <div className="set-av">
          {avatarUrl ? (
            <img
              src={avatarUrl}
              alt="프로필 사진"
              style={{ width: 40, height: 40, borderRadius: '50%', objectFit: 'cover' }}
            />
          ) : (
            <span className="av">{initialOf(profile?.display_name)}</span>
          )}
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp,image/gif"
            style={{ display: 'none' }}
            onChange={handleFileChange}
          />
          <button className="dlbtn" disabled={avatarBusy || profile === null} onClick={() => fileInputRef.current?.click()}>
            사진 변경
          </button>
          {profile?.has_avatar && (
            <button className="dlbtn danger" disabled={avatarBusy} onClick={handleRemoveAvatar}>
              삭제
            </button>
          )}
        </div>
      </SettingsRow>

      <SettingsRow label="이름" desc="워크스페이스에 표시되는 이름">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <input
            className="fld"
            value={nameInput}
            disabled={savingName || profile === null}
            maxLength={50}
            onChange={(e) => setNameInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSaveName()}
          />
          <button
            className="dlbtn"
            disabled={savingName || !nameInput.trim() || nameInput.trim() === profile?.display_name}
            onClick={handleSaveName}
          >
            {nameSaved ? '저장됨' : '저장'}
          </button>
        </div>
      </SettingsRow>
    </>
  );
}

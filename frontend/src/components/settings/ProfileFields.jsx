// 설정 화면 "계정" 섹션의 "프로필"(사진)·"이름" 행 — 예전엔 OAuth 로그인 이름을
// 그대로 보여주기만 하는 읽기전용이었다. 이제 앱 자체 profiles.display_name/
// avatar_object_key를 편집할 수 있다.
//
// 아바타는 비공개 버킷이라 <img src="URL">로 직접 못 부른다 — apiFetchBlob으로
// 인증 헤더와 함께 바이트를 받아 Object URL을 만들어 쓴다(언마운트/재조회 시 해제).

import { useEffect, useRef, useState } from 'react';
import SettingsRow from './SettingsRow';
import { fetchProfile, updateProfile, fetchAvatarBlob, uploadAvatar, deleteAvatar } from '../../api/profile';

function initialOf(name) {
  return (name || '?').charAt(0).toUpperCase();
}

export default function ProfileFields() {
  const [profile, setProfile] = useState(null);
  const [avatarUrl, setAvatarUrl] = useState(null);
  const [error, setError] = useState(null);

  const [nameInput, setNameInput] = useState('');
  const [savingName, setSavingName] = useState(false);
  const [nameSaved, setNameSaved] = useState(false);
  const [avatarBusy, setAvatarBusy] = useState(false);
  const fileInputRef = useRef(null);

  useEffect(() => {
    let alive = true;
    fetchProfile()
      .then((p) => {
        if (!alive) return;
        setProfile(p);
        setNameInput(p.display_name || '');
      })
      .catch((e) => alive && setError(e.message || '프로필을 불러오지 못했습니다.'));
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!profile?.has_avatar) {
      setAvatarUrl(null);
      return;
    }
    let alive = true;
    let objectUrl = null;
    fetchAvatarBlob()
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
  }, [profile?.has_avatar]);

  async function handleSaveName() {
    const trimmed = nameInput.trim();
    if (!trimmed || trimmed === profile?.display_name) return;
    setSavingName(true);
    setError(null);
    try {
      const updated = await updateProfile(trimmed);
      setProfile(updated);
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
      const updated = await uploadAvatar(file);
      setProfile(updated);
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
      setProfile((p) => (p ? { ...p, has_avatar: false } : p));
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

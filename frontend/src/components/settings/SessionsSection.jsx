// AdminPanel.jsx("관리" 섹션, 오너 전용)의 "세션" 탭 — 팀/개인 서브탭으로 전환한다.
// 예전엔 팀 세션·개인 세션 목록을 둘 다 항상 불러와서 나란히 보여줬다(불필요한 API
// 호출 2회 + 화면 길이 2배). 이제 선택한 쪽만 불러온다.

import { useEffect, useRef, useState } from 'react';
import SettingsRow from './SettingsRow';
import SegmentedControl from '../common/SegmentedControl';
import AdminSessionViewModal from './AdminSessionViewModal';
import { listWorkspaceSessions, getWorkspaceSessionMessages } from '../../api/admin';

const VISIBILITY_OPTIONS = [
  { value: 'team', label: '팀 세션' },
  { value: 'private', label: '개인 세션' },
];

export default function SessionsSection() {
  const [visibility, setVisibility] = useState('team');
  const [sessions, setSessions] = useState(null);
  const [error, setError] = useState(null);

  const [viewingSession, setViewingSession] = useState(null);
  const [sessionMessages, setSessionMessages] = useState(null);
  const [sessionMessagesLoading, setSessionMessagesLoading] = useState(false);
  const [sessionMessagesError, setSessionMessagesError] = useState(null);
  const latestSessionRequest = useRef(0);

  useEffect(() => {
    let alive = true;
    setSessions(null);
    setError(null);
    listWorkspaceSessions(visibility)
      .then((rows) => alive && setSessions(rows))
      .catch((e) => alive && setError(e.message || '세션 목록을 불러오지 못했습니다.'));
    return () => { alive = false; };
  }, [visibility]);

  function openSession(session) {
    const requestId = ++latestSessionRequest.current;
    setViewingSession(session);
    setSessionMessages(null);
    setSessionMessagesError(null);
    setSessionMessagesLoading(true);
    getWorkspaceSessionMessages(session.id)
      .then((rows) => { if (requestId === latestSessionRequest.current) setSessionMessages(rows); })
      .catch((e) => { if (requestId === latestSessionRequest.current) setSessionMessagesError(e.message || '대화 내용을 불러오지 못했습니다.'); })
      .finally(() => { if (requestId === latestSessionRequest.current) setSessionMessagesLoading(false); });
  }

  return (
    <>
      <SettingsRow label="보기" desc="열람할 세션 범위">
        <SegmentedControl options={VISIBILITY_OPTIONS} value={visibility} onChange={setVisibility} />
      </SettingsRow>

      {error && <SettingsRow label="오류" desc={error}><div /></SettingsRow>}
      {!error && sessions === null && (
        <SettingsRow label="불러오는 중…" desc=""><div /></SettingsRow>
      )}
      {!error && sessions !== null && sessions.length === 0 && (
        <SettingsRow label="세션이 없습니다" desc=""><div /></SettingsRow>
      )}
      {!error && (sessions ?? []).map((s) => (
        <SettingsRow key={s.id} label={s.title || '(제목 없음)'} desc={`작성자: ${s.owner_name || '알 수 없음'}`}>
          <button className="dlbtn" onClick={() => openSession(s)}>보기</button>
        </SettingsRow>
      ))}

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

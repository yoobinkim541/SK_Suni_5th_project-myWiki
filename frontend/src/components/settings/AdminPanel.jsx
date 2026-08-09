// 설정 화면의 "관리" 섹션 — 오너에게만 렌더링된다(SettingsPage.jsx에서 myRole 체크 후 렌더).
//
// ⚠ 수정: 예전엔 "관리"(역할 변경) + "팀 세션 전체 보기" + "개인 세션 전체 보기" +
//   "팀 배치 관리" + "전체 사용자 배치" 5개 카드가 항상 전부 펼쳐진 채 쌓여 있었고,
//   그중 "관리"와 "전체 사용자 배치"는 같은 사람 목록을 역할/팀으로 나눠 두 번 보여주는
//   중복이었다 — 한눈에 보기 너무 많다는 피드백으로 카드 하나 + 상단 탭(사용자/팀/세션)
//   으로 통합했다. 사용자 탭에서 역할·팀 배치·방출을 한 행에서 전부 처리한다.

import { useState } from 'react';
import SettingsGroup from './SettingsGroup';
import SettingsRow from './SettingsRow';
import SegmentedControl from '../common/SegmentedControl';
import UserManagementSection from './UserManagementSection';
import TeamCrudSection from './TeamCrudSection';
import SessionsSection from './SessionsSection';

const TAB_OPTIONS = [
  { value: 'users', label: '사용자' },
  { value: 'teams', label: '팀' },
  { value: 'sessions', label: '세션' },
];

export default function AdminPanel() {
  const [tab, setTab] = useState('users');

  return (
    <SettingsGroup title="관리">
      <SettingsRow label="보기" desc="사용자 역할·팀 배치, 팀 생성·삭제, 세션 열람">
        <SegmentedControl options={TAB_OPTIONS} value={tab} onChange={setTab} />
      </SettingsRow>

      {tab === 'users' && <UserManagementSection />}
      {tab === 'teams' && <TeamCrudSection />}
      {tab === 'sessions' && <SessionsSection />}
    </SettingsGroup>
  );
}

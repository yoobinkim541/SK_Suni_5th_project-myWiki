// 설정 페이지 — PC/모바일 공용 (#v-settings)
// 계정 설정 / 알림 / 세션 / 화면 / 데이터·파이프라인 / 앱·소스 6개 섹션을
// SettingsGroup + SettingsRow로 조립합니다.
//
// 다크 모드: 상단 톱니바퀴 드롭다운(SettingsPanel)의 다크 모드 토글과
// 이 페이지의 다크 모드 토글은 시안에서 "동일한 테마 상태"를 공유합니다
// (원본 vanilla JS 주석: "페이지 다크 토글도 상단 설정 패널과 동일한 테마 상태를 사용").
// 그래서 이 컴포넌트는 dark/onToggleDark를 App.jsx에서 그대로 내려받아 씁니다 —
// 컴포넌트 안에서 새로 상태를 만들지 않습니다.
// (App.jsx에서 <SettingsPage dark={dark} onToggleDark={setDark} /> 로 내려주고 있습니다.)
//
// ⚠ 수정: .view 클래스에 .on을 붙였습니다. globals.css가 `.view{display:none}` /
//   `.view.on{display:block}` 이라서, .on이 없으면 설정 페이지 전체가 화면에 안 그려졌습니다.
//
// ⚠ 알림(notiReport/notiWiki)도 다크모드와 같은 이유로 App.jsx 상태를 그대로 받습니다 —
//   상단바 톱니바퀴 드롭다운(SettingsPanel)에도 같은 알림 토글이 새로 생겨서, 여기서만
//   따로 상태를 들고 있으면 둘이 어긋납니다.
//
// 에이전트 참조 범위·일일 리포트 생성 시간은 아직 백엔드가 없어서 이 페이지 안의
// 로컬 상태로만 관리합니다(localStorage에 저장해 새로고침해도 유지).
//
// ⚠ 수정: Wiki 업데이트 주기 / 대화 보관 기간은 workspace_settings 테이블(GET·PATCH
//   /settings)에 실제로 연결했습니다 — 예전엔 localStorage에만 저장돼서 드롭다운을
//   바꿔도 실제 위키 갱신 주기(항상 6시간 고정)엔 아무 영향이 없었습니다. 이제 값을
//   바꾸면 바로 서버에 저장되고, 다음 wiki-refresh-gate 배치부터 그 주기를 따릅니다.
//   localStorage는 그대로 두되(오프라인/초기 렌더용 캐시), 마운트 시 서버 값으로 덮어씁니다.
//
// ⚠ 수정: "수집 소스" 표기를 services/settingsApi.js 경유로 바꿨습니다.
//   기존 문구("네이버 뉴스 API · OpenDART · RSS 6개 매체" / "3종 연결됨")가
//   scripts/register_sources.py의 실제 등록 내용과 달라서(GNews 누락, RSS는 1건)
//   화면이 근거 없는 숫자를 단정하고 있었습니다.
//
// ⚠ 수정(2026-08-04): "일일 수집 시각"(고정 텍스트 "08:00", 백엔드 미연결)을 걷어내고
//   "데이터 갱신 주기" 드롭다운으로 교체했습니다 — Wiki 업데이트 주기와 동일하게
//   workspace_settings.data_refresh_cycle_minutes에 실제로 연결됩니다.
//   설정 저장 성공 시 우측 하단 토스트(.settings-toast)로 피드백을 줍니다 — Wiki 업데이트
//   주기·대화 보관 기간 저장도 동일하게 토스트가 뜨도록 통일했습니다.
//
// ⚠ 수정(2026-08-05): 계정 섹션에 "소속 팀", 세션 섹션에 "회원 탈퇴"를 추가했습니다.
//   · 소속 팀 — 워크스페이스 이름 + 내 역할(관리자/팀장/팀원/게스트).
//     둘 다 없으면 행 자체를 숨깁니다(없는 값을 "소속 없음"처럼 단정하지 않습니다).
//   · 회원 탈퇴 — 되돌릴 수 없는 동작이라 여기서 바로 실행하지 않고, App.jsx가 들고 있는
//     DeleteAccountModal을 열어 한 번 더 확인받습니다.

import { useState, useEffect } from 'react';
import SettingsGroup from '../components/settings/SettingsGroup';
import SettingsRow from '../components/settings/SettingsRow';
import ToggleSwitch from '../components/common/ToggleSwitch';
import SegmentedControl from '../components/common/SegmentedControl';
import { roleLabel, roleClass } from '../constants/roles';
import AdminPanel from '../components/settings/AdminPanel';
import TeamPanel from '../components/settings/TeamPanel';
import ProfileFields from '../components/settings/ProfileFields';
import {
  fetchCollectSources,
  formatSourceSummary,
  formatSourceCount,
  fetchWorkspaceSettings,
  updateWikiCycle,
  updateDataRefreshCycle,
  updateChatRetention,
} from '../services/settingsApi';

function getInitial(key, fallback) {
  try {
    return localStorage.getItem(key) || fallback;
  } catch {
    return fallback;
  }
}

export default function SettingsPage({
  dark = false,
  onToggleDark = () => {},
  notiReport = true,
  onToggleNotiReport = () => {},
  notiWiki = true,
  onToggleNotiWiki = () => {},
  profile = null,
  myProfile = null,
  myAvatarUrl = null,
  onProfileChange,
  workspaceName = null,
  myRole = null,
  onLogout,
  onDeleteAccount,
  onResetInterests,
}) {
  const [agentScope, setAgentScope] = useState('all');
  const [reportTime, setReportTime] = useState(() => getInitial('mywiki-report-time', '08:30'));
  const [wikiCycle, setWikiCycle] = useState(() => getInitial('mywiki-wiki-cycle', '6h'));
  const [dataCycle, setDataCycle] = useState(() => getInitial('mywiki-data-cycle', '2h'));
  const [chatKeep, setChatKeep] = useState(() => getInitial('mywiki-chat-keep', '90'));

  // 설정 저장 성공 토스트 — 우측 하단, 2.8초 뒤 자동 소멸(report/ReportSection.jsx의
  // .dl-toast와 같은 패턴이지만 위치만 다름).
  const [toast, setToast] = useState('');
  function showToast(message) {
    setToast(message);
    window.clearTimeout(showToast._t);
    showToast._t = window.setTimeout(() => setToast(''), 2800);
  }

  // 수집 소스 — 백엔드 조회 엔드포인트가 열리면 settingsApi 쪽만 바뀝니다.
  const [sources, setSources] = useState([]);

  const accountEmail = profile?.email || '';
  const hasTeam = Boolean(workspaceName || myRole);

  useEffect(() => {
    let alive = true;
    fetchCollectSources()
      .then((rows) => alive && setSources(rows))
      .catch(() => alive && setSources([]));
    return () => {
      alive = false;
    };
  }, []);

  // 실제 워크스페이스 설정으로 localStorage 초기값을 덮어씁니다(목업 모드거나 조회
  // 실패 시에는 그대로 localStorage 값을 씁니다 — fetchWorkspaceSettings가 null 반환).
  useEffect(() => {
    let alive = true;
    fetchWorkspaceSettings()
      .then((settings) => {
        if (!alive || !settings) return;
        setWikiCycle(settings.wikiCycle);
        setDataCycle(settings.dataCycle);
        setChatKeep(settings.chatKeep);
      })
      .catch(() => { /* 조회 실패 — localStorage 초기값 유지 */ });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    try { localStorage.setItem('mywiki-report-time', reportTime); } catch { /* noop */ }
  }, [reportTime]);
  useEffect(() => {
    try { localStorage.setItem('mywiki-wiki-cycle', wikiCycle); } catch { /* noop */ }
  }, [wikiCycle]);
  useEffect(() => {
    try { localStorage.setItem('mywiki-data-cycle', dataCycle); } catch { /* noop */ }
  }, [dataCycle]);
  useEffect(() => {
    try { localStorage.setItem('mywiki-chat-keep', chatKeep); } catch { /* noop */ }
  }, [chatKeep]);

  // 드롭다운을 바꾸면 즉시 서버에 저장합니다. 성공하면 우측 하단에 토스트를 띄우고,
  // 실패해도 화면 값은 그대로 두고 콘솔에만 남깁니다(재시도 UI는 이번 범위 밖).
  function handleWikiCycleChange(value) {
    setWikiCycle(value);
    updateWikiCycle(value)
      .then(() => showToast('Wiki 업데이트 주기가 저장됐습니다'))
      .catch((err) => console.error('Wiki 업데이트 주기 저장 실패', err));
  }
  function handleDataCycleChange(value) {
    setDataCycle(value);
    updateDataRefreshCycle(value)
      .then(() => showToast('데이터 갱신 주기가 저장됐습니다'))
      .catch((err) => console.error('데이터 갱신 주기 저장 실패', err));
  }
  function handleChatKeepChange(value) {
    setChatKeep(value);
    updateChatRetention(value)
      .then(() => showToast('대화 보관 기간이 저장됐습니다'))
      .catch((err) => console.error('대화 보관 기간 저장 실패', err));
  }

  return (
    // 설정 화면은 사용성이 우선이라 다른 페이지처럼 영역별로 순서대로 뜨는 stagger는
    // 안 쓰고, 전체를 sr-1 하나로만 묶어서 빠르게 한 번에 페이드인시킨다(딜레이 0s).
    <section className="view on sr-1" id="v-settings"
      data-pri="—"
      data-cap="계정·화면·데이터 설정. 다크 모드는 이 브라우저에 저장되고, 나머지는 파이프라인·에이전트 동작에 연결된다."
    >
      <div className="ph">
        <h2>설정</h2>
        <span className="dt">myWiki · 개인 환경 설정</span>
      </div>

      {/* ⚠ 수정(2026-08-09): 프로필 사진·이름을 다시 편집 가능하게 바꿨습니다 — profiles.
          display_name/avatar_object_key를 ProfileFields가 직접 조회·수정합니다(OAuth
          로그인 이름을 그대로 보여주기만 하던 읽기전용에서 전환). 이메일은 로그인 계정
          자체라 여전히 읽기전용입니다. */}
      <SettingsGroup title="계정">
        <ProfileFields profile={myProfile} avatarUrl={myAvatarUrl} onProfileChange={onProfileChange} />
        <SettingsRow label="이메일" desc="로그인 계정 · 알림 수신 주소">
          <div className="vl">{accountEmail}</div>
        </SettingsRow>
        {/* 워크스페이스 이름·역할이 내려올 때만 보여줍니다. */}
        {hasTeam && (
          <SettingsRow label="소속 팀" desc="현재 참여 중인 워크스페이스와 역할">
            <div className="vl">
              {workspaceName || '이름 없음'}
              {myRole && (
                <span className={`pt-role ${roleClass(myRole)}`}>{roleLabel(myRole)}</span>
              )}
            </div>
          </SettingsRow>
        )}
      </SettingsGroup>

      {myRole && <TeamPanel myRole={myRole} myUserId={profile?.id} />}

      <SettingsGroup title="알림">
        <SettingsRow label="일일 리포트 생성 알림" desc="일일 동향 보고서가 생성되면 알립니다">
          <ToggleSwitch checked={notiReport} onChange={onToggleNotiReport} />
        </SettingsRow>
        <SettingsRow label="Wiki 업데이트 알림" desc="위키 문서가 신규 생성·수정되면 알립니다">
          <ToggleSwitch checked={notiWiki} onChange={onToggleNotiWiki} />
        </SettingsRow>
      </SettingsGroup>

      <SettingsGroup title="세션">
        <SettingsRow label="로그아웃" desc="이 기기에서 myWiki 세션을 종료합니다">
          <button className="dlbtn danger" onClick={() => onLogout?.()}>로그아웃</button>
        </SettingsRow>
        <SettingsRow label="회원 탈퇴" desc="계정과 모든 데이터가 삭제됩니다. 되돌릴 수 없습니다.">
          <button className="dlbtn danger" onClick={() => onDeleteAccount?.()}>회원 탈퇴</button>
        </SettingsRow>
      </SettingsGroup>

      {myRole === 'owner' && <AdminPanel />}

      <SettingsGroup title="화면">
        <SettingsRow label="다크 모드" desc="어두운 배경으로 전환합니다. 이 브라우저에만 저장됩니다.">
          <ToggleSwitch checked={dark} onChange={onToggleDark} />
        </SettingsRow>
      </SettingsGroup>

      <SettingsGroup title="데이터 · 파이프라인">
        {/* 수정사항 1) 첫 화면에서 고른 관심사를 여기서 다시 고를 수 있게 했습니다. */}
        <SettingsRow label="관심사 다시 선택" desc="첫 화면의 관심사 선택으로 돌아갑니다. 대시보드 뉴스 필터에 반영됩니다.">
          <button className="dlbtn" onClick={() => onResetInterests?.()}>관심사 다시 고르기</button>
        </SettingsRow>
        <SettingsRow label="에이전트 참조 범위" desc="답변 생성 시 근거로 삼는 문서 범위">
          <SegmentedControl
            options={[
              { value: 'all', label: '위키 전체' },
              { value: '30d', label: '최근 30일' },
            ]}
            value={agentScope}
            onChange={setAgentScope}
          />
        </SettingsRow>
        <SettingsRow label="데이터 갱신 주기" desc="뉴스 수집·분석을 실행하는 주기">
          <select
            className="fld"
            value={dataCycle}
            onChange={(e) => handleDataCycleChange(e.target.value)}
            aria-label="데이터 갱신 주기"
          >
            <option value="30m">30분</option>
            <option value="1h">1시간</option>
            <option value="2h">2시간</option>
            <option value="3h">3시간</option>
            <option value="6h">6시간</option>
            <option value="12h">12시간</option>
            <option value="24h">24시간</option>
          </select>
        </SettingsRow>
        <SettingsRow label="일일 리포트 생성 시간" desc="수집 완료 후 일일 동향 보고서를 생성할 시각">
          <input
            className="fld"
            type="time"
            value={reportTime}
            onChange={(e) => setReportTime(e.target.value)}
            aria-label="일일 리포트 생성 시간"
          />
        </SettingsRow>
        <SettingsRow label="Wiki 업데이트 주기" desc="수집 결과를 위키 문서에 반영하는 주기">
          <select
            className="fld"
            value={wikiCycle}
            onChange={(e) => handleWikiCycleChange(e.target.value)}
            aria-label="Wiki 업데이트 주기"
          >
            <option value="30m">30분</option>
            <option value="1h">1시간</option>
            <option value="3h">3시간</option>
            <option value="6h">6시간</option>
            <option value="12h">12시간</option>
            <option value="24h">24시간</option>
          </select>
        </SettingsRow>
        <SettingsRow label="에이전트 대화 기록 보관 기간" desc="보관 기간이 지난 대화는 자동으로 삭제됩니다">
          <select
            className="fld"
            value={chatKeep}
            onChange={(e) => handleChatKeepChange(e.target.value)}
            aria-label="에이전트 대화 기록 보관 기간"
          >
            <option value="7">7일</option>
            <option value="30">30일</option>
            <option value="90">90일</option>
            <option value="forever">영구 보관</option>
          </select>
        </SettingsRow>
      </SettingsGroup>

      <SettingsGroup title="앱 · 소스">
        <SettingsRow label="참조 도메인" desc="현재 수집·분석 대상 산업">
          <div className="vl">반도체</div>
        </SettingsRow>
        {/* ⚠ 수정: 하드코딩된 "네이버 뉴스 API · OpenDART · RSS 6개 매체" / "3종 연결됨"을
            settingsApi 경유로 바꿨습니다. 실제 매체명(전자신문·ZDNet 등)은 수집 결과에서만
            나오는 값이라 백엔드 조회 API가 열린 뒤에 채웁니다. */}
        <SettingsRow label="수집 소스" desc={formatSourceSummary(sources)}>
          <div className="vl">{formatSourceCount(sources)}</div>
        </SettingsRow>
      </SettingsGroup>

      <div className="set-ver">myWiki · SK SUNI 5기 Team 5 · 버전 0.4 화면 시안</div>

      {toast && <div className="settings-toast" role="status">{toast}</div>}
    </section>
  );
}

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
// 나머지(에이전트 참조 범위, 수집/리포트 시각 등)는 아직 백엔드가 없어서 이 페이지 안의
// 로컬 상태로만 관리합니다. 리포트 생성 시간/Wiki 주기/대화 보관 기간은 원본 시안과 동일하게
// localStorage에 저장해 새로고침해도 유지됩니다.
//
// ⚠ 수정: "수집 소스" 표기를 services/settingsApi.js 경유로 바꿨습니다.
//   기존 문구("네이버 뉴스 API · OpenDART · RSS 6개 매체" / "3종 연결됨")가
//   scripts/register_sources.py의 실제 등록 내용과 달라서(GNews 누락, RSS는 1건)
//   화면이 근거 없는 숫자를 단정하고 있었습니다.

import { useState, useEffect } from 'react';
import SettingsGroup from '../components/settings/SettingsGroup';
import SettingsRow from '../components/settings/SettingsRow';
import ToggleSwitch from '../components/common/ToggleSwitch';
import SegmentedControl from '../components/common/SegmentedControl';
import {
  fetchCollectSources,
  formatSourceSummary,
  formatSourceCount,
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
  onLogout,
  onResetInterests,
}) {
  const [agentScope, setAgentScope] = useState('all');
  const [reportTime, setReportTime] = useState(() => getInitial('mywiki-report-time', '08:30'));
  const [wikiCycle, setWikiCycle] = useState(() => getInitial('mywiki-wiki-cycle', '6h'));
  const [chatKeep, setChatKeep] = useState(() => getInitial('mywiki-chat-keep', '90'));

  // 수집 소스 — 백엔드 조회 엔드포인트가 열리면 settingsApi 쪽만 바뀝니다.
  const [sources, setSources] = useState([]);

  const accountName = profile?.user_metadata?.full_name || profile?.user_metadata?.name || profile?.email || '';
  const accountEmail = profile?.email || '';

  useEffect(() => {
    let alive = true;
    fetchCollectSources()
      .then((rows) => alive && setSources(rows))
      .catch(() => alive && setSources([]));
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
    try { localStorage.setItem('mywiki-chat-keep', chatKeep); } catch { /* noop */ }
  }, [chatKeep]);

  return (
    <section className="view on" id="v-settings"
      data-pri="—"
      data-cap="계정·화면·데이터 설정. 다크 모드와 글자 크기는 이 브라우저에 저장되고, 나머지는 파이프라인·에이전트 동작에 연결된다."
    >
      <div className="ph">
        <h2>설정</h2>
        <span className="dt">myWiki · 개인 환경 설정</span>
      </div>

      {/* ⚠ 수정: "계정 설정" → "계정". 편집 기능(이미지 변경·이름/이메일 입력·비밀번호 변경)을
          전부 빼고, 로그인 계정 정보를 그대로 보여주기만 하는 읽기 전용 섹션으로 바꿨습니다.
          App.jsx가 실제 Supabase 세션(profile)을 내려준다. */}
      <SettingsGroup title="계정">
        <SettingsRow label="프로필" desc="에이전트 답변·리포트에 표시되는 프로필입니다">
          <div className="set-av">
            <span className="av">{accountName.charAt(0).toUpperCase()}</span>
          </div>
        </SettingsRow>
        <SettingsRow label="이름" desc="워크스페이스에 표시되는 이름">
          <div className="vl">{accountName}</div>
        </SettingsRow>
        <SettingsRow label="이메일" desc="로그인 계정 · 알림 수신 주소">
          <div className="vl">{accountEmail}</div>
        </SettingsRow>
      </SettingsGroup>

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
      </SettingsGroup>

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
        <SettingsRow label="일일 수집 시각" desc="무인 파이프라인 실행 시각 · 백엔드 연동">
          <div className="vl">08:00</div>
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
            onChange={(e) => setWikiCycle(e.target.value)}
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
            onChange={(e) => setChatKeep(e.target.value)}
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
    </section>
  );
}

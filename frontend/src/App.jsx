// 부품들을 실제로 조립하는 파일. PC/모바일에 따라 다른 내비게이션을 보여주고,
// 어떤 화면(view)을 보여줄지 상태로 관리합니다.
//
// ── 이번 수정사항 중 여기서 처리하는 것 ─────────────────────────────────
// 1) 첫 진입 시 선호 조사 화면(OnboardingPage — 관심 키워드/직무/연령대)을 대시보드 대신 띄웁니다.
//    - 판단 기준: localStorage 'mywiki-interests' 키가 있는지 여부.
//      ("건너뛰기"를 눌러도 빈 값이 저장되기 때문에,
//       두 번째 실행부터는 이 화면이 다시 뜨지 않습니다.)
//    - 여기서 고른 관심 키워드는 DashboardPage로 내려가 "최신 뉴스" 기본 필터가 됩니다.
//      직무·연령대는 지금은 저장만 하고, 추후 이슈 랭킹 가중치로 쓸 자리입니다.
//    - 설정 화면에서 다시 고르고 싶을 때를 대비해 resetOnboarding도 만들어 뒀습니다.
//
// 2) "myWiki" 로고를 누르면 화면이 새로고침됩니다.
//    - 브라우저 통째로 새로고침(location.reload)이 아니라 앱 상태 초기화 방식입니다.
//      → 대시보드로 이동 + 열려 있던 드로어/시트/설정 패널 닫기 + 스크롤 최상단 +
//        refreshKey를 올려서 페이지 컴포넌트를 강제로 다시 마운트(= 데이터 재조회).
//      브라우저 새로고침보다 빠르고, 다크모드·관심사 같은 설정이 유지됩니다.
//    - PC 상단바 로고 / PC 사이드바 브랜드 / 모바일 상단바 로고 / 모바일 드로어 브랜드
//      네 군데 전부 같은 동작에 걸려 있습니다.
//
// 3) PC 상단바 우측 — 환경설정(톱니바퀴) 옆에 프로필 버튼을 추가했습니다.
//    - 톱니바퀴 → SettingsPanel(다크모드 · 알림) 드롭다운.
//    - 프로필 → ProfilePanel(계정 정보 + 소속 팀 + 로그인/로그아웃 + 회원 탈퇴) 드롭다운.
//    - 알림 상태(notiReport/notiWiki)는 다크모드처럼 여기서 들고 SettingsPage에도 그대로
//      내려줘서, 상단 드롭다운과 설정 페이지가 항상 같은 값을 보게 했습니다.
//    - authed/profile은 실제 Supabase 세션(api/auth.js, api/supabaseClient.js)을 따라갑니다.
//
// 4) [2026-08-05] 소속 팀 표시 + 회원 탈퇴
//    - myRole: 워크스페이스 멤버 목록에서 로그인 사용자의 role을 찾아 씁니다.
//      ⚠ 백엔드가 role을 안 내려주면 null이 되고, 그 경우 소속 팀 영역이 숨겨집니다
//        (없는 값을 "소속 없음"처럼 단정해 보여주지 않습니다).
//    - 회원 탈퇴: 되돌릴 수 없는 동작이라 DeleteAccountModal로 한 번 더 확인받습니다.
//      실제 삭제 API는 아직 백엔드에 없습니다(service_role이 필요해 프론트에서 못 합니다).
// ────────────────────────────────────────────────────────────────────
//
// 다크모드 :root 처리 / localStorage 저장은 기존 그대로입니다.

import { useState, useEffect } from 'react';
import useIsMobile from './hooks/useIsMobile';

import TopBar from './components/common/TopBar';
import SideNav from './components/common/SideNav';
import { BottomNav, Drawer, MoreSheet } from './components/common/MobileNav';
import SettingsPanel from './components/common/SettingsPanel';
import ProfilePanel from './components/common/ProfilePanel';
import Footer from './components/common/Footer';
import DeleteAccountModal from './components/common/DeleteAccountModal';
import { signInWithProvider, signOut, getCurrentSession, isNewAccount } from './api/auth';
import { supabase } from './api/supabaseClient';
import { listWorkspaceMembers } from './services/agentApi';
import {
  enableWikiPushNotifications,
  disableWikiPushNotifications,
  getActivePushSubscription,
} from './lib/pushNotifications';

import EntryFlow from './pages/EntryFlow';
import DashboardPage from './pages/DashboardPage';
import ReportPage from './pages/ReportPage';
import CategoryPage from './pages/CategoryPage';
import WikiPage from './pages/WikiPage';
import AgentPage from './pages/AgentPage';
import SettingsPage from './pages/SettingsPage';
import PrivacyPage from './pages/PrivacyPage';

const INTERESTS_KEY = 'mywiki-interests';

function getInitial(key, fallback) {
  try {
    return localStorage.getItem(key) || fallback;
  } catch {
    return fallback;
  }
}

// 저장된 선호 조사 결과를 읽습니다. 키 자체가 없으면 null(= 아직 온보딩 전)을 돌려줍니다.
// 저장 형태: { keywords: [], role: string|null }
// (예전 버전은 배열만 저장했어서, 배열로 들어오면 keywords로 승격시킵니다)
function readPrefs() {
  try {
    const raw = localStorage.getItem(INTERESTS_KEY);
    if (raw === null) return null;
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return { keywords: parsed, role: null };
    return {
      keywords: Array.isArray(parsed?.keywords) ? parsed.keywords : [],
      role: parsed?.role ?? null,
    };
  } catch {
    return null;
  }
}

export default function App() {
  const isMobile = useIsMobile();
  const [view, setView] = useState('dash');
  const [wikiDocId, setWikiDocId] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [authed, setAuthed] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);
  // 로그인 없이 "건너뛰기"로 들어온 상태 — 대시보드는 실데이터 그대로 보여주고, 다른 메뉴로
  // 가려고 하면 화면 전환 대신 프로필 드롭다운(로그인 유도)을 연다.
  const [guestMode, setGuestMode] = useState(false);
  const [entryStep, setEntryStep] = useState(null); // 'landing' | 'survey' | null(=일반 앱 화면)
  const [profile, setProfile] = useState(null);
  const [notiReport, setNotiReport] = useState(true);
  const [notiWiki, setNotiWiki] = useState(true);
  const [dark, setDark] = useState(() => getInitial('mywiki-theme', 'light') === 'dark');
  const [fontSize, setFontSize] = useState(() => getInitial('mywiki-fontsize', 'm'));
  // PC 사이드바 접기 상태. 페이지를 옮겨다녀도(새로고침해도) 유지되게 localStorage에 저장.
  const [sideCollapsed, setSideCollapsed] = useState(
    () => getInitial('mywiki-side-collapsed', 'false') === 'true'
  );

  // 소속 팀 — 워크스페이스 이름과 로그인 사용자의 역할.
  // ⚠ 워크스페이스 이름을 주는 엔드포인트가 아직 없어 null로 둡니다(백엔드 요청 중).
  const [workspaceName, setWorkspaceName] = useState(null);
  const [myRole, setMyRole] = useState(null);

  // 회원 탈퇴 확인 모달
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState(null);

  // 선호 조사 결과: null이면 아직 온보딩을 안 거친 상태입니다.
  const [prefs, setPrefs] = useState(readPrefs);
  // 로고 클릭 새로고침용. 값이 바뀌면 현재 페이지 컴포넌트가 통째로 다시 마운트됩니다.
  const [refreshKey, setRefreshKey] = useState(0);

  // PWA 설치 프롬프트 — 브라우저가 설치 가능하다고 알려줄 때까지는 안내 문구만 보여줍니다.
  const [deferredPrompt, setDeferredPrompt] = useState(null);
  const [pwaStateLabel, setPwaStateLabel] = useState('홈 화면에 추가');

  useEffect(() => {
    function handleBeforeInstall(e) {
      e.preventDefault();
      setDeferredPrompt(e);
      setPwaStateLabel('지금 설치 가능');
    }
    function handleInstalled() {
      setPwaStateLabel('설치됨');
    }
    window.addEventListener('beforeinstallprompt', handleBeforeInstall);
    window.addEventListener('appinstalled', handleInstalled);
    return () => {
      window.removeEventListener('beforeinstallprompt', handleBeforeInstall);
      window.removeEventListener('appinstalled', handleInstalled);
    };
  }, []);

  // notiWiki 토글의 실제 상태 — 지금까지는 하드코딩된 true였는데, 실제 구독이
  // 없으면(권한 거부됐거나 애초에 켠 적 없으면) 거짓말을 하고 있었던 셈이라 실제로 확인한다.
  useEffect(() => {
    let alive = true;
    getActivePushSubscription()
      .then((subscription) => {
        if (alive) setNotiWiki(!!subscription);
      })
      .catch(() => {
        if (alive) setNotiWiki(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  // 로그인 후 워크스페이스 멤버 목록에서 내 역할을 찾습니다.
  // ⚠ 응답에 role이 없으면 null로 남고, 프로필 패널의 소속 팀 영역이 숨겨집니다.
  useEffect(() => {
    if (!authed || !profile?.id) {
      setMyRole(null);
      return;
    }
    let alive = true;
    listWorkspaceMembers()
      .then((members) => {
        if (!alive) return;
        const me = (members ?? []).find((m) => m.user_id === profile.id);
        setMyRole(me?.role ?? null);
      })
      .catch(() => alive && setMyRole(null));
    return () => { alive = false; };
  }, [authed, profile?.id]);

  // 실제 Supabase 세션 동기화 + 어느 화면(entryStep)부터 시작할지 결정.
  // determineEntryStep은 매 세션 변화(최초 로드·OAuth 콜백 복귀·로그아웃)마다 다시 계산한다 —
  // "로그인 진행 중이었다" 같은 중간 상태를 따로 안 들고 있어도 항상 같은 결론에 도달한다.
  useEffect(() => {
    function determineEntryStep(session) {
      if (!session) {
        setEntryStep('landing');
        return;
      }
      const existingPrefs = readPrefs();
      if (existingPrefs !== null) {
        setPrefs(existingPrefs);
        setEntryStep(null);
        return;
      }
      if (isNewAccount(session)) {
        setEntryStep('survey');
        return;
      }
      // 기존 계정인데 이 기기엔 관심사 기록이 없음(다른 기기로 처음 로그인) — 빈 기본값으로 대시보드 진입.
      // "설정 > 관심사 다시 고르기"로 나중에 채우면 됨.
      setPrefs({ keywords: [], role: null });
      setEntryStep(null);
    }
    function applySession(session) {
      // 구글 로그인 등 OAuth 콜백은 access_token/refresh_token을 URL 해시에 실어 돌아온다.
      // supabase-js(detectSessionInUrl)가 그 해시를 읽어 세션으로 파싱하긴 하지만, 파싱이
      // 끝난 이 시점까지도 주소창엔 토큰이 그대로 남아 있을 수 있다 — 여기서 확실히 지운다.
      // 앱은 라우팅에 URL 해시를 쓰지 않으므로(view는 React state) 안전하게 지울 수 있다.
      if (window.location.hash) {
        window.history.replaceState(null, '', window.location.pathname);
      }
      setAuthed(!!session);
      setProfile(session?.user ?? null);
      determineEntryStep(session);
    }
    getCurrentSession()
      .then((session) => {
        applySession(session);
      })
      .catch(() => {
        // 세션 조회 실패(네트워크 등) — 세션 없음으로 간주하고 랜딩부터 보여준다.
        applySession(null);
      })
      .finally(() => {
        setAuthChecked(true);
      });
    const { data: subscription } = supabase.auth.onAuthStateChange((_event, session) => {
      applySession(session);
    });
    return () => subscription?.subscription?.unsubscribe();
  }, []);

  function handlePwaInstallClick() {
    if (deferredPrompt) {
      deferredPrompt.prompt();
      deferredPrompt.userChoice.then(() => setDeferredPrompt(null));
    } else {
      setPwaStateLabel('브라우저 메뉴 → 홈 화면에 추가');
    }
  }

  // 다크모드는 :root(<html>)에 data-theme을 설정해야 CSS가 먹습니다.
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    try {
      localStorage.setItem('mywiki-theme', dark ? 'dark' : 'light');
    } catch {
      // 저장 실패해도 화면 동작에는 지장 없음(시크릿 모드 등)
    }
  }, [dark]);

  // 폰트 크기 저장/복원. 실제 배율 적용 로직은 TODO(아래 참고).
  useEffect(() => {
    document.documentElement.setAttribute('data-font-size', fontSize);
    try {
      localStorage.setItem('mywiki-fontsize', fontSize);
    } catch {
      // 저장 실패해도 화면 동작에는 지장 없음
    }
  }, [fontSize]);

  // PC 사이드바 접기 상태 저장. 모바일은 이 상태와 무관(Drawer/BottomNav를 따로 씀).
  useEffect(() => {
    try {
      localStorage.setItem('mywiki-side-collapsed', sideCollapsed ? 'true' : 'false');
    } catch {
      // 저장 실패해도 화면 동작에는 지장 없음
    }
  }, [sideCollapsed]);

  // 온보딩 완료 — 선호 조사 결과를 저장하고 대시보드로 들어갑니다.
  // 관심 키워드는 대시보드 "최신 뉴스" 기본 필터로, 직무는 추후 랭킹 가중치로 씁니다.
  function handleOnboardingComplete(result) {
    const value = {
      keywords: Array.isArray(result?.keywords) ? result.keywords : [],
      role: result?.role ?? null,
    };
    setPrefs(value);
    try {
      localStorage.setItem(INTERESTS_KEY, JSON.stringify(value));
    } catch {
      // 저장 실패해도 이번 세션 동안은 상태로 유지됩니다.
    }
    setView('dash');
    setEntryStep(null);
  }

  // 관심사 다시 고르기 — 설정 화면 버튼에 연결. entryStep을 'survey'로 되돌려서
  // EntryFlow가 다시 선호조사 화면(OnboardingPage)을 보여주게 한다.
  function resetOnboarding() {
    try {
      localStorage.removeItem(INTERESTS_KEY);
    } catch {
      // 무시
    }
    setPrefs(null);
    setEntryStep('survey');
  }

  // 대시보드 InterestsBar에서 씀 — 온보딩 전체를 다시 거치지 않고 관심 키워드만 즉시
  // 추가·삭제한다. role은 건드리지 않고 그대로 유지, keywords만 교체해서 저장.
  function updateInterests(nextKeywords) {
    setPrefs((prev) => {
      const value = { keywords: nextKeywords, role: prev?.role ?? null };
      try {
        localStorage.setItem(INTERESTS_KEY, JSON.stringify(value));
      } catch {
        // 저장 실패해도 이번 세션 동안은 상태로 유지됩니다.
      }
      return value;
    });
  }

  // 두 번째 인자(payload)는 위키 문서 지정용입니다.
  // 대시보드·리포트의 "관련 위키" 링크에서 navigateTo('wiki', 'hbm4') 처럼 넘기면
  // 위키 페이지가 해당 문서를 열고 시작합니다.
  function navigateTo(key, payload) {
    if (guestMode && key !== 'dash') {
      // 게스트는 대시보드 외 메뉴를 못 본다 — 화면 전환 대신 로그인 유도(프로필 드롭다운 오픈).
      setProfileOpen(true);
      return;
    }
    setView(key);
    if (key === 'wiki' && payload) setWikiDocId(payload);
    setDrawerOpen(false);
    setSheetOpen(false);
  }

  // 수정사항 2) 로고 클릭 = 화면 새로고침
  function handleLogoClick() {
    setView('dash');
    setWikiDocId(null);
    setDrawerOpen(false);
    setSheetOpen(false);
    setSettingsOpen(false);
    setProfileOpen(false);
    setRefreshKey((k) => k + 1);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // 수정사항 3) 톱니바퀴/프로필 드롭다운 — 한쪽을 열면 다른 쪽은 닫습니다(동시에 두 개가 안 뜨게).
  function handleSettingsClick() {
    setProfileOpen(false);
    setSettingsOpen((o) => !o);
  }
  function handleProfileClick() {
    setSettingsOpen(false);
    setProfileOpen((o) => !o);
  }
  // provider: 'google' | 'github' | 'custom:naver' — 브라우저가 OAuth 제공자로 리다이렉트된다.
  // 돌아온 뒤의 상태 반영은 위 onAuthStateChange가 처리한다.
  function handleLogin(provider) {
    setProfileOpen(false);
    signInWithProvider(provider);
  }
  function handleLogout() {
    setProfileOpen(false);
    setGuestMode(false);
    signOut();
  }

  // 회원 탈퇴 — 프로필 드롭다운/설정 페이지에서 누르면 확인 모달만 연다.
  function handleOpenDeleteAccount() {
    setProfileOpen(false);
    setDeleteError(null);
    setDeleteOpen(true);
  }

  // 실제 탈퇴 실행.
  // ⚠ Supabase는 클라이언트에서 본인 계정 삭제를 허용하지 않는다(service_role 필요).
  //   백엔드에 삭제 엔드포인트가 생기면 아래 throw를 그 호출로 바꾸면 된다.
  //   또한 chat_sessions.user_id가 profiles ON DELETE CASCADE라, 삭제 시 이 사용자가
  //   만든 팀 공유 대화가 다른 참여자에게도 사라진다 — 백엔드 정책 확인이 필요하다.
  async function handleDeleteAccount() {
    setDeleting(true);
    setDeleteError(null);
    try {
      // TODO: await deleteAccount();  (백엔드 엔드포인트 대기)
      throw new Error('계정 삭제는 백엔드 연동 후 동작합니다. 관리자에게 문의해 주세요.');
    } catch (e) {
      setDeleteError(e.message || '탈퇴 처리에 실패했습니다.');
    } finally {
      setDeleting(false);
    }
  }

  // Wiki 업데이트 알림 토글 — 켤 때 실패하면(권한 거부·브라우저 미지원 등) 토글을 다시
  // 끔 상태로 되돌리고 이유를 알려준다. 끌 때는 실패해도 화면상 토글은 그대로 꺼둔다.
  async function handleToggleNotiWiki(next) {
    if (next) {
      try {
        await enableWikiPushNotifications();
        setNotiWiki(true);
      } catch (err) {
        setNotiWiki(false);
        alert(err.message || '알림을 켜지 못했습니다.');
      }
    } else {
      setNotiWiki(false);
      disableWikiPushNotifications().catch(() => {});
    }
  }

  // 세션 확인이 끝나기 전엔 아무것도 그리지 않는다(로그인된 사용자가 잠깐 랜딩으로
  // 잘못 보이는 걸 막기 위함 — 확인은 보통 수백ms 안에 끝나서 별도 스피너 없이도 자연스럽다).
  if (!authChecked) {
    return null;
  }

  // 신규 계정 로그인 직후 — 사람확인/로그인 없이 곧장 선호조사.
  if (entryStep === 'survey') {
    return <EntryFlow initialStep="survey" onSurveyComplete={handleOnboardingComplete} />;
  }

  // 첫 방문(세션 없음, 게스트도 아님) — 랜딩부터. 로그인/회원가입 화면의 "건너뛰기"를 누르면
  // guestMode로 전환되어 실데이터가 붙은 진짜 메인 대시보드로 곧장 들어간다.
  if (entryStep === 'landing' && !guestMode) {
    return (
      <EntryFlow
        initialStep="landing"
        onSurveyComplete={handleOnboardingComplete}
        onGuestSkip={() => {
          setGuestMode(true);
          setEntryStep(null);
        }}
      />
    );
  }

  return (
    <div className={`app${!isMobile && sideCollapsed ? ' side-collapsed' : ''}`}>
      <TopBar
        variant={isMobile ? 'mobile' : 'pc'}
        onMenuClick={() => setDrawerOpen(true)}
        onMoreClick={() => setSheetOpen(true)}
        onSettingsClick={handleSettingsClick}
        settingsOpen={settingsOpen}
        onProfileClick={handleProfileClick}
        profileOpen={profileOpen}
        authed={authed}
        avatarInitial={(profile?.user_metadata?.full_name || profile?.email || '?').charAt(0).toUpperCase()}
        onLogoClick={handleLogoClick}
      />

      {isMobile ? (
        <Drawer
          isOpen={drawerOpen}
          activeKey={view}
          onNavigate={navigateTo}
          onClose={() => setDrawerOpen(false)}
          onLogoClick={handleLogoClick}
        />
      ) : (
        <SideNav
          activeKey={view}
          onNavigate={navigateTo}
          onLogoClick={handleLogoClick}
          collapsed={sideCollapsed}
          onToggleCollapsed={() => setSideCollapsed((c) => !c)}
        />
      )}

      {/* key를 view까지 포함시켜서 페이지를 바꿀 때마다 .main이 다시 마운트되고,
          globals.css의 .page-enter 애니메이션(위→아래로 서서히 밝아지며 드러나는 효과)이
          매번 새로 재생되게 한다 — 토스 앱의 페이지 전환과 비슷한 "화면이 움직이는" 느낌. */}
      <main className="main page-enter" key={`${view}-${refreshKey}`}>
        {view === 'dash' && (
          <DashboardPage
            onNavigate={navigateTo}
            interests={prefs?.keywords ?? []}
            onUpdateInterests={updateInterests}
          />
        )}
        {view === 'report' && <ReportPage onNavigate={navigateTo} />}
        {view === 'cat' && <CategoryPage />}
        {view === 'wiki' && <WikiPage docId={wikiDocId} />}
        {view === 'agent' && <AgentPage profile={profile} />}
        {view === 'settings' && (
          <SettingsPage
            dark={dark}
            onToggleDark={setDark}
            notiReport={notiReport}
            onToggleNotiReport={setNotiReport}
            notiWiki={notiWiki}
            onToggleNotiWiki={handleToggleNotiWiki}
            profile={profile}
            workspaceName={workspaceName}
            myRole={myRole}
            onLogout={handleLogout}
            onDeleteAccount={handleOpenDeleteAccount}
            onResetInterests={resetOnboarding}
          />
        )}
        {view === 'privacy' && <PrivacyPage onBack={() => navigateTo('dash')} />}
      </main>

      <Footer
        onNavigate={navigateTo}
        onPwaInstallClick={handlePwaInstallClick}
        pwaStateLabel={pwaStateLabel}
      />

      {isMobile && (
        <>
          <BottomNav
            activeKey={view}
            onNavigate={navigateTo}
            onMoreClick={() => setSheetOpen(true)}
          />
          <MoreSheet
            isOpen={sheetOpen}
            onClose={() => setSheetOpen(false)}
            onNavigate={navigateTo}
            onPwaInstallClick={handlePwaInstallClick}
            pwaStateLabel={pwaStateLabel}
            onLogoutClick={handleLogout}
          />
        </>
      )}

      <SettingsPanel
        isOpen={settingsOpen}
        dark={dark}
        onToggleDark={setDark}
        notiReport={notiReport}
        onToggleNotiReport={setNotiReport}
        notiWiki={notiWiki}
        onToggleNotiWiki={handleToggleNotiWiki}
      />

      <ProfilePanel
        isOpen={profileOpen}
        authed={authed}
        profile={profile}
        workspaceName={workspaceName}
        myRole={myRole}
        onLogin={handleLogin}
        onLogout={handleLogout}
        onDeleteAccount={handleOpenDeleteAccount}
      />

      <DeleteAccountModal
        open={deleteOpen}
        busy={deleting}
        error={deleteError}
        onConfirm={handleDeleteAccount}
        onClose={() => setDeleteOpen(false)}
      />
    </div>
  );
}

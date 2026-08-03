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
//    - 설정 화면에서 다시 고르고 싶을 때를 대비해 resetOnboarding도 만들어 뒀습니다(TODO 연결).
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
//    - 톱니바퀴 → SettingsPanel(다크모드 · 글자크기 · 알림) 드롭다운.
//    - 프로필 → ProfilePanel(계정 정보 + 로그인/로그아웃) 드롭다운.
//    - 두 드롭다운은 시안 CSS(.settings-panel/.profile-panel)에 이미 있었는데
//      프로필 쪽은 실제로 연결된 컴포넌트가 없었어서 이번에 처음 붙였습니다.
//    - 알림 상태(notiReport/notiWiki)는 다크모드처럼 여기서 들고 SettingsPage에도 그대로
//      내려줘서, 상단 드롭다운과 설정 페이지가 항상 같은 값을 보게 했습니다.
//
// 4) [이번 수정] authed를 실제 Supabase Auth 세션에 연결했습니다.
//    - 예전엔 로그인/로그아웃 버튼이 로컬 상태만 토글하고 실제 세션은 만들지 않았습니다
//      (api/auth.js에 signInWithProvider/signOut이 이미 구현돼 있었는데 어디서도 안 쓰이고
//      있었습니다). 그 상태에서는 apiFetch가 세션 토큰을 못 구해서 위키·에이전트·설정
//      화면이 전부 "missing bearer token"으로 실패합니다.
//    - 이제 getCurrentSession()으로 초기 세션을 읽고, onAuthStateChange로 로그인/로그아웃/
//      토큰 갱신을 계속 구독합니다. OAuth 리다이렉트로 돌아왔을 때도 이 구독이 세션을
//      잡아서 authed·account를 자동으로 갱신합니다.
//    - account(표시 이름·이메일)도 더 이상 mockAccount 목업이 아니라 세션의 user 정보에서
//      뽑습니다. 로그아웃 상태에서는 null입니다.
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
import { signInWithProvider, signOut, getCurrentSession } from './api/auth';
import { supabase } from './api/supabaseClient';

import OnboardingPage from './pages/OnboardingPage';
import DashboardPage from './pages/DashboardPage';
import ReportPage from './pages/ReportPage';
import CategoryPage from './pages/CategoryPage';
import WikiPage from './pages/WikiPage';
import AgentPage from './pages/AgentPage';
import SettingsPage from './pages/SettingsPage';

const INTERESTS_KEY = 'mywiki-interests';

function getInitial(key, fallback) {
  try {
    return localStorage.getItem(key) || fallback;
  } catch {
    return fallback;
  }
}

// 저장된 선호 조사 결과를 읽습니다. 키 자체가 없으면 null(= 아직 온보딩 전)을 돌려줍니다.
// 저장 형태: { keywords: [], role: string|null, age: string|null }
// (예전 버전은 배열만 저장했어서, 배열로 들어오면 keywords로 승격시킵니다)
function readPrefs() {
  try {
    const raw = localStorage.getItem(INTERESTS_KEY);
    if (raw === null) return null;
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return { keywords: parsed, role: null, age: null };
    return {
      keywords: Array.isArray(parsed?.keywords) ? parsed.keywords : [],
      role: parsed?.role ?? null,
      age: parsed?.age ?? null,
    };
  } catch {
    return null;
  }
}

// Supabase session.user -> ProfilePanel/SettingsPage가 쓰는 { name, email } 모양으로 변환.
// full_name/name은 OAuth 프로바이더(Google 등)가 채워주는 user_metadata 값이고,
// 없으면 이메일 아이디 부분을 이름으로 씁니다(카카오 등은 이메일 동의를 안 받을 수도 있음).
function toAccount(session) {
  const user = session?.user;
  if (!user) return null;
  const meta = user.user_metadata || {};
  const name = meta.full_name || meta.name || user.email?.split('@')[0] || '사용자';
  return { name, email: user.email || '' };
}

export default function App() {
  const isMobile = useIsMobile();
  const [view, setView] = useState('dash');
  const [wikiDocId, setWikiDocId] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  // authed/account는 실제 Supabase Auth 세션에서 옵니다(아래 useEffect). 세션 확인이
  // 끝나기 전까지는 로그아웃 상태로 취급합니다 — 아주 짧은 순간이라 로딩 UI는 따로 두지 않습니다.
  const [authed, setAuthed] = useState(false);
  const [account, setAccount] = useState(null);
  const [notiReport, setNotiReport] = useState(true);
  const [notiWiki, setNotiWiki] = useState(true);
  const [dark, setDark] = useState(() => getInitial('mywiki-theme', 'light') === 'dark');
  const [fontSize, setFontSize] = useState(() => getInitial('mywiki-fontsize', 'm'));

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

  function handlePwaInstallClick() {
    if (deferredPrompt) {
      deferredPrompt.prompt();
      deferredPrompt.userChoice.then(() => setDeferredPrompt(null));
    } else {
      setPwaStateLabel('브라우저 메뉴 → 홈 화면에 추가');
    }
  }

  // 실제 로그인 상태 연결. 초기 세션을 한 번 읽고, 이후 로그인/로그아웃/토큰 갱신은
  // onAuthStateChange 구독으로 계속 반영합니다 — 소셜 로그인은 OAuth 제공자 화면으로
  // 리다이렉트됐다가 돌아오는 흐름이라, 버튼 클릭 시점이 아니라 이 구독이 실제 로그인
  // 완료 시점을 알려줍니다.
  useEffect(() => {
    let alive = true;
    let unsubscribe = () => {};

    getCurrentSession()
      .then((session) => {
        if (!alive) return;
        setAuthed(!!session);
        setAccount(toAccount(session));
      })
      .catch(() => {
        // Supabase 환경변수가 없는 등 초기화 실패 — 로그아웃 상태로 둡니다.
        if (alive) {
          setAuthed(false);
          setAccount(null);
        }
      });

    try {
      const { data } = supabase.auth.onAuthStateChange((_event, session) => {
        if (!alive) return;
        setAuthed(!!session);
        setAccount(toAccount(session));
      });
      unsubscribe = () => data.subscription.unsubscribe();
    } catch {
      // getCurrentSession()의 catch와 동일한 사유(환경변수 없음) — 구독을 그냥 건너뜁니다.
    }

    return () => {
      alive = false;
      unsubscribe();
    };
  }, []);

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

  // 온보딩 완료 — 선호 조사 결과를 저장하고 대시보드로 들어갑니다.
  // 관심 키워드는 대시보드 "최신 뉴스" 기본 필터로, 직무·연령대는 추후 랭킹 가중치로 씁니다.
  function handleOnboardingComplete(result) {
    const value = {
      keywords: Array.isArray(result?.keywords) ? result.keywords : [],
      role: result?.role ?? null,
      age: result?.age ?? null,
    };
    setPrefs(value);
    try {
      localStorage.setItem(INTERESTS_KEY, JSON.stringify(value));
    } catch {
      // 저장 실패해도 이번 세션 동안은 상태로 유지됩니다.
    }
    setView('dash');
  }

  // 관심사 다시 고르기 — 설정 화면에 버튼을 붙일 때 이걸 넘기면 됩니다. (TODO)
  function resetOnboarding() {
    try {
      localStorage.removeItem(INTERESTS_KEY);
    } catch {
      // 무시
    }
    setPrefs(null);
  }

  // 두 번째 인자(payload)는 위키 문서 지정용입니다.
  // 대시보드·리포트의 "관련 위키" 링크에서 navigateTo('wiki', 'hbm4') 처럼 넘기면
  // 위키 페이지가 해당 문서를 열고 시작합니다.
  function navigateTo(key, payload) {
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
  // 소셜 로그인 — provider는 ProfilePanel의 OAUTH_PROVIDERS.key ('google' | 'github' | 'kakao').
  // signInWithOAuth는 성공하면 그 자리에서 브라우저를 OAuth 제공자 화면으로 이동시키므로
  // (Promise가 풀리기 전에 리다이렉트) 여기서 authed를 직접 set하지 않습니다 — 로그인
  // 완료 후 이 앱으로 돌아오면 위 useEffect의 onAuthStateChange 구독이 세션을 잡습니다.
  // 리다이렉트 전에 에러(예: 프로바이더 비활성화)가 나면 콘솔에 남기고 패널만 닫습니다.
  function handleLogin(provider) {
    setProfileOpen(false);
    try {
      // supabaseClient.js가 Supabase 환경변수 없을 때 동기적으로 throw할 수 있어서
      // (Promise reject가 아니라) .catch만으론 못 잡습니다 — try/catch로 감쌉니다.
      signInWithProvider(provider).catch((e) => {
        console.error(`[auth] ${provider} 로그인 실패`, e);
      });
    } catch (e) {
      console.error(`[auth] ${provider} 로그인 실패`, e);
    }
  }
  function handleLogout() {
    setProfileOpen(false);
    try {
      signOut().catch((e) => console.error('[auth] 로그아웃 실패', e));
    } catch (e) {
      console.error('[auth] 로그아웃 실패', e);
    }
    // onAuthStateChange가 곧 SIGNED_OUT을 알려주지만, 버튼 누른 즉시 반응하도록 먼저 반영합니다.
    setAuthed(false);
    setAccount(null);
  }

  // 첫 진입 — 선호 조사 화면. 앱 뼈대(상단바/내비)를 띄우지 않고 이 화면만 보여줍니다.
  if (prefs === null) {
    return <OnboardingPage onComplete={handleOnboardingComplete} />;
  }

  return (
    <div className="app">
      <TopBar
        variant={isMobile ? 'mobile' : 'pc'}
        onMenuClick={() => setDrawerOpen(true)}
        onMoreClick={() => setSheetOpen(true)}
        onSettingsClick={handleSettingsClick}
        settingsOpen={settingsOpen}
        onProfileClick={handleProfileClick}
        profileOpen={profileOpen}
        authed={authed}
        avatarInitial={account?.name?.charAt(0) || ''}
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
        <SideNav activeKey={view} onNavigate={navigateTo} onLogoClick={handleLogoClick} />
      )}

      <main className="main" key={refreshKey}>
        {view === 'dash' && <DashboardPage onNavigate={navigateTo} interests={prefs.keywords} />}
        {view === 'report' && <ReportPage onNavigate={navigateTo} />}
        {view === 'cat' && <CategoryPage />}
        {view === 'wiki' && <WikiPage docId={wikiDocId} />}
        {view === 'agent' && <AgentPage />}
        {view === 'settings' && (
          <SettingsPage
            dark={dark}
            onToggleDark={setDark}
            notiReport={notiReport}
            onToggleNotiReport={setNotiReport}
            notiWiki={notiWiki}
            onToggleNotiWiki={setNotiWiki}
            onLogout={handleLogout}
            onResetInterests={resetOnboarding}
            account={account}
          />
        )}
      </main>

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
        fontSize={fontSize}
        onFontSizeChange={setFontSize}
        notiReport={notiReport}
        onToggleNotiReport={setNotiReport}
        notiWiki={notiWiki}
        onToggleNotiWiki={setNotiWiki}
      />

      <ProfilePanel
        isOpen={profileOpen}
        authed={authed}
        account={account}
        onLogin={handleLogin}
        onLogout={handleLogout}
      />
    </div>
  );
}

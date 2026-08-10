// 부품들을 실제로 조립하는 파일. PC/모바일에 따라 다른 내비게이션을 보여주고,
// react-router-dom의 <Routes>로 어떤 화면을 보여줄지 URL 경로 기준으로 관리합니다.
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
//      [2026-08-06] DELETE /account 실제 연결 완료 — 백엔드가 profiles를 소프트 삭제(deleted_at)하고
//      auth 사용자를 지우면, 여기서 signOut()까지 호출해 브라우저 세션도 정리합니다.
// ────────────────────────────────────────────────────────────────────
//
// 다크모드 :root 처리 / localStorage 저장은 기존 그대로입니다.

import { useState, useEffect, useCallback, useRef } from 'react';
import { Routes, Route, Navigate, Outlet, useNavigate, useLocation } from 'react-router-dom';
import useIsMobile from './hooks/useIsMobile';

import TopBar from './components/common/TopBar';
import SideNav from './components/common/SideNav';
import { BottomNav, Drawer, MoreSheet } from './components/common/MobileNav';
import SettingsPanel from './components/common/SettingsPanel';
import ProfilePanel from './components/common/ProfilePanel';
import Footer from './components/common/Footer';
import DeleteAccountModal from './components/common/DeleteAccountModal';
import { signInWithProvider, signOut, getCurrentSession, deleteAccount } from './api/auth';
import { supabase } from './api/supabaseClient';
import { listWorkspaceMembers, getWorkspace } from './services/agentApi';
import { fetchProfile, fetchAvatarBlob } from './api/profile';
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

// entryStep 게이트 — 세션이 없으면(랜딩) 또는 이번 로그인에서 선호조사를 아직 안 봤으면(설문)
// 아래 실제 앱 라우트(Outlet)로 들어가지 못하게 막고 EntryFlow를 대신 그린다.
// 라우트 트리 맨 바깥(레이아웃 라우트)에 둬서, 어떤 경로로 진입해도 항상 먼저 걸리게 한다.
function EntryGate({ entryStep, guestMode, onSurveyComplete, onGuestSkip }) {
  if (entryStep === 'survey') {
    return <EntryFlow initialStep="survey" onSurveyComplete={onSurveyComplete} />;
  }
  if (entryStep === 'landing' && !guestMode) {
    return (
      <EntryFlow
        initialStep="landing"
        onSurveyComplete={onSurveyComplete}
        onGuestSkip={onGuestSkip}
      />
    );
  }
  return <Outlet />;
}

// 게스트 게이트 — 게스트 모드는 대시보드(/)만 허용한다. 주소창에 직접 다른 경로를 치고
// 들어오거나 뒤로/앞으로가기로 넘어와도 여기서 걸러서 대시보드로 돌려보내고, 프로필
// 드롭다운(로그인 유도)을 연다.
function GuestGate({ guestMode, onBlocked }) {
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    if (guestMode && location.pathname !== '/') {
      onBlocked();
      navigate('/', { replace: true });
    }
  }, [guestMode, location.pathname, navigate, onBlocked]);
  return <Outlet />;
}

const INTERESTS_KEY = 'mywiki-interests';
// 로그아웃 직후 표시(sessionStorage) — "방금 이 탭에서 로그아웃했다가 다시 로그인했다"를
// 판별하는 용도. 자세한 이유는 App() 안 determineEntryStep 주석 참고.
const JUST_LOGGED_OUT_KEY = 'mywiki-just-logged-out';
// "이번 로그인 세션에서 선호도 조사를 이미 봤는지"만 담는 별도 플래그(localStorage).
// ⚠ INTERESTS_KEY(선호도 데이터 자체)와는 완전히 분리한다 — DB/localStorage에 예전
//   선호도가 남아있어도 그건 "이번 로그인에서 조사를 또 보여줄지"와 무관한 문제다.
//   새로고침·페이지 이동에는 살아남아야 해서 sessionStorage가 아니라 localStorage를
//   쓰고, 대신 "로그아웃 후 재로그인" 시점(JUST_LOGGED_OUT_KEY 감지)에 여기서 직접
//   지워서 다음 로그인에서 다시 뜨게 만든다.
const SURVEY_SEEN_KEY = 'mywiki-survey-seen-this-login';

// [시연용 하드코딩] 소속 팀 — 실제 워크스페이스 이름 API(getWorkspace)는 그대로 호출하고
// 구조도 안 건드린다. 다만 지금 단계에서는 화면에 보여줄 "소속 팀" 표시값만 1~5팀 중
// 하나로 고정한다. 사용자 id를 해시해서 같은 사람은 새로고침해도 항상 같은 팀으로 보이게
// 했다 — 매번 랜덤으로 바뀌면 "이 사람 팀이 뭐였지"가 화면마다 달라 보여서 시연 때 이상하다.
// 실제 팀 데이터가 준비되면 getDemoTeamName 호출부만 ws?.name으로 되돌리면 된다(아래
// useEffect 주석 참고) — 이 상수/함수 자체를 지우거나 API 호출을 없애지는 않았다.
const DEMO_TEAMS = ['1팀', '2팀', '3팀', '4팀', '5팀'];
function getDemoTeamName(userId) {
  if (!userId) return DEMO_TEAMS[0];
  let hash = 0;
  for (let i = 0; i < userId.length; i += 1) hash = (hash * 31 + userId.charCodeAt(i)) >>> 0;
  return DEMO_TEAMS[hash % DEMO_TEAMS.length];
}

function getInitial(key, fallback) {
  try {
    return localStorage.getItem(key) || fallback;
  } catch {
    return fallback;
  }
}

// 저장된 선호 조사 결과를 읽습니다. 키 자체가 없으면 null(= 아직 온보딩 전)을 돌려줍니다.
// 저장 형태: { keywords: [], role: string|null, userId: string|null }
// (예전 버전은 배열만 저장했거나 userId가 없었어서, 없으면 null로 승격시킵니다)
// ⚠ userId를 같이 저장하는 이유: localStorage는 계정이 아니라 "이 브라우저" 기준이다.
//   userId 없이 keywords만 보고 판단하면, 한 브라우저에서 계정 A가 선호도를 저장한 뒤
//   계정 B로 새로 로그인해도 "이미 선호도가 있다"고 오판해서 B는 선호조사 화면을 영영
//   못 보게 된다 — 그래서 아래 determineEntryStep에서 저장된 userId와 현재 로그인한
//   사용자의 id가 같을 때만 "이미 완료됨"으로 인정한다.
function readPrefs() {
  try {
    const raw = localStorage.getItem(INTERESTS_KEY);
    if (raw === null) return null;
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return { keywords: parsed, role: null, userId: null };
    return {
      keywords: Array.isArray(parsed?.keywords) ? parsed.keywords : [],
      role: parsed?.role ?? null,
      userId: parsed?.userId ?? null,
    };
  } catch {
    return null;
  }
}

export default function App() {
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const location = useLocation();
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
  const [workspaceName, setWorkspaceName] = useState(null);
  const [myRole, setMyRole] = useState(null);

  // 내 프로필(이름·사진) — 상단바/프로필 패널이 여기서 받아 쓴다. Settings의
  // ProfileFields가 이름/사진을 바꾸면 onProfileChange로 loadMyProfile을 다시 불러서
  // 상단바에도 바로 반영되게 한다(예전엔 Settings에서만 바뀌고 다른 화면은 그대로였다).
  const [myProfile, setMyProfile] = useState(null);
  const [myAvatarUrl, setMyAvatarUrl] = useState(null);
  const myAvatarObjectUrlRef = useRef(null);

  const loadMyProfile = useCallback(() => {
    if (!authed || !profile?.id) {
      setMyProfile(null);
      if (myAvatarObjectUrlRef.current) {
        URL.revokeObjectURL(myAvatarObjectUrlRef.current);
        myAvatarObjectUrlRef.current = null;
      }
      setMyAvatarUrl(null);
      return;
    }
    fetchProfile()
      .then((p) => {
        setMyProfile(p);
        if (!p.has_avatar) {
          if (myAvatarObjectUrlRef.current) {
            URL.revokeObjectURL(myAvatarObjectUrlRef.current);
            myAvatarObjectUrlRef.current = null;
          }
          setMyAvatarUrl(null);
          return;
        }
        // has_avatar가 이전에도 true였을 수 있으므로(사진을 다른 사진으로 교체한 경우)
        // 항상 새로 받아온다 — hasAvatar 값 자체의 변화에만 반응하는 useAvatarUrl
        // 훅과 달리, 방금 올린 사진을 바로 반영해야 하는 "내 사진"은 매번 다시 조회한다.
        return fetchAvatarBlob().then(({ blob }) => {
          if (myAvatarObjectUrlRef.current) URL.revokeObjectURL(myAvatarObjectUrlRef.current);
          const url = URL.createObjectURL(blob);
          myAvatarObjectUrlRef.current = url;
          setMyAvatarUrl(url);
        });
      })
      .catch(() => {
        setMyProfile(null);
        setMyAvatarUrl(null);
      });
  }, [authed, profile?.id]);

  useEffect(() => {
    loadMyProfile();
  }, [loadMyProfile]);

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

  // 경로 전환 시 스크롤 최상단 초기화.
  // ⚠ createBrowserRouter의 <ScrollRestoration>이 아니라 plain <BrowserRouter>를 쓰고
  //   있어서 스크롤 복원이 자동으로 되지 않는다 — 직접 처리한다.
  //   실제로 스크롤되는 대상은 .main이 아니라 window다 — .side(사이드바)만 자체
  //   overflow-y:auto를 갖고 있고 .main은 그냥 문서 흐름을 따라 늘어나며 body가 스크롤된다
  //   (globals.css .app/.side/.main 참고). 그래서 컨테이너의 scrollTop이 아니라
  //   window.scrollTo로 초기화한다.
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [location.pathname]);

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

  // 로그인 후 워크스페이스 이름을 조회합니다(설정 페이지 "소속 팀" 표시용).
  useEffect(() => {
    if (!authed || !profile?.id) {
      setWorkspaceName(null);
      return;
    }
    let alive = true;
    getWorkspace()
      // [시연용 하드코딩] 실제로는 ws?.name을 써야 한다 — DEMO_TEAMS 설명 참고.
      // 실백엔드 워크스페이스명이 준비되면 아래 두 줄을 `ws?.name ?? null` /
      // `null`로 되돌리기만 하면 된다.
      .then((_ws) => alive && setWorkspaceName(getDemoTeamName(profile?.id)))
      .catch(() => alive && setWorkspaceName(getDemoTeamName(profile?.id)));
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
      // ⚠ 선호도 조사를 다시 보여줄지는 "DB/localStorage에 예전 선호도 데이터가 있는가"가
      //   아니라 "이번 로그인 세션에서 이미 봤는가"만으로 정한다. 그 둘은 별개 문제다 —
      //   예전 선호도가 있어도 새로 로그인했으면 다시 보여줘야 하고, 반대로 이번 세션에서
      //   이미 봤으면(완료했든 건너뛰기로 닫았든) 새로고침·페이지 이동에도 또 뜨면 안 된다.
      //   그래서 SURVEY_SEEN_KEY 하나만 본다 — 선호도 데이터(INTERESTS_KEY)는 여기서
      //   전혀 안 건드린다(읽지도, 지우지도 않는다).
      //
      // "방금 로그아웃했다가 다시 로그인했다"는 supabase auth 이벤트로는 못 잡는다(OAuth가
      //   리다이렉트 방식이라 로그인 완료 후 돌아오는 것도 결국 새 페이지 로드이고, 세션을
      //   localStorage에서 복원할 때도 첫 콜백이 SIGNED_IN으로 오는 경우가 있어서 "재로그인"과
      //   "그냥 브라우저 껐다 켜서 기존 세션 이어받기"를 구별할 수 없다). 그래서
      //   handleLogout()이 로그아웃하는 그 순간 sessionStorage에 명시적으로 표시를 남긴다
      //   (sessionStorage는 리다이렉트를 낀 같은 탭 왕복엔 살아남고, 탭/브라우저를 완전히
      //   닫으면 사라진다). 그 표시가 있으면 "새로운 로그인 세션이 시작됐다"는 뜻이니
      //   SURVEY_SEEN_KEY를 지워서 이번 세션엔 아직 안 본 상태로 되돌린다.
      if (sessionStorage.getItem(JUST_LOGGED_OUT_KEY)) {
        sessionStorage.removeItem(JUST_LOGGED_OUT_KEY);
        try {
          localStorage.removeItem(SURVEY_SEEN_KEY);
        } catch {
          // 무시 — 못 지워도 아래 판단은 그대로 진행된다.
        }
      }
      // 기존 선호도는 화면 초기값 등으로 계속 쓰이므로 세션 판단과 무관하게 로드해둔다.
      const existingPrefs = readPrefs();
      if (existingPrefs) setPrefs(existingPrefs);

      let alreadySeen = false;
      try {
        alreadySeen = localStorage.getItem(SURVEY_SEEN_KEY) === '1';
      } catch {
        alreadySeen = false;
      }
      setEntryStep(alreadySeen ? null : 'survey');
    }
    function applySession(session) {
      // 구글 로그인 등 OAuth 콜백은 access_token/refresh_token을 URL 해시에 실어 돌아온다.
      // supabase-js(detectSessionInUrl)가 그 해시를 읽어 세션으로 파싱하긴 하지만, 파싱이
      // 끝난 이 시점까지도 주소창엔 토큰이 그대로 남아 있을 수 있다 — 여기서 확실히 지운다.
      // 앱은 라우팅에 URL 해시를 쓰지 않으므로(BrowserRouter는 pathname 기준) 안전하게 지울 수 있다.
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
      // profile은 세션이 잡히면서 이미 채워진 뒤라(determineEntryStep → 'survey' 진입 시점엔
      // applySession이 setProfile을 먼저 부른 상태), 여기서 로그인한 사용자 id를 같이 저장한다.
      userId: profile?.id ?? null,
    };
    setPrefs(value);
    try {
      localStorage.setItem(INTERESTS_KEY, JSON.stringify(value));
      // 이번 로그인 세션에서 선호도 조사를 봤다는 표시. "완료"든 "건너뛰기"든 이 한
      // 함수로 들어오므로(OnboardingPage 쪽에서 스킵도 빈 값으로 여기를 호출) 여기
      // 한 곳에만 표시해두면 된다 — 다음 로그아웃→재로그인 전까지는 다시 안 뜬다.
      localStorage.setItem(SURVEY_SEEN_KEY, '1');
    } catch {
      // 저장 실패해도 이번 세션 동안은 상태로 유지됩니다.
    }
    navigate('/');
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
      const value = { keywords: nextKeywords, role: prev?.role ?? null, userId: prev?.userId ?? profile?.id ?? null };
      try {
        localStorage.setItem(INTERESTS_KEY, JSON.stringify(value));
      } catch {
        // 저장 실패해도 이번 세션 동안은 상태로 유지됩니다.
      }
      return value;
    });
  }

  // 수정사항 2) 로고 클릭 = 화면 새로고침
  function handleLogoClick() {
    navigate('/');
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

  // 설정/프로필 드롭다운 바깥 클릭 시 닫기 (+ ESC).
  // ⚠ 'click'이 아니라 'mousedown'을 듣는다 — 톱니바퀴/프로필 아이콘을 다시 눌러서 닫는
  //   기존 토글도 그대로 살려둬야 하는데, 'click'으로 들으면 그 클릭 자체가 이 리스너에도
  //   먼저 잡혀 setOpen(false)를 부르고, 그 다음 TopBar의 onClick이 handleSettingsClick을
  //   불러 다시 setOpen(true)로 되돌리는 식으로 앞뒤가 꼬인다. mousedown은 click보다 먼저
  //   일어나므로, 여기서는 아이콘 자체를 누른 경우(.gear/.avatar)는 애초에 안 닫히게
  //   걸러내고, 그 뒤에 이어지는 click이 TopBar의 토글을 정상적으로 처리하게 둔다.
  useEffect(() => {
    if (!settingsOpen && !profileOpen) return;
    function handleOutside(e) {
      const target = e.target;
      if (settingsOpen && !target.closest('.settings-panel') && !target.closest('.gear')) {
        setSettingsOpen(false);
      }
      if (profileOpen && !target.closest('.profile-panel') && !target.closest('.avatar')) {
        setProfileOpen(false);
      }
    }
    function handleEscape(e) {
      if (e.key === 'Escape') {
        setSettingsOpen(false);
        setProfileOpen(false);
      }
    }
    document.addEventListener('mousedown', handleOutside);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('mousedown', handleOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [settingsOpen, profileOpen]);
  // provider: 'google' | 'github' | 'custom:naver' — 브라우저가 OAuth 제공자로 리다이렉트된다.
  // 돌아온 뒤의 상태 반영은 위 onAuthStateChange가 처리한다.
  function handleLogin(provider) {
    setProfileOpen(false);
    signInWithProvider(provider);
  }
  function handleLogout() {
    setProfileOpen(false);
    setGuestMode(false);
    // 다음 로그인 때 선호도 조사를 다시 보여주기 위한 표시. determineEntryStep 참고.
    sessionStorage.setItem(JUST_LOGGED_OUT_KEY, '1');
    signOut();
  }

  // 회원 탈퇴 — 프로필 드롭다운/설정 페이지에서 누르면 확인 모달만 연다.
  function handleOpenDeleteAccount() {
    setProfileOpen(false);
    setDeleteError(null);
    setDeleteOpen(true);
  }

  // 실제 탈퇴 실행 — DELETE /account.
  // ⚠ 백엔드는 profiles를 하드 삭제하지 않고 deleted_at만 남긴다(소프트 삭제) — 이 사람이
  //   만든 팀 공유 대화 등 다른 참여자가 보는 콘텐츠는 그대로 유지된다. 성공 응답을 받으면
  //   여기서 signOut()까지 호출해야 브라우저 쪽 세션도 정리되고 랜딩 화면으로 돌아간다
  //   (onAuthStateChange가 이어서 authed/profile을 초기화한다).
  async function handleDeleteAccount() {
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteAccount();
      setDeleteOpen(false);
      await signOut();
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

  return (
    <Routes>
      {/* entryStep 게이트 — 세션 없음/선호조사 미완료면 EntryFlow가 아래 라우트 대신 그려진다. */}
      <Route
        element={
          <EntryGate
            entryStep={entryStep}
            guestMode={guestMode}
            onSurveyComplete={handleOnboardingComplete}
            onGuestSkip={() => {
              setGuestMode(true);
              setEntryStep(null);
            }}
          />
        }
      >
        {/* 레이아웃 라우트 — TopBar/SideNav/Footer 등 앱 셸을 그리고, 실제 화면은 Outlet에 채워진다. */}
        <Route
          element={
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
                avatarInitial={(myProfile?.display_name || profile?.user_metadata?.full_name || profile?.email || '?').charAt(0).toUpperCase()}
                avatarUrl={myAvatarUrl}
                onLogoClick={handleLogoClick}
              />

              {isMobile ? (
                <Drawer
                  isOpen={drawerOpen}
                  onClose={() => setDrawerOpen(false)}
                  onLogoClick={handleLogoClick}
                />
              ) : (
                <SideNav
                  onLogoClick={handleLogoClick}
                  collapsed={sideCollapsed}
                  onToggleCollapsed={() => setSideCollapsed((c) => !c)}
                />
              )}

              {/* key에 경로+refreshKey를 넣어서 라우트를 옮길 때마다 .main이 다시 마운트되고,
                  globals.css의 .page-enter 애니메이션(위→아래로 서서히 밝아지며 드러나는 효과)이
                  매번 새로 재생되게 한다 — 토스 앱의 페이지 전환과 비슷한 "화면이 움직이는" 느낌. */}
              <main className="main page-enter" key={`${location.pathname}-${refreshKey}`}>
                <Outlet />
              </main>

              <Footer onPwaInstallClick={handlePwaInstallClick} pwaStateLabel={pwaStateLabel} />

              {isMobile && (
                <>
                  <BottomNav onMoreClick={() => setSheetOpen(true)} />
                  <MoreSheet
                    isOpen={sheetOpen}
                    onClose={() => setSheetOpen(false)}
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
                displayName={myProfile?.display_name}
                avatarUrl={myAvatarUrl}
                workspaceName={workspaceName}
                myRole={myRole}
                jobTitle={prefs?.role}
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
          }
        >
          {/* 게스트 게이트 — 게스트 모드는 대시보드(index)만 통과, 나머지는 /로 되돌아간다. */}
          <Route element={<GuestGate guestMode={guestMode} onBlocked={() => setProfileOpen(true)} />}>
            <Route
              index
              element={<DashboardPage interests={prefs?.keywords ?? []} onUpdateInterests={updateInterests} />}
            />
            <Route path="report" element={<ReportPage />} />
            <Route path="category" element={<CategoryPage />} />
            <Route path="wiki" element={<WikiPage />} />
            <Route path="wiki/:docId" element={<WikiPage />} />
            <Route path="agent" element={<AgentPage profile={profile} myProfile={myProfile} />} />
            <Route
              path="settings"
              element={
                <SettingsPage
                  dark={dark}
                  onToggleDark={setDark}
                  notiReport={notiReport}
                  onToggleNotiReport={setNotiReport}
                  notiWiki={notiWiki}
                  onToggleNotiWiki={handleToggleNotiWiki}
                  profile={profile}
                  myProfile={myProfile}
                  myAvatarUrl={myAvatarUrl}
                  onProfileChange={loadMyProfile}
                  workspaceName={workspaceName}
                  myRole={myRole}
                  onLogout={handleLogout}
                  onDeleteAccount={handleOpenDeleteAccount}
                  onResetInterests={resetOnboarding}
                />
              }
            />
            <Route path="privacy" element={<PrivacyPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Route>
      </Route>
    </Routes>
  );
}

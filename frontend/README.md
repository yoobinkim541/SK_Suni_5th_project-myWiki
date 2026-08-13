# myWiki — 프론트엔드

SK mySUNI 써니C 5기 Team 5 · AI 기반 산업 동향 자동 큐레이션 시스템의 화면 레이어.
React 18 + Vite + react-router-dom, 외부 UI 컴포넌트 라이브러리 없이 직접 구현했습니다.

> 프로젝트 전체 배경·기능 현황은 저장소 루트 [`README.md`](../README.md)를 참고하세요.
> 이 문서는 `frontend/` 디렉터리(이 브랜치, `develop-frontend`) 자체에 대한 안내입니다.

---

## 상태

프로덕션(mywiki.pe.kr)에서 실제 백엔드(`api.mywiki.pe.kr`)에 연결돼 운영 중입니다.
`data/mock*.js`의 목업 데이터는 여전히 저장소에 남아있지만, 이는 백엔드 없이 화면만
띄워볼 때 쓰는 개발용 폴백(`VITE_USE_MOCK=true`)이고 기본 동작은 아닙니다.

---

## 빠른 시작

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

### 환경변수 (`.env.local`)
```env
VITE_API_BASE_URL=          # 백엔드 API 주소 (로컬: http://localhost:8000, 운영: https://api.mywiki.pe.kr)
VITE_SUPABASE_URL=          # Supabase 프로젝트 URL — 로그인(OAuth)에 필요
VITE_SUPABASE_ANON_KEY=     # Supabase anon key
VITE_USE_MOCK=true          # true면 백엔드 없이 data/mock*.js로 화면만 렌더링
VITE_VAPID_PUBLIC_KEY=      # 브라우저 푸시 알림 구독에 필요(선택)
```
`VITE_USE_MOCK=false`(또는 값 자체를 지움)로 두고 `VITE_API_BASE_URL`·Supabase 값을 채우면
실제 백엔드에 붙습니다. 백엔드 실행 방법은 루트 README 13번 "Run — Backend" 참고.

### 빌드
```bash
npm run build     # 정적 산출물 생성 (Vercel이 develop-frontend push 시 자동 실행)
npm run preview   # 빌드 결과 로컬 미리보기
```

---

## 폴더 구조

```text
frontend/src/
├── App.jsx                 앱 조립 · 라우팅(react-router-dom) · 다크모드 · PWA
├── main.jsx
├── pages/                  화면 단위
│   ├── EntryFlow.jsx       랜딩 · 로그인/회원가입 · 게스트 진입
│   ├── OnboardingPage.jsx  관심 키워드 선호조사
│   ├── DashboardPage.jsx   메인 대시보드(KPI·추이·최신뉴스·최근 산업 이슈)
│   ├── ReportPage.jsx      일일 리포트(다운로드·히스토리)
│   ├── CategoryPage.jsx    카테고리 현황
│   ├── WikiPage.jsx        위키 이슈/주제 페이지
│   ├── AgentPage.jsx       팀 공유 에이전트 채팅
│   ├── SettingsPage.jsx    계정·팀·데이터 파이프라인 설정, 관리자 화면
│   └── PrivacyPage.jsx     개인정보 처리방침
│
├── api/                     백엔드 REST 호출 저수준 클라이언트(엔드포인트별 1파일)
│   ├── client.js            공통 fetch 래퍼(Bearer JWT 첨부 등)
│   ├── supabaseClient.js     Supabase Auth 클라이언트
│   └── auth·agent·category·dashboard·report·wiki·settings·teams·admin·profile·workspaceSettings.js
│
├── services/                화면별 API 오케스트레이션 — 페이지는 이 계층만 바라봄
│   ├── dashboardApi.js  categoryApi.js  reportApi.js  wikiApi.js  agentApi.js  settingsApi.js
│   └── retry.js             네트워크 재시도 공통 로직
│
├── data/                    목업 데이터 — VITE_USE_MOCK=true일 때만 사용되는 개발용 폴백
│   └── mockOnboarding/Dashboard/Category/Report/Wiki.js, wikiKeywords.js
│
├── components/
│   ├── common/     Card TopBar SideNav MobileNav SettingsPanel ProfilePanel Spinner 등
│   ├── dashboard/  KpiCard TrendChart IssueList KnowledgeGraph InterestsBar/Modal CategoryPreview
│   ├── category/   CategoryCard CategoryRow CategoryDetail KeywordPie CategoryKeywordChart
│   ├── report/     ReportSummary ReportSection ReportDetailModal
│   ├── wiki/       WikiCard CitationTag WikiSideNav WikiKeywordBar/Modal/DocsModal
│   ├── agent/      ChatMessage ChatComposer ParticipantsModal ShareToTeamModal TeamMembersModal
│   └── settings/   SettingsGroup/Row ProfileFields TeamPanel/CrudSection AdminPanel
│                    SessionsSection AdminSessionViewModal UserManagementSection
│
├── hooks/           useIsMobile useAvatarUrl useRevealOnScroll
├── lib/              formatDate relativeTime pushNotifications(Web Push 구독 오케스트레이션)
├── constants/        navPaths roles
├── styles/           globals.css(시안 CSS) tailwind.css wiki-keyword-bar.css wiki-sidenav.css
└── assets/           로고·마스코트 이미지
```

---

## 코드 읽는 법

- 페이지(`pages/`)는 `data/`를 직접 보지 않고 반드시 `services/*.js`를 거칩니다. `services/`가
  내부적으로 `api/*.js`(실제 fetch) 또는 `VITE_USE_MOCK=true`일 때 `data/mock*.js`를 선택합니다.
- 백엔드 연동 상태를 파일별로 확인하려면 각 `api/*.js` 상단 주석을 보세요 — 대응하는 백엔드
  라우터 파일(`src/api/*_router.py`)을 함께 적어둔 파일이 많습니다.
- `TODO:` 주석은 백엔드에 아직 없는 기능이거나, 의도적으로 자리만 잡아둔 곳입니다.

---

## 참고

- 전체 기능 현황·기술 스택·배포 파이프라인: 저장소 루트 [`README.md`](../README.md)
- 백엔드 API 명세: 백엔드 서버 실행 후 `http://localhost:8000/docs` (FastAPI 자동 문서)

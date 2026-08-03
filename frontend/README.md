# myWiki — 프론트엔드 컴포넌트 (v0.4)

SK mySUNI 써니C 5기 Team 5 · RAG + LLM 기반 산업 트렌드 자동 큐레이션 시스템의 화면 레이어.
React 18 + Vite, 외부 UI·차트 라이브러리 없음. 데이터는 아직 전부 `src/data/` 목업입니다.

```bash
npm install && npm run dev
```

---

## 반영된 수정사항

**1. 첫 진입 — 선호 조사 화면**
앱을 처음 열면 대시보드 대신 선호 조사 화면이 뜹니다(진행 단계 바 + 관심 키워드 복수 선택 +
직무 택1 + 연령대 택1 — 기존 시안 구성 그대로).
`myWiki 시작하기`를 누르면 고른 관심 키워드가 대시보드 "최신 뉴스" 필터로 이어집니다.
직무·연령대는 저장만 하고 추후 이슈 랭킹 가중치로 쓸 자리입니다.
→ `pages/OnboardingPage.jsx`, `data/mockOnboarding.js`, `App.jsx`

**2. myWiki 로고 = 화면 새로고침**
브라우저 통째 새로고침이 아니라 앱 상태 초기화(대시보드 이동 + 패널 닫기 + 재마운트 + 스크롤 상단).
다크모드·관심사 설정은 유지됩니다. 로고 4곳(PC 상단바/사이드바, 모바일 상단바/드로어) 모두 동작.
→ `App.jsx` `handleLogoClick`, `TopBar.jsx`, `SideNav.jsx`, `MobileNav.jsx`

**3. 대시보드 — 순서 변경 + 검색 제거**
`최근 현황 → 그래프 → 최신 뉴스 → 카테고리·키워드 → 최근 이슈` 순으로 재배치.
검색창은 마크업·state까지 완전 제거하고, 관심사 필터와 "오늘의 키워드" 클릭 필터로 대체.
→ `pages/DashboardPage.jsx`

**4. 위키 — 공시 원문·뉴스기사 연동**
본문에 등장하는 등록 키워드 17개가 자동으로 클릭 가능해지고, 누르면 공시·IR 원문과
관련 뉴스기사를 나눠서 보여주는 모달이 뜹니다. 본문 위 `연동 키워드` 칩 바도 추가.
→ `data/mockWiki.js`(`WIKI_KEYWORD_LINKS`), `components/wiki/WikiCard.jsx`, `WikiKeywordModal.jsx`

**5. 일일 동향 보고서 — 구조 개편**
처리 현황 KPI 삭제 → `분류 → 주요 이슈(다운로드 버튼 동봉) → 리포트 보관·내보내기` 순.
전체 다운로드와 이전 리포트 보관함은 그대로 유지.
→ `pages/ReportPage.jsx`, `components/report/ReportSummary.jsx`, `ReportSection.jsx`

**5-1. 주요 이슈 섹션 — 이슈별 즉시 다운로드 + 전체 리포트 모달**
이슈 목록 위에 있던 다운로드 바(`.dlbar.tight`)를 없애고, **이슈 행 하나하나**에 다운로드 버튼
(Word/PDF/PPT)을 붙였습니다 — 이슈를 보다가 그 자리에서 바로 받습니다.
**이슈 행 · 리포트 히스토리 카드**를 클릭하면 같은 전체 리포트 모달이 뜹니다
(총평 → 키워드 → 다운로드 → 선별 이슈 전체 → 출처 원문). 이슈 행에서 열면 그 이슈가 모달 안에서 강조됩니다.
히스토리 카드는 "카드를 누르면 전체 리포트와 출처를 볼 수 있습니다" 안내문만 있고 핸들러가 없었는데 이번에 붙였습니다.
다운로드 버튼은 행/카드 클릭(모달 열기)으로 번지지 않게 `stopPropagation` 처리했고, 동작은 기존대로 토스트입니다(백엔드 연동 자리 유지).
→ `components/report/ReportDetailModal.jsx` ← 신규, `ReportSection.jsx`,
　`dashboard/IssueList.jsx`(`onOpenIssue` / `downloadFormats` / `onDownload` 옵션 prop —
　대시보드는 안 넘기므로 동작 변화 없음), `services/reportApi.js`(`fetchReportDetail`),
　`data/mockReport.js`(`MOCK_REPORT_DETAILS`)

**6. 카테고리 현황 — 키워드 원그래프**
도넛 2개. 왼쪽은 6개 분류 비중, 오른쪽은 선택한 분류 **내부**의 수집 키워드 구성.
왼쪽 조각/범례를 누르면 오른쪽이 바뀝니다.
→ `components/category/KeywordPie.jsx`, `CategoryKeywordChart.jsx`, `data/mockCategory.js`

**7. 계정 설정 제거 → "계정" 읽기 전용**
우측 상단 더보기 시트의 `계정 설정` 항목을 삭제했습니다. 설정 페이지의 `계정 설정` 섹션은
`계정`으로 이름을 바꾸고, 프로필 사진·이름·이메일을 **보여주기만** 하도록 고정했습니다
(이미지 변경·이름/이메일 입력·비밀번호 변경 제거). 계정 정보는 `SettingsPage.jsx`의 `ACCOUNT` 상수.
→ `components/common/MobileNav.jsx`, `pages/SettingsPage.jsx`, `App.jsx`

**8. 서비스 계층 연결**
`DashboardPage` / `ReportPage` / `CategoryPage` / `CategoryRow`가 `data/`를 직접 보지 않고
`services/*.js`를 거쳐 `useEffect`로 받아오도록 정리됐습니다. 로딩 상태(`불러오는 중…`)도 추가.
대시보드 KPI 숫자(312·18·124·보통)도 코드에 박혀 있던 걸 `MOCK_KPI_SUMMARY`로 분리했습니다.
→ API 클라이언트 작업 시 `services/` 함수 몸통만 `fetch`로 바꾸면 됩니다.

**그 외 버그 수정**
- `CategoryDetail.jsx` / `SettingsPage.jsx`의 `.view`에 `.on`이 빠져 있어 두 페이지가
  `display:none` 상태였습니다.
- PC 레이아웃 — `.app`이 2열 그리드인데 자식이 `.deck`/`.side`/`.main` 3개라
  본문이 아래 줄로 밀려 있었습니다. `.deck`를 전체 폭 헤더 행으로 고정. `globals.css`는 기존 값을 건드리지 않고 신규 클래스만 뒤에 추가.

---

## 폴더 구조

```
src/
├── App.jsx                    앱 조립 · 온보딩 분기 · 로고 새로고침 · 다크모드 · PWA
├── main.jsx
├── hooks/useIsMobile.js       768px 기준 PC/모바일 판별
├── styles/globals.css         시안 CSS 전체 + v0.4 신규 클래스(파일 끝에 추가)
│
├── data/                      목업 데이터 — API 붙기 전까지의 단일 소스
│   ├── mockOnboarding.js      ← 신규: 관심사 목록 + 뉴스 매칭 로직
│   ├── mockDashboard.js       뉴스 / 이슈 / 추이 / 카테고리 미리보기 / 키워드
│   ├── mockCategory.js        분류 카드 + 분류 요약 + 키워드 분포(원그래프)
│   ├── mockReport.js          분류 / 주요 이슈 / 보관함 / 전체 리포트 상세(MOCK_REPORT_DETAILS)
│   └── mockWiki.js            위키 문서·출처·연결문서 + 키워드 연동 매핑
│
├── services/                  API 호출부 (지금은 목업을 Promise.resolve)
│   └── dashboardApi.js  categoryApi.js  reportApi.js  wikiApi.js
│
├── components/
│   ├── common/     Card TopBar SideNav MobileNav SettingsPanel SegmentedControl ToggleSwitch
│   ├── dashboard/  KpiCard TrendChart IssueList CategoryPreview
│   ├── category/   CategoryCard CategoryRow CategoryDetail CategoryNewsModal
│   │               KeywordPie ← 신규    CategoryKeywordChart ← 신규
│   ├── report/     ReportSummary ReportSection    ReportDetailModal ← 신규
│   ├── wiki/       WikiCard CitationTag    WikiKeywordModal ← 신규
│   ├── agent/      ChatMessage ChatComposer
│   └── settings/   SettingsGroup SettingsRow
│
└── pages/
    ├── OnboardingPage.jsx ← 신규
    └── DashboardPage  ReportPage  CategoryPage  WikiPage  AgentPage  SettingsPage
```

---

## 코드 주석 읽는 법

파일마다 상단에 그 파일이 뭘 하는지, 이번에 뭘 바꿨는지 적어뒀습니다.

| 표시 | 뜻 |
|---|---|
| `⚠ 수정사항 N)` | 위 6건 중 N번 요청으로 바뀐 부분. 왜 그렇게 바꿨는지까지 적혀 있음 |
| `TODO:` | 백엔드·인증이 없어서 자리만 잡아둔 곳 (로그아웃, 계정 설정 모달 등) |
| `반응형 참고:` | CSS가 이미 처리하므로 JS에서 화면 폭 분기를 하면 안 되는 곳 |
| 파일 하단 주석 | 그 컴포넌트가 쓰는 목업 데이터의 위치 |

특히 아래 세 곳은 손대기 전에 주석을 먼저 읽어주세요.

- `App.jsx` 상단 — 온보딩 분기 조건과 로고 새로고침이 왜 `location.reload`가 아닌지
- `WikiCard.jsx` — 각주(①②③)와 연동 키워드의 **역할 차이**, 긴 키워드 우선 매칭 이유
- `CategoryKeywordChart.jsx` — 두 원그래프가 같은 소스를 봐서 합계가 어긋나지 않는 구조

---

## 다음 작업 — API 클라이언트

곧 API 클라이언트 작업에 들어갑니다. 화면은 이미 그 전제로 짜여 있습니다.
컴포넌트는 `data/`를 직접 보지 않고 `services/`만 바라보므로,
**`services/*.js`의 함수 몸통을 `fetch`로 바꾸면 컴포넌트는 손댈 필요가 없습니다.**

| 항목 | 대상 |
|---|---|
| HTTP 클라이언트 공통화 | base URL · 타임아웃 · 에러 핸들링 · 재시도 |
| 로딩 / 에러 상태 | 각 페이지 스켈레톤·폴백 (지금은 즉시 렌더 전제) |
| 관심사 저장 | `localStorage` → `GET/POST /api/me/interests` |
| 키워드 연동 | `WIKI_KEYWORD_LINKS` → `GET /api/wiki/keywords/{word}` |
| 키워드 분포 | `MOCK_CATEGORY_KEYWORDS` → `GET /api/categories/keyword-stats` |
| 리포트 다운로드 | `downloadReport()` → 실제 파일 스트림 (현재는 상태 토스트만) |
| 상대시간 표기 | `"12분 전"` 하드코딩 → 서버 타임스탬프 변환 유틸 |
| 인증 | 로그인 / 로그아웃, `ACCOUNT` 상수 → 로그인 세션 정보 |

목업은 API 연동 후에도 개발용 폴백으로 남깁니다.

---

myWiki · SK mySUNI 써니C 5기 Team 5 · 화면 시안 v0.4

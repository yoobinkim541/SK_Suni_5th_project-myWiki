# 프론트엔드 연동 매핑 (2026-07-30)

카카오톡으로 받은 프론트 초안(`mywiki-team5-merged-polished.zip`, 김주현 담당분 병합본) 기준.
페이지 구조는 안정적이라고 확인됨 — `src/App.jsx`의 `view` 분기(`dash/cat/settings/report/wiki/agent`)와
`pages/*.jsx` 단위는 그대로 두고, 각 페이지가 쓰는 목업 데이터를 실제 API로 교체하는 매핑만 정리한다.

프론트 쪽 연결 함수는 초안 `src/api/*.js`로 만들어뒀다(`client.js`, `supabaseClient.js`,
`wiki.js`, `agent.js`, `report.js`, `dashboard.js`, `category.js`, `auth.js`, `settings.js`).
실제 프론트 레포에 그대로 복사해서 쓰면 된다.

## 상태 범례
- 🟢 LIVE — 백엔드 존재, 지금 바로 연결 가능
- 🟡 계약만 — 프론트 함수는 만들어뒀지만 백엔드 없음, 엔드포인트는 제안 단계
- 🔴 설계 필요 — 어느 테이블/컬럼에 대응하는지 스키마 자체가 없어서 팀 논의 먼저 필요

---

## 1. WikiPage (`pages/WikiPage.jsx`) — 🟢 담당: 김유빈

새로 만든 `src/api/wiki_router.py` (`GET /wiki/pages`, `GET /wiki/pages/{slug}`,
`GET /wiki/pages/{page_id}/versions`)로 연결 가능. 프론트 함수: `src/api/wiki.js`.

| 화면 요소 | 목업 | 연결 함수 | 비고 |
|---|---|---|---|
| 좌측 트리 | `TREE` | `fetchWikiPages()` | `page_type` 5종(`industry/company/technology/issue/term`)으로만 그룹핑 가능. 목업 그룹명(제품·기술/경쟁사/고객·수요산업/공급망·생산)과 안 맞음 — **화면 그룹 라벨을 5종 기준으로 재조정 필요** |
| 문서 제목/카테고리/최종갱신 | `activeDoc`, `.dt`, `.st` | `fetchWikiPage(slug)` | `title`, `page_type`, `versions[0].created_at` |
| 본문 | `.zone` 개요/쟁점 문단 | `fetchWikiPage(slug).markdown` | 백엔드는 markdown 문자열 하나만 줌. "개요/쟁점" zone 나누기는 프론트에서 마크다운 렌더러 + heading 파싱, 또는 작성 규칙(`## 개요`, `## 쟁점`)을 팀에서 정해야 함 |
| 근거 출처 목록 | `SOURCES` | `fetchWikiPage(slug).sources[]` | 🔴 `document_version_id`만 옴. `"공시 원문 · 07.21"` 같은 라벨(문서 제목+날짜)을 만들려면 `documents`/`document_versions` 조인 필요 — **김보연(수집) 파트 확인 필요** |
| 연결된 문서 | `LINKED_DOCS` | 없음 | 🔴 wiki_pages 간 "상호 링크" 개념이 스키마에 없음(`parent_page_id` 계층만 있음). 필요하면 새 테이블(예: `wiki_page_links`) 논의부터 |
| 변경 이력 | `TIMELINE` | `fetchWikiVersions(pageId)` | `isNew`는 `versions[0]`을 프론트에서 표시. `desc`는 `change_summary` 그대로 |
| 평균 신뢰도 | `"보통"` | `fetchWikiPage(slug).confidence_score` | 0~1 숫자 → 라벨(높음/보통/낮음) 매핑은 프론트에서 |

## 2. AgentPage (`pages/AgentPage.jsx`) — 🟢 담당: 윤혜민 (이미 구현됨)

`src/api/main.py`의 `/chat/sessions` 계열 엔드포인트가 이미 있음. 프론트 함수: `src/api/agent.js`.

| 화면 요소 | 목업 | 연결 함수 | 비고 |
|---|---|---|---|
| 채팅 스레드 | `MOCK_THREAD` | `createChatSession()` → `sendChatMessage()`/`fetchChatMessages()` | `role`이 백엔드는 `user`/`assistant`, 프론트 목업은 `me`/`ai` — 매핑 필요 |
| 근거 없음 카드 | `none: {title, desc}` | `sendChatMessage().has_answer === false` | 백엔드는 `content`에 `"[근거 부족] <사유>"` 문자열 하나로만 줌 — title/desc 분리는 프론트에서 파싱 |
| 인용 칩 | `citations` | `message.citations[]` | `document_version_id`만 있고 출처 라벨 없음(WikiPage와 동일 제약) |
| 우측 "근거 원문" 카드 | `MOCK_EVIDENCE` (excerpt/footer) | 없음 | 🔴 원문 발췌+날짜+신뢰도 형태의 별도 조회 없음. citations 확장이 필요한지 논의 필요 |
| "웹에서 찾아볼까요?" 버튼 | 없음(신규) | `regenerateMessage(messageId, { allow_web_search: true })` | 근거 없음 카드가 뜨고(`has_answer === false`) `is_llm_fallback === false`일 때(위키+원문까지만 시도한 1턴 상태)만 노출. 새 함수 아님 — 기존 `regenerateMessage()`에 쿼리 파라미터만 추가해서 `POST .../messages/{message_id}/regenerate?allow_web_search=true` 호출 |
| 웹 검색 근거 배지 | 없음(신규) | `message.citations[]` | 응답 citation의 `document_version_id`가 `null`이면 "웹 검색 근거" 배지 표시, `source_url`/`document_title`로 링크 렌더링. `document_version_id`가 있으면 지금처럼 위키/원문 근거로 취급 |
| 출처 없음 표시 | 없음(신규) | `sendChatMessage()/regenerateMessage().is_llm_fallback` | `is_llm_fallback === true`면(웹 검색까지 실패) 기존과 동일하게 "출처 없음" 표시 + 위키 저장 버튼 비활성화 |

**배포 순서 주의:** 이 브랜치 이전에는 위키/원문 근거가 둘 다 없으면 1턴 안에서 자동으로 일반 지식 폴백까지 갔지만, 이제는 그 자동 폴백이 없어지고 사용자가 "웹에서 찾아볼까요?" 버튼을 눌러야만(2턴, `allow_web_search=true` 재생성) 이어진다 — 프론트가 이 버튼을 백엔드와 같이 배포하지 않으면, 기존에는 답이 나오던 질문이 갑자기 "근거 없음"만 뜨는 것으로 보여 기능 후퇴처럼 보인다.

## 3. ReportPage (`pages/ReportPage.jsx`) — 🟡 담당: 이환희

`reports`/`report_sections`/`report_citations` 테이블은 있지만 FastAPI 조회 엔드포인트가 없음.
프론트 함수(`src/api/report.js`)는 만들어뒀고 `GET /reports/daily?date=` 로 제안해둠 — 이환희 파트에서 구현하면 프론트는 import만 그대로 쓰면 됨.

| 화면 요소 | 목업 | 비고 |
|---|---|---|
| KPI 4개 | `MOCK_KPIS` | 수집/채택/이슈/위키갱신 건수 — 어느 테이블 집계인지는 이환희 파트에서 정의 |
| 분류별 개수 | `MOCK_CATEGORIES` | 🔴 §5 카테고리 불일치 문제와 동일 |
| 오늘의 키워드 | `MOCK_KEYWORDS` | 소스 불명 — 집계 로직 필요 |
| 이슈 카드(신뢰도 막대) | `MOCK_ISSUES` (`level`, `barWidth`) | 🔴 `report_sections`에 신뢰도(%) 컬럼이 없음 — 컬럼 추가 필요한지 확인 |
| 이슈 → 연관 위키 | `issue.wiki` | 🔴 `report_sections` ↔ `wiki_pages` 연결이 스키마에 없음 |

## 4. DashboardPage (`pages/DashboardPage.jsx`) — 🟡 담당: 김보연/이환희 (미정)

집계 성격상 파이프라인(`pipeline_jobs`)과 분석(`reports`) 양쪽에 걸쳐 있어 **어느 파트가 낼지 먼저 정해야 함**.
프론트 함수(`src/api/dashboard.js`)는 만들어뒀고 `/dashboard/kpis`, `/dashboard/trend`, `/dashboard/issues`로 제안.

| 화면 요소 | 목업 | 비고 |
|---|---|---|
| KPI 3개(수집/주의이슈/신뢰확보) | 하드코딩 | `pipeline_jobs` 집계로 추정 |
| 추이 차트 | `TrendChart` (현재 placeholder, recharts 예정) | `{date, value}[]` 형태로 이미 주석에 명시돼 있음 |
| 이슈 리스트 | `MOCK_ISSUES`(dashboard용, report용과 필드가 다름 — `confidence` 숫자) | ReportPage의 이슈와 통합할지 별도로 둘지 확인 필요 |

## 5. CategoryPage (`pages/CategoryPage.jsx`) — 🔴 담당 미정, 분류 기준부터 확정 필요

**문제:** 카테고리 이름이 화면마다 다르다.
- CategoryPage: 메모리 / 파운드리 / 장비
- WikiPage 트리: 제품·기술 / 경쟁사 / 고객·수요산업 / 공급망·생산
- `wiki_pages.page_type` (실제 DB 제약): industry / company / technology / issue / term

세 곳 중 어느 것도 서로 대응하지 않음. DB에 "카테고리" 개념 자체가 별도로 없어서, 이 화면은
**팀이 분류 기준을 하나로 합의하기 전까지 백엔드를 만들 수 없다.** 프론트 함수(`src/api/category.js`)는
자리만 잡아뒀음(`GET /categories/stats` 제안, 호출하면 항상 실패).

## 6. SettingsPage (`pages/SettingsPage.jsx`) — 다크모드/글자크기는 백엔드 불필요

화면 문구 그대로("이 브라우저에만 저장됩니다") 서버 저장 대상이 아님. `src/api/settings.js`에
localStorage 래퍼만 추가해둠 — `App.jsx`의 `dark`/`fontSize` state를 여기로 감싸면 새로고침해도 유지됨.

- 🔴 "데이터·파이프라인 / 앱·소스" 섹션(코드 내 TODO) — 무엇을 보여줄지부터 미정.

## 7. 온보딩 (`components/onboarding/*`) — 🟢 로그인 자체는 가능 / 🔴 선호도 서버 저장은 스키마 없음

- `LoginScreen` → `src/api/auth.js`의 `signInWithProvider('google'|'github'|'kakao')`로 바로 연결 가능
  (Supabase Auth, `src/api/auth.py`가 세션 JWT를 검증하는 구조와 맞음).
- `SurveyScreen`은 이미 `localStorage.setItem('mywiki-prefs', ...)`로 저장 중. 화면 문구는
  "계정에 저장됩니다"라고 돼 있지만 **`profiles` 테이블에 선호도 저장 컬럼이 없음**
  (현재 컬럼: `id, display_name, department, created_at, updated_at`). 서버 저장하려면
  `profiles.prefs jsonb` 같은 컬럼 추가가 필요 — 스키마 변경이라 팀 확인 후 진행.
- `GateScreen`(캡챠)은 순수 UI 검증이라 백엔드 연결 대상 아님.

---

## 요약

| 페이지 | 상태 | 막힌 지점 |
|---|---|---|
| Wiki | 🟢 연결 가능 | 근거 출처 라벨(문서 조인), 연결된 문서(스키마 없음) |
| Agent | 🟢 연결 가능 | role/근거없음 카드 프론트 매핑만 하면 됨 |
| 온보딩(로그인) | 🟢 연결 가능 | - |
| 온보딩(선호도 서버 저장) | 🔴 | `profiles` 컬럼 추가 필요 |
| Report | 🟡 계약만 | 이환희 파트 구현 대기 + 신뢰도 컬럼 확인 |
| Dashboard | 🟡 계약만 | 담당 파트 미정 |
| Category | 🔴 설계 필요 | 카테고리 분류 기준 3곳 불일치 — 팀 합의 먼저 |
| Settings | 로컬 전용 | (서버 연결 불필요) |

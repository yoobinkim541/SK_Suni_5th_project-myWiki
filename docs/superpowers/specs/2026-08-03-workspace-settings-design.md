# 워크스페이스 설정(Wiki 주기·대화 보관 기간) 설계

> 기준일: 2026-08-03
> 담당: 김유빈 (Wiki·지식베이스 + DB)
> 대상 파일: 신규 `src/settings/service.py`, `src/api/settings_router.py`(신규), `scripts/refresh_wiki_scheduled.py`(신규), `scripts/cleanup_old_chats.py`(신규), `.github/workflows/`(신규 2개), `frontend/src/api/settings.js`, `frontend/src/services/settingsApi.js`(신규), `frontend/src/pages/SettingsPage.jsx`

## 1. 문제

`SettingsPage.jsx`의 "Wiki 업데이트 주기"/"에이전트 대화 기록 보관 기간"이 지금은 localStorage에만 저장되고 실제로 아무것도 구동하지 않는다. 사용자가 값을 바꾸면 실제로 위키 갱신 빈도와 오래된 대화 삭제에 반영되어야 한다.

## 2. 핵심 결정

- **스코프**: 둘 다 워크스페이스(팀) 공유 설정 — 개인별 아님. 같은 팀 누구든 바꾸면 전체에 적용된다.
- **저장 위치**: 신규 테이블 `workspace_settings`(workspace_id 1행).
- **Wiki 주기를 실제로 구동하는 방법**: 크론 자체를 사용자 선택값으로 재작성하지 않는다. GitHub Actions를 가장 촘촘한 옵션(30분)마다 돌리고, 매번 "게이트" 스크립트가 `now - last_wiki_refresh_at >= wiki_update_cycle_minutes`인지 확인한 뒤에만 실제로 `refresh_wiki_from_recent_analysis()`를 호출한다. `refresh_wiki.py`(PR #17)는 상태 없이(stateless) 항상 "최근 N시간 분석분"만 처리하는 구조라서, 게이트를 통과할 때마다 넉넉한 고정 lookback(`since_hours=24`)으로 호출해도 안전하다 — 오늘 만든 이슈 페이지 중복방지 로직(`find_matching_issue_page`)이 겹쳐 호출되는 경우를 이미 막아준다.
- **대화 보관 기간을 실제로 구동하는 방법**: 게이트 로직 불필요 — 매일 1회 배치가 그 시점의 `chat_retention_days` 값 기준으로 지난 대화를 지운다.
- **"마지막 활동" 기준**: `chat_sessions.updated_at`은 메시지가 추가돼도 갱신되지 않는다(코드 확인 완료 — DB 트리거는 있지만 메시지 추가 시 세션 행 자체를 UPDATE하는 코드가 없음). 메시지 전송 코드를 건드리는 대신, 삭제 배치가 그때그때 `chat_messages`에서 세션별 최신 메시지 시각을 직접 조회해서 판단한다(메시지가 하나도 없으면 `chat_sessions.created_at` 사용).

## 3. 스키마

```sql
create table workspace_settings (
  workspace_id uuid primary key references workspaces(id) on delete cascade,
  wiki_update_cycle_minutes int not null default 360
    check (wiki_update_cycle_minutes in (30, 60, 180, 360, 720, 1440)),  -- 30분/1h/3h/6h/12h/24h
  chat_retention_days int
    check (chat_retention_days in (7, 30, 90) or chat_retention_days is null),  -- null = 영구 보관
  last_wiki_refresh_at timestamptz,
  updated_by uuid references profiles(id),
  updated_at timestamptz not null default now()
);

create trigger trg_workspace_settings_updated_at
  before update on workspace_settings
  for each row execute function set_updated_at();
```

기본값(360분=6시간, chat_retention_days 미지정)은 프론트 mock의 초기값(`wikiCycle` 기본 `'6h'`, `chatKeep` 기본 `'90'`)과 다르다는 점을 인지 — `chat_retention_days`는 스키마상 기본 NULL(영구 보관)로 두고, 실제 팀 정책값(90일)은 첫 배포 시 마이그레이션에서 명시적으로 넣는다(§7 참고).

## 4. `src/settings/service.py` + API

`src/settings/service.py` 신규 — `src/wiki/query.py`와 같은 구조(모듈 레벨 `_get_client()`, workspace_id 필수 인자):

```python
def get_workspace_settings(workspace_id: str, *, supabase: Client | None = None) -> WorkspaceSettings:
    """행이 없으면 기본값으로 즉시 생성 후 반환."""

def update_workspace_settings(
    workspace_id: str,
    *,
    wiki_update_cycle_minutes: int | None = None,
    chat_retention_days: int | None = ...,  # 명시적으로 None을 넘기면 "영구 보관으로 변경", 아예 안 넘기면 "그대로 유지" — 두 의미를 구분해야 하므로 sentinel 필요
    updated_by: str | None,
    supabase: Client | None = None,
) -> WorkspaceSettings: ...

def mark_wiki_refreshed(workspace_id: str, *, supabase: Client | None = None) -> None:
    """last_wiki_refresh_at = now()."""
```

`WorkspaceSettings`는 `src/settings/models.py`에 frozen dataclass로 정의(`wiki_page 모듈의 WikiPageContent 등과 같은 스타일): `workspace_id, wiki_update_cycle_minutes, chat_retention_days, last_wiki_refresh_at, updated_at`.

`src/api/settings_router.py` 신규, 기존 `wiki_router.py`와 동일한 인증·workspace 스코프 패턴(`get_current_user` + `db.get_default_workspace_id`).

```
GET /settings
  -> { wiki_update_cycle_minutes, chat_retention_days, updated_at }
  워크스페이스에 행이 없으면 기본값으로 즉시 생성 후 반환(최초 조회 시 자동 생성 — 프론트가 "설정 없음" 에러를 따로 처리할 필요 없음).

PATCH /settings
  body: { wiki_update_cycle_minutes?: int, chat_retention_days?: int|null }
  값 검증: wiki_update_cycle_minutes는 CHECK 허용값(30/60/180/360/720/1440)에 없으면 422.
           chat_retention_days는 CHECK 허용값(7/30/90) 또는 null 아니면 422.
  -> 갱신된 전체 설정 반환. updated_by = 현재 사용자.
```

## 5. Wiki 갱신 게이트

신규 `scripts/refresh_wiki_scheduled.py` — `refresh_wiki.py`를 대체하는 게 아니라 그 앞에 게이트를 얹는 새 진입점(`refresh_wiki.py`는 그대로 두고 내부 함수만 재사용):

```
1. workspace_id 결정 (기존 스크립트들과 동일한 방식 — workspaces 1행 자동 선택)
2. workspace_settings에서 (wiki_update_cycle_minutes, last_wiki_refresh_at) 조회 — 행 없으면 기본값(360) 취급, 즉시 실행
3. last_wiki_refresh_at이 없거나 (now - last_wiki_refresh_at) >= wiki_update_cycle_minutes 분이면:
     refresh_wiki_from_recent_analysis(workspace_id, since_hours=24) 호출
     workspace_settings.last_wiki_refresh_at = now() 로 갱신
   아니면:
     "아직 주기 안 됨 (다음: ...)" 출력하고 종료(exit 0)
```

GitHub Actions `.github/workflows/wiki-refresh-gate.yml` — `cron: "*/30 * * * *"`(30분마다, 가장 촘촘한 옵션 기준) + `workflow_dispatch`.

## 6. 대화 보관 기간 배치

신규 `scripts/cleanup_old_chats.py`:

```
1. workspace_id 결정
2. workspace_settings.chat_retention_days 조회 — null이면 "영구 보관 설정, 삭제 없음" 출력 후 종료
3. 각 chat_session에 대해 마지막 메시지 시각(없으면 세션 생성 시각) 조회
4. (now - 마지막 활동) > chat_retention_days 인 세션들을 삭제 대상으로 모음
5. 삭제 대상 세션들의 message_citations -> chat_messages -> chat_sessions 순서로 삭제(FK 순서, PR #12/13에서 이미 겪은 teardown 순서 문제와 동일한 원칙)
6. 삭제 건수 로그 출력
```

GitHub Actions `.github/workflows/chat-retention-cleanup.yml` — `cron: "13 3 * * *"`(매일 새벽 3시 13분, 부하 회피) + `workflow_dispatch`.

## 7. 마이그레이션

`workspace_settings` 테이블 생성 마이그레이션에서, 기존 팀 워크스페이스(`slug='mywiki'`)에 대해 `chat_retention_days=90`(mock 기본값과 맞춤), `wiki_update_cycle_minutes=360`으로 초기 행을 명시적으로 INSERT한다(마이그레이션 안에서, 별도 스크립트 실행 없이).

## 8. 프론트엔드 연결

`frontend/src/api/settings.js`에 `fetchSettings()`/`updateSettings(patch)` 추가(`api/wiki.js` 패턴 — `apiFetch` 사용).

신규 `frontend/src/services/settingsApi.js` — `agentApi.js`/`wikiApi.js`와 동일한 어댑터 패턴. 분 단위 정수 ↔ 프론트 문자열 코드("30m"/"1h"/"3h"/"6h"/"12h"/"24h") 변환, `chat_retention_days` 정수|null ↔ "7"/"30"/"90"/"forever" 변환.

`SettingsPage.jsx`의 `wikiCycle`/`chatKeep` state를 localStorage 대신 `fetchSettings()`/`updateSettings()`로 교체(`useEffect` 비동기 로딩, `AgentPage.jsx`/`WikiPage.jsx`와 같은 패턴). `reportTime`/`agentScope`는 이번 범위 밖이라 localStorage 상태 그대로 둔다.

## 9. 에러 처리

- 게이트 스크립트가 `workspace_settings` 조회에 실패하면(네트워크 등) 예외를 그대로 던져서 GitHub Actions가 실패로 표시하게 둔다 — 무인 배치라 실패는 로그/exit code로만 알 수 있어야 한다(`refresh_wiki.py`의 기존 방침과 동일).
- `cleanup_old_chats.py`도 동일 — 삭제 실패는 예외 전파.
- API의 PATCH 검증 실패는 422 + 상세 메시지(FastAPI 기본 동작).

## 10. 테스트

- `workspace_settings` CRUD: 실 DB 통합 테스트(`test_wiki_service.py`와 같은 패턴 — `_get_client()` 픽스처, 자격증명 없으면 skip)
- `GET /settings` 최초 조회 시 자동 생성 확인, `PATCH /settings` 값 검증(허용값 밖이면 422) — `test_wiki_router.py`처럼 `dependency_overrides`로 인증 우회한 라우터 단위 테스트
- 게이트 로직(`refresh_wiki_scheduled.py`의 판단 함수)은 순수 함수로 분리해서 `now`/`last_wiki_refresh_at`/`cycle_minutes` 조합별 유닛 테스트(실행함/안 함 경계값 포함)
- `cleanup_old_chats.py`의 "마지막 활동 시각 계산 + 삭제 대상 판정" 로직도 실 DB 통합 테스트로 확인(세션 생성 → 오래된 메시지로 조작 → 삭제 대상 판정 확인)

## 11. 이번 설계에 포함하지 않는 것

- `reportTime`(일일 리포트 생성 시간), `agentScope`(에이전트 참조 범위) — 이번 요청에 없었음
- 사용자별 설정 오버라이드 — 전부 워크스페이스 공유
- 삭제된 대화의 백업/복구

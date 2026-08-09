# 팀 기반 역할·권한 관리 설계

## 배경

현재 `workspace_members.role`(owner/admin/editor/viewer)만 존재하고 "팀"이라는 그룹 단위 자체가 스키마에 없다. `profiles.department` 자유 텍스트 필드가 있지만 실제로는 전원 NULL(미사용)이고, 조회·강제 어느 쪽으로도 쓰이지 않는다. 라이브 DB 기준 워크스페이스는 1개, 멤버 13명(owner 1, admin 2, editor 10, viewer 0)뿐인 단일 워크스페이스 MVP다.

요구사항은 3단 구조다:
- **팀원**: 팀원 초대 가능
- **팀장**: 소속 팀원의 초대/삭제/영입 가능
- **관리자(인사팀)**: 전체 사용자 및 팀별 멤버 리스트 조회, 사용자 팀 배치(추가/제외) 관리

## 목표

1. 워크스페이스 안에 "팀" 하위 그룹을 만들 수 있다.
2. 기존 `workspace_members.role`을 그대로 재사용해 팀 계층을 표현한다 — `owner`=관리자(인사팀), `admin`=팀장, `editor`=팀원. 새 역할 컬럼(`team_role`, `is_org_admin`)을 추가하지 않는다.
3. 팀원·팀장은 **자기 팀 소속 범위 안에서만** 팀원을 초대/삭제(팀장)할 수 있다. 워크스페이스 전체에 걸치지 않는다.
4. 팀장은 초대(미배치 사용자만 대상)뿐 아니라 영입(타 팀 소속자도 대상)까지 가능하다. 팀원은 초대만 가능하다.
5. 관리자(owner)는 워크스페이스 전체 사용자·팀별 명단을 조회하고, 누구든 어느 팀으로든 배치/제외할 수 있다.
6. 팀 생성·삭제는 관리자(owner) 전용이다.

## 비목표

- `viewer` 역할 — 현재 0명이며 이번 설계 범위 밖.
- 워크스페이스 간 팀 이동 — 워크스페이스가 1개뿐이라 범위 밖.
- 팀장 임명/`role` 자체 변경 — 기존 오너 전용 관리 패널(#165, `update_workspace_member_role`)이 이미 담당하며 이번 작업은 건드리지 않는다. 이번 기능은 "그 사람이 어느 팀 소속인지"만 다룬다.
- 팀 소속 알림(이메일 등).

## 아키텍처

### 스키마

```sql
CREATE TABLE public.teams (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  name text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (workspace_id, name)
);

ALTER TABLE public.workspace_members
  ADD COLUMN team_id uuid REFERENCES public.teams(id) ON DELETE RESTRICT;
```

- `team_id`는 `profiles`가 아니라 `workspace_members`에 둔다 — `role`과 한 행에서 "이 워크스페이스에서 이 사람의 소속·직급"을 함께 표현하는 게 자연스럽고, 향후 워크스페이스가 늘어나도 팀 소속이 워크스페이스별로 독립적으로 유지된다.
- `team_id`는 nullable — "미배치" 상태(신규 가입자 기본값)를 표현한다.
- `ON DELETE RESTRICT` — 소속 인원이 있는 팀은 DB 레벨에서 삭제를 막는다. API에서는 삭제 전 인원 수를 먼저 확인해 명확한 400 메시지로 처리한다(원본 FK 에러를 그대로 노출하지 않음).
- RLS: `teams`에 `is_workspace_member(workspace_id)` SELECT 정책만 추가(기존 `wiki_page_keywords` 등과 동일 패턴). 쓰기는 FastAPI가 service_role로 수행하므로 RLS 쓰기 정책은 불필요 — 실제 권한 검증은 전부 API 레이어.

### 권한 매핑

| `role` | 명칭 | 권한 범위 |
|---|---|---|
| `owner` | 관리자(인사팀) | 워크스페이스 전체 — 전체 사용자·팀별 명단 조회, 임의 사용자를 임의 팀에 배치/제외, 팀 생성·삭제 |
| `admin` | 팀장 | 자기 팀(`team_id` 일치)만 — 소속 팀원 초대/삭제, 타 팀 인원 영입 |
| `editor` | 팀원 | 자기 팀만 — 미배치 사용자 초대만 |
| `viewer` | (미사용) | 범위 밖 |

### API (`src/api/db.py` 신규 함수)

```
create_team(workspace_id, name) -> dict
list_teams(workspace_id) -> list[dict]                       # id, name, member_count
delete_team(team_id) -> None                                  # 소속 인원 있으면 ValueError
list_team_members(team_id) -> list[dict]                      # user_id, display_name, role
list_workspace_users_with_team(workspace_id) -> list[dict]    # 전체 사용자 + team_id/team_name/role — 관리자 전용 열람
move_member_to_team(workspace_id, user_id, team_id) -> None   # team_id=None 허용(제외). 인가되지 않은 원시 함수 — 호출부(main.py)가 대상 검증
```

기존 `remove_workspace_member`/`update_workspace_member_role` 패턴과 동일하게, `db.py` 함수 자체는 권한을 검증하지 않는 원시 동작만 하고, 역할·소속 범위 검증은 `main.py`가 담당한다.

### API (`src/api/main.py` 신규 엔드포인트)

```
POST   /teams                            관리자 전용 — {name}
DELETE /teams/{team_id}                  관리자 전용 — 소속 인원 있으면 400
GET    /teams                            워크스페이스 멤버 전체 열람 — 팀 목록 + 인원수
GET    /teams/{team_id}/members          워크스페이스 멤버 전체 열람 — 팀별 명단

GET    /admin/users                      관리자 전용 — 전체 사용자 + 소속 팀/role
PATCH  /admin/users/{user_id}/team       관리자 전용 — {team_id: uuid|null} 임의 배치/제외

POST   /teams/{team_id}/members          팀원+팀장(자기 팀만) — 초대. 대상 이미 배치돼 있으면 400
POST   /teams/{team_id}/members/recruit  팀장 전용(자기 팀만) — 영입. 대상이 타 팀 소속이어도 허용
DELETE /teams/{team_id}/members/{uid}    팀장 전용(자기 팀만) — 제외. 본인 대상이면 400
```

인가 헬퍼: `_require_owner`(기존, #165)는 그대로 재사용. 신규로 `_require_team_scope(profile, workspace_id, team_id, allow_roles)` — 호출자의 `role`이 `allow_roles`에 있고 `team_id`가 호출자의 소속과 일치하는지 확인.

## 에러 처리

- 초대 대상이 이미 다른 팀 소속 → 400 "이미 배치된 사용자입니다. 팀장만 영입할 수 있습니다"
- 영입 대상이 이미 같은 팀 → 400 "이미 같은 팀입니다"
- 팀장/팀원이 자기 팀이 아닌 `team_id`로 호출 → 403
- 관리자 전용 엔드포인트를 관리자가 아닌 사용자가 호출 → 403
- 팀 이름 중복 → 400
- 소속 인원이 있는 팀 삭제 시도 → 400
- 제외 대상이 이미 미배치 → idempotent하게 조용히 종료(에러 아님)

## 테스트

- `tests/test_teams.py`(신규): `db.py` 함수 단위 테스트(fake Supabase) — 팀 생성/삭제(인원 있을 때 차단 포함), 팀원 목록, 전체 사용자 목록, `move_member_to_team`(null 처리 포함).
- `tests/test_teams_router.py`(신규): 라우터 레벨 — 8개 엔드포인트 각각 역할별 403/성공 케이스, 자기 팀 범위 밖 호출 403, 초대/영입 대상 상태별 400.

## 영향받는 파일

| 파일 | 변경 |
|---|---|
| `supabase/migrations/20260809100000_create_teams.sql` | 신규 — `teams` 테이블 + `workspace_members.team_id` + RLS |
| `src/api/db.py` | 팀 관련 함수 5종 신규 |
| `src/api/schemas.py` | `TeamOut`, `TeamMemberOut`, `AdminUserOut`, `CreateTeamRequest`, `AssignTeamRequest` 신규 |
| `src/api/main.py` | `_require_team_scope` 헬퍼 + 8개 엔드포인트 신규 |
| `tests/test_teams.py`, `tests/test_teams_router.py` | 신규 |
| `docs/architecture/mywiki-erd.md` | `teams` 테이블 + `workspace_members.team_id` 반영 |
| ERDCloud | `teams` 테이블·관계선 동기화 |

프론트엔드(`develop-frontend` 브랜치, 별도 담당)는 이번 범위 밖 — 백엔드 API까지만 완료한다.

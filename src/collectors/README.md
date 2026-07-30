# src/collectors — 데이터 수집 담당

## 담당 테이블
- `sources` — 뉴스/RSS/공시/웹사이트 등 수집 출처 등록·설정
- `documents` — 수집한 문서의 메타데이터 (아직 정제 전)
- `pipeline_jobs` (`job_type='collect'`) — 수집 작업 상태 기록

## 참고 자료
- `docs/architecture/myWiki_v2_supabase.sql` — 위 테이블 정확한 컬럼/제약조건
- `docs/architecture/myWiki_v2_snapshot.json` — ERD (erdcloud로 열람 가능)

## DB 접속 (2026-07-30 팀 결정)
배치에는 로그인 사용자가 없어 RLS(`is_workspace_member` 기준)를 통과할 수 없다.
`SUPABASE_SERVICE_ROLE_KEY`로 RLS를 우회하고, 모든 쿼리에 `workspace_id`를 애플리케이션 코드에서
직접 필터링하는 방식으로 통일한다 — `src/api/db.py`, `src/wiki/query.py`와 동일한 패턴.
배치 전용 계정을 따로 만들어 `workspace_members`에 등록하는 방식(RLS 적용)은 채택하지 않는다.

## 이 파트가 해야 하는 일
1. GeekNews / 구글 RSS / 네이버 검색 API 등에서 반도체·SK하이닉스 관련 원문을 가져온다.
2. `sources`에 등록된 출처 기준으로 수집하고, 새 문서는 `documents` + `document_versions`(raw 단계)에 기록한다.
3. `canonical_url` 기준으로 이미 있는 문서면 새로 만들지 않는다 (중복 방지는 `UQ_DOCUMENTS_WORKSPACE_URL` 제약이 최종 방어선이지만, API 호출 자체를 줄이려면 여기서도 먼저 체크하는 게 좋다).
4. 수집 실패/재시도는 `pipeline_jobs`에 상태(`pending/running/completed/failed`)로 남긴다.

## 인터페이스 (`interface.py` 참고)
다음 파트(`preprocessing`)가 그대로 이어받을 수 있도록, `collect()`가 반환하는 값은
반드시 `documents.id` + 원문이 저장된 Storage 경로(`raw_object_key`)를 포함해야 한다.

## 다음 단계로 넘기는 것
`preprocessing` 담당이 `document_id`만 갖고 `document_versions.raw_object_key`를 읽어서
정제(Markdown 변환)를 시작할 수 있어야 한다.

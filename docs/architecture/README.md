# architecture

- `myWiki_v2_supabase.sql` — Supabase SQL Editor에 그대로 붙여넣어 실행하는 최종 스키마 (PostgreSQL 문법, 16개 테이블 + PK/FK/UNIQUE/CHECK 전부 포함).
- `myWiki_v2.sql` — 위와 같은 내용의 원본(erdcloud Import용, MySQL 스타일 backtick 포함). erdcloud에 다시 올릴 때는 이 파일을 쓴다.
- `myWiki_v2_snapshot.json` — erdcloud 다이어그램 스냅샷. erdcloud에서 Load/Import하면 테이블 배치까지 그대로 열린다. 단, UNIQUE/CHECK 제약은 이 포맷 자체가 저장 못 해서 필드 comment로만 표시돼 있다 — 실제 제약은 위 두 SQL 파일 기준이 정본이다.

멘토 피드백(workspace 격리·RLS, 보고서 버전 관리, artifacts 테이블, UNIQUE/CHECK 제약, object_key 버전 충돌 방지) 6개 항목이 전부 반영된 버전이다.

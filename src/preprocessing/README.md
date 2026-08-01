# src/preprocessing — 데이터 정제·검증 담당

구현 근거: **데이터 파이프라인 인터페이스 명세 v1.1** (§3-3 ~ §3-7)

## 스켈레톤 대비 변경 (명세 §2-2)

| 스켈레톤 | 구현 | 사유 |
|---|---|---|
| `process_document(document_id) -> DocumentVersion` | `preprocess(document_id) -> ProcessedDocument \| None` | 실패를 예외 대신 `None` + `pipeline_jobs`로 알린다 |
| `DocumentVersion` 6필드 | `ProcessedDocument` 14필드 | 하류가 `documents` 조인 없이 출처 메타를 쓸 수 있게 |
| — | `get_markdown()` · `get_document_refs()` | `analysis`·프론트가 `document_version_id`만으로 본문·출처 라벨을 얻게 (§3-6, §3-7) |

원문 경로는 `documents.raw_object_key`(존재하지 않는 컬럼, 지침 §9-D-8)가 아니라
**collect가 남긴 문서 단위 job의 `result.raw_object_key`**에서 읽는다 (명세 §3-3).

## 담당 테이블
- `document_versions` — 원문을 정제한 Markdown, 버전·중복 해시 관리
- `pipeline_jobs` (`job_type='parse_document'`)

## 참고 자료
- `docs/architecture/myWiki_v2_supabase.sql`

## DB 접속 (2026-07-30 팀 결정)
`collectors`와 동일하게 `SUPABASE_SERVICE_ROLE_KEY`로 RLS를 우회하고, `workspace_id`는
애플리케이션 코드에서 직접 필터링한다 (`src/collectors/README.md` 참고).

## 이 파트가 해야 하는 일
1. `collectors`가 만든 `documents.raw_object_key`(원문)를 읽어서 Markdown으로 변환한다.
2. `content_hash`(SHA-256)로 동일 내용 중복을 판별한다 — 같은 문서라도 재수집됐을 뿐이면
   새 버전을 만들지 않는다 (`UQ_DV_DOCUMENT_HASH` 제약이 최종 방어선).
3. 내용이 실제로 바뀐 경우에만 `version_no`를 올려서 새 `document_versions` 행을 추가한다
   (기존 버전은 절대 덮어쓰지 않는다 — myWiki 전체의 버전 관리 원칙).
4. 광고성 문구, 중복 문단 등 노이즈를 제거한다.
5. 출처 신뢰도(`sources.reliability_score`) 갱신 기준이 필요하면 이 단계에서 근거를 남긴다.

## 인터페이스 (`interface.py` 참고)
`analysis` 담당은 `document_version_id`만 갖고 정제된 Markdown 본문을 바로 읽을 수 있어야 한다.

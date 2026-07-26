# src/preprocessing — 데이터 정제·검증 담당

## 담당 테이블
- `document_versions` — 원문을 정제한 Markdown, 버전·중복 해시 관리
- `pipeline_jobs` (`job_type='parse_document'`)

## 참고 자료
- `docs/architecture/myWiki_v2_supabase.sql`

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

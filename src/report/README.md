# src/report — AI 분석·보고서 담당 (2/2: 보고서 생성)

## 담당 테이블
- `reports` — 보고서 생성 요청/결과. **재생성 시 UPDATE 금지, `report_key`+`version`으로 새 행을 추가한다.**
- `report_citations` — 섹션별 근거 연결
- `artifacts` — 완성된 산출물(markdown/pdf/pptx/docx) 버전별 관리 (예전엔 `reports.markdown_object_key`였던 걸 분리한 테이블)

## 참고 자료
- `docs/architecture/myWiki_v2_supabase.sql` — `reports`/`artifacts` UNIQUE·CHECK 제약 꼭 확인
- `docs/architecture/myWiki_v2.sql` 하단 주석 — `object_key` 경로 네이밍 규칙:
  bucket=`reports`, object_key=`{workspace_id}/{report_id}/{artifact_type}/v{version}.{ext}`

## 이 파트가 해야 하는 일
1. `analysis`가 만든 `SectionDraft` 중 `status='completed'`인 것만 모아서 `reports` + `report_sections`를 채운다.
2. 같은 날 리포트를 다시 만들어야 하면 기존 행을 고치지 말고 `version`을 올려 새로 INSERT한다.
3. Markdown/PDF 등 산출물을 만들면 `artifacts`에 `report_id`, `artifact_type`, `version`, `object_key`로 기록한다.
   같은 `(report_id, artifact_type, version)` 조합은 만들 수 없다 (`UQ_ARTIFACTS_REPORT_TYPE_VERSION`).

## 인터페이스 (`interface.py` 참고)

- ?? ??: `src/report/storage.py` ? `DEFAULT_REPORT_ARTIFACT_BUCKET = "reports"`

# src/wiki — Wiki·지식베이스 담당

## 담당 테이블
- `wiki_pages` — 산업/기업/기술/이슈별 페이지 논리 정보
- `wiki_page_versions` — 실제 본문(Markdown)과 버전·검수 이력
- `wiki_page_sources` — 위키 본문의 주장(claim)과 원문 근거(document_version) 연결
- `qmd_index_entries` — 검색 인덱스 연결 (지금 단계에서는 없어도 동작하게 설계돼 있음, 3번 참고)

## 참고 자료
- `docs/architecture/myWiki_v2_supabase.sql`
- Karpathy LLM Wiki 패턴 요약: raw sources(원문, 불변) → **wiki(이 폴더가 만드는 것)** → schema.
  핵심은 "덮어쓰지 않고 쌓는다" — 기존 버전을 지우거나 고치지 않고 새 `wiki_page_versions`를 추가한다.

## 이 파트가 해야 하는 일
1. `report`가 만든 섹션이나 새로 들어온 근거를 보고, 관련 위키 페이지(`wiki_pages`)를 찾거나 새로 만든다.
2. 본문을 갱신할 때는 **기존 문단을 지우지 말고 "변경 이력"에 갱신 사유와 함께 추가**한다 (시안에서 이미 이 방식으로 디자인돼 있음 — `wiki/topics/*.md`의 "변경 이력" 섹션 참고).
3. 새 버전(`wiki_page_versions`)을 만들 때마다, 그 안의 각 주장이 어떤 원문(`document_version_id`)에서
   왔는지 `wiki_page_sources`로 연결한다. **이 연결이 없으면 Agent가 그 내용을 인용할 방법이 없다.**
4. Markdown 본문은 Storage에 업로드하고 `markdown_object_key`에 경로를 저장한다 (DB에 본문 텍스트를 직접 넣지 않는다).
5. `wiki_pages.current_version_id`를 최신 버전으로 갱신한다.

## ⚠️ Agent 파트와의 계약 (중요)
`src/agent/wiki_tools.py`의 `read_wiki_page(slug)`가 이 파트의 산출물을 그대로 읽는다.
그 함수는 아래를 기대한다:
- `wiki_pages.current_version_id`가 채워져 있을 것
- `wiki_page_versions.markdown_object_key` 경로에 실제 Markdown 파일이 Storage에 있을 것
- 그 버전에 연결된 `wiki_page_sources` 행들의 `document_version_id`가 실제 존재하는 문서를 가리킬 것

이 세 가지가 안 맞으면 Agent가 근거를 못 찾아서 전부 "근거 부족"으로 처리된다.
새 위키 페이지/버전을 만들면 이 세 가지를 체크리스트로 확인해달라.

## 인터페이스 (`interface.py` 참고)

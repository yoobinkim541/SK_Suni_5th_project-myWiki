# 웹검색 근거 답변의 위키 저장 지원 설계

## 배경

에이전트 답변은 4단계 그라운딩 체인을 거친다: 위키 → 원문 → (옵트인) 웹검색/DART → LLM 일반지식 폴백. 마지막 단계(`is_llm_fallback=True`)는 출처가 없어 멘토 피드백에 따라 이미 "위키에 저장" 자체가 막혀 있다(할루시네이션 방지, 의도된 정책 — 이번 스펙의 대상이 아님).

문제는 3단계(웹검색/DART)다. 이 단계 결과는 `is_llm_fallback=False`이고 `citations`도 채워지므로, 프론트(`agentApi.js`의 `toViewMessage`)는 정상 응답과 동일하게 "위키에 저장" 버튼을 보여준다. 하지만 웹 근거 citation은 `document_version_id=None`(대신 `source_url`)인데, `save_message_to_wiki`(`src/api/main.py`)가 이걸 그대로 `WikiSourceInput(document_version_id=c["document_version_id"], ...)`에 꽂고, 라이브 DB 확인 결과 `wiki_page_sources.document_version_id`가 `NOT NULL` UUID FK다 — 즉 웹 근거가 하나라도 섞인 답변을 저장하려 하면 DB 제약 위반으로 실패한다.

반면 마크다운 본문의 "## 출처" 절 자체는 이미 문제없다 — `chat_wiki.py`의 `_citation_source_label`이 `document_title`/`source_name`/`published_at`을 사람이 읽는 문자열로 조합하는데, 이 필드들은 `db.list_message_citations()`(`_enrich_message_citations`)가 웹/문서 구분 없이 이미 균일하게 채워준다. 막히는 지점은 오직 `wiki_page_sources`에 근거 행을 **영속화**하는 단계다.

**범위 밖**: LLM 일반지식 폴백(출처 없는 답변)의 저장 허용 여부는 건드리지 않는다 — 멘토가 명시적으로 요청한 기존 정책 그대로 유지. 여러 턴의 대화 전체를 하나의 위키 문서로 저장하는 기능도 범위 밖(사용자가 브레인스토밍에서 확인 — 웹검색 근거 저장 버그 수정만 원함).

## 목표

1. 웹검색/DART 근거로 답한 메시지를 "위키에 저장"하면 실패 없이 저장된다.
2. 저장된 위키 페이지의 "근거 출처" 패널에 웹 근거도 (제목 · 날짜, 클릭 시 원문 이동) 형태로 나타난다 — 문서 근거와 같은 목록에서 함께 보인다.
3. 문서 근거의 기존 동작(라이브 조인으로 제목·매체명·게시일·개별 신뢰도 표시)은 그대로 유지한다 — 웹 근거 지원이 기존 경로를 퇴화시키지 않는다.
4. `document_version_id`도 `source_url`도 없는 근거 행은 DB 레벨에서 막는다(잘못된 빈 근거가 조용히 저장되는 일이 없게).

## 아키텍처

### DB 스키마 변경 (`wiki_page_sources`)

`message_citations`가 이미 웹/문서 근거를 균일하게 다루려고 쓰고 있는 정확히 같은 패턴을 재사용한다(라이브 DB 확인 결과 `message_citations`도 이미 `document_version_id` nullable + `source_url`/`source_title`/`published_at`(TEXT) 컬럼을 갖고 있다 — `docs/architecture/myWiki_v2.sql`의 문서화가 이 부분에서 이미 실제 스키마보다 낡아 있었다, 이번 작업에서 같이 바로잡는다).

```sql
ALTER TABLE wiki_page_sources ALTER COLUMN document_version_id DROP NOT NULL;
ALTER TABLE wiki_page_sources ADD COLUMN source_url TEXT;
ALTER TABLE wiki_page_sources ADD COLUMN source_title TEXT;
ALTER TABLE wiki_page_sources ADD COLUMN published_at TEXT;
ALTER TABLE wiki_page_sources ADD CONSTRAINT wiki_page_sources_has_reference
  CHECK (document_version_id IS NOT NULL OR source_url IS NOT NULL);
```

`published_at`을 TEXT로 두는 것도 `message_citations`와 맞춘다(citation 쪽이 이미 ISO 문자열을 그대로 저장하는 관례라, 타입을 갈라놓으면 두 테이블 간 값 이동 시 변환이 필요해진다).

### 백엔드 — 쓰기 경로 (`save_message_to_wiki`, `src/api/main.py`)

`db.list_message_citations(message_id)`가 반환하는 각 citation 딕셔너리는 이미 `document_version_id`/`document_title`/`source_url`/`published_at`을 웹·문서 구분 없이 균일하게 채워서 준다(`_enrich_message_citations`가 문서 근거는 조인으로, 웹 근거는 저장 시점 값을 그대로 통과시켜서 채움 — 기존 로직, 변경 없음). `WikiSourceInput` 생성부만 이 필드들을 추가로 넘기도록 바꾼다:

```python
sources=[
    WikiSourceInput(
        document_version_id=c["document_version_id"],
        source_url=c.get("source_url"),
        source_title=c.get("document_title"),
        published_at=c.get("published_at"),
        claim_text=c.get("quoted_text") or "",
        source_start_line=c.get("source_start_line"),
        source_end_line=c.get("source_end_line"),
        support_type="supports",
        citation_order=c.get("citation_order"),
    )
    for c in citations
],
```

`WikiSourceInput`(`src/wiki/interface.py`)은 `document_version_id: str` → `Optional[str] = None`으로 바꾸고 `source_url`/`source_title`/`published_at: Optional[str] = None` 3개 필드를 추가한다.

### 백엔드 — 읽기 경로 (`_enrich_sources`, `src/wiki/query.py`)

지금은 모든 행의 `document_version_id`가 존재한다고 가정하고 무조건 `document_versions`/`documents`/`sources`/`document_analysis_results`를 조인한다. 이걸 `document_version_id is not None`인 행만 조인 대상에 넣도록 바꾸고, 조인 후 각 행을 `WikiSource`로 조립할 때:

- `document_version_id`가 있으면: 지금과 동일하게 라이브 조인 결과(제목·매체명·게시일·신뢰도)를 쓴다.
- `document_version_id`가 없으면: 저장된 `source_url`/`source_title`/`published_at`을 그대로 쓰고 `source_name=None`, `reliability_score=None`(매체명·신뢰도 개념이 없음).

`WikiSource`(`src/wiki/interface.py`)의 `document_version_id: str`도 `Optional[str] = None`으로 바꾼다. `canonical_url`/`document_title`/`published_at` 필드는 이미 있으므로 새 필드 추가 없이 그대로 재사용한다(웹 근거의 `canonical_url`에 `source_url` 값을 채우는 식).

### 프론트엔드

**변경 없음.** `WikiPage.jsx`의 "근거 출처" 렌더링(`services/wikiApi.js`가 `canonical_url`→`url`, `document_title`→`title`, `source_name`→`sourceName`으로 매핑)이 이미 `sourceName`/`url` 없음을 정상 처리하도록 짜여 있다(`{s.sourceName ? ...: ''}`, `url`이 없으면 비활성 링크로 표시). 백엔드가 올바른 모양으로 채워 보내기만 하면 그대로 동작한다.

### ERDCloud / docs 동기화

`wiki_page_sources` 테이블에 관계선(FK) 변경(선택적 관계로), 컬럼 3개 추가를 ERDCloud에 반영하고 `docs/architecture/myWiki_v2.sql`도 같이 갱신한다. 겸사겸사 이번에 발견한 `message_citations`의 기존 문서-실제 스키마 불일치(`qmd_uri`만 있고 `source_url`/`source_title`/`published_at`이 빠져 있던 것, `document_version_id` nullable 여부)도 같이 바로잡는다.

## 에러 처리

- CHECK 제약(`document_version_id IS NOT NULL OR source_url IS NOT NULL`)이 최후 방어선 — 애플리케이션 코드가 실수로 빈 근거 행을 만들려 해도 DB가 거부한다.
- 기존 citations 빈 배열 검증(`if not citations: raise 400`)은 그대로 유지 — 이번 변경과 무관.

## 테스트

- `WikiSourceInput`/`WikiSource`: `document_version_id=None`이어도 생성되는지(dataclass이므로 타입 자체는 런타임 강제 안 되지만, `Optional`로 바뀐 시그니처가 의도를 명확히 하는지 확인하는 테스트 포함)
- `save_message_to_wiki`: 웹 근거만 있는 citations로 저장 시 `WikiSourceInput`이 `source_url`/`source_title`/`published_at`을 포함해서 만들어지는지(기존 `tests/test_chat_sessions.py`의 저장 테스트 패턴 확장)
- `_enrich_sources`: `document_version_id=None`인 행이 섞여 있을 때 (a) 문서 조인 쿼리에 그 행의 None이 안 들어가는지(조인 쿼리 자체가 죽지 않는지), (b) 결과 `WikiSource`가 저장된 `source_url`/`source_title`/`published_at`을 그대로 반영하는지, (c) 문서 근거 행은 기존처럼 라이브 조인 값을 쓰는지(회귀 확인)
- 통합: 웹 근거 citation → `save_message_to_wiki` → `_enrich_sources`까지 왕복해서 프론트가 받는 `WikiSourceOut` 모양이 기대한 그대로인지(`document_version_id: null, canonical_url: <웹 URL>, source_name: null`)

## 영향받는 파일

| 파일 | 변경 |
|---|---|
| Supabase 마이그레이션(신규) | `wiki_page_sources` 컬럼 추가 + nullable 변경 + CHECK 제약 |
| `src/wiki/interface.py` | `WikiSourceInput`/`WikiSource`의 `document_version_id` optional화 + 신규 필드 |
| `src/api/main.py` | `save_message_to_wiki`의 `WikiSourceInput` 생성부 |
| `src/wiki/query.py` | `_enrich_sources`가 `document_version_id is None`인 행을 분기 처리 |
| `tests/test_chat_sessions.py`, `tests/test_wiki_query.py` | 갱신 |
| ERDCloud + `docs/architecture/myWiki_v2.sql` | `wiki_page_sources` 갱신, `message_citations` 기존 불일치도 같이 정정 |

프론트엔드 코드 변경 없음.

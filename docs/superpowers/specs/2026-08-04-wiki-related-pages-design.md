# 위키 간 "연결된 문서"(관련 위키) 설계

## 배경

WikiPage.jsx 화면의 "연결된 문서" 섹션은 항상 0건으로 표시된다. 원인은 데이터 부족이
아니라 미구현: `frontend/src/services/wikiApi.js`의 `toDoc()`이 `links: []`를
하드코딩하고 있고, DB에도 위키-위키 관계를 표현하는 테이블이 없다. 존재하는 위키
테이블은 `wiki_pages`(계층은 `parent_page_id`뿐), `wiki_page_versions`,
`wiki_page_sources`(위키 주장 ↔ 원문 근거) 세 개뿐이다.

## 목표

두 위키가 같은 원문(evidence)을 근거로 인용하고 있으면 서로 "관련 위키"로 보여준다.
별도 관계 테이블 없이 기존 `wiki_page_sources` 데이터만으로 조회 시점에 계산한다.

## 연결 기준

**공유 근거 문서**: 위키 A와 B가 `wiki_page_sources.document_version_id`를 하나 이상
공유하면 관련 위키로 간주한다. 공유 원문 개수가 많은 위키부터 상위 5개까지만 노출한다.

## 계산 로직 (조회 시점 즉석 계산, 별도 테이블/배치 없음)

`src/wiki/query.py`의 `get_published_wiki_page()` 안에서, 이미 조회한 현재 페이지의
`sources`(document_version_id 목록)를 재사용해 다음 순서로 계산한다:

1. `wiki_page_sources`에서 그 `document_version_id`들을 인용하면서
   `wiki_version_id != 현재 version_id`인 행을 조회한다.
2. `wiki_version_id`별로 공유 `document_version_id`를 **집합(set)**으로 모은다 —
   같은 원문을 여러 주장(claim)에서 인용해도 1건으로만 카운트한다.
3. 그렇게 모인 `wiki_version_id` 후보들 중 실제로 어떤 위키의
   **현재 게시 버전(`wiki_pages.current_version_id`)**인지 확인한다. 수정으로 밀려난
   구버전은 이 필터에서 자연히 제외된다. `status='published'`, `workspace_id` 일치,
   현재 페이지 자신 제외 조건도 함께 건다.
4. 공유 원문 개수 내림차순 정렬 후 상위 5개만 반환한다.

## 데이터 흐름 / 변경 파일

- **`src/wiki/interface.py`**: `WikiRelatedPage` dataclass 신설
  (`page_id, slug, title, page_type, shared_source_count`). `WikiPageContent`에
  `related_pages: tuple[WikiRelatedPage, ...]` 필드 추가.
- **`src/wiki/query.py`**: `_get_related_pages(db, workspace_id, current_page_id,
  current_version_id, document_version_ids, limit=5)` 헬퍼 추가. `get_published_wiki_page()`
  리턴값에 `related_pages` 포함.
- **`src/api/schemas.py`**: `WikiRelatedPageOut(BaseModel)` 추가
  (`from_attributes=True`), `WikiPageContentOut.related_pages: list[WikiRelatedPageOut]`
  추가. `src/api/wiki_router.py`는 `response_model` 자동 변환이라 수정 불필요.
- **`frontend/src/services/wikiApi.js`**: `toDoc()`의 `links: []` 하드코딩을
  `content.related_pages`를 `{id: slug, title, desc}`로 매핑하는 코드로 교체.
  `desc`는 `· 공유 근거 N건 · <카테고리 라벨>` 형태.
- **`frontend/src/pages/WikiPage.jsx`**: 이미 `doc.links`를 렌더링하고 클릭 시
  `setCurrent(l.id)`로 이동하는 로직이 있음 — 수정 불필요.

## 엣지 케이스

- 근거 문서가 없는 위키(신규 생성/근거 부족): `related_pages`가 빈 배열 — 지금처럼
  "연결된 문서 0건"으로 정상 표시(에러 아님).
- 공유 원문은 있지만 상대 위키가 아직 `published` 상태가 아니거나 최신 버전이 아닌 경우:
  후보에서 제외(3단계 필터).
- 자기 자신은 항상 제외(`current_version_id` 비교 + `page_id` 비교로 이중 방지).

## 테스트 계획

- `src/wiki/query.py`: `_get_related_pages()` 단위 테스트 — 공유 문서 있음/없음,
  구버전 제외, 상위 5개 제한, 자기 자신 제외 케이스.
- `src/api/schemas.py`: `WikiPageContentOut`이 `related_pages`를 포함해 정상
  직렬화되는지 확인(기존 wiki API 테스트에 필드 추가 검증).
- 프론트: `toDoc()` 매핑 결과가 `WikiPage.jsx`가 기대하는 `{id, title, desc}` shape과
  맞는지 확인.
- 라이브 검증: 실제 워크스페이스 데이터로 API를 호출해 두 위키가 공유 근거로 실제
  연결되어 표시되는지 확인.

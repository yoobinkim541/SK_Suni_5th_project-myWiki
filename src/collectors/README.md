# src/collectors — 데이터 수집 담당

구현 근거: **데이터 파이프라인 인터페이스 명세 v1.1** (§3-1, §3-2)
스켈레톤과 시그니처가 다르면 명세가 우선한다 (명세 §1-1).

## 담당 테이블
- `sources` — 뉴스/RSS/공시/웹사이트 등 수집 출처 등록·설정
- `documents` — 수집한 문서의 메타데이터 (아직 정제 전)
- `pipeline_jobs` (`job_type='collect'`) — 수집 작업 상태 기록

> `document_versions`는 **이 파트가 만들지 않는다.** 정제(`preprocessing`)가 만든다.
> 스켈레톤 README의 "새 문서는 `documents` + `document_versions`(raw 단계)에 기록한다"는
> 명세 §3-2로 대체됐다.

## 참고 자료
- `docs/architecture/myWiki_v2_supabase.sql` — 위 테이블 정확한 컬럼/제약조건
- `docs/architecture/myWiki_v2_snapshot.json` — ERD (erdcloud로 열람 가능)

## DB 접속 (2026-07-30 팀 결정)
배치에는 로그인 사용자가 없어 RLS(`is_workspace_member` 기준)를 통과할 수 없다.
`SUPABASE_SERVICE_ROLE_KEY`로 RLS를 우회하고, 모든 쿼리에 `workspace_id`를 애플리케이션 코드에서
직접 필터링하는 방식으로 통일한다 — `src/api/db.py`, `src/wiki/query.py`와 동일한 패턴.
배치 전용 계정을 따로 만들어 `workspace_members`에 등록하는 방식(RLS 적용)은 채택하지 않는다.

> 구현에서는 `src/pipeline_common/db.py`가 이 접속을 담당하고,
> `workspace_id` 필터는 `src/pipeline_common/repository.py` 한 곳에 모여 있다.

## 이 파트가 해야 하는 일
1. GeekNews / 구글 RSS / 네이버 검색 API 등에서 반도체·SK하이닉스 관련 원문을 가져온다.
2. `sources`에 등록된 출처 기준으로 수집하고, 새 문서는 `documents`에 기록한다.
   (`document_versions`는 정제 단계에서 만든다 — 명세 §3-2)
3. `canonical_url` 기준으로 이미 있는 문서면 새로 만들지 않는다 (중복 방지는 `UQ_DOCUMENTS_WORKSPACE_URL` 제약이 최종 방어선이지만, API 호출 자체를 줄이려면 여기서도 먼저 체크하는 게 좋다).
4. 수집 실패/재시도는 `pipeline_jobs`에 상태(`pending/running/completed/failed`)로 남긴다.

## 공개 함수

| 함수 | 위치 | 설명 |
|---|---|---|
| `register_source(workspace_id, name, source_type, base_url=None, config=None) -> UUID` | `interface.py` | 출처 등록. 이미 있으면 기존 id 반환 (upsert 금지) |
| `collect(request: CollectRequest) -> list[CollectedDocument]` | `interface.py` | 원문 수집 + `documents` 행 + `raw` 업로드 |
| `get_markdown` · `get_document_refs` | `pipeline_common/refs.py` | 하류 조회 헬퍼 (명세 §3-6, §3-7). 편의를 위해 이 패키지에서도 re-export |

## 모듈 구성

```
src/collectors/
    interface.py   register_source / collect
    fetchers.py    source_type -> 수집기 매핑 (rss / news / website)
src/pipeline_common/
    constants.py   상태값 상수 (명세 §0) — 다른 파트도 이걸 import한다
    models.py      데이터 계약 (명세 §2)
    db.py          Supabase 클라이언트(service_role) 주입 지점
    storage.py     버킷 경로 규칙 (명세 §6)
    repository.py  DB 접근 계층 — 스키마 변경 시 여기만 고친다
    jobs.py        pipeline_jobs 기록 (명세 §4-4, §5-2)
    versioning.py  next_document_version_no (명세 §3-5)
    refs.py        get_markdown / get_document_refs (명세 §3-6, §3-7)
```

## 동작 요약

1. 소스 단위 job을 `running`으로 연다 (`target_type=NULL` — `ck_pj_target_type`에 `source`가 없다).
2. `sources.enabled`와 `workspace_id`를 확인한다. 어긋나면 job `cancelled` + 빈 리스트.
3. `source_type`에 맞는 수집기로 원문을 가져온다. 소스 접근 실패는 job `failed` + 빈 리스트.
4. 문서 1건마다 — `raw_object_key` 경로 구성 순서는 스켈레톤 주석 그대로다
   1. `documents` 행을 INSERT 또는 조회해 `document_id` 확보
      (`canonical_url`이 없으면 문서를 만들지 않고 `result.skip_reasons`에 사유를 쌓는다.
      `(workspace_id, canonical_url)`로 SELECT → 없으면 INSERT, 있으면 기존 행 재사용.
      `title`·`published_at`이 실제로 달라졌을 때만 UPDATE한다)
   2. `next_document_version_no(document_id)`로 `next_ver` 계산
   3. `raw/{workspace_id}/{document_id}/{next_ver}.{ext}`에 파일 업로드
   4. `CollectedDocument.raw_object_key`와 문서 단위 job의 `result.raw_object_key`에 경로 저장
      — **정제는 이 값을 그대로 인계받는다** (경로를 재계산하지 않는다, 명세 §6-2)
5. 소스 단위 job을 `completed`로 닫는다 (`collected`/`skipped`/`failed`/`skip_reasons`).

예외를 던지지 않는다. 실패는 전부 `pipeline_jobs`에 남는다 (명세 §1-3).

## 수집기 추가

```python
from src.collectors import fetchers

def fetch_dart(source: dict, request) -> fetchers.FetchOutcome: ...
fetchers.register_fetcher("disclosure", fetch_dart)
```

기본 제공: `rss`(GeekNews·구글 RSS) · `news`(네이버 검색 API) · `website`(단일 페이지).
`disclosure`(DART) 추가 여부는 지침 §9-C-4에서 결정 대기 중이다.

`sources.config`(JSONB)에서 읽는 키는 `fetchers.py` 상단 주석 참조.
스키마 확정 전이라 `config/sources.yaml` 분리는 아직 하지 않았다 (지침 §9-A-3).

## 환경변수

| 변수 | 용도 |
|---|---|
| `SUPABASE_URL` · `SUPABASE_SERVICE_ROLE_KEY` | 배치 접속 (위 "DB 접속" 절) |
| `NAVER_CLIENT_ID` · `NAVER_CLIENT_SECRET` | `source_type='news'` 수집기를 쓸 때만 |

배치 진입점에서 `workspace_id`를 1회 확보해 모든 함수에 인자로 넘긴다.
전역 상수로 두지 않는다 (명세 §4-5). 실제 UUID는 아직 공유 전이다 (지침 §9-B-3).

## 필요 패키지

`requirements.txt`에 추가돼 있다. 기존 항목은 건드리지 않고 아래 6개만 덧붙였다.

| 패키지 | 용도 |
|---|---|
| `httpx>=0.27` | 외부 소스 HTTP 요청 |
| `feedparser>=6.0` | RSS/Atom 파싱 (GeekNews·구글 RSS) |
| `beautifulsoup4>=4.12` | HTML 노이즈 제거 (표준 `html.parser` 사용 → `lxml` 불필요) |
| `markdownify>=0.13` | HTML → Markdown 변환 |
| `pytest>=8.0` | 테스트 |

`pypdf`는 **일부러 넣지 않았다.** MVP 소스 3종(GeekNews·구글 RSS·네이버)에 PDF가 없고,
`cryptography` 의존성 때문에 환경에 따라 설치가 막힌다. `parsers._parse_pdf`는 지연
import이고, 없으면 `ParseError`로 사유를 남기므로 다른 소스 수집에는 영향이 없다.
PDF 소스를 실제로 붙일 때 추가한다.

무거운 라이브러리는 전부 함수 안에서 지연 import한다. 그래서 RSS만 쓰는 배치는
`pypdf` 없이도 돌고, 테스트는 `supabase` 패키지 없이도 돈다.

## 테스트

```bash
pip install httpx feedparser beautifulsoup4 markdownify pytest
python -m pytest tests/pipeline
```

`tests/pipeline/fake_supabase.py`가 정본 SQL의 UNIQUE 제약을 흉내내므로 실제 DB 없이 돈다.
다른 파트 테스트에 영향을 주지 않도록 픽스처는 `tests/pipeline/` 안에만 둔다
(공용 `tests/conftest.py`를 만들지 않는다).

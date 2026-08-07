# 위키 페이지 연동 키워드 생성 + 키워드 기반 검색/필터 설계

## 배경

위키 페이지 목록/사이드바에서 키워드 칩을 눌러 "그 키워드를 가진 위키 페이지들만" 추려 보는 기능을 앞으로 프론트에 추가할 예정이다. 이번 스펙은 그 프론트 기능이 붙기 전에 백엔드(키워드 생성 + 검색/필터 API)를 먼저 만드는 것만 다룬다.

(참고: 프론트에는 이미 별개로 설계된 "본문 단어 클릭 → 공시·IR 원문/뉴스기사 모달" 기능(`WikiKeywordModal.jsx`, `GET /api/wiki/keywords/{word}` 계약)이 있는데, 이번 스펙은 그것과 다른 기능이다 — 이번 건 위키 "목록"을 키워드로 좁혀 보는 기능이고, 그 모달 기능은 이번 범위 밖이다.)

## 목표

1. 모든 위키 페이지(이슈/토픽/챗봇 저장 페이지 전부, 기존 페이지 포함)에 키워드가 채워진다.
2. 키워드는 `src/categories/keywords.py`의 기존 122개 사전에서만 선택된다(자유 텍스트 아님) — 카테고리 분류 프롬프트와 같은 체계를 재사용.
3. 키워드로 위키 페이지 목록을 조회/필터할 수 있는 API가 생긴다.

## 비목표

- 프론트엔드 필터 UI 구현 — 이번 스펙은 백엔드만.
- `WikiKeywordModal.jsx`(본문 단어 클릭 → 공시/뉴스 모달) 기능 — 별개 기능, 이번 범위 아님.
- 위키 페이지 생성 로직(`generation.py`, `chat_wiki.py`) 자체를 수정해 생성 시점에 키워드를 바로 끼워넣는 것 — 대신 아래 아키텍처에서 설명하는 별도 배치로 처리(비목표로 명시하는 이유는 "왜 생성 경로 3곳을 안 건드렸는지" 헷갈리지 않게 하기 위함).

## 아키텍처

새 정규화 테이블 + 별도 배치 잡으로 구성한다. 페이지 생성 로직(이슈/토픽/챗봇 저장, 3곳)은 건드리지 않고, `wiki-dedup-batch`/`citation_id_cleanup.py`와 같은 구조의 독립 배치가 "키워드 없는 published 페이지"를 찾아 채운다 — 기존 페이지 백필과 신규 페이지 커버를 같은 메커니즘으로 처리한다.

```
src/wiki/keyword_prompts.py (신규)
├── WIKI_KEYWORD_SYSTEM_PROMPT — 122개 사전을 전부 나열하고 "이 목록에서만 골라라" 지시
└── build_wiki_keyword_user_prompt(markdown) -> str

src/wiki/keyword_batch.py (신규)
├── WikiKeywordLLMResult(BaseModel): keywords: list[str]
├── find_pages_missing_keywords(workspace_id) -> list[dict]  # id, slug, title, markdown
├── extract_keywords_for_page(markdown, *, llm_client=None) -> list[str]
│     LLM 호출 → parse_json_response → 122개 사전에 있는 값만 남기고 필터링(사전 밖 값은
│     버림, 최대 8개로 자름) → 결과가 0개면 빈 리스트(정상 케이스, 매칭 안 될 수 있음)
└── run_wiki_keyword_batch(workspace_id) -> WikiKeywordBatchResult
      find_pages_missing_keywords로 대상 조회 → 페이지별 extract_keywords_for_page →
      wiki_page_keywords에 insert. 페이지 하나가 LLM 실패로 예외를 던지면 그 페이지만
      건너뛰고(로그 남김) 다음 페이지 계속 진행 — 한 페이지 실패가 배치 전체를 막지 않음
      (다음 배치 실행 때 여전히 "키워드 없음" 상태라 자동 재시도됨).

scripts/wiki_keyword_batch_scheduled.py (신규)
  scripts/dedup_wiki_scheduled.py와 동일한 뼈대(get_workspace_id 단일 워크스페이스 가정,
  run_wiki_keyword_batch 호출, 결과 로그 후 exit code).

.github/workflows/wiki-keyword-batch.yml (신규)
  wiki-dedup-batch.yml과 동일 패턴: 매일 1회 cron + workflow_dispatch.
```

`extract_keywords_for_page`의 LLM 호출은 `analysis/classifier.py`의 `create_json_completion`/`get_openrouter_settings()`를 그대로 재사용한다(새 모델 설정 없음, 기존 v4-flash/v4-pro 폴백 그대로).

## 데이터 모델

```sql
CREATE TABLE wiki_page_keywords (
    id          UUID          NOT NULL DEFAULT gen_random_uuid(),
    page_id     UUID          NOT NULL REFERENCES wiki_pages(id),
    keyword     VARCHAR(50)   NOT NULL,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (page_id, keyword)
);
CREATE INDEX idx_wiki_page_keywords_keyword ON wiki_page_keywords(keyword);
```

`keyword`는 항상 `CATEGORY_KEYWORDS`(122개) 중 하나. `UNIQUE(page_id, keyword)`로 같은 페이지에 같은 키워드가 중복 저장되지 않는다. `wiki_pages`/`wiki_page_sources`처럼 정규화된 형태를 쓴다(배열 컬럼 대신) — "이 키워드를 가진 페이지 전부" 조회가 검색 기능의 핵심 접근 패턴이라 인덱스가 걸리는 별도 테이블이 맞다.

## API 변경

### `GET /wiki/pages` (기존 엔드포인트 확장)

`src/wiki/query.py`의 `list_published_wiki_pages()`에 `keyword: Optional[str]` 파라미터 추가. 지정되면:
1. `wiki_page_keywords`에서 `keyword` 일치하는 `page_id` 목록을 먼저 조회(기존 `_enrich_sources`/`_enrich_message_citations`와 같은 순차 조회 관례 — embedded join 안 씀).
2. `wiki_pages` 쿼리에 `.in_("id", page_ids)` 추가.
3. 매칭되는 페이지가 없으면 빈 리스트(에러 아님).

`src/api/wiki_router.py`의 `list_pages()`에 동일하게 `keyword: Optional[str] = Query(default=None)` 추가해 그대로 전달.

### `GET /wiki/keywords` (신규)

워크스페이스 안에서 실제로 쓰이고 있는 키워드 목록 + 건수. 프론트가 필터 칩 바를 그릴 때 씀(어떤 칩을 보여줄지는 실제 사용 중인 키워드만).

```
Response: [{"keyword": "HBM", "count": 12}, {"keyword": "수출통제", "count": 5}, ...]
```

`published` 상태 페이지에 걸린 키워드만 집계(draft/pending 페이지는 아직 사용자에게 안 보이므로 제외) — `wiki_page_keywords`를 `wiki_pages.status = 'published'`인 페이지로 필터링 후 `keyword`별 group by count. 건수 내림차순 정렬.

## 에러 처리

- 배치 실행 중 개별 페이지의 LLM 호출/파싱 실패 → 그 페이지만 skip, 로그 남기고 계속(위 아키텍처 섹션 참고). 배치 전체가 실패로 끝나는 경우는 모든 페이지가 실패했을 때뿐(기존 `dedup_wiki_scheduled.py`의 exit code 관례와 동일).
- LLM이 122개 사전 밖의 값을 반환 → 그 값만 버리고 나머지는 정상 채택(페이지 전체를 스킵하지 않음).
- LLM이 빈 배열을 반환(본문에 사전 키워드가 하나도 안 맞음) → 정상 케이스로 처리, 빈 채로 저장하지 않고 다음 배치에서 재시도(즉, "키워드 0개 매칭"과 "아직 처리 안 됨"을 구분 안 함 — `wiki_page_keywords`에 행이 없으면 둘 다 "미처리"로 보고 매 배치마다 재시도. 실제로 122개 중 하나도 안 걸리는 페이지가 있다면 배치가 매번 그 페이지를 재시도하며 LLM을 낭비하게 되는데, 발생 빈도를 보고 필요하면 후속으로 "빈 결과였음"을 구분하는 표시를 추가할 수 있음 — 최초 버전에서는 단순함을 우선).

## 테스트

- `tests/test_wiki_keyword_prompts.py`(신규): 프롬프트에 122개 사전이 전부 포함되는지, user prompt에 markdown이 들어가는지.
- `tests/test_wiki_keyword_batch.py`(신규): `extract_keywords_for_page` — 정상 케이스(사전 안 값만 매칭), 사전 밖 값 필터링, 8개 초과 시 자르기, LLM 예외 시 해당 페이지 skip 하고 배치 계속 진행.
- `tests/test_wiki_query.py` 또는 기존 쿼리 테스트 파일: `list_published_wiki_pages`의 `keyword` 필터 — 매칭 있음/없음 케이스.
- `tests/test_wiki_router.py`: `GET /wiki/pages?keyword=`, `GET /wiki/keywords` 응답 형식.

## 영향받는 파일

| 파일 | 변경 |
|---|---|
| `src/wiki/keyword_prompts.py` | 신규 |
| `src/wiki/keyword_batch.py` | 신규 |
| `scripts/wiki_keyword_batch_scheduled.py` | 신규 |
| `.github/workflows/wiki-keyword-batch.yml` | 신규 |
| `src/wiki/query.py` | `list_published_wiki_pages`에 `keyword` 파라미터 추가 |
| `src/api/wiki_router.py` | `GET /wiki/pages`에 `keyword` 쿼리 파라미터 추가, `GET /wiki/keywords` 신규 |
| `tests/test_wiki_keyword_prompts.py` | 신규 |
| `tests/test_wiki_keyword_batch.py` | 신규 |
| 기존 wiki 쿼리/라우터 테스트 파일 | keyword 필터/신규 엔드포인트 테스트 추가 |
| `supabase/migrations/` | `wiki_page_keywords` 테이블 생성 마이그레이션 신규 |
| ERDCloud | `wiki_page_keywords` 테이블 + `wiki_pages` 관계선 추가 ([[feedback-docs-sync]]) |

프론트엔드 변경 없음.

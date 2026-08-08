# DART 공시 실시간 조회 설계

**작성일:** 2026-08-09
**선행 기능:** `docs/superpowers/specs/2026-08-08-web-search-grounded-answer-design.md` (3단계 웹 검색 그라운딩, `develop`에 이미 병합됨)

## 배경

3단계(웹 검색, "웹에서 찾아줘")는 네이버 뉴스만 실시간으로 찾는다. DART 공시는 예약 수집 파이프라인이 주기적으로 긁어다 `documents` 테이블에 넣어둔 것만 2단계(원문 그라운딩)에서 검색된다 — 아주 최신 공시(파이프라인이 아직 못 돈 것)는 뉴스로도 안 다뤄지면 3단계까지 가도 못 찾는다. 실제로 라이브 테스트 중 이런 케이스(SK하이닉스 독립이사 자사주 지급 관련 질문)가 나왔다 — 관련 뉴스 기사는 있었지만 그라운딩에 실패했고, DART 원문 자체는 애초에 조회할 방법이 없었다.

이번 기능은 3단계에 "DART를 그 자리에서 직접 조회하는" 도구를 추가해서 이 공백을 메운다.

## DART Open API 제약

- 자유 검색어를 지원하지 않는다 — `corp_code`(회사 고유번호 8자리) + 날짜 범위로 그 회사의 공시 **목록**(제목·접수번호·날짜)만 얻을 수 있다.
- 본문은 목록에 없다 — 접수번호(`rcept_no`)로 `document.xml`을 따로 호출해야 한다(zip으로 옴, 압축 해제하면 HTML).
- 기존 파이프라인 수집기(`src/collectors/fetchers.py::fetch_disclosure`, `_fetch_disclosure_document`)가 이미 이 두 호출을 쓰고 있다 — 로직은 참고하되, 파이프라인 전용 부분(`RawFetchResult`, source dict config, `CollectRequest`)은 빼고 가볍게 새로 짠다(네이버 실시간 검색을 만들 때 `fetch_naver_news`를 그대로 안 쓰고 `web_search.py`를 새로 만든 것과 같은 이유).

## 도구 구조 — 검색+읽기 2단계

```python
def search_recent_disclosures(days: int = 14) -> list[DisclosureHit]:
    """워크스페이스에 등록된 모든 disclosure 소스(회사)의 최근 N일 공시 제목 목록."""

@dataclass
class DisclosureHit:
    rcept_no: str
    report_name: str
    corp_name: str
    published_at: str | None

def read_disclosure(rcept_no: str) -> DisclosureDetail | None:
    """공시 1건의 실제 본문."""

@dataclass
class DisclosureDetail:
    rcept_no: str
    report_name: str
    corp_name: str
    markdown: str
    canonical_url: str
    published_at: str | None
```

원문 그라운딩(`search_documents`→`read_document`)과 같은 2단계 패턴이다 — 목록에서 제목만 보고 관련 있어 보이는 걸 모델이 골라서 읽는다.

**lookback 기본값 14일**: 파이프라인 수집기의 `DEFAULT_DART_LOOKBACK_DAYS=30`보다 짧게 잡는다 — 이 도구의 존재 이유가 "파이프라인이 아직 못 돈 최신 공시"를 메꾸는 것이라, 이미 파이프라인이 커버하는 30일 전체를 매번 다시 긁을 필요가 없다.

## 회사 범위(corp_code) — 하드코딩하지 않음

`sources` 테이블에서 해당 workspace의 `source_type='disclosure'`인 행 전부를 조회해 그 `config.corp_code` 목록을 쓴다(지금은 `DART - SK하이닉스` 하나, `corp_code: "00164779"`). 회사가 늘어나도 `sources`에 등록만 하면(이번에 고친 `scripts/register_sources.py`의 `DART_COMPANIES` 참고) 코드 변경 없이 확장된다. `search_recent_disclosures`는 등록된 회사 전부를 순회해서 합친 목록을 반환한다.

## 에이전트 배선

`src/agent/core.py`의 `WEB_SEARCH_TOOLS`에 도구 2개를 추가한다(기존 `search_web`과 나란히, `_SUBMIT_ANSWER_TOOL`/`_SUBMIT_NO_ANSWER_TOOL`은 그대로 공유). `_web_search_answer()`의 `tool_handlers`에 `handle_search_recent_disclosures`/`handle_read_disclosure`를 추가하고, `seen_identifiers`에 `rcept_no` 대신 **`canonical_url`(DART 뷰어 URL)을 추가한다** — 이게 다음 섹션의 핵심이다.

`WEB_SEARCH_ANSWER_SYSTEM_PROMPT`에 "질문이 공시성 내용(실적, 지분, 계약 등)이면 search_recent_disclosures도 같이 시도해라" 같은 안내를 한 줄 추가한다.

## 인용 처리 — 스키마 변경 없음

DART 조회 결과는 `document_version_id`가 없다(DB 문서가 아니므로). **이미 웹 검색용으로 만들어둔 `Citation.source_url`/`source_title`/`source_published_at` 필드를 그대로 쓴다** — `source_url`에 DART 뷰어 주소(`https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}`, 기존 `fetchers.py::DART_VIEWER_URL`과 동일한 형태)를 넣으면, `_is_grounded`/`message_citations`/프론트 "웹 검색" 배지까지 전부 손댈 필요 없이 그대로 동작한다. 프론트에서 "웹 검색"이라고만 뜨는 게 부정확하다고 느껴지면(DART 원문인데 "웹 검색"으로 라벨링됨) 그건 이번 스펙 범위 밖 — 필요하면 나중에 `source_url` 도메인(`dart.fss.or.kr`)으로 프론트가 구분하는 걸 검토한다.

## 에러 처리

- `DART_API_KEY` 없음/API 호출 실패 → 예외 → 다른 도구 핸들러와 동일하게 `_run_grounded_answer`가 잡지 않고 그대로 전파 → `_web_search_answer` 밖의 `_safe_run`이 잡아서 4단계로 넘어간다(기존 패턴 그대로, 새 예외 처리 없음).
- 등록된 disclosure 소스가 워크스페이스에 하나도 없으면 `search_recent_disclosures`가 빈 리스트를 반환(예외 아님) — 모델이 `submit_no_answer`로 자연스럽게 처리.
- 공시 목록엔 있는데 `read_disclosure`가 실패(zip 손상 등)하면 `None` 반환 — 그 문서만 건너뛰고 다른 후보 계속 시도(document_search.py의 storage 다운로드 실패 방어와 같은 패턴).

## 새 모듈

`src/pipeline_common/dart_lookup.py`(신규) — `src/collectors`를 참조하지 않는다(레이어 규칙, `web_search.py`/`document_search.py`와 동일 원칙). zip 해제·HTML 추출은 `fetchers.py`의 `_extract_disclosure_html`과 비슷한 로직을 가볍게 새로 짠다.

## 테스트

- `tests/test_pipeline_common_dart_lookup.py`(신규): `httpx.get` monkeypatch로 목록 조회·본문 조회·zip 해제·에러 케이스(자격증명 없음, HTTP 오류, 손상된 zip) 검증. `web_search.py` 테스트 패턴과 동일.
- `tests/test_agent_wiki_tools.py`: `WikiTools.search_recent_disclosures`/`read_disclosure` 위임 테스트.
- `tests/test_agent_core.py`: `_web_search_answer`가 두 도구 다 모델에 넘기는지, DART 근거로 그라운딩된 답변의 citation이 `source_url`(DART 뷰어)로 채워지는지, disclosure 소스가 없는 워크스페이스에서 크래시 없이 빈 목록으로 처리되는지.

## 범위 밖

- 프론트 "웹 검색" 배지를 "공시" 배지로 세분화하는 것 — 스키마 변경 없이 가능하지만 이번 스펙에서는 안 함(별도 논의).
- corp_code를 질문에서 자동 추론하는 것(예: "삼성전자 공시" 같은 미등록 회사 질문) — 등록된 회사만 다룬다.

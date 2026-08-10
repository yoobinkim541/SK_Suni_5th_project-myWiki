# 위키 페이지 신뢰도 자율 판정 + 발행 게이트 설계

## 배경

야간 배치(`generate_wiki_drafts_for_sections`, `src/wiki/generation.py:433`)가 만드는 위키 페이지(이슈 페이지 `_generate_issue_page`, 토픽 페이지 `_generate_topic_page`)는 지금 신뢰도와 무관하게 항상 자동 발행된다. 코드에 이미 그 설계 의도가 명시돼 있다(`generation.py:421-425`):

> "LLM 위키이므로 검증 통과 시 신뢰도와 무관하게 항상 자동 승인·발행한다. confidence_score는 계속 기록해서(표시·분석용) 남기되, 더 이상 발행 여부를 가르는 게이트로는 쓰지 않는다."

실제 발행 게이트(`publish_wiki_version()`, `src/wiki/service.py:222`)는 형식적으로 `validation_status=="passed" AND review_status=="approved"`를 요구하지만, 두 생성 경로 모두 이 값을 무조건 `"passed"`/`"approved"`로 세팅한 뒤 곧바로 발행을 호출한다(`generation.py:259-261`, `426-428`). 사람이 개입해 반려(`review_wiki_version(..., "rejected")`)하는 코드 경로는 저장소 어디에도 없다.

한편 "선정임계값"으로 불리는 `ReportSelectionConfig.min_reliability_score`(`src/report/interface.py:55`, 기본값 20)는 이것과 다른 층위다 — **원문 문서**가 리포트/위키 재료로 쓰일 자격이 있는지만 거르는 입력 단계 필터고, 일단 그 문턱(매우 낮은 20점)을 넘어 위키 초안이 만들어지면 그 이후엔 아무 신뢰도 검사도 없이 발행된다.

문서 단위 신뢰도(`document_analysis_results.reliability_score`, `src/analysis/reliability.py`)는 이미 LLM+기계신호 하이브리드로 정교하게 계산되고 낮음(0-39)/보통(40-69)/높음(70-100) 3단계로 분류되지만(`src/analysis/reliability_models.py:10-20`), 이건 **원문 문서 자체**가 얼마나 믿을 만한지를 보는 것이지 **위키 LLM이 그 원문을 근거로 실제로 쓴 문장**이 원문 범위를 벗어나지 않았는지(할루시네이션 여부)는 아무도 보지 않는다.

## 목표

1. 위키 페이지를 실제로 작성하는 생성 LLM이, 자신이 쓴 페이지 본문을 놓고 신뢰도를 스스로 판정한다(낮음/보통/높음 + 0-100점 + 항목별 근거).
2. 그 판정이 "낮음"이면 사람 개입 없이 그 자리에서 발행을 막는다 — 페이지/버전 row 자체를 DB에 남기지 않는다.
3. "보통"·"높음"은 지금처럼 즉시 자동 발행한다. 사람 검토 단계는 두지 않는다(완전 무인 자동화).
4. 이슈 페이지의 기존 안전장치("LLM 없이도 항상 생성에 성공해야 한다")는 유지한다 — 신뢰도 판정 LLM 호출 자체가 실패하면 "보통"으로 간주하고 그대로 발행한다.
5. 판정 근거(항목별 점수+이유)를 저장해서, 나중에 "왜 이 등급을 받았는지"를 설명 자료로 쓸 수 있게 한다.

**범위**: 야간 배치의 이슈/토픽 페이지 생성 경로만(`_generate_issue_page`, `_generate_topic_page`). 챗봇 "위키에 저장"(`src/api/main.py`)과 dedup 병합 재발행(`src/wiki/dedup.py`)은 건드리지 않는다 — 두 경로 다 지금처럼 무조건 승인·발행을 유지한다.

**범위 밖**: 기존 "선정임계값"(`ReportSelectionConfig.min_reliability_score`)은 그대로 둔다. 이번 판정은 그 뒤 단계(페이지가 이미 다 만들어진 다음)에 새로 추가되는 것이라 서로 겹치지 않는다.

## 아키텍처

### 판정 기준 — 페이지 단위 4개 항목, 가장 중요한 항목에 배점 가중 (합 0-100)

원문 문서 단위 5개 기준(`src/analysis/reliability_prompts.py`)을 그대로 재사용하지 않고, "이미 만들어진 페이지"를 평가하는 데 필요한 것만 4개로 재구성한다. 4개를 균등 배분(각 25점)하지 않고, 가장 핵심적인 `grounding_fidelity`에 다른 항목의 2배를 배정한다:

| 항목 | 배점 | 판단 내용 |
|---|---|---|
| `grounding_fidelity` (근거 반영 충실도) | **0-40** | 본문의 각 주장이 실제로 제공된 근거 문서 범위 안에 있는가, 근거 밖 내용을 추론·과장해서 쓰지 않았는가. 원문 문서 자체의 신뢰도와 무관하게, "LLM이 근거를 벗어나 없는 말을 지어냈는가"를 직접 잡아내는 유일한 항목 — 가장 중요하게 취급하며, 다른 세 항목보다 배점을 2배 크게 둔다. |
| `source_reliability` (근거 문서의 신뢰도) | 0-20 | 이 페이지가 인용한 원문들 자체가 얼마나 신뢰할 만한가. `ReportSectionDraft.reliability_score`(`src/report/models.py:248`, 대표 후보의 `document_analysis_results.reliability_score`를 이미 담고 있음)를 프롬프트에 참고 신호로 그대로 넘겨 LLM이 무시하지 않고 반영하게 한다. |
| `evidence_diversity` (근거의 다양성) | 0-20 | 단일 출처 하나에만 기대는지, 여러 독립된 출처가 같은 내용을 뒷받침하는지. |
| `currency` (정보의 최신성) | 0-20 | 인용한 근거가 최근 것인지, 이미 정정·철회된 정보가 섞여있지 않은지. |

`reliability_score = 4개 항목 합산(최대 40+20+20+20=100)`. `reliability_level`은 기존 `src/analysis/reliability_models.py:16-20`의 `RELIABILITY_LEVELS`/`ReliabilityLevel` Enum(값이 "낮음"/"보통"/"높음" 한글 문자열)을 그대로 import해서 재사용한다 — 새 타입을 만들지 않고 앱 전체에서 같은 3단계 잣대를 쓴다(낮음 0-39/보통 40-69/높음 70-100). 배점이 가장 큰 `grounding_fidelity`가 낮으면 총점도 그만큼 크게 깎여 "낮음" 구간(39점 이하)에 떨어지기 쉬워지므로, 배점 가중이 곧 "근거를 벗어난 페이지는 다른 항목이 아무리 좋아도 통과하기 어렵게" 만드는 실질적 효과로 이어진다.

각 항목에 짧은 `reason`(판정 이유)도 같이 받는다 — "왜 이 등급인지"를 나중에 그대로 보여줄 수 있게.

### 데이터 모델 변경

**`src/wiki/generation_models.py`** — 항목별 배점이 서로 달라서(40/20/20/20) 하나의 공용 스케일을 쓰는 dict 형태 대신, `document_analysis_results`용 `ReliabilityScoreBreakdown`(`src/analysis/reliability_models.py:157-176`)과 같은 방식으로 이름 붙은 필드 + 합계 검증을 쓰는 새 모델을 정의한다:

```python
from ..analysis.reliability_models import ReliabilityLevel, RELIABILITY_LEVELS

class PageReliabilityJudgment(BaseModel):
    grounding_fidelity_score: int = Field(ge=0, le=40)
    grounding_fidelity_reason: str
    source_reliability_score: int = Field(ge=0, le=20)
    source_reliability_reason: str
    evidence_diversity_score: int = Field(ge=0, le=20)
    evidence_diversity_reason: str
    currency_score: int = Field(ge=0, le=20)
    currency_reason: str
    reliability_score: int = Field(ge=0, le=100)
    reliability_level: ReliabilityLevel

    @model_validator(mode="after")
    def validate_total_and_level(self) -> "PageReliabilityJudgment":
        computed = (
            self.grounding_fidelity_score + self.source_reliability_score
            + self.evidence_diversity_score + self.currency_score
        )
        if computed != self.reliability_score:
            raise ValueError("총점이 항목별 점수 합과 일치하지 않습니다.")
        low, high = RELIABILITY_LEVELS[self.reliability_level.value]
        if not (low <= self.reliability_score <= high):
            raise ValueError("reliability_level이 reliability_score 구간과 일치하지 않습니다.")
        return self
```

- `WikiTopicLLMResult`(32행)에 `reliability: PageReliabilityJudgment` 필드를 추가(필수).
- `IssuePageRewriteResult`(63행)에 `reliability: PageReliabilityJudgment | None = None` 필드를 추가(Optional) — 목표 4에 따라 LLM 호출이 실패해 폴백될 때는 이 필드가 채워지지 않는다.

### 프롬프트 변경

**토픽 페이지** (`WIKI_TOPIC_SYSTEM_PROMPT`, `src/wiki/generation_prompts.py:8`): "절대 규칙"에 4개 항목 판정 지시(배점 40/20/20/20 명시)를 추가하고, JSON 출력 형식에 `reliability` 객체(`grounding_fidelity_score`/`grounding_fidelity_reason`/`source_reliability_score`/`source_reliability_reason`/`evidence_diversity_score`/`evidence_diversity_reason`/`currency_score`/`currency_reason`/`reliability_score`/`reliability_level`, `PageReliabilityJudgment`와 1:1 대응)를 추가한다. `build_wiki_topic_user_prompt()`(70행)의 `[이슈 정보]` 블록에 `f"근거 신뢰도(원문 문서 기준): {section.reliability_score}"` 줄을 추가해서 항목 2(source_reliability) 판단 재료를 넘긴다.

**이슈 페이지** (`ISSUE_PAGE_REWRITE_SYSTEM_PROMPT`, `generation_prompts.py:133`): 동일하게 4개 항목 판정 지시 + JSON 출력 필드 추가. `build_issue_page_rewrite_user_prompt()`(156행)에도 같은 근거 신뢰도 줄을 추가한다.

두 프롬프트 모두 "이 페이지가 실제로 근거 문서 범위를 벗어난 서술을 했는지"를 최우선으로 자기 검증하라고 명시한다(grounding_fidelity가 가장 중요하다는 목표 1의 취지를 프롬프트에도 반영).

### 게이트 위치 — DB에 쓰기 전에 판정부터 확인

**토픽 페이지** (`_generate_topic_page`, `generation.py:296`): LLM 결과(`result`)를 파싱한 직후, 기존 skip 체크들(352-356행, `action=="skip"` 또는 빈 markdown)과 같은 자리에 판정 체크를 추가한다:
```python
if result.reliability.reliability_level == ReliabilityLevel.LOW:
    logger.info(
        "wiki_topic_page_skipped_low_reliability",
        extra={"issue_key": section.issue_key, "reliability_score": result.reliability.reliability_score},
    )
    return "skip", None, None
```
`create_wiki_version()` 호출(420행) 전이므로 DB에 아무것도 안 남는다. 기존 "skip" 처리와 완전히 같은 리턴 모양이라 호출부(`generate_wiki_drafts_for_sections`)는 수정할 필요가 없다 — 이미 `topic_action=="skip"`을 정상 케이스로 다루고 있다.

**이슈 페이지** (`_generate_issue_page`, `generation.py:204`): `_rewrite_issue_page_content()` 호출(215행) 직후에 판정 체크를 추가한다. 단, 이슈 페이지는 지금 리턴 타입이 `tuple[str, str]`(항상 실제 id 두 개를 돌려줌 — "스킵" 개념이 아예 없음)이라 **계약을 바꿔야 한다**:

- 리턴 타입을 `tuple[str | None, str | None]`로 바꾼다.
- `_rewrite_issue_page_content()`가 신뢰도 판정을 못 받은 경우(폴백 — 원본 section을 그대로 반환한 경우, 목표 4)엔 "보통"으로 간주하고 그대로 진행한다.
- 판정이 "낮음"이면 `return None, None` — `find_matching_issue_page`/`upsert_wiki_page`/`create_wiki_version` 전부 호출 전이므로 DB에 아무것도 안 남는다.
- 호출부(`generate_wiki_drafts_for_sections`, 498-508행)를 다음과 같이 조정한다: `issue_page_id, issue_version_id = _generate_issue_page(...)`를 받은 뒤 `issue_page_id is None`이면 `WikiDraftGenerationResult(issue_page_id="", issue_version_id="", ...)`로 기존 예외 케이스(511-521행)와 동일한 "빈 문자열" 관례를 따르되 `error_message=None`으로 남겨 실패와 스킵을 구분한다. `published_count` 집계(536-538행)는 이미 `if result.issue_page_id else 0` truthy 체크라 별도 수정 없이 그대로 맞게 동작한다.

이슈 페이지가 "낮음"으로 스킵되면 `topic_page_id`가 있어도(토픽은 부모 페이지로 먼저 만들어짐) 이슈 페이지만 없는 상태가 될 수 있다 — 이건 정상이다(토픽 페이지와 이슈 페이지는 원래도 서로 독립적으로 성공/실패한다, 447행 docstring 참고).

`_rewrite_issue_page_content()` 자체의 반환 타입(`ReportSectionDraft`)에는 신뢰도 필드가 없다. `_rewrite_issue_page_content()`는 내부적으로 이미 `IssuePageRewriteResult`를 파싱했다가 4개 텍스트 필드만 뽑아 쓰고 버리는 구조이므로(196-201행), 그 안의 `reliability`(`PageReliabilityJudgment | None`)를 버리지 않고 같이 돌려주도록 리턴 타입을 `tuple[ReportSectionDraft, PageReliabilityJudgment | None]`로 바꾼다 — 재작성된 section과, 판정 결과(폴백 시 `None`)를 함께 반환한다. `_generate_issue_page`는 이 튜플을 받아 `rewritten_section`은 지금처럼 쓰고, 판정값이 `None`이 아니면 그 `reliability_level`을 게이트 판단에 쓴다(`None`이면 목표 4에 따라 "보통"으로 간주).

### DB 스키마 변경 (`wiki_page_versions`)

```sql
ALTER TABLE wiki_page_versions ADD COLUMN page_reliability_score INTEGER
  CHECK (page_reliability_score IS NULL OR (page_reliability_score >= 0 AND page_reliability_score <= 100));
ALTER TABLE wiki_page_versions ADD COLUMN page_reliability_level VARCHAR
  CHECK (page_reliability_level IS NULL OR page_reliability_level IN ('낮음', '보통', '높음'));
ALTER TABLE wiki_page_versions ADD COLUMN page_reliability_detail JSONB;
```

세 컬럼 다 nullable — 챗봇 저장/dedup 병합 등 이번 게이트를 거치지 않는 경로는 계속 NULL로 남는다(기존 페이지들도 마이그레이션 시점엔 전부 NULL). `page_reliability_detail`은 4개 항목의 `{score, reason}`을 JSON으로 저장한다(`document_analysis_results.reliability_detail`과 같은 패턴, `src/analysis/reliability_models.py:190`).

**"낮음"은 절대 저장되지 않는다** — 게이트가 `create_wiki_version()` 호출 자체를 막으므로, 저장된 행의 `page_reliability_level`은 실질적으로 `보통`/`높음`/`NULL` 중 하나만 나온다. DB 레벨에서 "낮음"을 막는 별도 제약은 두지 않는다(코드 레벨 게이트로 충분, 과설계 방지).

### 쓰기 경로 배선

`WikiDraftInput`(`src/wiki/interface.py:45`)에 optional 필드 3개를 추가한다:
```python
page_reliability_score: Optional[int] = None
page_reliability_level: Optional[str] = None
page_reliability_detail: Optional[dict] = None
```
`create_wiki_version()`(`src/wiki/service.py:74`)의 `insert_data` 구성부(117-126행, 기존 `change_summary`/`generator_model` 등과 같은 optional-필드 패턴)에 이 3개도 같은 방식으로 조건부 추가한다 — 별도 UPDATE 호출 없이 최초 INSERT 한 번에 같이 기록된다.

두 생성 함수(`_generate_issue_page`, `_generate_topic_page`)는 "보통"/"높음"으로 통과한 경우 `WikiDraftInput` 생성 시 이 3개 필드를 판정 결과로 채운다.

### 프론트엔드

**변경 없음.** 이번 스펙은 표시가 아니라 발행 게이트 자체가 목적이다. (표시하고 싶으면 별도 스펙 — `fetchWikiPage`/`WikiSource` 확장이 필요하며 이번 범위 밖.)

### ERDCloud / docs 동기화

`wiki_page_versions` 테이블에 컬럼 3개 추가를 ERDCloud 다이어그램과 `docs/architecture/myWiki_v2.sql`(ERDCloud import용), `docs/architecture/myWiki_v2_supabase.sql`(라이브 스키마 미러) 양쪽에 반영한다.

## 에러 처리

- **토픽 페이지**: 신뢰도 판정 필드가 `WikiTopicLLMResult` 스키마에 필수(non-optional)로 포함되므로, LLM이 이 필드를 빠뜨리면 지금과 동일하게 `pydantic.ValidationError`로 전체 생성이 실패한다(기존에도 다른 필수 필드 누락 시 이미 이렇게 동작 — 새로운 실패 모드가 아니다).
- **이슈 페이지**: 신뢰도 판정 LLM 호출 자체가 실패하면(`_rewrite_issue_page_content`의 기존 `except Exception` 폴백, 178-194행) 판정값 없이 원본 section 그대로 진행 — "보통"으로 간주하고 발행한다(목표 4, 사용자 확정 사항). 이슈 페이지의 "LLM 없이도 항상 성공" 원칙을 깨지 않는다.
- 판정이 "낮음"으로 스킵될 때는 예외가 아니라 정상적인 조기 반환이다 — `generate_wiki_drafts_for_sections`의 섹션별 실패 격리(482-522행)와 무관하게, 스킵된 섹션도 나머지 섹션 처리를 막지 않는다(애초에 예외를 던지지 않으므로 자연히 보장됨).

## 테스트

- `PageReliabilityJudgment`: 항목별 점수 합이 `reliability_score`와 다르거나 `reliability_level`이 점수 구간과 안 맞으면 `ValidationError`가 나는지(model_validator 검증). `WikiTopicLLMResult`/`IssuePageRewriteResult`: `reliability` 필드 포함 페이로드가 정상 파싱되는지, 이슈 쪽은 `reliability` 없이도(Optional) 파싱되는지.
- `_generate_topic_page`: `reliability.reliability_level="낮음"`인 LLM 응답을 주입했을 때 `create_wiki_version`이 호출되지 않고 `("skip", None, None)`을 반환하는지(기존 skip 테스트 패턴 확장). "보통"/"높음"일 때는 지금처럼 발행되고 `page_reliability_score`/`page_reliability_level`이 버전 row에 저장되는지.
- `_generate_issue_page`: 판정 "낮음" 주입 시 `(None, None)`을 반환하고 `create_wiki_version`이 호출되지 않는지. LLM 호출 실패(폴백) 주입 시에도 지금처럼 정상 발행되는지(회귀 확인 — 목표 4).
- `generate_wiki_drafts_for_sections`: 이슈 페이지가 스킵된 섹션에 대해 `WikiDraftGenerationResult(issue_page_id="", issue_version_id="", error_message=None)`이 만들어지고, `published_count` 집계에서 제외되는지.
- 통합: 낮은 신뢰도로 판정되는 섹션을 넣었을 때 `wiki_pages`/`wiki_page_versions`에 해당 페이지의 어떤 행도 생기지 않는지(진짜로 "남기지 않음"인지 DB 레벨에서 확인).

## 영향받는 파일

| 파일 | 변경 |
|---|---|
| `src/analysis/reliability_models.py` | 변경 없음(`ReliabilityLevel`/`RELIABILITY_LEVELS`를 그대로 import해서 재사용) |
| `src/wiki/generation_models.py` | `PageReliabilityJudgment` 신규 모델(배점 40/20/20/20 + 합계·구간 검증), `WikiTopicLLMResult`/`IssuePageRewriteResult`에 `reliability` 필드 추가 |
| `src/wiki/generation_prompts.py` | 두 시스템 프롬프트에 4개 항목 판정 지시 + JSON 출력 필드 추가, 두 user 프롬프트 빌더에 근거 신뢰도 줄 추가 |
| `src/wiki/generation.py` | `_generate_topic_page`(skip 체크 추가), `_generate_issue_page`(리턴 타입 변경 + skip 체크), `_rewrite_issue_page_content`(판정 필드도 함께 리턴하도록 확장), `generate_wiki_drafts_for_sections`(이슈 페이지 skip 처리) |
| `src/wiki/interface.py` | `WikiDraftInput`에 신뢰도 필드 3개 추가 |
| `src/wiki/service.py` | `create_wiki_version()`의 `insert_data`에 신뢰도 필드 3개 조건부 추가 |
| Supabase 마이그레이션(신규) | `wiki_page_versions`에 `page_reliability_score`/`page_reliability_level`/`page_reliability_detail` 컬럼 추가 |
| `tests/test_wiki_generation.py` (또는 해당 테스트 파일) | 위 테스트 항목 반영 |
| ERDCloud + `docs/architecture/myWiki_v2.sql` + `docs/architecture/myWiki_v2_supabase.sql` | `wiki_page_versions` 컬럼 3개 반영 |

프론트엔드 코드 변경 없음.

# 위키 페이지 신뢰도 자율 판정 + 발행 게이트 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 야간 배치가 만드는 위키 이슈/토픽 페이지에 대해, 생성 LLM이 자기 결과물의 신뢰도를 4개 항목(배점 40/20/20/20, 합 0-100)으로 직접 판정하게 하고, "낮음"(0-39)이면 사람 개입 없이 DB에 아무것도 남기지 않고 발행을 막는다.

**Architecture:** `_generate_topic_page`/`_generate_issue_page`(`src/wiki/generation.py`)가 LLM 결과를 파싱한 직후, `create_wiki_version()` 호출 전에 `reliability_level`을 확인해 "낮음"이면 조기 반환한다. "보통"/"높음"은 지금처럼 즉시 자동 발행하되, 판정 점수·등급·상세를 `wiki_page_versions`의 새 컬럼 3개에 같이 기록한다.

**Tech Stack:** Python 3 / FastAPI / Pydantic v2 / Supabase(Postgres) / pytest.

## Global Constraints

- 적용 범위는 야간 배치의 `_generate_issue_page`/`_generate_topic_page`뿐이다 — 챗봇 "위키에 저장"(`src/api/main.py`)과 dedup 병합(`src/wiki/dedup.py`)은 건드리지 않는다.
- 사람 검토 단계를 추가하지 않는다(완전 무인 자동화) — "낮음"이면 발행하지 않을 뿐, 보류 큐 같은 중간 상태를 만들지 않는다.
- 판정 배점은 `grounding_fidelity 0-40 / source_reliability 0-20 / evidence_diversity 0-20 / currency 0-20`(합 0-100)로 고정 — 균등 배분이 아니다.
- `reliability_level`은 반드시 `src/analysis/reliability_models.py`의 `ReliabilityLevel`/`RELIABILITY_LEVELS`(낮음 0-39/보통 40-69/높음 70-100, 값은 "낮음"/"보통"/"높음" 한글 문자열)를 그대로 import해서 재사용한다 — 새 타입을 만들지 않는다.
- 이슈 페이지의 "LLM 없이도 항상 생성에 성공해야 한다" 기존 원칙을 절대 깨지 않는다 — 신뢰도 판정 LLM 호출 자체가 실패하면 "보통"으로 간주하고 그대로 발행한다.
- 토픽 페이지는 신뢰도 필드가 필수(non-optional)다 — LLM이 빠뜨리면 `pydantic.ValidationError`로 전체 생성이 실패한다(기존에도 다른 필수 필드 누락 시 이미 이렇게 동작 — 새 실패 모드가 아니다).
- Supabase project_id: `uhzjshqmnlahhvqzygkp`. 라이브 스키마 문서는 `docs/architecture/myWiki_v2.sql`(ERDCloud import용)과 `docs/architecture/myWiki_v2_supabase.sql`(라이브 미러) 둘 다 갱신해야 한다.
- 참고 스펙: `docs/superpowers/specs/2026-08-10-wiki-page-reliability-autopublish-design.md`

---

### Task 1: DB 마이그레이션 — `wiki_page_versions` 신뢰도 컬럼 추가

**Files:**
- Create: `supabase/migrations/20260810020000_wiki_page_versions_reliability.sql`

**Interfaces:**
- Produces: `wiki_page_versions.page_reliability_score`(INTEGER, nullable), `wiki_page_versions.page_reliability_level`(VARCHAR, nullable), `wiki_page_versions.page_reliability_detail`(JSONB, nullable) — Task 2 이후 모든 태스크가 이 세 컬럼명을 그대로 쓴다.

- [ ] **Step 1: 마이그레이션 SQL 작성**

```sql
-- 위키 페이지 신뢰도 자율 판정 + 발행 게이트: wiki_page_versions에 판정 결과 컬럼 추가.
-- "낮음"으로 판정된 페이지는 create_wiki_version() 자체가 호출되지 않으므로, 저장되는
-- page_reliability_level 값은 실질적으로 '보통'/'높음'/NULL 중 하나만 나온다.
ALTER TABLE wiki_page_versions ADD COLUMN page_reliability_score INTEGER
  CHECK (page_reliability_score IS NULL OR (page_reliability_score >= 0 AND page_reliability_score <= 100));
ALTER TABLE wiki_page_versions ADD COLUMN page_reliability_level VARCHAR
  CHECK (page_reliability_level IS NULL OR page_reliability_level IN ('낮음', '보통', '높음'));
ALTER TABLE wiki_page_versions ADD COLUMN page_reliability_detail JSONB;
```

- [ ] **Step 2: 라이브 Supabase에 적용**

`mcp__c2efe9a0-2e64-4e70-a81f-15d0dabd2f27__apply_migration` (project_id: `uhzjshqmnlahhvqzygkp`, name: `wiki_page_versions_reliability`)로 위 SQL을 그대로 실행한다.

- [ ] **Step 3: 적용 확인**

`mcp__c2efe9a0-2e64-4e70-a81f-15d0dabd2f27__execute_sql`로 다음을 조회해서 컬럼 3개와 CHECK 제약이 실제로 생겼는지 확인한다:
```sql
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'wiki_page_versions' AND column_name LIKE 'page_reliability%';
```
Expected: 3행, 전부 `is_nullable = 'YES'`.

- [ ] **Step 4: Commit**

```bash
git add supabase/migrations/20260810020000_wiki_page_versions_reliability.sql
git commit -m "Feat: wiki_page_versions에 페이지 신뢰도 판정 컬럼 추가"
```

---

### Task 2: 데이터 모델 + 쓰기 경로 배선

**Files:**
- Modify: `src/wiki/generation_models.py`
- Modify: `src/wiki/interface.py:44-60` (`WikiDraftInput`)
- Modify: `src/wiki/service.py:74-139` (`create_wiki_version`)
- Test: `tests/test_wiki_generation_models.py`
- Test: `tests/test_wiki_service.py`

**Interfaces:**
- Consumes: Task 1의 `page_reliability_score`/`page_reliability_level`/`page_reliability_detail` 컬럼명.
- Produces: `PageReliabilityJudgment`(pydantic 모델, `src/wiki/generation_models.py`) — Task 3(프롬프트)·Task 4(토픽 게이트)·Task 5(이슈 게이트)가 그대로 쓴다. `WikiTopicLLMResult.reliability: PageReliabilityJudgment`(필수). `IssuePageRewriteResult.reliability: PageReliabilityJudgment | None`(Optional). `WikiDraftInput.page_reliability_score/page_reliability_level/page_reliability_detail: Optional`(`src/wiki/interface.py`) — Task 4·5가 `WikiDraftInput(...)` 생성 시 채워 넣는다.

- [ ] **Step 1: `PageReliabilityJudgment` 모델 실패 테스트 작성**

`tests/test_wiki_generation_models.py` 맨 위 import에 `PageReliabilityJudgment`를 추가하고, 파일 끝에 추가:

```python
def test_page_reliability_judgment_rejects_mismatched_total():
    with pytest.raises(ValidationError):
        PageReliabilityJudgment(
            grounding_fidelity_score=25, grounding_fidelity_reason="근거 범위 안에서 서술함",
            source_reliability_score=15, source_reliability_reason="원문 신뢰도 보통 수준",
            evidence_diversity_score=10, evidence_diversity_reason="출처 2건 확인",
            currency_score=10, currency_reason="최근 1주 이내 정보",
            reliability_score=99,  # 25+15+10+10=60 과 불일치
            reliability_level="보통",
        )


def test_page_reliability_judgment_rejects_level_outside_score_range():
    with pytest.raises(ValidationError):
        PageReliabilityJudgment(
            grounding_fidelity_score=25, grounding_fidelity_reason="근거 범위 안에서 서술함",
            source_reliability_score=15, source_reliability_reason="원문 신뢰도 보통 수준",
            evidence_diversity_score=10, evidence_diversity_reason="출처 2건 확인",
            currency_score=10, currency_reason="최근 1주 이내 정보",
            reliability_score=60,
            reliability_level="낮음",  # 60점은 '보통' 구간(40-69)인데 '낮음'이라고 함
        )


def test_page_reliability_judgment_accepts_valid_payload():
    judgment = PageReliabilityJudgment(
        grounding_fidelity_score=25, grounding_fidelity_reason="근거 범위 안에서 서술함",
        source_reliability_score=15, source_reliability_reason="원문 신뢰도 보통 수준",
        evidence_diversity_score=10, evidence_diversity_reason="출처 2건 확인",
        currency_score=10, currency_reason="최근 1주 이내 정보",
        reliability_score=60,
        reliability_level="보통",
    )
    assert judgment.reliability_score == 60


def test_wiki_topic_llm_result_requires_reliability():
    with pytest.raises(ValidationError):
        WikiTopicLLMResult(action="skip", confidence_score=0.4)


def test_issue_page_rewrite_result_reliability_defaults_to_none():
    result = IssuePageRewriteResult(
        current_summary="다듬어진 요약", key_facts=["사실 1"],
        implications=["시사점 1"], watch_points=["지점 1"],
    )
    assert result.reliability is None
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `pytest tests/test_wiki_generation_models.py -v`
Expected: `PageReliabilityJudgment`/`test_wiki_topic_llm_result_requires_reliability`/`test_issue_page_rewrite_result_reliability_defaults_to_none` 관련 테스트가 `NameError`(모델 없음) 또는 `ValidationError` 미발생으로 FAIL.

- [ ] **Step 3: `PageReliabilityJudgment` + 필드 추가 구현**

`src/wiki/generation_models.py` 상단 import에 추가:
```python
from pydantic import BaseModel, Field, field_validator, model_validator

from ..analysis.reliability_models import RELIABILITY_LEVELS, ReliabilityLevel
```

`WikiClaim` 클래스 위(또는 `TopicPageType` 선언부 아래) 아무 곳에나 새 모델 추가:
```python
class PageReliabilityJudgment(BaseModel):
    """위키 LLM이 자기가 쓴 페이지를 놓고 스스로 매기는 신뢰도 판정.
    document_analysis_results의 원문 문서 판정과 별개로, 이 페이지 본문이 근거
    범위를 벗어나지 않았는지(grounding_fidelity)를 가장 중요하게 취급한다."""

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

`WikiTopicLLMResult`에 필드 추가(`confidence_score` 필드 바로 아래):
```python
    reliability: PageReliabilityJudgment
```

`IssuePageRewriteResult`에 필드 추가(`watch_points` 필드 바로 아래):
```python
    reliability: PageReliabilityJudgment | None = None
```

기존 `test_wiki_topic_llm_result_confidence_score_bounds`(35-39행)와 `test_wiki_topic_llm_result_update_existing_with_claims`(42-50행)는 이제 `reliability`가 없으면 실패하므로, 두 테스트 모두에 아래 상수를 만들어 넘긴다. 파일 상단(마지막 import 다음)에 추가:
```python
_VALID_RELIABILITY = dict(
    grounding_fidelity_score=25, grounding_fidelity_reason="근거 범위 안에서 서술함",
    source_reliability_score=15, source_reliability_reason="원문 신뢰도 보통 수준",
    evidence_diversity_score=10, evidence_diversity_reason="출처 2건 확인",
    currency_score=10, currency_reason="최근 1주 이내 정보",
    reliability_score=60, reliability_level="보통",
)
```
그리고 두 테스트를 아래처럼 고친다:
```python
def test_wiki_topic_llm_result_confidence_score_bounds():
    with pytest.raises(ValidationError):
        WikiTopicLLMResult(action="skip", confidence_score=1.5, reliability=PageReliabilityJudgment(**_VALID_RELIABILITY))
    result = WikiTopicLLMResult(action="skip", confidence_score=0.4, reliability=PageReliabilityJudgment(**_VALID_RELIABILITY))
    assert result.claims == []


def test_wiki_topic_llm_result_update_existing_with_claims():
    result = WikiTopicLLMResult(
        action="update_existing",
        target_wiki_page_id="page-1",
        markdown="# 갱신된 본문",
        change_summary="신규 근거 반영",
        claims=[WikiClaim(document_version_id="doc-1", claim_text="근거", citation_order=1)],
        confidence_score=0.8,
        reliability=PageReliabilityJudgment(**_VALID_RELIABILITY),
    )
    assert result.claims[0].document_version_id == "doc-1"
```
파일 상단 import에 `PageReliabilityJudgment`를 추가한다.

- [ ] **Step 4: `WikiDraftInput`에 신뢰도 필드 3개 추가**

`src/wiki/interface.py:44-60`의 `WikiDraftInput` 마지막 필드(`generation_run_id`) 다음에 추가:
```python
    page_reliability_score: Optional[int] = None
    page_reliability_level: Optional[str] = None
    page_reliability_detail: Optional[dict] = None
```

- [ ] **Step 5: `create_wiki_version()`의 `insert_data`에 조건부 추가**

`src/wiki/service.py:117-126`(기존 `change_summary`/`generator_model` 등 optional-필드 패턴) 바로 다음에 추가:
```python
    if draft.page_reliability_score is not None:
        insert_data["page_reliability_score"] = draft.page_reliability_score
    if draft.page_reliability_level is not None:
        insert_data["page_reliability_level"] = draft.page_reliability_level
    if draft.page_reliability_detail is not None:
        insert_data["page_reliability_detail"] = draft.page_reliability_detail
```

- [ ] **Step 6: 쓰기 경로 통합 테스트 추가**

`tests/test_wiki_service.py`의 `test_create_wiki_version_basic`(146-172행) 바로 다음에 추가(같은 `workspace_id` 라이브 fixture 사용):
```python
def test_create_wiki_version_stores_page_reliability_fields(workspace_id):
    slug = f"test-ver-rel-{uuid.uuid4().hex[:8]}"
    draft = WikiDraftInput(
        workspace_id=workspace_id,
        slug=slug,
        title="신뢰도 필드 테스트",
        page_type="term",
        markdown="# 테스트\n내용입니다.",
        sources=[],
        page_reliability_score=85,
        page_reliability_level="높음",
        page_reliability_detail={"grounding_fidelity_score": 35},
    )
    version_id = create_wiki_version(draft)

    db = _get_client()
    ver = db.table("wiki_page_versions").select("*").eq("id", version_id).single().execute()
    assert ver.data["page_reliability_score"] == 85
    assert ver.data["page_reliability_level"] == "높음"
    assert ver.data["page_reliability_detail"] == {"grounding_fidelity_score": 35}

    # teardown
    obj_key = ver.data["markdown_object_key"]
    db.storage.from_("wiki").remove([obj_key])
    db.table("wiki_page_sources").delete().eq("wiki_version_id", version_id).execute()
    db.table("wiki_page_versions").delete().eq("id", version_id).execute()
    db.table("wiki_pages").delete().eq("slug", slug).eq("workspace_id", workspace_id).execute()
```

- [ ] **Step 7: 테스트 실행 — 통과 확인**

Run: `pytest tests/test_wiki_generation_models.py tests/test_wiki_service.py -v`
Expected: 전부 PASS(`test_create_wiki_version_stores_page_reliability_fields`는 Supabase 자격증명이 없으면 skip — CI/로컬 환경에 따라 정상).

- [ ] **Step 8: Commit**

```bash
git add src/wiki/generation_models.py src/wiki/interface.py src/wiki/service.py tests/test_wiki_generation_models.py tests/test_wiki_service.py
git commit -m "Feat: 페이지 신뢰도 판정 데이터 모델 + 쓰기 경로 배선"
```

---

### Task 3: 프롬프트 변경

**Files:**
- Modify: `src/wiki/generation_prompts.py`
- Test: `tests/test_wiki_generation_prompts.py`

**Interfaces:**
- Consumes: Task 2의 `PageReliabilityJudgment` 필드명(JSON 출력 스키마와 1:1 대응해야 함).
- Produces: 두 시스템 프롬프트에 신뢰도 판정 지시 + JSON 스키마, 두 user 프롬프트 빌더에 `근거 신뢰도(원문 문서 기준): {section.reliability_score}` 줄.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_wiki_generation_prompts.py` 파일 끝에 추가:
```python
def test_wiki_topic_system_prompt_requests_weighted_reliability_judgment():
    assert "grounding_fidelity" in WIKI_TOPIC_SYSTEM_PROMPT
    assert "40" in WIKI_TOPIC_SYSTEM_PROMPT
    assert "reliability_level" in WIKI_TOPIC_SYSTEM_PROMPT


def test_issue_page_rewrite_system_prompt_requests_weighted_reliability_judgment():
    assert "grounding_fidelity" in ISSUE_PAGE_REWRITE_SYSTEM_PROMPT
    assert "reliability_level" in ISSUE_PAGE_REWRITE_SYSTEM_PROMPT


def test_wiki_topic_user_prompt_includes_source_reliability_signal():
    prompt = build_wiki_topic_user_prompt(
        section=_topic_section_with_reliability_score(72), candidates=[], top_level_pages=[],
    )
    assert "근거 신뢰도(원문 문서 기준): 72" in prompt


def test_issue_page_rewrite_user_prompt_includes_source_reliability_signal():
    prompt = build_issue_page_rewrite_user_prompt(_topic_section_with_reliability_score(72))
    assert "근거 신뢰도(원문 문서 기준): 72" in prompt
```
파일 상단에 이미 있는 섹션 빌더 헬퍼(예: `_section`류)를 확인하고 없으면 최소 헬퍼를 추가한다:
```python
def _topic_section_with_reliability_score(score: int) -> ReportSectionDraft:
    return ReportSectionDraft(
        issue_key="issue-1", representative_analysis_result_id="analysis-1",
        category=Category.PRODUCT_TECHNOLOGY, title="테스트 이슈",
        reliability_score=score,
    )
```
(`ReportSectionDraft`/`Category` import가 파일에 이미 있으면 그대로 쓰고, 없으면 `from src.analysis.models import Category`, `from src.report.models import ReportSectionDraft`를 추가한다.)

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `pytest tests/test_wiki_generation_prompts.py -v`
Expected: 4개 신규 테스트 FAIL(문자열 없음 / 프롬프트에 신뢰도 줄 없음).

- [ ] **Step 3: 시스템 프롬프트에 판정 지시 + JSON 스키마 추가**

`WIKI_TOPIC_SYSTEM_PROMPT`(`generation_prompts.py:8`)의 "절대 규칙" 목록에서 `confidence_score` 항목(35번째 줄, `- confidence_score(0~1)에...`) 바로 다음에 추가:
```
- 아래 4개 항목으로 이 페이지 자체의 신뢰도를 직접 판정해 reliability 객체로 반환하십시오.
  grounding_fidelity(0~40, 가장 중요 — 본문의 각 주장이 [근거 문서] 범위를 벗어나 추론·과장한
  부분이 있는지), source_reliability(0~20, [이슈 정보]의 "근거 신뢰도" 값을 참고해 원문 자체의
  신뢰도를 반영), evidence_diversity(0~20, 단일 출처에만 의존하는지), currency(0~20, 근거가
  최근 것인지). reliability_score는 4개 항목의 합, reliability_level은 0~39=낮음/40~69=보통/
  70~100=높음 구간을 그대로 따르십시오. 각 항목마다 reason을 한 문장으로 쓰십시오.
```
JSON 출력 형식(38-50행)의 `"confidence_score": 0.0` 다음에 콤마 추가 후 아래 삽입:
```
  "reliability": {
    "grounding_fidelity_score": 0, "grounding_fidelity_reason": "",
    "source_reliability_score": 0, "source_reliability_reason": "",
    "evidence_diversity_score": 0, "evidence_diversity_reason": "",
    "currency_score": 0, "currency_reason": "",
    "reliability_score": 0, "reliability_level": "낮음" | "보통" | "높음"
  }
```

`ISSUE_PAGE_REWRITE_SYSTEM_PROMPT`(`generation_prompts.py:133`)의 "절대 규칙" 목록 마지막(145행, `- 마크다운 코드블록 없이...` 위)에 같은 지시를 추가하고, JSON 출력 형식(148-153행)의 `"watch_points": [...]` 다음에 콤마 추가 후 같은 `"reliability": {...}` 블록을 삽입한다.

- [ ] **Step 4: user 프롬프트 빌더에 근거 신뢰도 줄 추가**

`build_wiki_topic_user_prompt()`(`generation_prompts.py:70`)의 `[이슈 정보]` 블록 구성부(86-92행, `f"현재 상황 요약: ..."` 다음)에 추가:
```python
        f"근거 신뢰도(원문 문서 기준): {section.reliability_score}",
```

`build_issue_page_rewrite_user_prompt()`(`generation_prompts.py:156`)의 `[이슈 정보]` 블록(160-163행, `f"카테고리: ..."` 다음)에 같은 줄을 추가한다:
```python
        f"근거 신뢰도(원문 문서 기준): {section.reliability_score}",
```

- [ ] **Step 5: 테스트 실행 — 통과 확인**

Run: `pytest tests/test_wiki_generation_prompts.py -v`
Expected: 전부 PASS, 기존 테스트도 회귀 없이 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/wiki/generation_prompts.py tests/test_wiki_generation_prompts.py
git commit -m "Feat: 위키 생성 프롬프트에 페이지 신뢰도 판정 지시 추가"
```

---

### Task 4: 토픽 페이지 게이트

**Files:**
- Modify: `src/wiki/generation.py:296-430` (`_generate_topic_page`)
- Test: `tests/test_wiki_generation.py`

**Interfaces:**
- Consumes: Task 2의 `WikiTopicLLMResult.reliability`(필수), `WikiDraftInput.page_reliability_*` 필드. Task 3의 프롬프트(런타임 동작에만 영향, 테스트는 mock LLM 응답을 직접 주입하므로 무관).
- Produces: `_generate_topic_page()`는 그대로 `tuple[str, str | None, str | None]`을 반환한다(계약 변경 없음 — `"skip"` 케이스를 재사용).

**이 태스크의 핵심 위험**: `WikiTopicLLMResult.reliability`가 필수 필드가 되므로, `create_json_completion`/`llm_client`가 반환하는 JSON에 `"reliability"` 키가 없는 기존 테스트는 전부 `pydantic.ValidationError`로 깨진다. `tests/test_wiki_generation.py`에서 토픽 페이지 LLM 응답 JSON을 만드는 자리가 아래 18곳이다(전부 `"action":` 키를 포함하는 dict 리터럴) — 이 태스크에서 전부 고친다:

```
377, 399, 428, 466, 494, 533, 571, 608, 645, 688, 709, 737, 770, 808, 842, 872, 908, 936
```

- [ ] **Step 1: 공유 신뢰도 픽스처 추가**

`tests/test_wiki_generation.py`의 `_section()` 헬퍼(20-39행) 바로 다음에 추가:
```python
_RELIABILITY_MEDIUM = {
    "grounding_fidelity_score": 25, "grounding_fidelity_reason": "근거 범위 안에서 서술함",
    "source_reliability_score": 15, "source_reliability_reason": "원문 신뢰도 보통 수준",
    "evidence_diversity_score": 10, "evidence_diversity_reason": "출처 2건 확인",
    "currency_score": 10, "currency_reason": "최근 1주 이내 정보",
    "reliability_score": 60, "reliability_level": "보통",
}

_RELIABILITY_LOW = {
    "grounding_fidelity_score": 5, "grounding_fidelity_reason": "근거에 없는 수치를 추가함",
    "source_reliability_score": 10, "source_reliability_reason": "단일 출처",
    "evidence_diversity_score": 5, "evidence_diversity_reason": "교차검증 불가",
    "currency_score": 5, "currency_reason": "오래된 정보",
    "reliability_score": 25, "reliability_level": "낮음",
}
```

- [ ] **Step 2: 기존 18개 JSON 픽스처에 `"reliability"` 키 추가**

아래 18개 줄(현재 라인 번호 기준) 각각의 dict 리터럴에 `"reliability": _RELIABILITY_MEDIUM,`을 추가한다. 패턴은 전부 동일하다 — 대표 예시 3개:

라인 377 (`test_generate_topic_page_prompt_includes_mapped_evidence_text` 안):
```python
# before
return json.dumps({"action": "skip", "claims": [], "confidence_score": 0.1})
# after
return json.dumps({"action": "skip", "claims": [], "confidence_score": 0.1, "reliability": _RELIABILITY_MEDIUM})
```

라인 399 (`test_generate_topic_page_skips_when_llm_returns_skip` 안 — `action=="skip"` 분기 자체를 테스트하는 것이라 신뢰도값은 무관하므로 medium을 넣는다. "낮음" 판정 스킵은 Step 3에서 별도 신규 테스트로 검증한다):
```python
# before
lambda **kwargs: json.dumps({"action": "skip", "claims": [], "confidence_score": 0.1}),
# after
lambda **kwargs: json.dumps({"action": "skip", "claims": [], "confidence_score": 0.1, "reliability": _RELIABILITY_MEDIUM}),
```

라인 428 (`test_generate_topic_page_updates_existing_when_confidence_high` 안, 여러 줄짜리 dict):
```python
# before
                "claims": [{"document_version_id": "doc-1", "claim_text": "근거", "citation_order": 1}],
                "confidence_score": 0.9,
            }
# after
                "claims": [{"document_version_id": "doc-1", "claim_text": "근거", "citation_order": 1}],
                "confidence_score": 0.9,
                "reliability": _RELIABILITY_MEDIUM,
            }
```

나머지 15곳(466, 494, 533, 571, 608, 645, 688, 709, 737, 770, 808, 842, 872, 908, 936행)도 각 dict 리터럴의 마지막 키(`"confidence_score": ...` 또는 `"claims": [...]`) 다음 줄에 `"reliability": _RELIABILITY_MEDIUM,`(한 줄짜리 `json.dumps({...})` 형태인 688행·908행은 `"reliability": _RELIABILITY_MEDIUM`을 같은 줄에)을 추가한다 — 전부 신뢰도 판정 자체를 테스트하는 게 아니라 다른 동작(update_existing/create_new/skip 분기, 중복 제목 스킵 등)을 테스트하므로 모두 "보통"으로 통일한다.

- [ ] **Step 3: 신뢰도 "낮음" 스킵 테스트 추가**

`tests/test_wiki_generation.py`의 `test_generate_topic_page_skips_when_llm_returns_skip`(394-409행) 바로 다음에 추가:
```python
def test_generate_topic_page_skips_when_reliability_is_low(monkeypatch):
    calls = []
    monkeypatch.setattr(generation, "list_top_level_topic_pages", lambda workspace_id, supabase=None: [])
    monkeypatch.setattr(
        generation,
        "create_json_completion",
        lambda **kwargs: json.dumps({
            "action": "create_new",
            "slug": "hbm4-supply", "title": "HBM4_수급현황", "page_type": "technology",
            "markdown": "# 본문",
            "claims": [{"document_version_id": "doc-1", "claim_text": "근거", "citation_order": 1}],
            "confidence_score": 0.2,
            "reliability": _RELIABILITY_LOW,
        }),
    )
    monkeypatch.setattr(generation, "create_wiki_version", lambda draft, **k: calls.append("create") or "should-not-happen")
    monkeypatch.setattr(generation, "upsert_wiki_page", lambda *a, **k: calls.append("upsert") or "should-not-happen")

    action, page_id, version_id = generation._generate_topic_page(
        _section(), [], workspace_id="ws-1", requested_by=None,
    )

    assert action == "skip"
    assert page_id is None
    assert version_id is None
    assert calls == []  # create_wiki_version/upsert_wiki_page 둘 다 호출되면 안 된다


def test_generate_topic_page_stores_reliability_fields_when_published(monkeypatch):
    calls = []
    monkeypatch.setattr(generation, "list_top_level_topic_pages", lambda workspace_id, supabase=None: [])
    monkeypatch.setattr(
        generation,
        "create_json_completion",
        lambda **kwargs: json.dumps({
            "action": "create_new",
            "slug": "hbm4-supply", "title": "HBM4_수급현황", "page_type": "technology",
            "markdown": "# 본문",
            "claims": [{"document_version_id": "doc-1", "claim_text": "근거", "citation_order": 1}],
            "confidence_score": 0.8,
            "reliability": _RELIABILITY_MEDIUM,
        }),
    )
    monkeypatch.setattr(generation, "upsert_wiki_page", lambda *a, **k: "page-1")
    monkeypatch.setattr(
        generation, "create_wiki_version",
        lambda draft, **k: calls.append(
            ("create", draft.page_reliability_score, draft.page_reliability_level, draft.page_reliability_detail)
        ) or "version-1",
    )
    monkeypatch.setattr(generation, "record_wiki_validation", lambda *a, **k: None)
    monkeypatch.setattr(generation, "review_wiki_version", lambda *a, **k: None)
    monkeypatch.setattr(generation, "publish_wiki_version", lambda *a, **k: None)

    action, page_id, version_id = generation._generate_topic_page(
        _section(), [], workspace_id="ws-1", requested_by=None,
    )

    assert action == "create_new"
    create_call = next(call for call in calls if call[0] == "create")
    assert create_call[1] == 60
    assert create_call[2] == "보통"
    assert create_call[3] is not None
```

- [ ] **Step 4: 테스트 실행 — 실패 확인 (구현 전)**

Run: `pytest tests/test_wiki_generation.py -k "topic_page" -v`
Expected: 새로 추가한 2개 테스트 FAIL(`_generate_topic_page`가 아직 `reliability`를 안 읽음). 기존 테스트들은 Step 2에서 픽스처를 고쳤으므로 이 시점엔 이미 PASS해야 정상 — 만약 FAIL한다면 Step 2에서 빠뜨린 라인이 있는지 위 18개 라인 번호를 다시 확인한다.

- [ ] **Step 5: 게이트 구현**

`src/wiki/generation.py`의 `_generate_topic_page()`(296-430행) 안, 기존 skip 체크들(352-356행) 바로 다음에 추가:
```python
    if result.reliability.reliability_level == ReliabilityLevel.LOW:
        logger.info(
            "wiki_topic_page_skipped_low_reliability",
            extra={"issue_key": section.issue_key, "reliability_score": result.reliability.reliability_score},
        )
        return "skip", None, None
```
(`ReliabilityLevel`을 파일 상단 import에 추가: `from ..analysis.reliability_models import ReliabilityLevel`.)

`WikiDraftInput(...)` 생성부(408-419행)에 3개 필드 추가:
```python
        page_reliability_score=result.reliability.reliability_score,
        page_reliability_level=result.reliability.reliability_level.value,
        page_reliability_detail=result.reliability.model_dump(),
```

- [ ] **Step 6: 테스트 실행 — 통과 확인**

Run: `pytest tests/test_wiki_generation.py -v`
Expected: 전체 PASS(기존 테스트 포함, 회귀 없음).

- [ ] **Step 7: Commit**

```bash
git add src/wiki/generation.py tests/test_wiki_generation.py
git commit -m "Feat: 토픽 페이지 생성에 신뢰도 자율 판정 발행 게이트 적용"
```

---

### Task 5: 이슈 페이지 게이트 + 리턴 계약 변경

**Files:**
- Modify: `src/wiki/generation.py:164-262` (`_rewrite_issue_page_content`, `_generate_issue_page`)
- Modify: `src/wiki/generation.py:433-546` (`generate_wiki_drafts_for_sections`)
- Test: `tests/test_wiki_generation.py`

**Interfaces:**
- Consumes: Task 2의 `IssuePageRewriteResult.reliability`(Optional), `WikiDraftInput.page_reliability_*`.
- Produces: `_rewrite_issue_page_content()`는 이제 `tuple[ReportSectionDraft, PageReliabilityJudgment | None]`을 반환한다(이전: `ReportSectionDraft`만 반환). `_generate_issue_page()`는 이제 `tuple[str | None, str | None]`을 반환한다(이전: `tuple[str, str]`, 항상 실제 id).

**이 태스크의 핵심 위험**: `_rewrite_issue_page_content()`의 리턴 타입이 바뀌므로 이 함수를 직접 호출하는 기존 테스트(`test_rewrite_issue_page_content_uses_llm_result`, `test_rewrite_issue_page_content_falls_back_on_invalid_json`, `test_rewrite_issue_page_content_falls_back_on_empty_fields`, `test_rewrite_issue_page_content_falls_back_on_llm_exception` — 199-246행)가 전부 깨진다. `_generate_issue_page()`의 리턴을 `page_id, version_id = ...`로 언패킹하는 기존 테스트(53-186행, 950-1263행 다수)는 "보통"/"높음" 경로에서는 여전히 실제 id 두 개를 받으므로 변경 없이 통과한다.

- [ ] **Step 1: `_rewrite_issue_page_content` 호출부 테스트부터 실패하게 고치기**

`tests/test_wiki_generation.py`의 4개 테스트(199-246행)를 아래로 교체:
```python
def test_rewrite_issue_page_content_uses_llm_result():
    def fake_llm(system_prompt, user_prompt, model):
        return json.dumps({
            "current_summary": "다듬어진 요약",
            "key_facts": ["다듬어진 사실"],
            "implications": ["다듬어진 시사점"],
            "watch_points": ["다듬어진 지점"],
            "reliability": _RELIABILITY_MEDIUM,
        })

    rewritten, judgment = generation._rewrite_issue_page_content(_section(), llm_client=fake_llm)

    assert rewritten.current_summary == "다듬어진 요약"
    assert rewritten.key_facts == ["다듬어진 사실"]
    assert rewritten.implications == ["다듬어진 시사점"]
    assert rewritten.watch_points == ["다듬어진 지점"]
    assert rewritten.title == _section().title  # 제목은 재작성 대상이 아니다
    assert judgment is not None
    assert judgment.reliability_level.value == "보통"


def test_rewrite_issue_page_content_falls_back_on_invalid_json(monkeypatch):
    monkeypatch.setattr(generation, "create_json_completion", lambda **kwargs: "not json")

    rewritten, judgment = generation._rewrite_issue_page_content(_section())

    assert rewritten == _section()
    assert judgment is None


def test_rewrite_issue_page_content_falls_back_on_empty_fields(monkeypatch):
    monkeypatch.setattr(
        generation, "create_json_completion",
        lambda **kwargs: json.dumps(
            {"current_summary": "", "key_facts": [], "implications": [], "watch_points": []}
        ),
    )

    rewritten, judgment = generation._rewrite_issue_page_content(_section())

    assert rewritten == _section()
    assert judgment is None


def test_rewrite_issue_page_content_falls_back_on_llm_exception(monkeypatch):
    def exploding_completion(**kwargs):
        raise generation.OpenRouterTimeoutError("타임아웃")

    monkeypatch.setattr(generation, "create_json_completion", exploding_completion)

    rewritten, judgment = generation._rewrite_issue_page_content(_section())

    assert rewritten == _section()
    assert judgment is None
```

- [ ] **Step 2: 이슈 페이지 신뢰도 게이트 테스트 추가**

`test_generate_issue_page_creates_and_auto_publishes`(53-93행) 바로 다음에 추가:
```python
def test_generate_issue_page_skips_when_reliability_is_low(monkeypatch):
    calls = []

    def fake_llm(system_prompt, user_prompt, model):
        return json.dumps({
            "current_summary": "요약", "key_facts": ["사실"],
            "implications": ["시사점"], "watch_points": ["지점"],
            "reliability": _RELIABILITY_LOW,
        })

    monkeypatch.setattr(generation, "find_matching_issue_page", lambda *a, **k: None)
    monkeypatch.setattr(generation, "upsert_wiki_page", lambda *a, **k: calls.append("upsert") or "should-not-happen")
    monkeypatch.setattr(generation, "create_wiki_version", lambda draft, **k: calls.append("create") or "should-not-happen")

    page_id, version_id = generation._generate_issue_page(
        _section(), workspace_id="ws-1", requested_by=None, llm_client=fake_llm,
    )

    assert page_id is None
    assert version_id is None
    assert calls == []  # upsert_wiki_page/create_wiki_version 둘 다 호출되면 안 된다


def test_generate_issue_page_publishes_when_reliability_llm_call_fails(monkeypatch):
    """이슈 페이지는 'LLM 없이도 항상 성공해야 한다'는 기존 원칙이 있다 — 신뢰도
    판정 LLM 호출 자체가 실패하면(기존 폴백) '보통'으로 간주하고 그대로 발행해야
    한다(목표 4 회귀 방지)."""
    calls = []
    monkeypatch.setattr(generation, "create_json_completion", lambda **kwargs: "not json")
    monkeypatch.setattr(generation, "find_matching_issue_page", lambda *a, **k: None)
    monkeypatch.setattr(generation, "upsert_wiki_page", lambda *a, **k: "page-1")
    monkeypatch.setattr(
        generation, "create_wiki_version",
        lambda draft, **k: calls.append(("create", draft.page_reliability_level)) or "version-1",
    )
    monkeypatch.setattr(generation, "record_wiki_validation", lambda *a, **k: None)
    monkeypatch.setattr(generation, "review_wiki_version", lambda *a, **k: None)
    monkeypatch.setattr(generation, "publish_wiki_version", lambda *a, **k: None)

    page_id, version_id = generation._generate_issue_page(
        _section(), workspace_id="ws-1", requested_by=None,
    )

    assert page_id == "page-1"
    assert version_id == "version-1"
    create_call = next(call for call in calls if call[0] == "create")
    assert create_call[1] is None  # 판정을 못 받았으므로 page_reliability_level은 기록하지 않는다
```

`generate_wiki_drafts_for_sections`의 이슈 페이지 스킵 처리 테스트를 `test_generate_wiki_drafts_for_sections_skips_notification_when_nothing_published`(1349행) 근처에 추가:
```python
def test_generate_wiki_drafts_for_sections_handles_issue_page_skip(monkeypatch):
    def fake_generate_topic_page(section, wiki_contexts, **kwargs):
        return "skip", None, None

    def fake_generate_issue_page(section, **kwargs):
        return None, None  # 신뢰도 낮음으로 스킵된 경우

    monkeypatch.setattr(generation, "_generate_topic_page", fake_generate_topic_page)
    monkeypatch.setattr(generation, "_generate_issue_page", fake_generate_issue_page)
    monkeypatch.setattr(generation, "send_wiki_notification", lambda *a, **k: pytest.fail("호출되면 안 됨"))

    results = generation.generate_wiki_drafts_for_sections(
        [_section("issue-low-reliability")],
        [_enriched_group("issue-low-reliability", candidate_summary="근거")],
        workspace_id="ws-1",
    )

    assert len(results) == 1
    assert results[0].issue_page_id == ""
    assert results[0].issue_version_id == ""
    assert results[0].error_message is None  # 실패가 아니라 정상 스킵이므로 에러 메시지 없음
```

- [ ] **Step 3: 테스트 실행 — 실패 확인 (구현 전)**

Run: `pytest tests/test_wiki_generation.py -k "issue_page or rewrite_issue" -v`
Expected: 새 테스트 및 Step 1에서 고친 4개 테스트 전부 FAIL(리턴 타입이 아직 안 바뀜).

- [ ] **Step 4: `_rewrite_issue_page_content` 리턴 타입 변경**

`src/wiki/generation.py`의 `_rewrite_issue_page_content()`(164-201행)를 아래로 교체:
```python
def _rewrite_issue_page_content(
    section: ReportSectionDraft,
    evidence_texts: dict[str, str] | None = None,
    *,
    llm_client: WikiTopicLLMClient | None = None,
) -> tuple[ReportSectionDraft, PageReliabilityJudgment | None]:
    """이슈 페이지 본문 4개 필드(현재상황/핵심사실/시사점/주시할지점)를 LLM으로 다듬고,
    페이지 신뢰도 판정도 같이 받는다.

    실패(LLM 오류·잘못된 JSON·빈 필드)하면 원본 section을 그대로 반환하고 판정은 None이다
    — 이슈 페이지는 지금까지 LLM 없이도 항상 생성에 성공했으므로, 이 재작성 단계가 그
    신뢰성을 깨서는 안 된다. 판정이 None이면 호출부(_generate_issue_page)가 '보통'으로
    간주하고 발행을 막지 않는다.
    "## 출처" 섹션(_build_issue_page_sources)은 여기서 건드리는 필드와 무관해 영향받지 않는다.
    """
    settings = get_openrouter_settings()
    user_prompt = build_issue_page_rewrite_user_prompt(section, evidence_texts)
    try:
        if llm_client is not None:
            response_text = llm_client(ISSUE_PAGE_REWRITE_SYSTEM_PROMPT, user_prompt, settings.model)
        else:
            response_text = create_json_completion(
                system_prompt=ISSUE_PAGE_REWRITE_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                model=settings.model,
            )
        payload = parse_json_response(response_text)
        result = IssuePageRewriteResult.model_validate(payload)
    except Exception as exc:  # noqa: BLE001 — 이 함수는 항상 성공해야 하므로 모든 실패를 폴백으로 흡수한다.
        logger.exception(
            "issue_page_rewrite_llm_fallback",
            extra={"issue_key": section.issue_key, "error": str(exc)},
        )
        return section, None

    rewritten = section.model_copy(update={
        "current_summary": result.current_summary,
        "key_facts": result.key_facts,
        "implications": result.implications,
        "watch_points": result.watch_points,
    })
    return rewritten, result.reliability
```

- [ ] **Step 5: `_generate_issue_page` 게이트 + 리턴 타입 변경**

`_generate_issue_page()`(204-262행)를 아래로 교체:
```python
def _generate_issue_page(
    section: ReportSectionDraft,
    *,
    workspace_id: str,
    requested_by: str | None,
    parent_page_id: str | None = None,
    evidence_texts: dict[str, str] | None = None,
    citation_attribution: dict[str, ReportCandidate] | None = None,
    supabase: Client | None = None,
    llm_client: WikiTopicLLMClient | None = None,
) -> tuple[str | None, str | None]:
    rewritten_section, reliability = _rewrite_issue_page_content(section, evidence_texts, llm_client=llm_client)

    if reliability is not None and reliability.reliability_level == ReliabilityLevel.LOW:
        logger.info(
            "wiki_issue_page_skipped_low_reliability",
            extra={"issue_key": section.issue_key, "reliability_score": reliability.reliability_score},
        )
        return None, None

    matched = find_matching_issue_page(
        workspace_id,
        category=section.category.value,
        document_version_ids=[c.document_version_id for c in section.news_citations],
        supabase=supabase,
    )

    if matched is not None:
        page_id = matched.page_id
        draft_slug = matched.slug
        draft_title = matched.title
        draft_page_type = matched.page_type
        draft_parent_page_id = matched.parent_page_id if matched.parent_page_id is not None else parent_page_id
    else:
        page_id = upsert_wiki_page(
            workspace_id,
            section.issue_key,
            section.title,
            "issue",
            parent_page_id,
            supabase=supabase,
        )
        draft_slug = section.issue_key
        draft_title = section.title
        draft_page_type = "issue"
        draft_parent_page_id = parent_page_id

    draft = WikiDraftInput(
        workspace_id=workspace_id,
        slug=draft_slug,
        title=draft_title,
        page_type=draft_page_type,
        parent_page_id=draft_parent_page_id,
        markdown=_build_issue_page_markdown(rewritten_section, evidence_texts, citation_attribution),
        sources=_build_issue_page_sources(section, evidence_texts),
        change_summary=(
            "리포트 파이프라인에서 기존 이슈 페이지 갱신" if matched is not None else "리포트 파이프라인에서 자동 생성"
        ),
        created_by=requested_by,
        generated_by="llm",
        page_reliability_score=reliability.reliability_score if reliability is not None else None,
        page_reliability_level=reliability.reliability_level.value if reliability is not None else None,
        page_reliability_detail=reliability.model_dump() if reliability is not None else None,
    )
    version_id = create_wiki_version(draft, supabase=supabase)
    record_wiki_validation(version_id, "passed", None, supabase=supabase)
    review_wiki_version(version_id, None, "approved", supabase=supabase)
    publish_wiki_version(page_id, version_id, supabase=supabase)
    return page_id, version_id
```

- [ ] **Step 6: `generate_wiki_drafts_for_sections`의 이슈 페이지 스킵 처리**

`generate_wiki_drafts_for_sections()`(433-546행)에서 이슈 페이지 호출부(498-522행)를 아래로 교체:
```python
        try:
            issue_page_id, issue_version_id = _generate_issue_page(
                section,
                workspace_id=workspace_id,
                requested_by=requested_by,
                parent_page_id=topic_page_id,
                evidence_texts=evidence_texts,
                citation_attribution=citation_attribution,
                supabase=supabase,
                llm_client=llm_client,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("wiki_issue_page_generation_failed", extra={"issue_key": section.issue_key})
            results.append(
                WikiDraftGenerationResult(
                    issue_key=section.issue_key,
                    issue_page_id="",
                    issue_version_id="",
                    topic_action=topic_action,
                    topic_page_id=topic_page_id,
                    topic_version_id=topic_version_id,
                    error_message=str(exc) if topic_error is None else f"{topic_error}; {exc}",
                )
            )
            continue

        results.append(
            WikiDraftGenerationResult(
                issue_key=section.issue_key,
                issue_page_id=issue_page_id or "",
                issue_version_id=issue_version_id or "",
                topic_action=topic_action,
                topic_page_id=topic_page_id,
                topic_version_id=topic_version_id,
                error_message=topic_error,
            )
        )
```
(변경점: 마지막 `results.append(...)`에서 `issue_page_id`/`issue_version_id`를 그대로 넣던 것을 `issue_page_id or ""`/`issue_version_id or ""`로 바꿔, `None`(스킵)일 때 기존 실패 케이스와 동일한 빈 문자열 관례를 따르게 한다. `error_message=topic_error`는 그대로라 스킵된 이슈 페이지는 `topic_error`가 없는 한 `None`으로 유지된다.)

`published_count` 집계(536-538행)는 이미 `if result.issue_page_id else 0` truthy 체크라 수정 불필요.

- [ ] **Step 7: 테스트 실행 — 통과 확인**

Run: `pytest tests/test_wiki_generation.py -v`
Expected: 전체 PASS(기존 950-1263행대의 이슈 페이지 테스트들 포함 — 전부 "보통" 이상 경로이므로 리턴값이 여전히 실제 id 두 개라 회귀 없음).

- [ ] **Step 8: 전체 회귀 확인**

Run: `pytest tests/test_wiki_generation.py tests/test_wiki_generation_models.py tests/test_wiki_generation_prompts.py tests/test_wiki_service.py -v`
Expected: 전체 PASS.

- [ ] **Step 9: Commit**

```bash
git add src/wiki/generation.py tests/test_wiki_generation.py
git commit -m "Feat: 이슈 페이지 생성에 신뢰도 자율 판정 발행 게이트 적용"
```

---

### Task 6: ERDCloud + docs 동기화

**Files:**
- Modify: `docs/architecture/myWiki_v2.sql`
- Modify: `docs/architecture/myWiki_v2_supabase.sql`
- ERDCloud 다이어그램 (MCP)

**Interfaces:**
- Consumes: Task 1에서 라이브 DB에 이미 적용된 3개 컬럼(`page_reliability_score`/`page_reliability_level`/`page_reliability_detail`) — 이 태스크는 문서만 그 실제 상태에 맞춘다.

- [ ] **Step 1: `myWiki_v2_supabase.sql`의 `wiki_page_versions` 정의 갱신**

`docs/architecture/myWiki_v2_supabase.sql`의 `CREATE TABLE wiki_page_versions`(274-292행)에서 `confidence_score NUMERIC,` 다음에 추가:
```sql
    page_reliability_score      INTEGER,
    page_reliability_level      VARCHAR,
    page_reliability_detail     JSONB,
```
파일 상단 변경 이력 주석 블록(28행 근처, 마지막 항목 다음)에 새 항목 추가:
```sql
--  29) [8/10] wiki_page_versions.page_reliability_score/level/detail 추가
--      (야간 배치 위키 페이지 생성 LLM의 자율 신뢰도 판정 + 발행 게이트)
```
CHECK 제약 섹션(파일 하단, `ck_wpv_validation_status`/`ck_wpv_review_status` 근처)에 추가:
```sql
ALTER TABLE wiki_page_versions ADD CONSTRAINT ck_wpv_page_reliability_score
  CHECK (page_reliability_score IS NULL OR (page_reliability_score >= 0 AND page_reliability_score <= 100));
ALTER TABLE wiki_page_versions ADD CONSTRAINT ck_wpv_page_reliability_level
  CHECK (page_reliability_level IS NULL OR page_reliability_level IN ('낮음', '보통', '높음'));
```

- [ ] **Step 2: `myWiki_v2.sql`(ERDCloud import용) 동일 반영**

`docs/architecture/myWiki_v2.sql`의 `wiki_page_versions` 정의에도 Step 1과 동일하게 3개 컬럼 + CHECK 제약을 추가한다(이 파일은 backtick 문법이므로 기존 파일의 다른 CHECK 제약 표기 스타일을 그대로 따른다).

- [ ] **Step 3: ERDCloud 다이어그램 갱신**

`mcp__erdcloud__add_column`으로 `wiki_page_versions` 테이블에 컬럼 3개를 추가한다(`page_reliability_score`: INTEGER, `page_reliability_level`: VARCHAR, `page_reliability_detail`: JSONB — 전부 nullable). `create_relation`은 쓰지 않는다(새 FK 관계가 아니므로).

- [ ] **Step 4: 반영 확인**

`mcp__erdcloud__get_table`로 `wiki_page_versions`를 조회해서 컬럼 3개가 실제로 보이는지 확인한다.

- [ ] **Step 5: Commit**

```bash
git add docs/architecture/myWiki_v2.sql docs/architecture/myWiki_v2_supabase.sql
git commit -m "Docs: wiki_page_versions 신뢰도 판정 컬럼 ERDCloud/스키마 문서 동기화"
```

---

## Self-Review 결과

- **스펙 커버리지**: 목표 1-5, 범위(야간 배치만), 판정 기준 4항목(40/20/20/20), 게이트 위치(DB 쓰기 전), DB 스키마, 쓰기 경로, ERDCloud/docs 동기화, 에러 처리(토픽 필수/이슈 폴백), 테스트 절의 5개 항목 — 전부 Task 1-6에 대응됨. 확인 완료.
- **플레이스홀더 스캔**: "TBD"/"적절히 처리" 류 표현 없음. Task 4 Step 2의 "나머지 15곳"은 정확한 라인 번호 전체를 명시했고 변형이 동일 패턴이라 모호하지 않음.
- **타입 일관성**: `_rewrite_issue_page_content` 리턴 `tuple[ReportSectionDraft, PageReliabilityJudgment | None]`, `_generate_issue_page` 리턴 `tuple[str | None, str | None]`, `_generate_topic_page` 리턴 `tuple[str, str | None, str | None]`(변경 없음) — Task 4/5 본문과 스펙이 일치함을 재확인.

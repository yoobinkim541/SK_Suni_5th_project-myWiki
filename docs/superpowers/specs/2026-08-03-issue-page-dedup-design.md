# 이슈 위키 페이지 중복 생성 방지 설계

> 기준일: 2026-08-03
> 담당: 김유빈 (Wiki·지식베이스)
> 대상 파일: `src/wiki/generation_repository.py`, `src/wiki/generation.py`

---

## 1. 문제

`_generate_issue_page()`는 `section.issue_key`(리포트 그룹핑 단계가 멤버 `analysis_result_id` 집합의 해시로 만든 값, `report/grouper.py` 소유 — 이 설계에서 건드리지 않음)를 slug로 써서 이슈 위키 페이지를 만든다. 같은 사건이 여러 리포트/갱신 주기에 걸쳐 계속 보도되면 매번 그룹 멤버 구성이 달라져 `issue_key`가 매번 바뀌고, 그 결과 같은 사건에 대해 새 `wiki_pages` 행이 계속 생긴다. 2시간 주기 갱신(`feature/wiki-periodic-refresh`, 별도 PR)이 이 문제를 하루 최대 12배로 증폭시킨다.

## 2. 핵심 원칙

- `report/grouper.py`(다른 파트도 공유하는 이미 배포된 로직)는 건드리지 않는다. `issue_key` 자체를 안정화하지 않고, 위키 쪽에서 "같은 사건인지" 별도로 판단한다.
- 스키마 변경 없음 — `wiki_pages`에 category 컬럼을 추가하지 않는다. 매칭 시점에 후보 페이지의 출처 문서로부터 카테고리를 그때그때 조회한다.
- 이미 주제 페이지(`_generate_topic_page`)가 쓰는 "기존 것과 매칭 vs 신규 생성" 패턴과 `get_wiki_page_identity` 기반 멱등 갱신 방식을 그대로 재사용한다.

## 3. 매칭 기준

- **후보 범위**: `page_type='issue'`, `status='published'`, 현재 버전(`current_version_id`)의 `created_at`이 최근 7일 이내인 페이지만.
- **1차 필터**: 이번 이슈의 근거 문서(`section.news_citations`의 `document_version_id` 집합)와 `wiki_page_sources.document_version_id`가 하나라도 겹치는 후보만 남긴다.
- **카테고리 확인**: 후보 페이지의 출처 `document_version_id`들을 `document_analysis_results.primary_category`로 역조회해서, 이번 `section.category`와 같은 카테고리가 하나라도 있는지 확인한다.
- **과반수 확인**: 겹치는 문서 수 / 이번 이슈의 근거 문서 수 >= 0.5.
- 카테고리 확인과 과반수 확인을 모두 통과한 후보만 매칭으로 인정한다. 여러 후보가 통과하면 겹침 비율이 가장 높은 것을, 동률이면 `current_version_id`가 가리키는 버전의 `created_at`이 더 최신인 것을 고른다.

## 4. 신규 함수

`src/wiki/generation_repository.py`에 추가:

```python
def find_matching_issue_page(
    workspace_id: str,
    *,
    category: str,
    document_version_ids: list[str],
    within_days: int = 7,
    supabase: Client | None = None,
) -> WikiPageIdentity | None:
```

내부적으로 `document_version_ids`가 비어 있으면 즉시 `None`을 반환한다(근거 없는 이슈는 애초에 `_generate_issue_page`까지 오지 않지만 방어적으로).

## 5. `_generate_issue_page` 변경

기존 흐름(`upsert_wiki_page(workspace_id, section.issue_key, section.title, "issue", parent_page_id)` → `WikiDraftInput(slug=section.issue_key, ...)`)을, `_generate_topic_page`의 `update_existing` 분기와 동일한 패턴으로 바꾼다:

```
matched = find_matching_issue_page(workspace_id, category=section.category.value, document_version_ids=[c.document_version_id for c in section.news_citations])

매칭됨:
  slug/title/page_type/parent_page_id는 matched(기존 페이지)의 값을 그대로 쓴다.
  (upsert_wiki_page가 ignore_duplicates=True라 title 등은 실제로 안 바뀐다 — 주제 페이지와 동일한 기존 제약.
   markdown 본문만 이번 섹션의 최신 스냅샷으로 완전히 교체된다.)

매칭 안 됨:
  기존 그대로 — slug=section.issue_key로 upsert_wiki_page 호출 후 신규 생성.
```

`page_id`를 얻는 방식(매칭 시 `matched.page_id`, 신규 시 `upsert_wiki_page()` 반환값)만 분기하고, 그 이후 `create_wiki_version` → `record_wiki_validation` → `review_wiki_version` → `publish_wiki_version`(confidence 게이트 없이 항상 발행) 흐름은 기존과 동일하게 유지한다.

## 6. 에러 처리

`find_matching_issue_page` 조회 자체가 실패하면(DB 오류 등) 예외를 그대로 전파한다 — `_generate_issue_page`를 감싸는 기존 이슈 단위 try/except(`generate_wiki_drafts_for_sections`)가 이미 이걸 처리하므로 별도 방어 로직을 추가하지 않는다.

## 7. 테스트

- `find_matching_issue_page`: 7일 이내/이후 경계, 카테고리 불일치, 과반수 미달, 여러 후보 중 최고 비율 선택, `page_type != 'issue'`인 페이지(주제 페이지)는 후보에서 제외, 빈 `document_version_ids` 즉시 `None`.
- `_generate_issue_page`: 매칭 시 기존 페이지 identity로 draft를 만드는지(신규 slug/title이 아니라), 매칭 안 될 때 기존 동작(신규 생성) 그대로인지.

## 8. 이번 설계에 포함하지 않는 것

- `wiki_pages`에 category 컬럼 추가 — 매칭 시점 역조회로 대체.
- 주제 페이지 쪽 매칭 로직 변경 — 이미 잘 동작하므로 그대로 둠.
- `report/grouper.py`의 `issue_key` 안정화 — 다른 파트 소유, 범위 밖.

# 위키 page_type 확장 — 설계 문서

날짜: 2026-08-04
작성: 김유빈 (Wiki·지식베이스 담당) + Claude Code

## 배경

`wiki-refresh-gate.yml`이 30분마다 정상적으로 돌고 있었지만, 실제 published 위키 페이지는
수동으로 만든 테스트 문서 1건뿐이었다. 원인을 추적한 결과 두 겹의 문제가 있었다.

1. **1차 원인 (이미 해결됨)**: 리포트/위키 후보 선정 기준이 너무 엄격해서 후보가 0건으로
   나오고 있었다 — PR #36에서 이미 수정됨.
2. **2차 원인 (이 설계의 대상)**: 후보 선정이 고쳐진 뒤 VM에서 `refresh_wiki_from_recent_analysis()`를
   직접 실행해 확인해보니, "시장·경영" 카테고리 이슈 3건이 전부 아래 에러로 실패했다.

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for WikiTopicLLMResult
page_type
  Input should be 'industry', 'company', 'technology' or 'term' [input_value='market_management', ...]
```

"제품·기술" 카테고리 1건은 정상적으로 성공(`topic_action=create_new`)했다 — 파이프라인 자체는
정상이고, 리포트의 6종 카테고리 중 3종(시장·경영/정책·규제/공급망·생산)이 위키 topic
`page_type` 4종(industry/company/technology/term)에 대응하는 값이 없어서, LLM이 없는 값을
지어내고 있었다.

## 결정한 접근

리포트 카테고리 ↔ 위키 page_type을 1:1로 맞춘다(3가지 대안 중 "분류 체계 자체를 확장" 선택 —
프롬프트 매핑 지침만 추가하는 임시방편이나 재시도 루프보다, 애초에 선택지를 리포트 6종과
맞추는 게 근본적인 해결이라고 판단).

**범위**: 위키 topic page_type ↔ 리포트 6종 카테고리만 맞춘다. `CategoryPage`(메모리/파운드리/장비)
까지 포함한 3자 통일은 이번 범위 밖 — 7/30에 보류됐던 별도 이슈로 남겨둔다.

## 새 page_type 분류 체계

| 리포트 카테고리 | wiki page_type | 비고 |
|---|---|---|
| 제품·기술 | `technology` | 기존 값 |
| 경쟁사 | `company` | 기존 값 |
| 고객·수요산업 | `industry` | 기존 값 |
| 공급망·생산 | `supply_chain` | 신규 |
| 정책·규제 | `policy` | 신규 |
| 시장·경영 | `market` | 신규 (오늘 실패한 케이스) |

`term`(용어)·`issue`(개별 이슈 페이지)는 리포트 카테고리와 무관하게 그대로 유지한다.

**최종 `page_type` 전체 값(8종)**: `industry, company, technology, supply_chain, policy, market, issue, term`

## 변경 사항

### 1. DB 스키마
`wiki_pages`의 `ck_wp_page_type` CHECK 제약을 8종으로 확장하는 마이그레이션.
기존 데이터는 순수 확장이라 영향 없음(현재 published 1건, `page_type='issue'`).

### 2. 백엔드 타입
- `src/wiki/interface.py`의 `PageType` — 8종으로 확장
- `src/wiki/generation_models.py`의 `TopicPageType` — `issue` 제외 7종으로 확장

### 3. LLM 프롬프트 (`src/wiki/generation_prompts.py`)
- 시스템 프롬프트 JSON 스펙의 `page_type` 허용값을 7종으로 확장
- 사용자 프롬프트는 이미 `카테고리: {section.category.value}`(예: "시장·경영")를 그대로 전달하고
  있었다 — 지금까지는 대응하는 선택지가 없어서 실패했을 뿐, 이제 카테고리명과 거의 1:1로
  대응되므로(시장·경영→market 등) 큰 매핑 설명 없이도 해결될 가능성이 높다. 이름이 직접 안
  겹치는 2개(고객·수요산업→industry, 경쟁사→company)만 짧은 안내를 추가한다.

### 4. 안전망 (defense-in-depth)
`_generate_topic_page`에서 `WikiTopicLLMResult` 검증 실패 시 즉시 실패 처리하지 않고
`page_type='industry'`로 대체 + 경고 로그를 남기도록 폴백을 추가한다. 프롬프트를 고쳐도
LLM이 또 다른 값을 지어낼 가능성은 남아있으므로, 페이지 생성 자체가 막히는 것만은 방지한다.

### 5. 프론트엔드
`frontend/src/api/wiki.js`의 `WIKI_PAGE_TYPE_LABELS`에 3개 라벨 추가:
`supply_chain: '공급망·생산'`, `policy: '정책·규제'`, `market: '시장·경영'`

## 검증 계획

1. 로컬/VM에서 유닛 테스트 실행 (`tests/test_wiki_generation*.py` 등)
2. 마이그레이션을 실제 Supabase 프로젝트에 적용
3. VM에 배포된 코드로 `refresh_wiki_from_recent_analysis()`를 직접 실행해, 오늘 실패했던
   "시장·경영" 카테고리 이슈가 이제 성공하는지 확인 (필요하면 폴백 없이 정확한 값으로
   성공하는지까지 확인)
4. 프론트 빌드 확인, 실제 화면에서 새 카테고리 라벨이 정상 표시되는지 확인

## 롤아웃

- 백엔드(마이그레이션 + 타입 + 프롬프트 + 폴백): `develop` 브랜치 PR
- 프론트(라벨): `develop-frontend` 브랜치 PR
- 각각 머지되면 기존 CI/CD가 자동 배포

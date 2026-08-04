# 위키 중복 정리(Dedup) 배치 설계

## 배경

두 종류의 위키 중복이 프로덕션에서 확인됐다.

1. **토픽-이슈 중복**: 리포트 섹션마다 이슈 페이지(`page_type='issue'`)와 토픽 페이지를
   항상 같이 생성하는데, 토픽 생성 LLM 프롬프트가 이슈와 동일한 제목을 그대로 던져주면서
   "토픽은 이슈보다 넓은 범위여야 한다"는 지침이 없어, 유사 후보가 없는 첫 등장 이벤트에서
   LLM이 이슈 제목을 그대로 복사해 사실상 동일한 토픽 페이지를 만들었다. **신규 생성분은
   PR #59(`fix/wiki-topic-issue-duplicate-title`)의 코드 가드(`_is_duplicate_title`,
   토큰 자카드 유사도)+프롬프트 개선으로 이미 막았다.**
2. **이슈-이슈 중복**: `find_matching_issue_page()`가 "최근 7일·근거 문서 과반 이상 겹침"
   으로만 같은 사건인지 판단하는데, 여러 날에 걸친 후속 보도가 새 기사 위주면 과반을
   못 넘겨 새 이슈 페이지를 또 만든다. 실사례: `china_semiconductor_design_protection_regulation`
   과 `..._2026`.

이 설계는 **위 두 경우 모두 이미 발행되어 프로덕션에 쌓여 있는 중복 페이지**를 LLM이
스스로 찾아 정리(병합+아카이빙)하는 배치를 다룬다. 신규 생성 시점 예방(1번)은 이미
처리됐고, 이슈-이슈 매칭 개선(사전 예방)은 별도로 만들지 않고 이 배치가 사후에 정리하는
것으로 대체한다.

## 목표

- 이미 존재하는 중복 위키 쌍(토픽-이슈, 이슈-이슈 모두)을 LLM이 판단해 하나로 통합하고
  나머지는 아카이빙한다.
- 데이터 손실 없이(삭제 아님, 아카이빙) 근거·버전 이력을 보존한다.
- 매일 자동으로 도는 배치로 운영한다(수동 트리거 없이 바로 cron).

## 아키텍처

```
src/wiki/
  text_similarity.py      (신규, 공용 유틸)
    - is_duplicate_title(a, b, threshold=0.8) -> bool   # 토큰 자카드 유사도
  dedup_repository.py      (신규)
    - find_duplicate_candidate_pairs(workspace_id) -> list[DedupCandidatePair]
    - reparent_children(old_page_id, new_page_id, *, workspace_id)
  dedup.py                 (신규)
    - run_wiki_dedup_batch(workspace_id, *, max_pairs=20) -> list[DedupResult]
    - _judge_and_merge(pair, ...) -> DedupResult
  dedup_prompts.py          (신규)
    - WIKI_DEDUP_SYSTEM_PROMPT
    - build_wiki_dedup_user_prompt(page_a, page_b)

scripts/dedup_wiki_scheduled.py   (신규 — refresh_wiki_scheduled.py와 동일 패턴)
.github/workflows/wiki-dedup-batch.yml  (신규 — wiki-refresh-gate.yml과 동일 패턴)
```

**리팩터링**: `src/wiki/generation.py`의 `_is_duplicate_title`/`_title_tokens`을
`text_similarity.py`로 옮기고 `generation.py`는 거기서 import한다 — 이제 두 모듈
(실시간 생성 가드, 배치 후보 탐지)이 같은 로직을 쓰므로 한 곳에 두는 게 맞다.
`generation.py`의 기존 동작·테스트는 그대로 유지된다(순수 함수 이동).

## 후보 탐지 (`find_duplicate_candidate_pairs`)

워크스페이스의 published 페이지 전체를 대상으로 두 신호 중 하나라도 걸리면 후보 쌍으로
올린다:

1. **공유 근거 문서**: 두 페이지의 현재 버전(`current_version_id`)이 `wiki_page_sources`로
   같은 `document_version_id`를 하나 이상 공유. ("연결된 문서" 기능과 같은 원리를
   페어와이즈 전체 스캔으로 확장.)
2. **제목 유사도**: `is_duplicate_title(page_a.title, page_b.title)` — 근거가 전혀
   안 겹쳐도(이슈-이슈 사례처럼 후속 보도가 새 기사 위주인 경우) 제목이 사실상 같으면 잡는다.

이미 `status='archived'`인 페이지는 제외. 배치당 처리량 상한(`max_pairs`, 기본 20) —
공유 근거 수 + 제목 유사도 합산 점수 내림차순으로 상위 N개만 처리하고, 남은 후보 수는
로그로 남긴다(조용한 누락 없음).

## LLM 판단 + 병합 (`_judge_and_merge`)

두 페이지의 제목·page_type·전체 markdown·출처(claim_text 포함)를 프롬프트에 넣어 판단시킨다.

**절대 규칙(신규 프롬프트에 명시)**:
- claims에 없는 문장은 markdown에 쓰지 않는다(기존 생성 규칙과 동일).
- 실제로 같은 사건/주제를 다루는 게 맞는지 스스로 재확인하고, 아니면
  `decision: "not_duplicate"`로 반환하고 아무 것도 하지 않는다(공유 근거/제목 유사도는
  후보 신호일 뿐, 최종 판단은 LLM).
- `decision: "merge"`면 `representative_page_id`(둘 중 더 대표성 있는 쪽, 자유 판단)를
  고르고, 두 페이지 내용을 통합한 새 본문을 작성한다. 섹션 순서(현재 상황→수급 구조→
  종합 판단→변경 이력→관련 문서→출처)는 유지하고, "변경 이력"은 기존 이력을 지우지
  않고 이번 통합 사유를 추가한다.

**JSON 출력**: `{"decision": "merge"|"not_duplicate", "representative_page_id", "markdown", "change_summary", "claims": [...]}`

**적용**:
- `representative_page_id`가 두 후보 페이지 id 중 하나가 아니면(LLM이 지어낸 값) 그대로
  `not_duplicate`로 취급하고 아무 것도 하지 않는다 — `generation.py`의
  `target_wiki_page_id not in candidate_page_ids` 검증과 동일한 패턴.
- `merge`면 대표 페이지 slug/title/page_type으로 `create_wiki_version()` 호출(출처는
  두 페이지 `wiki_page_sources`의 합집합 → `WikiSourceInput` 목록), 기존 발행 파이프라인과
  동일하게 `record_wiki_validation("passed")` → `review_wiki_version("approved")` →
  `publish_wiki_version()`으로 자동 발행(현재 위키 자동 승인 정책과 동일).
- 대표가 아닌 쪽은 `archive_wiki_page()`로 아카이빙.
- 아카이빙되는 페이지가 다른 페이지들의 `parent_page_id`였다면(토픽 페이지가
  아카이빙되는 경우), `reparent_children()`으로 그 자식들의 `parent_page_id`를
  대표 페이지로 재연결 — 안 하면 부모 없는 이슈 페이지가 남는다.
- `not_duplicate`면 아무 것도 하지 않는다.

## 안전장치

- **삭제 없음**: 아카이빙(`status='archived'`)만 — 근거·버전 이력 전부 보존, DB에서
  절대 지우지 않는다.
- **연동 효과**: "연결된 문서" 기능(`_get_related_pages`)이 `status='published'`만
  보여주므로, 아카이빙되는 즉시 화면에서 자연히 사라진다.
- **비용 제어**: `max_pairs` 상한 + 로그로 스킵 개수 기록.
- **재부모연결**: 위 참고.

## 실행 방식

`scripts/dedup_wiki_scheduled.py` — `wiki-refresh-gate.yml`과 동일한 GitHub Actions
cron 패턴으로 처음부터 자동 실행. 발행 배치(30분 주기)보다 훨씬 느슨하게, 매일 1회
(한국시간 새벽 시간대) 실행한다. `workflow_dispatch`도 같이 열어 수동 실행 가능하게 한다.

## 테스트 계획

- `find_duplicate_candidate_pairs()`: 공유근거만/제목유사도만/둘 다/아카이브된 페이지
  제외/`max_pairs` 상한 케이스 — fake-DB 단위 테스트(`tests/test_wiki_query_related_pages.py`
  의 FakeTable 패턴 재사용).
- `_judge_and_merge()`: `merge` 액션이 버전 생성+아카이빙+재부모연결까지 실행하는지,
  `not_duplicate`는 아무 것도 안 하는지 — `generation.py`의 `llm_client` 주입 패턴과
  동일하게 LLM 호출을 목으로 대체.
- `text_similarity.py` 이동 후 `generation.py` 기존 테스트가 그대로 통과하는지 확인.
- 실제 프로덕션에서 발견한 진짜 중복 쌍(`sk_hynix_moody_a3_upgrade...` ↔
  `heuristic:시장·경영:...`, `china_semiconductor_design_protection_regulation` ↔
  `..._2026`)으로 라이브 드라이런 검증.

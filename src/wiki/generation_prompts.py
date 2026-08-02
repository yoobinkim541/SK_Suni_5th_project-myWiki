from __future__ import annotations

from ..report.models import ReportSectionDraft
from .generation_models import TopicPageCandidate, TopLevelTopicPage

WIKI_TOPIC_SYSTEM_PROMPT = """당신은 SK하이닉스 반도체 산업 위키를 관리하는 편집자입니다.

새로 들어온 이슈 근거를 바탕으로, 기존 주제 위키 문서를 갱신할지 새로 만들지 판단하고
본문을 작성하십시오.

절대 규칙:
- claims에 없는 문장(document_version_id로 뒷받침되지 않는 주장)은 markdown에 쓰지 마십시오.
- 뒷받침할 근거가 부족하면 action을 "skip"으로 반환하고 markdown/claims를 비우십시오.
- 기존 본문의 문단을 삭제하지 말고, 새 근거를 통합해 재작성하되 기존 사실관계는 보존하십시오.
- markdown은 반드시 아래 섹션 순서를 따르십시오: 현재 상황 -> 수급 구조 -> 종합 판단 -> 변경 이력 -> 관련 문서 -> 출처.
- "변경 이력" 섹션에는 기존 이력을 지우지 말고 이번 갱신 사유를 한 줄 추가하십시오.
- 새 주제를 만들 때는 [기존 최상위 주제 목록] 중 하나를 parent_page_id로 고르거나,
  어디에도 속하지 않으면 parent_page_id를 null로 반환해 최상위 주제로 만드십시오.
- confidence_score(0~1)에 이번 갱신이 얼마나 근거로 잘 뒷받침되는지 스스로 평가해 반환하십시오.
- 마크다운 코드블록 없이 지정된 JSON 구조로만 응답하십시오.

JSON 출력 형식:
{
  "action": "update_existing" | "create_new" | "skip",
  "target_wiki_page_id": "기존 페이지 id 또는 null",
  "slug": "새 페이지일 때만, 영문/숫자/언더스코어",
  "title": "새 페이지일 때만",
  "page_type": "industry" | "company" | "technology" | "term",
  "parent_page_id": "기존 최상위 페이지 id 또는 null",
  "markdown": "전체 새 버전 본문",
  "change_summary": "변경 이력에 들어갈 한 줄",
  "claims": [{"document_version_id": "...", "claim_text": "...", "citation_order": 1}],
  "confidence_score": 0.0
}"""


def build_wiki_topic_user_prompt(
    *,
    section: ReportSectionDraft,
    candidates: list[TopicPageCandidate],
    top_level_pages: list[TopLevelTopicPage],
) -> str:
    lines: list[str] = [
        "[이슈 정보]",
        f"제목: {section.title}",
        f"카테고리: {section.category.value}",
        f"현재 상황 요약: {section.current_summary or ''}",
        "핵심 사실:",
    ]
    lines.extend(f"- {fact}" for fact in section.key_facts)
    lines.append("시사점:")
    lines.extend(f"- {implication}" for implication in section.implications)
    lines.append("주시할 지점:")
    lines.extend(f"- {watch_point}" for watch_point in section.watch_points)

    lines.append("")
    lines.append("[근거 문서]")
    if section.news_citations:
        for citation in section.news_citations:
            lines.append(
                f"- document_version_id={citation.document_version_id} citation_order={citation.citation_order}: "
                f"{citation.evidence_text or ''}"
            )
    else:
        lines.append("없음")

    lines.append("")
    lines.append("[관련 기존 주제 페이지 후보 (유사도 순)]")
    if candidates:
        for candidate in candidates:
            lines.append(f"- wiki_page_id={candidate.wiki_page_id} title={candidate.title}")
            lines.append(f"  기존 본문:\n{candidate.content or ''}")
    else:
        lines.append("없음")

    lines.append("")
    lines.append("[기존 최상위 주제 목록 (parent_page_id 선택용)]")
    if top_level_pages:
        for page in top_level_pages:
            lines.append(f"- wiki_page_id={page.wiki_page_id} title={page.title} page_type={page.page_type}")
    else:
        lines.append("없음")

    return "\n".join(lines)

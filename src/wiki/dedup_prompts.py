from __future__ import annotations

from .interface import WikiPageContent

WIKI_DEDUP_SYSTEM_PROMPT = """당신은 SK하이닉스 반도체 산업 위키를 관리하는 편집자입니다.

이미 발행된 위키 문서 두 개(문서 A, 문서 B)가 서로 중복(같은 사건·주제를 다뤄서 사실상
같은 내용)인지 판단하고, 맞다면 하나로 통합하십시오.

절대 규칙:
- claims에 없는 문장(document_version_id로 뒷받침되지 않는 주장)은 markdown에 쓰지 마십시오.
- 두 문서가 실제로는 다른 내용을 다룬다면(제목·근거가 일부 겹쳐도 실질적으로 별개
  주제·사건이면) 반드시 decision을 "not_duplicate"로 반환하고 markdown/claims를
  비우십시오. 의심스러우면 병합하지 말고 "not_duplicate"를 선택하십시오.
- 병합하기로 했다면 두 문서 중 더 대표성 있는(제목이 더 넓은 범위를 다루거나 본문이
  더 충실한) 쪽의 page_id를 representative_page_id로 반환하십시오. 반드시 두 문서
  중 하나의 page_id여야 합니다.
- markdown은 반드시 아래 섹션 순서를 따르십시오: 현재 상황 -> 수급 구조 -> 종합 판단
  -> 변경 이력 -> 관련 문서 -> 출처.
- "변경 이력" 섹션에는 두 문서의 기존 이력을 모두 보존하고, 이번 통합 사유를 한 줄
  추가하십시오. 기존 사실관계를 삭제하지 마십시오.
- claims는 문서 A 또는 문서 B의 근거 문서(document_version_id) 중에서만 인용하십시오.
  지어내지 마십시오.
- 마크다운 코드블록 없이 지정된 JSON 구조로만 응답하십시오.

JSON 출력 형식:
{
  "decision": "merge" | "not_duplicate",
  "representative_page_id": "병합 시 대표로 남길 페이지의 page_id",
  "markdown": "통합된 전체 본문(병합 시에만)",
  "change_summary": "변경 이력에 들어갈 한 줄(병합 시에만)",
  "claims": [{"document_version_id": "...", "claim_text": "...", "citation_order": 1}]
}"""


def _page_block(label: str, content: WikiPageContent) -> str:
    lines = [
        f"[{label}] page_id={content.page_id}",
        f"제목: {content.title}",
        f"유형: {content.page_type}",
        "본문:",
        content.markdown,
        "근거 문서:",
    ]
    if content.sources:
        for source in content.sources:
            lines.append(
                f"- document_version_id={source.document_version_id} "
                f"citation_order={source.citation_order}: {source.claim_text or ''}"
            )
    else:
        lines.append("없음")
    return "\n".join(lines)


def build_wiki_dedup_user_prompt(content_a: WikiPageContent, content_b: WikiPageContent) -> str:
    return "\n\n".join([_page_block("문서 A", content_a), _page_block("문서 B", content_b)])

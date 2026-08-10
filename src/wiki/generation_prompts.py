from __future__ import annotations

from datetime import datetime

from ..report.models import ReportCandidate, ReportSectionDraft
from .generation_models import TopicPageCandidate, TopLevelTopicPage

WIKI_TOPIC_SYSTEM_PROMPT = """당신은 SK하이닉스 반도체 산업 위키를 관리하는 편집자입니다.

새로 들어온 이슈 근거를 바탕으로, 기존 주제 위키 문서를 갱신할지 새로 만들지 판단하고
본문을 작성하십시오.

절대 규칙:
- 이 이슈 자체는 별도의 "이슈 페이지"로 항상 자동 생성됩니다. 여기서 당신이 만들거나
  갱신하는 것은 그보다 상위의 "주제(topic)" 페이지입니다 — 이 이슈 하나만이 아니라
  여러 이슈에 걸쳐 재사용될 수 있는 더 넓은 범위(예: 특정 기업 전체, 기술 전체, 산업
  전체)를 다뤄야 합니다. 새 제목이 [이슈 정보]의 제목을 거의 그대로 반복하거나 이
  이슈 하나만 다루는 좁은 내용이면, 그것은 상위 주제가 아니라 이슈 페이지의 중복이니
  반드시 action을 "skip"으로 반환하십시오.
- claims에 없는 문장(document_version_id로 뒷받침되지 않는 주장)은 markdown에 쓰지 마십시오.
- 뒷받침할 근거가 부족하면 action을 "skip"으로 반환하고 markdown/claims를 비우십시오.
- 기존 본문의 문단을 삭제하지 말고, 새 근거를 통합해 재작성하되 기존 사실관계는 보존하십시오.
- markdown은 반드시 아래 섹션 순서를 따르십시오: 현재 상황 -> 수급 구조 -> 종합 판단 -> 변경 이력 -> 관련 문서 -> 출처.
- "출처" 섹션은 각 근거 문서마다 "{기사 제목} · {매체명} · {날짜}" 형식으로 한 줄씩
  쓰십시오(예: "삼성전자, HBM4 양산 돌입 - 전자신문 · Google RSS - 삼성전자 · 2026.07.10").
  아래 [근거 문서] 목록에 제공된 제목·매체명·날짜를 그대로 쓰고, document_version_id는
  claims 배열을 채우는 데만 쓰십시오 — markdown 본문에 document_version_id 문자열을
  그대로 노출하지 마십시오.
- "변경 이력" 섹션에는 기존 이력을 지우지 말고 이번 갱신 사유를 한 줄 추가하십시오.
- 새 주제를 만들 때는 [기존 최상위 주제 목록] 중 하나를 parent_page_id로 고르거나,
  어디에도 속하지 않으면 parent_page_id를 null로 반환해 최상위 주제로 만드십시오.
- page_type은 [이슈 정보]의 카테고리에 맞춰 고르십시오: 제품·기술→technology,
  경쟁사→company, 고객·수요산업→industry, 공급망·생산→supply_chain, 정책·규제→policy,
  시장·경영→market. 이 7종 밖의 값은 절대 반환하지 마십시오.
- confidence_score(0~1)에 이번 갱신이 얼마나 근거로 잘 뒷받침되는지 스스로 평가해 반환하십시오.
- 아래 4개 항목으로 이 페이지 자체의 신뢰도를 직접 판정해 reliability 객체로 반환하십시오.
  grounding_fidelity(0~40, 가장 중요 — 본문의 각 주장이 [근거 문서] 범위를 벗어나 추론·과장한
  부분이 있는지), source_reliability(0~20, [이슈 정보]의 "근거 신뢰도" 값을 참고해 원문 자체의
  신뢰도를 반영), evidence_diversity(0~20, 단일 출처에만 의존하는지), currency(0~20, 근거가
  최근 것인지). reliability_score는 4개 항목의 합, reliability_level은 0~39=낮음/40~69=보통/
  70~100=높음 구간을 그대로 따르십시오. 각 항목마다 reason을 한 문장으로 쓰십시오.
- 마크다운 코드블록 없이 지정된 JSON 구조로만 응답하십시오.

JSON 출력 형식:
{
  "action": "update_existing" | "create_new" | "skip",
  "target_wiki_page_id": "기존 페이지 id 또는 null",
  "slug": "새 페이지일 때만, 영문/숫자/언더스코어",
  "title": "새 페이지일 때만",
  "page_type": "industry" | "company" | "technology" | "supply_chain" | "policy" | "market" | "term",
  "parent_page_id": "기존 최상위 페이지 id 또는 null",
  "markdown": "전체 새 버전 본문",
  "change_summary": "변경 이력에 들어갈 한 줄",
  "claims": [{"document_version_id": "...", "claim_text": "...", "citation_order": 1}],
  "confidence_score": 0.0,
  "reliability": {
    "grounding_fidelity_score": 0, "grounding_fidelity_reason": "",
    "source_reliability_score": 0, "source_reliability_reason": "",
    "evidence_diversity_score": 0, "evidence_diversity_reason": "",
    "currency_score": 0, "currency_reason": "",
    "reliability_score": 0, "reliability_level": "낮음" | "보통" | "높음"
  }
}"""


def _format_source_date(published_at) -> str:
    if published_at is None:
        return ""
    return published_at.strftime("%Y.%m.%d")


def _source_attribution(candidate: ReportCandidate | None) -> str:
    if candidate is None:
        return "(제목·매체 정보 없음)"
    parts = [
        part
        for part in (candidate.title, candidate.source_name, _format_source_date(candidate.published_at))
        if part
    ]
    return " · ".join(parts) if parts else "(제목·매체 정보 없음)"


def build_wiki_topic_user_prompt(
    *,
    section: ReportSectionDraft,
    candidates: list[TopicPageCandidate],
    top_level_pages: list[TopLevelTopicPage],
    evidence_texts: dict[str, str] | None = None,
    citation_attribution: dict[str, ReportCandidate] | None = None,
) -> str:
    """evidence_texts: {document_version_id: 근거 본문} — 원문 후보(ReportCandidate)에서 만든 맵.

    ReportCitationDraft.evidence_text는 현재 composer가 채우지 않으므로, 이 맵이
    [근거 문서] 블록의 실제 근거 텍스트 출처가 된다.

    citation_attribution: {document_version_id: ReportCandidate} — "출처" 섹션을
    사람이 읽을 수 있게(제목·매체명·날짜) 쓸 수 있도록 LLM에 보여주는 맵.
    """
    lines: list[str] = [
        "[이슈 정보]",
        f"제목: {section.title}",
        f"카테고리: {section.category.value}",
        f"현재 상황 요약: {section.current_summary or ''}",
        f"근거 신뢰도(원문 문서 기준): {section.reliability_score}",
        "핵심 사실:",
    ]
    lines.extend(f"- {fact}" for fact in section.key_facts)
    lines.append("시사점:")
    lines.extend(f"- {implication}" for implication in section.implications)
    lines.append("주시할 지점:")
    lines.extend(f"- {watch_point}" for watch_point in section.watch_points)

    lines.append("")
    lines.append("[근거 문서] (document_version_id는 claims 매칭에만 쓰고, markdown 출처 절엔 절대"
                 " 쓰지 마십시오 — 출처 절엔 제목·매체명·날짜를 쓰십시오)")
    if section.news_citations:
        for citation in section.news_citations:
            evidence = (evidence_texts or {}).get(citation.document_version_id) or citation.evidence_text or ""
            candidate = (citation_attribution or {}).get(citation.document_version_id)
            lines.append(
                f"- document_version_id={citation.document_version_id} citation_order={citation.citation_order}: "
                f"{evidence} [제목·매체명·날짜: {_source_attribution(candidate)}]"
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


ISSUE_PAGE_REWRITE_SYSTEM_PROMPT = """당신은 SK하이닉스 반도체 산업 위키를 관리하는 편집자입니다.

아래 리포트 섹션의 네 항목(현재 상황/핵심 사실/시사점/주시할 지점)을 더 자연스러운 문장으로
다듬어 위키 문서 본문에 쓸 수 있게 재작성하십시오.

절대 규칙:
- [현재 상황]/[핵심 사실]/[시사점]/[주시할 지점]과 [근거 문서 원문]에 없는 새로운 사실·수치·
  기업명·날짜·인용을 추가하지 마십시오. 문장을 다듬을 뿐 내용을 지어내면 안 됩니다.
- current_summary는 한 문단(3~5문장)으로 자연스럽게 이어 쓰십시오.
- key_facts/implications/watch_points는 각각 원본과 비슷한 개수의 리스트로, 항목마다
  한 문장 이내로 쓰십시오. 원본에 있던 사실을 누락하지 마십시오.
- 출처·인용 표기는 이 작업과 무관합니다 — 절대 언급하거나 만들어내지 마십시오.
- 아래 4개 항목으로 이 페이지 자체의 신뢰도를 직접 판정해 reliability 객체로 반환하십시오.
  grounding_fidelity(0~40, 가장 중요 — 본문의 각 주장이 [근거 문서 원문] 범위를 벗어나 추론·과장한
  부분이 있는지), source_reliability(0~20, [이슈 정보]의 "근거 신뢰도" 값을 참고해 원문 자체의
  신뢰도를 반영), evidence_diversity(0~20, 단일 출처에만 의존하는지), currency(0~20, 근거가
  최근 것인지). reliability_score는 4개 항목의 합, reliability_level은 0~39=낮음/40~69=보통/
  70~100=높음 구간을 그대로 따르십시오. 각 항목마다 reason을 한 문장으로 쓰십시오.
- 마크다운 코드블록 없이 지정된 JSON 구조로만 응답하십시오.

JSON 출력 형식:
{
  "current_summary": "다듬어진 현재 상황 문단",
  "key_facts": ["핵심 사실 1", "핵심 사실 2"],
  "implications": ["시사점 1", "시사점 2"],
  "watch_points": ["주시할 지점 1", "주시할 지점 2"],
  "reliability": {
    "grounding_fidelity_score": 0, "grounding_fidelity_reason": "",
    "source_reliability_score": 0, "source_reliability_reason": "",
    "evidence_diversity_score": 0, "evidence_diversity_reason": "",
    "currency_score": 0, "currency_reason": "",
    "reliability_score": 0, "reliability_level": "낮음" | "보통" | "높음"
  }
}"""


def build_issue_page_rewrite_user_prompt(
    section: ReportSectionDraft,
    evidence_texts: dict[str, str] | None = None,
) -> str:
    lines: list[str] = [
        "[이슈 정보]",
        f"제목: {section.title}",
        f"카테고리: {section.category.value}",
        f"근거 신뢰도(원문 문서 기준): {section.reliability_score}",
        "",
        "[현재 상황]",
        section.current_summary or "",
        "",
        "[핵심 사실]",
    ]
    lines.extend(f"- {fact}" for fact in section.key_facts)
    lines.append("")
    lines.append("[시사점]")
    lines.extend(f"- {implication}" for implication in section.implications)
    lines.append("")
    lines.append("[주시할 지점]")
    lines.extend(f"- {watch_point}" for watch_point in section.watch_points)
    lines.append("")
    lines.append("[근거 문서 원문] (문맥 이해용 — 여기 없는 사실을 새로 추가하지 마십시오)")
    if section.news_citations:
        for citation in section.news_citations:
            evidence = (evidence_texts or {}).get(citation.document_version_id) or citation.evidence_text or ""
            lines.append(f"- {evidence}")
    else:
        lines.append("없음")
    return "\n".join(lines)

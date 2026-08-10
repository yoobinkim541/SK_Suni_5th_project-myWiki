from __future__ import annotations

import logging

from .reliability_models import EvidenceDocument, ReliabilityEvaluationRequest

MAX_RELIABILITY_ARTICLE_CHARS = 8000
MAX_RELIABILITY_DOCUMENTS = 5

RELIABILITY_SYSTEM_PROMPT = """당신은 SK하이닉스 및 반도체 산업 동향 보고서의 근거를 검증하는 전문 팩트체커입니다.

입력된 하나 이상의 기사를 바탕으로 해당 이슈의 신뢰도를 평가하십시오.

중요:
신뢰도는 이 이슈가 중요한지를 평가하는 것이 아닙니다.
신뢰도는 기사와 이슈의 사실을 보고서 근거로 믿고 사용할 수 있는지를 평가하는 것입니다.

다음 5개 기준을 각각 0점에서 20점으로 평가하십시오.

1. 원문 추적 가능성
핵심 주장이 어떤 문서와 원문에서 나왔는지 추적할 수 있는지 평가합니다.
원문 URL, 문서 버전, 출처, 게시일, 근거 문장과 본문의 존재 여부를 확인하십시오.

2. 출처의 권위성과 직접 근거성
공식 발표, 공시, 정부 자료, 원 논문, 직접 인터뷰 등 1차 출처인지 평가하십시오.
출처가 공식적이라는 이유만으로 높은 점수를 주지 말고,
해당 원문이 핵심 주장을 실제로 직접 뒷받침하는지 확인하십시오.

3. 정보의 현재 유효성
정보가 현재도 유효한지 평가하십시오.
후속 정정, 철회, 반박, 변경된 발표 또는 상충되는 최신 정보가 있는지 확인하십시오.
계획, 검토, 전망과 확정, 실행, 완료를 명확히 구분하십시오.

4. 독립 근거의 충분성
같은 사실을 독립적인 출처에서 확인할 수 있는지 평가하십시오.
동일 보도자료를 여러 언론사가 재인용한 경우에는 여러 독립 근거로 계산하지 마십시오.
언론사와 URL이 달라도 실제 원출처가 같다면 하나의 근거로 판단하십시오.

5. 출처 간 사실 일치성
여러 출처가 제시하는 핵심 사실, 수치, 날짜, 기업명, 제품명 및 사건 상태가 일치하는지 평가하십시오.
수치가 다르면 평균을 계산하지 말고 불일치 사실을 기록하십시오.

평가 규칙:
- 각 기준은 반드시 0~20점의 정수로 평가하십시오.
- 기사 수가 많다는 이유만으로 높은 점수를 주지 마십시오.
- 기사에 없는 내용을 추측하지 마십시오.
- 확인할 수 없는 정보는 확인되었다고 판단하지 마십시오.
- 동일 원문을 재인용한 기사들은 하나의 독립 근거로 판단하십시오.
- 핵심 사실과 세부 사실을 구분하십시오.
- 각 판단에는 관련된 document_version_id를 근거로 포함하십시오.
- 불일치하는 주장이나 수치를 구체적으로 기록하십시오.
- 정보가 부족하면 missing_information에 기록하십시오.
- 전체 총점과 최종 등급은 반환하지 마십시오.
- 반드시 지정된 JSON 구조로만 응답하십시오."""


def build_reliability_user_prompt(request: ReliabilityEvaluationRequest) -> str:
    selected_documents = select_reliability_documents(request.documents)
    chunks = [
        "다음 이슈와 근거 기사들의 신뢰도를 평가하십시오.",
        "",
        "[이슈 정보]",
        f"이슈 ID: {request.issue_id or ''}",
        f"이슈 제목: {request.issue_title}",
        f"카테고리: {request.category}",
        "",
        "[근거 기사 수]",
        str(len(selected_documents)),
        "",
    ]

    for index, document in enumerate(selected_documents, start=1):
        chunks.extend([
            f"[기사 {index}]",
            f"document_version_id: {document.document_version_id}",
            f"제목: {document.title}",
            f"출처: {document.source_name}",
            f"출처 유형: {document.source_type or ''}",
            f"출처 기본 신뢰도: {document.source_reliability_score if document.source_reliability_score is not None else ''}",
            f"게시일: {document.published_at or ''}",
            f"원문 URL: {document.canonical_url or ''}",
            f"문서 버전: {document.version_no if document.version_no is not None else ''}",
            "",
            "본문:",
            select_reliability_excerpt(document.markdown),
            "",
        ])

    chunks.extend([
        "다음 JSON 구조로만 응답하십시오.",
        "",
        "{",
        '  "traceability": {',
        '    "score": 0,',
        '    "reason": "",',
        '    "evidence_document_ids": [],',
        '    "warnings": []',
        "  },",
        '  "source_authority": {',
        '    "score": 0,',
        '    "reason": "",',
        '    "evidence_document_ids": [],',
        '    "warnings": []',
        "  },",
        '  "current_validity": {',
        '    "score": 0,',
        '    "reason": "",',
        '    "evidence_document_ids": [],',
        '    "warnings": []',
        "  },",
        '  "independent_evidence": {',
        '    "score": 0,',
        '    "reason": "",',
        '    "evidence_document_ids": [],',
        '    "warnings": []',
        "  },",
        '  "factual_consistency": {',
        '    "score": 0,',
        '    "reason": "",',
        '    "evidence_document_ids": [],',
        '    "warnings": []',
        "  },",
        '  "conflicting_claims": [],',
        '  "missing_information": []',
        "}",
    ])
    return "\n".join(chunks)


def select_reliability_documents(documents: list[EvidenceDocument]) -> list[EvidenceDocument]:
    unique_documents: list[EvidenceDocument] = []
    seen_keys: set[str] = set()

    sorted_documents = sorted(
        documents,
        key=lambda item: (
            0 if _is_official_source(item.source_type) else 1,
            -(item.source_reliability_score or 0.0),
            -(0 if item.published_at is None else int(''.join(ch for ch in item.published_at if ch.isdigit())[:14] or '0')),
            item.document_version_id,
        ),
    )

    for document in sorted_documents:
        dedupe_key = (document.canonical_url or "").strip() or _normalize_text(document.title)
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        unique_documents.append(document)
        if len(unique_documents) >= MAX_RELIABILITY_DOCUMENTS:
            break

    return unique_documents


def select_reliability_excerpt(markdown: str) -> str:
    normalized = markdown.strip()
    if len(normalized) <= MAX_RELIABILITY_ARTICLE_CHARS:
        return normalized

    paragraphs = [paragraph.strip() for paragraph in normalized.split("\n\n") if paragraph.strip()]
    if not paragraphs:
        logging.info("reliability article truncated to %s chars", MAX_RELIABILITY_ARTICLE_CHARS)
        return normalized[:MAX_RELIABILITY_ARTICLE_CHARS]

    selected: list[str] = []
    budget = MAX_RELIABILITY_ARTICLE_CHARS

    def maybe_add(paragraph: str) -> None:
        nonlocal budget
        if not paragraph or paragraph in selected:
            return
        extra = len(paragraph) + (2 if selected else 0)
        if extra <= budget:
            selected.append(paragraph)
            budget -= extra

    maybe_add(paragraphs[0])
    if len(paragraphs) > 1:
        maybe_add(paragraphs[1])

    for paragraph in paragraphs[2:-1]:
        if _contains_key_fact(paragraph):
            maybe_add(paragraph)

    if len(paragraphs) > 2:
        maybe_add(paragraphs[-1])

    excerpt = "\n\n".join(selected)
    if not excerpt:
        excerpt = normalized[:MAX_RELIABILITY_ARTICLE_CHARS]

    logging.info("reliability article truncated from %s to %s chars", len(normalized), len(excerpt))
    return excerpt[:MAX_RELIABILITY_ARTICLE_CHARS]


def _contains_key_fact(paragraph: str) -> bool:
    keywords = [
        "공식",
        "발표",
        "보도자료",
        "공시",
        "정부",
        "계약",
        "매출",
        "영업이익",
        "생산",
        "투자",
        "양산",
        "출시",
        "예정",
        "확정",
        "계획",
        "정정",
        "철회",
    ]
    return any(keyword in paragraph for keyword in keywords) or any(char.isdigit() for char in paragraph)


def _is_official_source(source_type: str | None) -> bool:
    if not source_type:
        return False
    normalized = source_type.lower()
    return any(token in normalized for token in ["official", "government", "regulator", "filing", "press", "research", "conference", "disclosure"])


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().split())

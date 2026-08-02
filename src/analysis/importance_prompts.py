from __future__ import annotations

import logging

from .importance_models import ImportanceDocument, ImportanceEvaluationRequest

MAX_IMPORTANCE_ARTICLE_CHARS = 8000
MAX_IMPORTANCE_DOCUMENTS = 5

IMPORTANCE_SYSTEM_PROMPT = """당신은 SK하이닉스의 반도체 산업 동향을 분석하고
기업 관점의 이슈 우선순위를 평가하는 전문 산업 분석가입니다.

입력된 하나 이상의 기사와 기존 분석 결과를 바탕으로
해당 이슈가 SK하이닉스에 얼마나 중요한지 평가하십시오.

중요:
중요도는 기사의 사실 여부를 평가하는 신뢰도가 아닙니다.
중요도는 해당 이슈가 SK하이닉스의 사업, 제품, 고객, 생산,
수익성, 경쟁력, 공급망 또는 전략에 얼마나 큰 영향을 미치는지를 평가합니다.

동시에 기사 핵심 요약도 함께 작성하십시오.
- core_summary: 기사/이슈에서 실제로 무슨 일이 있었는지 2~4문장으로 요약
- importance_summary_reason: 왜 이 이슈가 중요한지는 점수 근거로 별도 계산되며, core_summary와 섞지 마십시오.
- key_points: 기사 핵심 포인트 3~5개
- key_numbers: 기사에 실제로 등장한 수치만 최대 8개 정리
- sk_hynix_implication: SK하이닉스 관점의 함의를 1~3문장으로 정리
- summary_evidence_refs: 위 요약 필드를 뒷받침하는 기사 원문 인용과 문서 참조

다음 6개 기준으로 평가하십시오.

1. SK하이닉스 직접 관련성: 0~25점
2. 사업 영향 규모: 0~25점
3. 긴급성과 대응 필요성: 0~15점
4. 산업·시장 파급력: 0~15점
5. 영향 지속성과 전략적 중요성: 0~10점
6. 외부 관심도와 확산 신호: 0~10점

평가 규칙:
- 기사 수가 많다는 이유만으로 높은 점수를 주지 마십시오.
- 동일 보도자료를 재배포한 기사들은 하나의 신호로 판단하십시오.
- 기업명이 등장한다는 이유만으로 직접 관련성이 높다고 판단하지 마십시오.
- 전망, 검토, 계획, 예정과 확정, 시행, 완료를 구분하십시오.
- 기사에 없는 매출, 투자액 또는 영향 규모를 임의로 생성하지 마십시오.
- 실제 사업 영향의 경로를 구체적으로 판단하십시오.
- 단기 주가 변동만으로 사업 중요도가 높다고 판단하지 마십시오.
- 각 점수에는 구체적인 근거를 작성하십시오.
- 확인할 수 없는 내용은 missing_information에 기록하십시오.
- 각 판단과 요약에는 사용한 document_version_id를 기록하십시오.
- 기회와 위험이 동시에 있으면 impact_direction을 혼합으로 반환하십시오.
- 전체 중요도 총점과 최종 등급은 반환하지 마십시오.
- 마크다운 코드블록 없이 지정된 JSON 구조로만 응답하십시오."""


def build_importance_user_prompt(request: ImportanceEvaluationRequest) -> str:
    selected_documents = select_importance_documents(request.documents)
    chunks = [
        "다음 산업 이슈가 SK하이닉스에 얼마나 중요한지 평가하고, 기사 핵심 요약도 함께 생성하십시오.",
        "",
        "[이슈 정보]",
        f"이슈 ID: {request.issue_id or ''}",
        f"이슈 제목: {request.issue_title}",
        f"주 카테고리: {request.primary_category}",
        f"보조 카테고리: {request.secondary_categories}",
        "",
        "[기존 신뢰도 평가]",
        f"신뢰도 점수: {request.reliability_score if request.reliability_score is not None else ''}",
        f"신뢰도 등급: {request.reliability_level.value if request.reliability_level is not None else ''}",
        "",
        "주의:",
        "신뢰도는 참고 정보일 뿐이며 중요도 점수에 직접 반영하지 마십시오.",
        "요약은 기사 원문에 있는 사실만 사용하십시오.",
        "summary_evidence_refs.supports는 core_summary, sk_hynix_implication, key_points[i], key_numbers[i] 형식만 사용하십시오.",
        "",
        "[이슈 관찰 정보]",
        f"근거 기사 수: {len(selected_documents)}",
        f"독립 출처 추정 수: {request.independent_source_count}",
        f"최초 확인일: {request.first_seen_at or ''}",
        f"최근 확인일: {request.last_seen_at or ''}",
        "",
    ]

    for index, document in enumerate(selected_documents, start=1):
        chunks.extend([
            f"[기사 {index}]",
            f"document_version_id: {document.document_version_id}",
            f"제목: {document.title}",
            f"출처: {document.source_name}",
            f"게시일: {document.published_at or ''}",
            f"원문 URL: {document.canonical_url or ''}",
            "",
            "본문:",
            select_importance_excerpt(document.markdown),
            "",
        ])

    chunks.extend([
        "다음 JSON 구조로만 응답하십시오.",
        "",
        "{",
        '  "direct_relevance": {"score": 0, "reason": "", "evidence_document_ids": [], "uncertainties": []},',
        '  "business_impact": {"score": 0, "reason": "", "evidence_document_ids": [], "uncertainties": []},',
        '  "urgency": {"score": 0, "reason": "", "evidence_document_ids": [], "uncertainties": []},',
        '  "industry_impact": {"score": 0, "reason": "", "evidence_document_ids": [], "uncertainties": []},',
        '  "duration": {"score": 0, "reason": "", "evidence_document_ids": [], "uncertainties": []},',
        '  "external_attention": {"score": 0, "reason": "", "evidence_document_ids": [], "uncertainties": []},',
        '  "impact_direction": "기회 | 위험 | 혼합 | 중립",',
        '  "time_horizon": "즉시 | 단기 | 중기 | 장기",',
        '  "core_summary": "",',
        '  "key_points": ["", "", ""],',
        '  "key_numbers": [{"label": "", "value": "", "unit": "", "context": "", "information_type": "fact|plan|forecast|estimate", "evidence_document_version_id": "", "quoted_text": "", "source_start_line": 0, "source_end_line": 0}],',
        '  "sk_hynix_implication": "",',
        '  "summary_evidence_refs": [{"document_version_id": "", "quoted_text": "", "source_start_line": 0, "source_end_line": 0, "supports": ["core_summary", "key_points[0]"]}],',
        '  "affected_areas": [],',
        '  "opportunities": [],',
        '  "risks": [],',
        '  "watch_points": [],',
        '  "missing_information": []',
        "}",
    ])
    return "\n".join(chunks)


def select_importance_documents(documents: list[ImportanceDocument]) -> list[ImportanceDocument]:
    unique_documents: list[ImportanceDocument] = []
    seen_keys: set[str] = set()

    sorted_documents = sorted(
        documents,
        key=lambda item: (
            0 if _mentions_sk_hynix(item.title, item.markdown) else 1,
            0 if _is_official_source(item.source_type) else 1,
            0 if _contains_quantitative_signal(item.markdown) else 1,
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
        if len(unique_documents) >= MAX_IMPORTANCE_DOCUMENTS:
            break

    return unique_documents


def select_importance_excerpt(markdown: str) -> str:
    normalized = markdown.strip()
    if len(normalized) <= MAX_IMPORTANCE_ARTICLE_CHARS:
        return normalized

    paragraphs = [paragraph.strip() for paragraph in normalized.split("\n\n") if paragraph.strip()]
    if not paragraphs:
        logging.info("importance article truncated to %s chars", MAX_IMPORTANCE_ARTICLE_CHARS)
        return normalized[:MAX_IMPORTANCE_ARTICLE_CHARS]

    selected: list[str] = []
    budget = MAX_IMPORTANCE_ARTICLE_CHARS

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
        if _importance_key_paragraph(paragraph):
            maybe_add(paragraph)

    if len(paragraphs) > 2:
        maybe_add(paragraphs[-1])

    excerpt = "\n\n".join(selected)
    if not excerpt:
        excerpt = normalized[:MAX_IMPORTANCE_ARTICLE_CHARS]

    logging.info("importance article truncated from %s to %s chars", len(normalized), len(excerpt))
    return excerpt[:MAX_IMPORTANCE_ARTICLE_CHARS]


def _importance_key_paragraph(paragraph: str) -> bool:
    keywords = [
        "sk하이닉스", "hbm", "dram", "nand", "고객", "엔비디아", "nvidia", "삼성", "마이크론",
        "생산", "투자", "매출", "영업이익", "가격", "수율", "양산", "규제", "공급망", "출하",
        "계약", "데이터센터", "ai", "공장", "보조금", "관세",
    ]
    normalized = paragraph.lower()
    return any(keyword in normalized for keyword in keywords) or any(char.isdigit() for char in paragraph)


def _contains_quantitative_signal(markdown: str) -> bool:
    return any(char.isdigit() for char in markdown)


def _mentions_sk_hynix(title: str, markdown: str) -> bool:
    normalized = f"{title} {markdown}".lower()
    return any(token in normalized for token in ["sk하이닉스", "sk hynix", "하이닉스"])


def _is_official_source(source_type: str | None) -> bool:
    if not source_type:
        return False
    normalized = source_type.lower()
    return any(token in normalized for token in ["official", "government", "regulator", "filing", "press", "research", "conference"])


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().split())


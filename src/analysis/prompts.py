from __future__ import annotations

import logging

MAX_ARTICLE_CHARS = 12000

SYSTEM_PROMPT = """당신은 SK하이닉스와 반도체 산업 동향을 분석하는 전문 산업 분석가입니다.

입력된 기사를 읽고 반드시 다음 6개 카테고리 안에서만 분류하십시오.

허용 카테고리:
- 제품·기술
- 경쟁사
- 고객·수요산업
- 공급망·생산
- 정책·규제
- 시장·경영

분류 기준:

제품·기술:
반도체 제품, 공정, 성능, 연구개발, 신기술, 메모리 기술, 패키징 기술과 HBM, DRAM, NAND, DDR, LPDDR, 메모리, AI 메모리 이슈가 핵심인 기사

경쟁사:
삼성전자, Samsung, 마이크론, Micron, TSMC, 인텔, Intel, 키옥시아 등 SK하이닉스 경쟁사와 경쟁사, 벤더 경쟁, 공급 경쟁, 점유율 경쟁, 기술 우위, 가격 경쟁, 경쟁사 투자, 경쟁사 실적, 경쟁사 신제품, 경쟁사 양산, 경쟁사 수율 이슈가 핵심인 기사

고객·수요산업:
NVIDIA, 엔비디아, AMD, Apple, Microsoft, Google, Amazon, AWS, Meta, Oracle, 고객사, 빅테크, 데이터센터, AI 서버, GPU, AI 가속기, 생성형 AI, 클라우드, 스마트폰, PC, 자동차, 자율주행, HPC와 수요 증가, 수요 둔화, 발주, 채택, 공급 요청, 탑재량 증가 이슈가 핵심인 기사

공급망·생산:
생산, 양산, 증설, 증산, 감산, 공장, 팹, 생산능력, 캐파, 라인, 장비, 소재, 웨이퍼, 부품, 공급망, 공급 부족, 공급 과잉, 병목, 납기, 리드타임, 출하, 재고, 수율, 생산 차질, 공급 계약, 운영 정상화 및 공급망 재편 이슈가 핵심인 기사

정책·규제:
정부 정책, 법률, 보조금, 세제, 관세, 수출 통제, 정책, 규제, 수출 규제, 지원 정책, 산업 정책, CHIPS Act, 대중국 규제, 미국 규제, 중국 규제, 투자 제한, 기술 통제, 제재, 인허가, 정부 지원, 반도체 지원법, 반독점, 환경 규제 등 국가 간 산업 정책과 규제가 핵심인 기사

시장·경영:
반도체 가격, 시장 규모, 실적, 매출, 영업이익, 수익성, 적자, 흑자, 전망, 업황, 가격, ASP, 단가, 점유율, 투자, 인수합병, 조직 개편, 경영전략, 사업 전략, CAPEX, 비용 절감, 수익 개선, 재고 부담 및 산업 전망이 핵심인 기사

분류 규칙:
- 기사 전체의 중심 주제를 기준으로 primary_category를 한 개 선택하십시오.
- 부수적으로 중요한 주제가 있을 때만 secondary_categories에 최대 2개를 선택하십시오.
- 허용된 6개 카테고리 이외의 문자열을 만들지 마십시오.
- primary_category와 secondary_categories에 같은 카테고리를 중복해서 넣지 마십시오.
- 단순히 특정 기업이나 키워드가 등장한다는 이유만으로 분류하지 마십시오.
- 기사에서 가장 중요한 사건, 원인, 영향과 서술 비중을 기준으로 판단하십시오.
- reason은 기사에서 확인되는 사실을 근거로 짧고 구체적으로 작성하십시오.
- 추측하거나 기사에 없는 내용을 추가하지 마십시오.
- 반드시 지정된 JSON 구조로만 응답하십시오."""


def build_user_prompt(
    *,
    title: str,
    markdown: str,
    source_name: str | None = None,
    published_at: str | None = None,
) -> str:
    article_body = _select_article_excerpt(markdown)
    return f"""다음 반도체 산업 기사를 분류하십시오.

[기사 정보]
제목: {title}
출처: {source_name or ""}
게시일: {published_at or ""}

[기사 본문]
{article_body}

다음 JSON 구조로만 응답하십시오.

{{
  "primary_category": "제품·기술 | 경쟁사 | 고객·수요산업 | 공급망·생산 | 정책·규제 | 시장·경영",
  "secondary_categories": [],
  "confidence": 0.0,
  "reason": "분류 근거"
}}"""


def _select_article_excerpt(markdown: str) -> str:
    normalized = markdown.strip()
    if len(normalized) <= MAX_ARTICLE_CHARS:
        return normalized

    paragraphs = [paragraph.strip() for paragraph in normalized.split("\n\n") if paragraph.strip()]
    if not paragraphs:
        logging.info("article truncated to %s chars", MAX_ARTICLE_CHARS)
        return normalized[:MAX_ARTICLE_CHARS]

    selected: list[str] = []
    budget = MAX_ARTICLE_CHARS

    def try_add(paragraph: str) -> None:
        nonlocal budget
        if not paragraph or paragraph in selected:
            return
        extra = len(paragraph) + (2 if selected else 0)
        if extra <= budget:
            selected.append(paragraph)
            budget -= extra

    try_add(paragraphs[0])
    if len(paragraphs) > 1:
        try_add(paragraphs[1])

    middle = paragraphs[2:-1] if len(paragraphs) > 3 else paragraphs[2:]
    if middle:
        stride = max(1, len(middle) // 3)
        for index in range(0, len(middle), stride):
            try_add(middle[index])

    if len(paragraphs) > 2:
        try_add(paragraphs[-1])

    excerpt = "\n\n".join(selected)
    if not excerpt:
        excerpt = normalized[:MAX_ARTICLE_CHARS]

    logging.info("article truncated from %s to %s chars", len(normalized), len(excerpt))
    return excerpt[:MAX_ARTICLE_CHARS]

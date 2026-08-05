"""
카테고리별 키워드 사전 — 카드의 tags를 뽑는 데 쓴다.

왜 필요한가: 카드가 보여주는 tags는 'HBM4', 'AI 가속기' 같은 짧은 낱말인데,
document_analysis_results에는 그런 필드가 없다. core_summary는 평균 190자 문장이고
key_points도 80~100자 문장이라 둘 다 태그로 못 쓴다. 그래서 문서 제목에서
아래 사전에 있는 낱말을 찾아 빈도순으로 뽑는다.

⚠ 동기화 의무
이 목록은 src/analysis/prompts.py의 분류 프롬프트에 실린 것과 같은 체계다.
그쪽은 LLM에게 주는 자연어 문자열이라 파싱하면 깨지기 쉬워서 여기에 구조화해 따로 둔다.
분류 기준이 바뀌면 **두 곳을 같이** 고쳐야 한다. prompts.py는 이환희 담당이므로
그쪽이 바뀌면 이 파일도 맞춰야 한다는 뜻이다.

슬러그(id)는 프론트 data/mockCategory.js의 MOCK_CATEGORIES[].id 및
MOCK_CATEGORY_KEYWORDS의 키와 1:1로 맞아야 한다. 어긋나면 카테고리 현황의
원그래프 두 개가 조용히 빈 상태가 된다 — 에러도 경고도 안 뜬다.
"""
from __future__ import annotations

import re

# 카테고리명 -> 프론트 슬러그. mockCategory.js의 id와 정확히 일치해야 한다.
CATEGORY_SLUGS: dict[str, str] = {
    "제품·기술": "product-tech",
    "경쟁사": "competitor",
    "고객·수요산업": "customer-demand",
    "공급망·생산": "supply-chain",
    "정책·규제": "policy",
    "시장·경영": "market",
}

# 카테고리 표시 순서 — 화면 카드 순서를 결정한다.
CATEGORY_ORDER: tuple[str, ...] = tuple(CATEGORY_SLUGS)

CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "제품·기술": (
        "반도체 제품", "공정", "성능", "연구개발", "신기술", "메모리 기술", "패키징",
        "HBM", "DRAM", "D램", "NAND", "낸드", "DDR", "LPDDR", "메모리", "AI 메모리",
    ),
    "경쟁사": (
        "삼성전자", "Samsung", "마이크론", "Micron", "TSMC", "인텔", "Intel", "키옥시아",
        "경쟁사", "벤더 경쟁", "공급 경쟁", "점유율 경쟁", "기술 우위", "가격 경쟁",
    ),
    "고객·수요산업": (
        "NVIDIA", "엔비디아", "AMD", "Apple", "애플", "Microsoft", "Google", "구글",
        "Amazon", "AWS", "Meta", "Oracle", "고객사", "빅테크", "데이터센터", "AI 서버",
        "GPU", "AI 가속기", "생성형 AI", "클라우드", "스마트폰", "자율주행", "HPC",
    ),
    "공급망·생산": (
        "생산", "양산", "증설", "증산", "감산", "공장", "팹", "생산능력", "캐파", "라인",
        "장비", "소재", "웨이퍼", "부품", "공급망", "공급 부족", "공급 과잉", "병목",
        "납기", "리드타임", "출하", "재고", "수율", "공급 계약",
    ),
    "정책·규제": (
        "정부 정책", "보조금", "세제", "관세", "수출 통제", "정책", "규제", "수출 규제",
        "지원 정책", "산업 정책", "CHIPS Act", "대중국 규제", "미국 규제", "중국 규제",
        "투자 제한", "기술 통제", "제재", "인허가", "정부 지원", "반도체 지원법",
        "반독점", "환경 규제",
    ),
    "시장·경영": (
        "반도체 가격", "시장 규모", "실적", "매출", "영업이익", "수익성", "적자", "흑자",
        "전망", "업황", "가격", "ASP", "단가", "점유율", "투자", "인수합병", "조직 개편",
        "경영전략", "사업 전략", "CAPEX", "비용 절감", "수익 개선", "재고 부담",
    ),
}

# 태그는 카드 한 장에 3개까지만 넣는다. CategoryCard가 slice 없이 전부 렌더링해서
# 개수가 많으면 카드 높이가 들쭉날쭉해진다.
MAX_TAGS = 3

# 영문·숫자 키워드는 단어 경계를 봐야 한다. 'AMD'가 'AMDX'에 걸리면 안 된다.
_ASCII_ONLY = re.compile(r"^[A-Za-z0-9 .]+$")


def _matches(keyword: str, text: str) -> bool:
    """제목에 키워드가 들어 있는가. 영문 키워드만 단어 경계를 적용한다.

    한글은 조사가 붙어서('메모리가', '수율은') 단어 경계를 쓰면 대부분 놓친다.
    """
    if _ASCII_ONLY.match(keyword):
        return re.search(rf"\b{re.escape(keyword)}\b", text, re.IGNORECASE) is not None
    return keyword in text


def extract_tags(titles: list[str], category: str, *, limit: int = MAX_TAGS) -> list[str]:
    """제목 목록에서 해당 카테고리 키워드를 빈도순으로 뽑는다.

    같은 키워드가 두 번 들어가면 React가 중복 key 경고를 내므로 중복은 제거한다.
    매칭이 하나도 없으면 빈 리스트를 반환한다 — 카드는 tags.length > 0을 보고
    태그 블록 자체를 생략하므로 빈 배열이어도 화면이 깨지지 않는다.
    """
    keywords = CATEGORY_KEYWORDS.get(category, ())
    if not keywords or not titles:
        return []

    counted: list[tuple[str, int]] = []
    for keyword in keywords:
        hits = sum(1 for title in titles if _matches(keyword, title))
        if hits:
            counted.append((keyword, hits))

    # 빈도 내림차순, 동점이면 사전에 적힌 순서를 유지한다(정렬 안정성).
    counted.sort(key=lambda pair: -pair[1])
    return [keyword for keyword, _ in counted[:limit]]

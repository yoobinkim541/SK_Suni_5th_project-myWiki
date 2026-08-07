// 연동 키워드 카탈로그 — 분류 체계 6종 고정
//
// 이 파일은 "키워드가 어느 분류에 속하는가"만 정의합니다.
// 키워드를 눌렀을 때 뜨는 공시·IR 원문/뉴스기사 목록은 data/mockWiki.js의
// WIKI_KEYWORD_LINKS가 따로 들고 있습니다 — 두 층이 다릅니다.
//   카탈로그 : 분류·노출 대상 (아래)
//   링크     : 근거 원문 데이터 (WIKI_KEYWORD_LINKS)
// 카탈로그에 있지만 링크 데이터가 없는 키워드는 화면에서 클릭 불가로 남겨 둡니다.
// 없는 원문을 지어내지 않기 위한 처리입니다.
//
// [LIVE] GET /wiki/keywords 실제 연결 완료 — services/wikiApi.js의 fetchWikiKeywordCatalog()가
// 백엔드의 [{ word, category }] 응답을 groupKeywordCatalog()로 이 파일과 같은 분류별 배열
// 모양으로 바꿔서 WikiPage.jsx state로 들고 있다가 prop으로 내려줍니다.
// 아래 WIKI_KEYWORD_CATALOG는 목업 모드(USE_MOCK) 전용 기본값으로 남겨둡니다 — 이 파일의
// 모든 함수는 catalog를 인자로 받고, 생략하면 이 상수를 기본값으로 씁니다.

import { MOCK_WIKI_DOCS, WIKI_KEYWORD_LINKS } from './mockWiki';

export const WIKI_KEYWORD_CATALOG = [
  {
    cat: '제품·기술',
    words: [
      '반도체 제품', '공정', '성능', '연구개발', '신기술', '메모리 기술', '패키징 기술',
      'HBM', 'DRAM', 'NAND', 'DDR', 'LPDDR', '메모리', 'AI 메모리',
    ],
  },
  {
    cat: '경쟁사',
    words: [
      '삼성전자', 'Samsung', '마이크론', 'Micron', 'TSMC', '인텔', 'Intel', '키옥시아',
      '경쟁사', '벤더 경쟁', '공급 경쟁', '점유율 경쟁', '기술 우위', '가격 경쟁',
      '경쟁사 투자', '경쟁사 실적', '경쟁사 신제품', '경쟁사 양산', '경쟁사 수율',
    ],
  },
  {
    cat: '고객·수요산업',
    words: [
      'NVIDIA', '엔비디아', 'AMD', 'Apple', 'Microsoft', 'Google', 'Amazon', 'AWS',
      'Meta', 'Oracle', '고객사', '빅테크', '데이터센터', 'AI 서버', 'GPU', 'AI 가속기',
      '생성형 AI', '클라우드', '스마트폰', 'PC', '자동차', '자율주행', 'HPC',
      '수요 증가', '수요 둔화', '발주', '채택', '공급 요청', '탑재량 증가',
    ],
  },
  {
    cat: '공급망·생산',
    words: [
      '생산', '양산', '증설', '증산', '감산', '공장', '팹', '생산능력', '캐파', '라인',
      '장비', '소재', '웨이퍼', '부품', '공급망', '공급 부족', '공급 과잉', '병목',
      '납기', '리드타임', '출하', '재고', '수율', '생산 차질', '공급 계약',
      '운영 정상화', '공급망 재편',
    ],
  },
  {
    cat: '정책·규제',
    words: [
      '정부 정책', '법률', '보조금', '세제', '관세', '수출 통제', '정책', '규제',
      '수출 규제', '지원 정책', '산업 정책', 'CHIPS Act', '대중국 규제', '미국 규제',
      '중국 규제', '투자 제한', '기술 통제', '제재', '인허가', '정부 지원',
      '반도체 지원법', '반독점', '환경 규제',
    ],
  },
  {
    cat: '시장·경영',
    words: [
      '반도체 가격', '시장 규모', '실적', '매출', '영업이익', '수익성', '적자', '흑자',
      '전망', '업황', '가격', 'ASP', '단가', '점유율', '투자', '인수합병', '조직 개편',
      '경영전략', '사업 전략', 'CAPEX', '비용 절감', '수익 개선', '재고 부담', '산업 전망',
    ],
  },
];

/**
 * 백엔드 GET /wiki/keywords의 평탄한 [{word, category}] 응답을 이 파일의 분류별
 * [{cat, words}] 모양으로 묶습니다. 카테고리가 응답 안에서 흩어져 있어도(연속이 아니어도)
 * Map으로 모으므로 정상 동작합니다 — 그룹 "순서"만 처음 등장한 순서를 따릅니다.
 * 같은 카테고리 안에서 같은 단어가 중복으로 와도 한 번만 남깁니다(React key 충돌 방지).
 */
export function groupKeywordCatalog(flatCatalog) {
  if (!flatCatalog?.length) return [];
  const order = [];
  const byCat = new Map();
  for (const { word, category } of flatCatalog) {
    if (!byCat.has(category)) {
      byCat.set(category, new Set());
      order.push(category);
    }
    byCat.get(category).add(word);
  }
  return order.map((cat) => ({ cat, words: [...byCat.get(cat)] }));
}

/** 카탈로그 전체 키워드 수 — 화면 표기용(하드코딩 금지). */
export function getKeywordTotal(catalog = WIKI_KEYWORD_CATALOG) {
  return catalog.reduce((sum, g) => sum + g.words.length, 0);
}

/** 카탈로그 전체를 평탄화. 긴 키워드가 먼저 매칭되도록 길이 내림차순. */
export function getCatalogKeywordList(catalog = WIKI_KEYWORD_CATALOG) {
  return catalog
    .flatMap((g) => g.words)
    .sort((a, b) => b.length - a.length);
}

/** 키워드 → 분류 조회. */
export function getKeywordCategory(word, catalog = WIKI_KEYWORD_CATALOG) {
  const found = catalog.find((g) => g.words.includes(word));
  return found ? found.cat : null;
}

// 문서 본문 문자열을 뽑습니다. 목업(zone.paragraphs)과 실제 백엔드(zone.markdown)
// 두 경로 모두 대응합니다.
function docBody(doc) {
  if (!doc?.zones) return '';
  return doc.zones
    .flatMap((z) => (z.markdown ? [z.markdown] : z.paragraphs.flat()))
    .filter((p) => typeof p === 'string')
    .join(' ');
}

/**
 * 문서 본문에 실제로 등장하는 카탈로그 키워드를 등장 횟수 내림차순으로 돌려줍니다.
 * 본문에 없는 키워드를 상단에 띄우지 않기 위한 함수입니다 — 등장하지 않으면 제외합니다.
 * @returns {{ word: string, count: number, cat: string|null }[]}
 */
export function collectDocCatalogKeywords(doc, catalog = WIKI_KEYWORD_CATALOG) {
  const body = docBody(doc);
  if (!body) return [];
  return getCatalogKeywordList(catalog)
    .map((word) => ({
      word,
      count: body.split(word).length - 1,
      cat: getKeywordCategory(word, catalog),
    }))
    .filter((k) => k.count > 0)
    .sort((a, b) => b.count - a.count || b.word.length - a.word.length);
}

/** 특정 분류에 속한 키워드 목록. */
export function getCategoryWords(cat, catalog = WIKI_KEYWORD_CATALOG) {
  const found = catalog.find((g) => g.cat === cat);
  return found ? found.words : [];
}

/**
 * 임의의 텍스트에서 카탈로그 키워드를 뽑아 등장 횟수 내림차순으로 돌려줍니다.
 * 위키 문서뿐 아니라 리포트 이슈 요약에도 씁니다 — 두 화면이 같은 키워드 사전을 보게 하려는
 * 목적입니다. 텍스트에 없는 키워드는 넣지 않습니다.
 *
 * 짧은 키워드가 긴 키워드에 포함되면(예: 'HBM' ⊂ 'HBM4') 긴 쪽만 남깁니다.
 *
 * @param {string} text 검사할 텍스트
 * @param {string[]} extraWords 카탈로그 외에 함께 볼 키워드(선택)
 * @param {{cat: string, words: string[]}[]} catalog 생략하면 목업 상수(WIKI_KEYWORD_CATALOG) —
 *   reportApi.js의 "오늘의 키워드"처럼 실제 카탈로그를 안 들고 있는 호출부용 기본값입니다.
 *   실제 카탈로그가 있는 호출부(getDocCoreKeywords)는 반드시 명시적으로 넘겨야 합니다.
 * @returns {{ word: string, count: number, cat: string|null }[]}
 */
export function extractCatalogKeywords(text, extraWords = [], catalog = WIKI_KEYWORD_CATALOG) {
  if (!text) return [];

  const words = new Set([
    ...catalog.flatMap((g) => g.words),
    ...extraWords,
  ]);

  const rows = [...words]
    .map((word) => ({
      word,
      count: text.split(word).length - 1,
      cat: getKeywordCategory(word, catalog),
    }))
    .filter((k) => k.count > 0);

  return rows
    .filter((k) => !rows.some((o) => o.word !== k.word && o.word.includes(k.word)))
    .sort((a, b) => b.count - a.count || b.word.length - a.word.length);
}

/**
 * 이 문서의 핵심 키워드. 두 소스를 합칩니다.
 *   1) 분류 카탈로그(catalog) 중 본문에 등장한 키워드
 *   2) linkWords(본문 단어 클릭 → 공시·IR 원문/뉴스기사 모달 대상 단어) 중 본문에 등장한 키워드
 * 둘 다 "본문에 실제로 등장한 것"만 잡으므로 근거 없는 키워드는 올라오지 않습니다.
 * 정렬은 문서 분류와 일치하는 키워드 → 등장 횟수 → 긴 키워드 순입니다.
 *
 * linkWords 기본값(WIKI_KEYWORD_LINKS)은 목업 전용 데이터입니다 — 실제 모드 호출부
 * (WikiKeywordBar.jsx, services/wikiApi.js의 getKeywordLinkWords() 경유)는 반드시
 * linkWords를 명시적으로 넘겨야 합니다. 안 그러면 백엔드 122개 사전에 없는 목업 단어가
 * 칩으로 뜨고, 눌러도 GET /wiki/pages?keyword=가 빈 결과만 돌려주는 막다른 클릭이 됩니다.
 */
export function getDocCoreKeywords(doc, catalog = WIKI_KEYWORD_CATALOG, linkWords = Object.keys(WIKI_KEYWORD_LINKS)) {
  const body = docBody(doc);
  if (!body) return [];

  const rows = extractCatalogKeywords(body, linkWords, catalog);

  // 이 문서 분류와 같은 키워드를 앞으로 올립니다.
  const cat = doc?.category;
  return rows.sort((a, b) => {
    const am = a.cat === cat ? 0 : 1;
    const bm = b.cat === cat ? 0 : 1;
    return am - bm;
  });
}

/**
 * 이 키워드가 본문에 등장하는 위키 문서 목록을 돌려줍니다. 목업 모드 전용입니다 —
 * MOCK_WIKI_DOCS 본문을 직접 훑어 등장 횟수를 셉니다.
 * [LIVE] 실제 백엔드 모드는 services/wikiApi.js의 fetchDocsWithKeyword()가
 * GET /wiki/pages?keyword=로 실제 태깅된 페이지를 가져옵니다(이 함수는 안 씀) —
 * 본문 등장 횟수 대신 실제 wiki_page_keywords 태깅 여부를 근거로 삼습니다.
 * @returns {{ id: string, title: string, group: string, count: number }[]}
 */
export function findDocsWithKeyword(word, tree) {
  if (!word || !tree) return [];
  const rows = [];
  for (const section of tree) {
    for (const item of section.items) {
      const full = MOCK_WIKI_DOCS[item.id];
      let count = 0;
      if (full) {
        const body = docBody(full);
        count = body.split(word).length - 1;
        if (item.title.includes(word)) count += 1;
      } else if (item.title.includes(word)) {
        count = 1;
      }
      if (count > 0) rows.push({ id: item.id, title: item.title, group: section.group, count });
    }
  }
  return rows.sort((a, b) => b.count - a.count);
}

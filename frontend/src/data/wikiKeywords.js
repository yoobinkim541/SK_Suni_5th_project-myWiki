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
// ⚠ 실제 API 연동 시: GET /api/wiki/keywords 가 [{ word, category }] 로 내려주면
//    이 상수만 교체하면 됩니다. 개수는 전부 이 배열에서 계산하므로 화면 수정이 필요 없습니다.

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

/** 카탈로그 전체 키워드 수 — 화면 표기용(하드코딩 금지). */
export function getKeywordTotal() {
  return WIKI_KEYWORD_CATALOG.reduce((sum, g) => sum + g.words.length, 0);
}

/** 카탈로그 전체를 평탄화. 긴 키워드가 먼저 매칭되도록 길이 내림차순. */
export function getCatalogKeywordList() {
  return WIKI_KEYWORD_CATALOG
    .flatMap((g) => g.words)
    .sort((a, b) => b.length - a.length);
}

/** 키워드 → 분류 조회. */
export function getKeywordCategory(word) {
  const found = WIKI_KEYWORD_CATALOG.find((g) => g.words.includes(word));
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
export function collectDocCatalogKeywords(doc) {
  const body = docBody(doc);
  if (!body) return [];
  return getCatalogKeywordList()
    .map((word) => ({
      word,
      count: body.split(word).length - 1,
      cat: getKeywordCategory(word),
    }))
    .filter((k) => k.count > 0)
    .sort((a, b) => b.count - a.count || b.word.length - a.word.length);
}

/** 특정 분류에 속한 키워드 목록. */
export function getCategoryWords(cat) {
  const found = WIKI_KEYWORD_CATALOG.find((g) => g.cat === cat);
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
 * @returns {{ word: string, count: number, cat: string|null }[]}
 */
export function extractCatalogKeywords(text, extraWords = []) {
  if (!text) return [];

  const words = new Set([
    ...WIKI_KEYWORD_CATALOG.flatMap((g) => g.words),
    ...extraWords,
  ]);

  const rows = [...words]
    .map((word) => ({
      word,
      count: text.split(word).length - 1,
      cat: getKeywordCategory(word),
    }))
    .filter((k) => k.count > 0);

  return rows
    .filter((k) => !rows.some((o) => o.word !== k.word && o.word.includes(k.word)))
    .sort((a, b) => b.count - a.count || b.word.length - a.word.length);
}

/**
 * 이 문서의 핵심 키워드. 두 소스를 합칩니다.
 *   1) 분류 카탈로그(WIKI_KEYWORD_CATALOG) 중 본문에 등장한 키워드
 *   2) 원문 연동 키워드(WIKI_KEYWORD_LINKS) 중 본문에 등장한 키워드
 * 둘 다 "본문에 실제로 등장한 것"만 잡으므로 근거 없는 키워드는 올라오지 않습니다.
 * 정렬은 문서 분류와 일치하는 키워드 → 등장 횟수 → 긴 키워드 순입니다.
 */
export function getDocCoreKeywords(doc) {
  const body = docBody(doc);
  if (!body) return [];

  const rows = extractCatalogKeywords(body, Object.keys(WIKI_KEYWORD_LINKS));

  // 이 문서 분류와 같은 키워드를 앞으로 올립니다.
  const cat = doc?.category;
  return rows.sort((a, b) => {
    const am = a.cat === cat ? 0 : 1;
    const bm = b.cat === cat ? 0 : 1;
    return am - bm;
  });
}

/**
 * 이 키워드가 본문에 등장하는 위키 문서 목록을 돌려줍니다.
 * 목업 모드에서는 MOCK_WIKI_DOCS 본문을 직접 훑고, 실제 백엔드 모드에서는 본문을
 * 미리 갖고 있지 않으므로 좌측 트리의 문서 제목 매칭으로만 좁힙니다 —
 * 확인되지 않은 문서를 목록에 끼워 넣지 않기 위한 처리입니다.
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
